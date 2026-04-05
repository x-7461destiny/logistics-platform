import json
from datetime import datetime
from typing import List

from app.services.communication.websocket_service import manager
from app.services.messaging.kafka_service import (
    KAFKA_TOPIC_DRIVER_ASSIGNMENTS, kafka_service)


async def notify_driver_assignment(driver_id: int, booking_id: int):
    """
    Notify the driver about the new booking assignment via Kafka.
    """
    message = {
        "type": "assignment",
        "data": {
            "booking_id": booking_id,
            "message": "You have been assigned a new booking.",
        },
    }
    # Publish to Kafka instead of sending directly via WebSocket
    assignment_event = {
        "driver_id": driver_id,
        "message": message,
        "timestamp": datetime.utcnow().isoformat(),
    }
    await kafka_service.send_message(KAFKA_TOPIC_DRIVER_ASSIGNMENTS, assignment_event)


async def notify_nearby_drivers(booking_id: int, nearby_driver_ids: List[int]):
    """
    Notify all nearby drivers about a new booking.
    """
    message = json.dumps(
        {
            "type": "new_booking",
            "data": {
                "booking_id": booking_id,
                "message": "A new booking has been created near your location.",
            },
        }
    )
    for driver_id in nearby_driver_ids:
        await manager.send_message_to_driver(str(driver_id), "new_booking", message)
