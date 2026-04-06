import json
import logging
from datetime import datetime
from typing import Any, Dict

import h3
from app.models import Driver
from app.services.booking.booking_service import update_booking_status
from app.services.messaging.kafka_service import (
    KAFKA_TOPIC_DRIVER_AVAILABILITY_UPDATES, KAFKA_TOPIC_DRIVER_LOCATIONS,
    kafka_service)
from app.services.tracking.location_update import update_driver_locations
from fastapi import WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession


class TrackingService:
    def __init__(self, manager):
        self.manager = manager

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
        except Exception as e:
            await self.manager.send_personal_message(f"Error: {str(e)}", websocket)
            await self.manager.disconnect_driver(driver_id)

    async def get_nearby_drivers(
        self,
        lat: float,
        lng: float,
        initial_radius_km: float,
        max_radius_km: float,
        vehicle_type: str,
    ) -> Dict[str, Any]:
        nearby_drivers = []
        current_radius = initial_radius_km

        while current_radius <= max_radius_km and not nearby_drivers:
            h3_index = h3.geo_to_h3(lat, lng, self.manager.h3_resolution)
            search_indexes = h3.k_ring(
                h3_index, int(current_radius / self.manager.h3_ring_distance)
            )

            for index in search_indexes:
                drivers = self.manager.h3_index_to_drivers.get(index, [])
                for driver_id in drivers:
                    driver_info = self.manager.driver_locations.get(driver_id)
                    if driver_info and (
                        vehicle_type.lower() == "all"
                        or driver_info["vehicle_type"] == vehicle_type
                    ):
                        nearby_drivers.append(
                            {
                                "driver_id": driver_id,
                                "location": driver_info["h3_index"],
                                "vehicle_type": driver_info["vehicle_type"],
                            }
                        )

            if not nearby_drivers:
                current_radius *= 2  # Double the radius for the next iteration

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

        # Publish location update to Kafka
        location_update_event = {
            "driver_id": driver_id,
            "latitude": latitude,
            "longitude": longitude,
            "vehicle_type": vehicle_type,
            "timestamp": datetime.utcnow().isoformat(),
        }
        await kafka_service.send_message(
            KAFKA_TOPIC_DRIVER_LOCATIONS, location_update_event
        )

        # If availability status has changed, publish to Kafka
        availability_update_event = {
            "driver_id": driver_id,
            "is_available": is_available,
            "timestamp": datetime.utcnow().isoformat(),
        }
        await kafka_service.send_message(
            KAFKA_TOPIC_DRIVER_AVAILABILITY_UPDATES, availability_update_event
        )
