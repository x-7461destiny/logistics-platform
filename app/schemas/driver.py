from datetime import datetime
from typing import Optional

from app.models import VehicleTypeEnum
from app.schemas.booking import BookingStatus
from pydantic import BaseModel


class DriverBase(BaseModel):
    name: str
    email: str
    phone_number: str


class DriverCreate(DriverBase):
    password: str
    vehicle_type: VehicleTypeEnum


class DriverResponse(DriverBase):
    id: int
    vehicle_type: VehicleTypeEnum
    is_available: bool

    class Config:
        orm_mode = True

class BookingAssignment(BaseModel):
    booking_id: int
    pickup_location: str
    dropoff_location: str
    vehicle_type: VehicleTypeEnum
    price: float
    scheduled_time: Optional[datetime] = None


class StatusUpdateRequest(BaseModel):
    status: BookingStatus


class AcceptBookingResponse(BaseModel):
    booking_id: int
    pickup_location: str
    dropoff_location: str
    vehicle_type: VehicleTypeEnum
    price: float
    scheduled_time: Optional[datetime] = None
    status: BookingStatus
