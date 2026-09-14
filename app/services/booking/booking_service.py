import json
import struct
from datetime import datetime, timedelta, timezone

from app.models import Booking, BookingStatusEnum, BookingStatusHistory, User
from app.schemas.booking import BookingDetailResponse, BookingRequest, BookingResponse, StatusUpdate
from app.services.caching.cache import cache
from app.services.messaging.kafka_service import (
    KAFKA_TOPIC_BOOKING_STATUS_UPDATES, KAFKA_TOPIC_BOOKING_UPDATES,
    kafka_service)
from app.services.pricing import calculate_price
from app.services.validation.booking_validation import validate_booking
from app.tasks import process_immediate_booking, schedule_booking_processing
from app.utils.kafka_producer import publish_event
from fastapi import BackgroundTasks, HTTPException
from geoalchemy2.elements import WKBElement
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload


BEIJING_TZ = timezone(timedelta(hours=8))


def to_beijing_time(value: datetime | None) -> datetime | None:
    if value is None:
        return None

    if value.tzinfo is None:
        return value.replace(tzinfo=BEIJING_TZ)

    return value.astimezone(BEIJING_TZ)


def to_utc_naive(value: datetime | None) -> datetime | None:
    if value is None:
        return None

    beijing_time = to_beijing_time(value)
    return beijing_time.astimezone(timezone.utc).replace(tzinfo=None)


def format_point(point_value) -> str:
    if isinstance(point_value, WKBElement):
        raw = bytes(point_value.data)
        if len(raw) < 21:
            raise ValueError("Invalid WKB POINT data")

        byte_order = "<" if raw[0] == 1 else ">"
        geometry_type = struct.unpack(f"{byte_order}I", raw[1:5])[0]
        if geometry_type != 1:
            raise ValueError("Geometry is not a POINT")

        longitude = struct.unpack(f"{byte_order}d", raw[5:13])[0]
        latitude = struct.unpack(f"{byte_order}d", raw[13:21])[0]
        return f"POINT({longitude} {latitude})"

    return str(point_value)


async def get_booking_details(
    booking_id: int, current_user: User, db: AsyncSession
) -> BookingDetailResponse:
    result = await db.execute(
        select(Booking)
        .options(selectinload(Booking.status_history))
        .where(Booking.id == booking_id, Booking.user_id == current_user.id)
    )
    booking = result.scalar_one_or_none()
    if booking is None:
        raise HTTPException(status_code=404, detail="Booking not found")

    status_history = sorted(booking.status_history, key=lambda entry: entry.timestamp)

    return BookingDetailResponse(
        booking_id=booking.id,
        driver_id=booking.driver_id,
        pickup_location=format_point(booking.pickup_location),
        dropoff_location=format_point(booking.dropoff_location),
        vehicle_type=booking.vehicle_type.value,
        price=booking.price,
        date=to_beijing_time(booking.date),
        status=booking.status,
        status_history=[
            StatusUpdate(status=entry.status, timestamp=to_beijing_time(entry.timestamp))
            for entry in status_history
        ],
    )


async def create_new_booking(
    booking_data: BookingRequest,
    current_user: User,
    db: AsyncSession,
    background_tasks: BackgroundTasks,
) -> BookingResponse:
    """
    Create a new booking and handle subsequent operations.
    """
    try:
        # Validate booking
        await validate_booking(db, booking_data)

        # Calculate price
        price = await calculate_price(booking_data.dict())

        # Determine if booking is scheduled
        beijing_scheduled_time = to_beijing_time(booking_data.scheduled_time)
        normalized_scheduled_time = to_utc_naive(booking_data.scheduled_time)

        scheduled_time = normalized_scheduled_time or datetime.utcnow()
        is_scheduled = (
            normalized_scheduled_time is not None
            and normalized_scheduled_time > datetime.utcnow()
        )

        # Set booking status based on scheduling
        status = (
            BookingStatusEnum.scheduled if is_scheduled else BookingStatusEnum.pending
        )

        # Create booking
        booking = Booking(
            user_id=current_user.id,
            pickup_location=f"POINT({booking_data.pickup_longitude} {booking_data.pickup_latitude})",
            dropoff_location=f"POINT({booking_data.dropoff_longitude} {booking_data.dropoff_latitude})",
            vehicle_type=booking_data.vehicle_type,
            price=price,
            date=scheduled_time,
            scheduled_time=normalized_scheduled_time,
            status=status,
        )
        db.add(booking)
        await db.flush()  # Populate booking.id

        # Add initial status to BookingStatusHistory
        status_history_entry = BookingStatusHistory(
            booking_id=booking.id, status=status, timestamp=datetime.utcnow()
        )
        db.add(status_history_entry)

        # Cache the booking
        cache_key = f"booking:{current_user.id}:{booking_data.pickup_latitude},{booking_data.pickup_longitude}:{booking_data.dropoff_latitude},{booking_data.dropoff_longitude}"
        await cache.set(cache_key, {"id": booking.id, "price": price}, expire=300)

        # Publish booking creation event to Kafka
        booking_event = {
            "event_type": "booking_created",
            "booking_id": booking.id,
            "user_id": current_user.id,
            "status": status,
            "timestamp": datetime.utcnow().isoformat(),
        }
        await publish_event(KAFKA_TOPIC_BOOKING_UPDATES, booking_event)

        await db.commit()

        if is_scheduled:
            schedule_booking_processing.apply_async(args=[booking.id, scheduled_time])
            booking_status_event = {
                "booking_id": booking.id,
                "status": "scheduled",
                "scheduled_time": beijing_scheduled_time.isoformat() if beijing_scheduled_time else None,
                "timestamp": datetime.utcnow().isoformat(),
            }
            await kafka_service.send_message(
                KAFKA_TOPIC_BOOKING_STATUS_UPDATES, booking_status_event
            )
        else:
            # Process immediate booking
            background_tasks.add_task(process_immediate_booking, booking.id)

        return BookingResponse(
            booking_id=booking.id,
            initial_status=status,
            processing=True,
            message="Booking created. Check the booking record later for the latest assignment status.",
        )

    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


async def update_booking_status(booking_id: int, status: str):
    return None
