import asyncio
from datetime import datetime

from app.services.caching.cache import get_redis_client
from app.services.messaging.kafka_service import (
    KAFKA_TOPIC_BOOKING_STATUS_UPDATES, KAFKA_TOPIC_BOOKING_UPDATES,
    kafka_service)


async def handle_booking_update(booking_data):
    redis = await get_redis_client()
    booking_id = booking_data["booking_id"]
    status = booking_data["status"]

    # Update booking status in Redis
    await redis.set(f"booking:status:{booking_id}", status)
    await redis.expire(f"booking:status:{booking_id}", 3600)  # 1 hour

    # Publish status update to Kafka
    booking_status_event = {
        "booking_id": booking_id,
        "status": status,
        "timestamp": datetime.utcnow().isoformat(),
    }
    await kafka_service.send_message(
        KAFKA_TOPIC_BOOKING_STATUS_UPDATES, booking_status_event
    )

    # The booking processing service already publishes the assignment event.


async def start_booking_consumer():
    await kafka_service.consume_messages(
        KAFKA_TOPIC_BOOKING_UPDATES, handle_booking_update
    )


# Run this function in a separate process or thread
if __name__ == "__main__":
    asyncio.run(start_booking_consumer())
