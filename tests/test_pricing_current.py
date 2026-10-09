from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from app.services.pricing.pricing import calculate_price


@pytest.mark.asyncio
async def test_van_price_uses_current_vehicle_types():
    data = {
        "pickup_latitude": 37.7749,
        "pickup_longitude": -122.4194,
        "dropoff_latitude": 37.8044,
        "dropoff_longitude": -122.2711,
        "vehicle_type": "van",
    }
    with patch("app.services.pricing.pricing.get_distance_duration", new=AsyncMock(
        return_value={"distance_km": 10, "duration_min": 20}
    )), patch("app.services.pricing.pricing.get_surge_multiplier", new=AsyncMock(return_value=1)):
        price = await calculate_price(data)
    assert price >= 20


@pytest.mark.asyncio
async def test_rejects_unknown_vehicle_type():
    with pytest.raises(ValidationError):
        await calculate_price({
            "pickup_latitude": 37.7749,
            "pickup_longitude": -122.4194,
            "dropoff_latitude": 37.8044,
            "dropoff_longitude": -122.2711,
            "vehicle_type": "standard",
        })
