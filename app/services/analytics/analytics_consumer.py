from app.schemas.analytics import AnalyticsCreate
from db.database import async_session

from app.services.analytics.analytics_service import create_analytics_service
from app.services.messaging.kafka_service import (
    KAFKA_TOPIC_ANALYTICS_UPDATES, kafka_service)


async def handle_analytics_update(data: dict):
    """
    Process analytics updates from Kafka.
    """
    payload = AnalyticsCreate(**data)
    async with async_session() as db:
        await create_analytics_service(payload, db)


async def start_analytics_consumer():
    await kafka_service.consume_messages(
        KAFKA_TOPIC_ANALYTICS_UPDATES, handle_analytics_update
    )
