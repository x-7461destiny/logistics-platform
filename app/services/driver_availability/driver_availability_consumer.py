
from app.services.caching.cache import cache_driver_availability
from app.services.messaging.kafka_service import (
    KAFKA_TOPIC_DRIVER_AVAILABILITY_UPDATES, kafka_service)


async def handle_driver_availability_update(data: dict):
    if not isinstance(data["is_available"], bool):
        raise ValueError("is_available must be a boolean")
    await cache_driver_availability(data["driver_id"], data["is_available"])


async def start_driver_availability_consumer():
    await kafka_service.consume_messages(
        KAFKA_TOPIC_DRIVER_AVAILABILITY_UPDATES, handle_driver_availability_update
    )
