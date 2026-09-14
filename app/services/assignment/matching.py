import json
import struct
from typing import Optional

import h3
from app.models import Booking, Driver
from app.services.assignment.driver_assignment import assign_driver
from app.services.caching.cache import get_redis_client
from geoalchemy2.elements import WKBElement
from sqlalchemy.ext.asyncio import AsyncSession


def parse_point_coordinates(point_value) -> tuple[float, float]:
    if isinstance(point_value, WKBElement):
        raw = bytes(point_value.data)
        if len(raw) < 21:
            raise ValueError("Invalid WKB POINT data")

        byte_order = "<" if raw[0] == 1 else ">"
        geometry_type = struct.unpack(f"{byte_order}I", raw[1:5])[0]
        if geometry_type != 1:
            raise ValueError("Geometry is not a POINT")

        longitude = struct.unpack(f"{byte_order}d", raw[5:13])[0]
        latitude = struct.unpack(f"{byte_order}d", raw[13:21])[0]
        return latitude, longitude

    point_text = str(point_value)
    coordinates = point_text.removeprefix("POINT(").removesuffix(")").split()
    longitude = float(coordinates[0])
    latitude = float(coordinates[1])
    return latitude, longitude


async def find_nearest_driver(booking: Booking, db: AsyncSession) -> Optional[Driver]:
    """
    Assign the nearest available driver based on pickup location and vehicle type.
    """
    pickup_lat, pickup_lng = parse_point_coordinates(booking.pickup_location)
    vehicle_type = booking.vehicle_type.value
    pickup_h3 = h3.latlng_to_cell(pickup_lat, pickup_lng, 9)

    redis = await get_redis_client()
    tried_driver_ids: set[int] = set()

    for k in range(5):
        hex_ring = h3.grid_disk(pickup_h3, k)
        for hex_index in hex_ring:
            drivers = await redis.smembers(f"drivers:{hex_index}:{vehicle_type}")
            if not drivers:
                continue

            ranked_drivers = await rank_nearest_drivers(
                drivers, pickup_h3, redis, tried_driver_ids
            )
            for driver_id in ranked_drivers:
                tried_driver_ids.add(driver_id)
                assigned_driver = await assign_driver(driver_id, db)
                if assigned_driver:
                    return assigned_driver

    return None


async def rank_nearest_drivers(
    drivers: set, pickup_h3: str, redis, tried_driver_ids: set[int]
) -> list[int]:
    """
    Rank nearby drivers by distance while treating Redis availability as a hint only.
    """
    ranked_drivers: list[tuple[int, int]] = []

    for driver_id in drivers:
        driver_id_int = int(driver_id)
        if driver_id_int in tried_driver_ids:
            continue

        availability_value = await redis.get(f"driver:availability:{driver_id_int}")
        if availability_value == "False":
            continue

        raw_location = await redis.get(f"driver:location:{driver_id}")
        if not raw_location:
            continue

        location = json.loads(raw_location)
        driver_h3 = h3.latlng_to_cell(location["latitude"], location["longitude"], 9)
        distance = h3.grid_distance(pickup_h3, driver_h3)
        ranked_drivers.append((distance, driver_id_int))

    ranked_drivers.sort(key=lambda item: item[0])
    return [driver_id for _, driver_id in ranked_drivers]
