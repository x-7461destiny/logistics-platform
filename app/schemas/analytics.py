from typing import List

from pydantic import BaseModel, Field


class AnalyticsCreate(BaseModel):
    metric: str = Field(..., description="Analytics metric name")
    value: float = Field(..., description="Analytics metric value")


class PopularPickupLocation(BaseModel):
    location: str = Field(..., description="Pickup location")
    count: int = Field(..., description="Number of bookings for this location")


class AnalyticsResponse(BaseModel):
    total_bookings: int = Field(
        ..., description="Total number of bookings in the last 24 hours"
    )
    total_revenue: float = Field(..., description="Total revenue in the last 24 hours")
    average_price: float = Field(
        ..., description="Average price per booking in the last 24 hours"
    )
    popular_pickup_locations: List[PopularPickupLocation] = Field(
        ..., description="Most popular pickup locations in the last 24 hours"
    )
    active_drivers: int = Field(..., description="Number of currently active drivers")
    new_users: int = Field(
        ..., description="Number of new users registered in the last 24 hours"
    )
