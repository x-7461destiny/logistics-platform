import json
from datetime import datetime

from app.models import Booking, BookingStatusEnum, BookingStatusHistory, User
from app.schemas.booking import BookingRequest, BookingResponse, StatusUpdate
from app.services.caching.cache import cache
from app.services.messaging.kafka_service import (
    KAFKA_TOPIC_BOOKING_STATUS_UPDATES, KAFKA_TOPIC_BOOKING_UPDATES,
    kafka_service)
from app.services.pricing import calculate_price
from app.services.validation.booking_validation import validate_booking
from app.tasks import process_immediate_booking, schedule_booking_processing
from app.utils.kafka_producer import publish_event
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession


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
        scheduled_time = booking_data.scheduled_time or datetime.utcnow()
        is_scheduled = (
            booking_data.scheduled_time is not None
            and booking_data.scheduled_time > datetime.utcnow()
        )

        # Set booking status based on scheduling
        status = (
            BookingStatusEnum.scheduled if is_scheduled else BookingStatusEnum.pending
        )

        async with db.begin():
            # Create booking
            booking = Booking(
                user_id=current_user.id,
                pickup_location=f"POINT({booking_data.pickup_longitude} {booking_data.pickup_latitude})",
                dropoff_location=f"POINT({booking_data.dropoff_longitude} {booking_data.dropoff_latitude})",
                vehicle_type=booking_data.vehicle_type,
                price=price,
                date=scheduled_time,
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

            if is_scheduled:
                # Schedule background task for scheduled booking
                background_tasks.add_task(
                    schedule_booking_processing, booking.id, scheduled_time
                )
                booking_status_event = {
                    "booking_id": booking.id,
                    "status": "scheduled",
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
            user_id=current_user.id,
            driver_id=booking.driver_id,
            pickup_location=f"POINT({booking_data.pickup_longitude} {booking_data.pickup_latitude})",
            dropoff_location=f"POINT({booking_data.dropoff_longitude} {booking_data.dropoff_latitude})",
            vehicle_type=booking.vehicle_type,
            price=price,
            date=scheduled_time,
            status=status,
            status_history=[
                StatusUpdate(
                    status=status,
                    timestamp=status_history_entry.timestamp,
                )
            ],
        )

    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


async def update_booking_status(booking_id: int, status: str):
    return None
