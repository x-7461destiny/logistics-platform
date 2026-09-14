import json
import logging
import math
from datetime import datetime
from typing import Any, Dict

import h3
from app.models import Driver
from app.services.booking.booking_service import update_booking_status
from app.services.caching.cache import get_redis_client
from app.services.messaging.kafka_service import (
    KAFKA_TOPIC_DRIVER_AVAILABILITY_UPDATES, KAFKA_TOPIC_DRIVER_LOCATIONS,
    kafka_service)
from app.services.pricing.pricing import calculate_approx_distance_duration
from app.services.tracking.location_update import update_driver_locations
from fastapi import WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession


class TrackingService:
    def __init__(self, manager):
        self.manager = manager
        if not hasattr(self.manager, "h3_resolution"):
            self.manager.h3_resolution = 9
        if not hasattr(self.manager, "h3_ring_distance"):
            self.manager.h3_ring_distance = 1.0
        if not hasattr(self.manager, "h3_index_to_drivers"):
            self.manager.h3_index_to_drivers = {}
        if not hasattr(self.manager, "driver_locations"):
            self.manager.driver_locations = {}

    def _store_driver_location(
        self, driver_id: str, latitude: float, longitude: float, vehicle_type: str
    ):
        new_h3_index = h3.latlng_to_cell(latitude, longitude, self.manager.h3_resolution)
        previous = self.manager.driver_locations.get(driver_id)
        previous_h3_index = previous["h3_index"] if previous else None

        if previous_h3_index and previous_h3_index != new_h3_index:
            drivers_in_old_index = self.manager.h3_index_to_drivers.get(previous_h3_index)
            if drivers_in_old_index:
                drivers_in_old_index.discard(driver_id)
                if not drivers_in_old_index:
                    self.manager.h3_index_to_drivers.pop(previous_h3_index, None)

        self.manager.driver_locations[driver_id] = {
            "latitude": latitude,
            "longitude": longitude,
            "vehicle_type": vehicle_type,
            "h3_index": new_h3_index,
        }
        self.manager.h3_index_to_drivers.setdefault(new_h3_index, set()).add(driver_id)

    async def handle_acknowledgment(self, driver_id: str, data: Dict[str, Any]):
        booking_id = data.get("booking_id")
        status = data.get("status")
        if not booking_id or not status:
            logging.error(
                f"Invalid acknowledgment data from driver {driver_id}: {data}"
            )
            return
        logging.info(
            f"Driver {driver_id} acknowledged booking {booking_id} with status {status}"
        )
        # Update booking status in the database
        await update_booking_status(booking_id, status)

    async def handle_location_update(self, driver_id: str, data: Dict[str, Any]):
        latitude = data.get("latitude")
        longitude = data.get("longitude")
        if latitude is None or longitude is None:
            logging.error(f"Invalid location data for driver {driver_id}: {data}")
            return

        vehicle_type = data.get("vehicle_type", "unknown")

        await update_driver_locations(
            [
                {
                    "driver_id": driver_id,
                    "latitude": latitude,
                    "longitude": longitude,
                    "vehicle_type": vehicle_type,
                }
            ]
        )
        self._store_driver_location(driver_id, latitude, longitude, vehicle_type)

    async def process_websocket_message(self, driver_id: str, data: Dict[str, Any]):
        message_type = data.get("type")
        if message_type == "acknowledgment":
            await self.handle_acknowledgment(driver_id, data)
        else:
            await self.handle_location_update(driver_id, data)

    async def websocket_connection(
        self, websocket, driver_id: str, current_driver: Driver, db: AsyncSession
    ):
        if str(current_driver.id) != driver_id:
            await websocket.close(code=4003)
            return

        await websocket.accept()
        await self.manager.connect_driver(driver_id, websocket)
        try:
            while True:
                try:
                    data = await websocket.receive_json()
                    await self.process_websocket_message(driver_id, data)
                except Exception as e:
                    await websocket.send_text(f"Error processing data: {e}")
        except WebSocketDisconnect:
            await self.manager.disconnect_driver(driver_id)
        except Exception:
            await self.manager.disconnect_driver(driver_id)

    async def get_nearby_drivers(
        self,
        lat: float,
        lng: float,
        initial_radius_km: float,
        max_radius_km: float,
        vehicle_type: str,
    ) -> Dict[str, Any]:
        redis = await get_redis_client()
        nearby_drivers = []
        seen_driver_ids = set()
        current_radius = max(initial_radius_km, 0.1)
        center_h3_index = h3.latlng_to_cell(lat, lng, self.manager.h3_resolution)

        while current_radius <= max_radius_km and not nearby_drivers:
            search_k = max(1, math.ceil(current_radius))
            search_indexes = h3.grid_disk(center_h3_index, search_k)

            for index in search_indexes:
                driver_keys = [
                    f"drivers:{index}:{vehicle_type}"
                ] if vehicle_type.lower() != "all" else []

                if vehicle_type.lower() == "all":
                    pattern = f"drivers:{index}:*"
                    matching_keys = await redis.keys(pattern)
                    driver_keys.extend(matching_keys)

                for driver_key in driver_keys:
                    drivers = await redis.smembers(driver_key)
                    for driver_id in drivers:
                        if driver_id in seen_driver_ids:
                            continue

                        raw_location = await redis.get(f"driver:location:{driver_id}")
                        if not raw_location:
                            continue

                        driver_info = json.loads(raw_location)
                        distance_info = calculate_approx_distance_duration(
                            lat,
                            lng,
                            driver_info["latitude"],
                            driver_info["longitude"],
                        )
                        distance_km = distance_info["distance_km"] / 1.2
                        if distance_km > current_radius:
                            continue

                        nearby_drivers.append(
                            {
                                "driver_id": str(driver_id),
                                "location": driver_info["h3_index"],
                                "vehicle_type": driver_info["vehicle_type"],
                                "latitude": driver_info["latitude"],
                                "longitude": driver_info["longitude"],
                                "distance_km": distance_km,
                            }
                        )
                        seen_driver_ids.add(driver_id)

            if not nearby_drivers:
                current_radius *= 2

        return {"nearby_drivers": nearby_drivers, "search_radius_km": current_radius}

    async def update_driver_location(
        self,
        driver_id: str,
        latitude: float,
        longitude: float,
        vehicle_type: str,
        is_available: bool,
    ):
        """
        Update the driver's location and availability.
        """
        # Update in Redis or database as needed
        await update_driver_locations(
            [
                {
                    "driver_id": driver_id,
                    "latitude": latitude,
                    "longitude": longitude,
                    "vehicle_type": vehicle_type,
                }
            ]
        )
        self._store_driver_location(driver_id, latitude, longitude, vehicle_type)

        # If availability status has changed, publish to Kafka
        availability_update_event = {
            "driver_id": driver_id,
            "is_available": is_available,
            "timestamp": datetime.utcnow().isoformat(),
        }
        await kafka_service.send_message(
            KAFKA_TOPIC_DRIVER_AVAILABILITY_UPDATES, availability_update_event
        )
