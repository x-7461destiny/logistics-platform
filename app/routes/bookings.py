from app.dependencies import get_current_user, get_db, rate_limit
from app.models import User
from app.schemas.booking import BookingDetailResponse, BookingRequest, BookingResponse
from app.services.booking.booking_service import create_new_booking, get_booking_details
from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


@router.post("/book", response_model=BookingResponse)
@rate_limit(max_calls=5, time_frame=60)
async def create_booking(
    booking_data: BookingRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await create_new_booking(booking_data, current_user, db, background_tasks)


@router.get("/bookings/{booking_id}", response_model=BookingDetailResponse)
async def get_booking(
    booking_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await get_booking_details(booking_id, current_user, db)
