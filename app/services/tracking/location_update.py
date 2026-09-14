import json
import time
from typing import Any, Dict, List

import h3
from app.services.messaging.kafka_service import kafka_service

KAFKA_TOPIC_DRIVER_LOCATIONS = "driver_locations"


async def update_driver_locations(driver_updates: List[Dict[str, Any]]):
    """
    Update multiple drivers' locations and publish to Kafka.
    """
    for update in driver_updates:
        driver_id = update["driver_id"]
        latitude = update["latitude"]
        longitude = update["longitude"]
        vehicle_type = update["vehicle_type"]

        h3_index = h3.latlng_to_cell(latitude, longitude, 9)  # Adjust resolution as needed

        location_data = {
            "driver_id": driver_id,
            "latitude": latitude,
            "longitude": longitude,
            "vehicle_type": vehicle_type,
            "h3_index": h3_index,
            "timestamp": int(time.time()),
        }

        # Publish location update to Kafka
        await kafka_service.send_message(KAFKA_TOPIC_DRIVER_LOCATIONS, location_data)
