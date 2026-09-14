from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from app.services.assignment.driver_assignment import assign_driver
from app.services.assignment.matching import find_nearest_driver, rank_nearest_drivers


class FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


@pytest.mark.asyncio
async def test_assign_driver_returns_none_when_atomic_claim_fails():
    db = AsyncMock()
    db.execute = AsyncMock(return_value=FakeResult(None))

    claimed_driver = await assign_driver(7, db)

    assert claimed_driver is None


@pytest.mark.asyncio
async def test_assign_driver_returns_driver_when_atomic_claim_succeeds():
    db = AsyncMock()
    claimed_driver = SimpleNamespace(id=7, is_available=False)
    db.execute = AsyncMock(return_value=FakeResult(7))

    with patch(
        "app.services.assignment.driver_assignment.get_driver_from_db",
        AsyncMock(return_value=claimed_driver),
    ) as mock_get_driver:
        result = await assign_driver(7, db)

    assert result is claimed_driver
    mock_get_driver.assert_awaited_once_with(7, db)


@pytest.mark.asyncio
async def test_rank_nearest_drivers_orders_candidates_and_skips_unavailable():
    redis = AsyncMock()

    async def fake_get(key):
        values = {
            "driver:availability:1": "True",
            "driver:availability:2": "False",
            "driver:availability:3": "True",
            "driver:location:1": '{"latitude": 6.5244, "longitude": 3.3792}',
            "driver:location:3": '{"latitude": 6.53, "longitude": 3.38}',
        }
        return values.get(key)

    redis.get = AsyncMock(side_effect=fake_get)

    with patch(
        "app.services.assignment.matching.h3.latlng_to_cell",
        side_effect=lambda lat, lng, resolution: (
            "driver_h3_1" if lat == 6.5244 else "driver_h3_3"
        ),
    ), patch(
        "app.services.assignment.matching.h3.grid_distance",
        side_effect=lambda pickup_h3, driver_h3: 0 if driver_h3 == "driver_h3_1" else 2,
    ):
        ranked = await rank_nearest_drivers({"1", "2", "3"}, "pickup_h3", redis, {2})

    assert ranked == [1, 3]


@pytest.mark.asyncio
async def test_find_nearest_driver_falls_back_when_first_claim_loses_race():
    booking = SimpleNamespace(
        pickup_location="POINT(3.3792 6.5244)",
        vehicle_type=SimpleNamespace(value="van"),
    )
    redis = AsyncMock()
    redis.smembers = AsyncMock(return_value={"1", "2"})

    with patch(
        "app.services.assignment.matching.get_redis_client",
        AsyncMock(return_value=redis),
    ), patch(
        "app.services.assignment.matching.rank_nearest_drivers",
        AsyncMock(return_value=[1, 2]),
    ), patch(
        "app.services.assignment.matching.assign_driver",
        AsyncMock(side_effect=[None, SimpleNamespace(id=2)]),
    ) as mock_assign_driver:
        assigned_driver = await find_nearest_driver(booking, AsyncMock())

    assert assigned_driver.id == 2
    assert mock_assign_driver.await_count == 2
