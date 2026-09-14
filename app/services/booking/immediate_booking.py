from datetime import datetime

from app.models import Booking, BookingStatusEnum, BookingStatusHistory
from app.services.assignment.matching import find_nearest_driver
from app.services.caching.cache import cache_driver_availability
from app.services.communication.notification import notify_driver_assignment
from app.services.messaging.kafka_service import (KAFKA_TOPIC_BOOKING_UPDATES,
                                                  kafka_service)
from db.database import async_session


async def process_immediate_booking(booking_id: int):
    async with async_session() as db:
        booking = await db.get(Booking, booking_id)
        if not booking:
            return

        if booking.status != BookingStatusEnum.pending:
            return

        assigned_driver = await find_nearest_driver(booking, db)
        if not assigned_driver:
            booking.status = BookingStatusEnum.cancelled
            status_history_entry = BookingStatusHistory(
                booking_id=booking.id,
                status=BookingStatusEnum.cancelled,
                timestamp=datetime.utcnow(),
            )
            db.add(status_history_entry)
            await db.commit()
            return

        booking.driver_id = assigned_driver.id
        booking.status = BookingStatusEnum.confirmed

        status_history_entry = BookingStatusHistory(
            booking_id=booking.id,
            status=BookingStatusEnum.confirmed,
            timestamp=datetime.utcnow(),
        )
        db.add(status_history_entry)

        await db.commit()
        await cache_driver_availability(assigned_driver.id, False)

        await notify_driver_assignment(assigned_driver.id, booking.id)
        await kafka_service.send_message(
            KAFKA_TOPIC_BOOKING_UPDATES,
            {
                "booking_id": booking.id,
                "status": BookingStatusEnum.confirmed,
                "driver_id": assigned_driver.id,
            },
        )
