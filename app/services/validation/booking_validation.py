from app.schemas.booking import BookingRequest
from sqlalchemy.ext.asyncio import AsyncSession


async def validate_booking(db: AsyncSession, booking_data: BookingRequest):
    scheduled_time = booking_data.scheduled_time

    if scheduled_time is None:
        return
