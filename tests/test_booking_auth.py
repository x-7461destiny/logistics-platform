from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import BackgroundTasks

from app.models import User
from app.schemas.booking import BookingRequest
from app.services.booking.booking_service import create_new_booking


class DummyTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_create_new_booking_uses_authenticated_user_for_cache_key_and_event():
    booking_data = BookingRequest(
        pickup_latitude=6.5244,
        pickup_longitude=3.3792,
        dropoff_latitude=6.6018,
        dropoff_longitude=3.3515,
        vehicle_type="van",
    )
    current_user = User(
        id=42,
        email="user@example.com",
        name="User",
        phone_number="08012345678",
        password_hash="hashed",
    )
    created_objects = []

    def add_object(obj):
        if getattr(obj, "id", None) is None:
            obj.id = len(created_objects) + 1
        created_objects.append(obj)

    db = SimpleNamespace(
        begin=lambda: DummyTransaction(),
        add=add_object,
        flush=AsyncMock(),
        commit=AsyncMock(),
        rollback=AsyncMock(),
    )
    background_tasks = BackgroundTasks()

    with patch("app.services.booking.booking_service.validate_booking", new=AsyncMock()), patch(
        "app.services.booking.booking_service.calculate_price", new=AsyncMock(return_value=2500.0)
    ), patch(
        "app.services.booking.booking_service.cache.set", new=AsyncMock()
    ) as cache_set, patch(
        "app.services.booking.booking_service.publish_event", new=AsyncMock()
    ) as publish_event, patch(
        "app.services.booking.booking_service.process_immediate_booking", new=AsyncMock()
    ):
        response = await create_new_booking(booking_data, current_user, db, background_tasks)

    assert response.booking_id == created_objects[0].id
    assert cache_set.await_args.args[0].startswith("booking:42:")
    assert publish_event.await_args.args[1]["user_id"] == current_user.id
