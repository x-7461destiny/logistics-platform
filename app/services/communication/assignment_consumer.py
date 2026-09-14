from app.services.communication.websocket_service import manager
from app.services.messaging.kafka_service import (
    KAFKA_TOPIC_DRIVER_ASSIGNMENTS, kafka_service,
)


async def handle_driver_assignment(data: dict):
    await manager.send_message_to_driver(
        str(data["driver_id"]), "assignment", data["message"]
    )


async def start_assignment_consumer():
    await kafka_service.consume_messages(
        KAFKA_TOPIC_DRIVER_ASSIGNMENTS, handle_driver_assignment
    )
