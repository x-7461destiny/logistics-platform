import asyncio
import json

from app.services.caching.cache import get_redis_client
from app.services.messaging.kafka_service import (KAFKA_TOPIC_DRIVER_LOCATIONS,
                                                  kafka_service)


LOCATION_TTL_SECONDS = 300


async def handle_location_update(message):
    redis = await get_redis_client()
    location_data = message.value if hasattr(message, "value") else message
    driver_id = location_data["driver_id"]
    h3_index = location_data["h3_index"]
    vehicle_type = location_data["vehicle_type"]

    previous_h3_key = f"driver:h3:{driver_id}"
    previous_h3_index = await redis.get(previous_h3_key)
    previous_location_raw = await redis.get(f"driver:location:{driver_id}")
    previous_location = json.loads(previous_location_raw) if previous_location_raw else None
    previous_vehicle_type = (
        previous_location.get("vehicle_type") if previous_location else vehicle_type
    )
    if previous_h3_index and (
        previous_h3_index != h3_index or previous_vehicle_type != vehicle_type
    ):
        await redis.srem(
            f"drivers:{previous_h3_index}:{previous_vehicle_type}", driver_id
        )

    location_key = f"driver:location:{driver_id}"
    await redis.set(location_key, json.dumps(location_data), ex=LOCATION_TTL_SECONDS)

    drivers_key = f"drivers:{h3_index}:{vehicle_type}"
    await redis.sadd(drivers_key, driver_id)
    await redis.expire(drivers_key, LOCATION_TTL_SECONDS)

    await redis.set(previous_h3_key, h3_index, ex=LOCATION_TTL_SECONDS)


async def start_location_consumer():
    await kafka_service.consume_messages(
        KAFKA_TOPIC_DRIVER_LOCATIONS, handle_location_update
    )


# Run this function in a separate process or thread
if __name__ == "__main__":
    asyncio.run(start_location_consumer())
