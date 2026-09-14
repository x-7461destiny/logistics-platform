from datetime import datetime
from typing import Optional

from app.models import VehicleTypeEnum
from pydantic import BaseModel, Field, validator


class PricingCreate(BaseModel):
    vehicle_type: str = Field(..., description="Type of vehicle.")
    base_fare: float = Field(..., ge=0, description="Base fare amount.")
    cost_per_km: float = Field(..., ge=0, description="Cost per kilometer.")


class PricingResponse(PricingCreate):
    id: int


class PricingSchema(BaseModel):
    pickup_latitude: float = Field(
        ..., ge=-90.0, le=90.0, description="Latitude of the pickup location."
    )
    pickup_longitude: float = Field(
        ..., ge=-180.0, le=180.0, description="Longitude of the pickup location."
    )
    dropoff_latitude: float = Field(
        ..., ge=-90.0, le=90.0, description="Latitude of the dropoff location."
    )
    dropoff_longitude: float = Field(
        ..., ge=-180.0, le=180.0, description="Longitude of the dropoff location."
    )
    vehicle_type: VehicleTypeEnum = Field(
        ..., description="Type of vehicle selected for the booking."
    )
    scheduled_time: Optional[datetime] = Field(
        None, description="Scheduled time for the booking in ISO format."
    )

    @validator("scheduled_time")
    def validate_scheduled_time(cls, v):
        return v  # Pydantic automatically validates datetime fields
