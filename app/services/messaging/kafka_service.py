import asyncio
import json

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from app.config import settings

KAFKA_TOPIC_DRIVER_LOCATIONS = "driver_locations"
KAFKA_TOPIC_BOOKING_UPDATES = "booking_updates"
KAFKA_TOPIC_DRIVER_ASSIGNMENTS = "driver_assignments"
KAFKA_TOPIC_DRIVER_AVAILABILITY_UPDATES = "driver_availability_updates"
KAFKA_TOPIC_BOOKING_STATUS_UPDATES = "booking_status_updates"
KAFKA_TOPIC_ANALYTICS_UPDATES = "analytics_updates"
KAFKA_TOPIC_DEMAND_UPDATES = "demand_updates"


class KafkaService:
    def __init__(self):
        self.producer = None
        self.consumer = None
        self._producer_lock = asyncio.Lock()

    async def _get_or_create_producer(self):
        if self.producer is not None:
            return self.producer

        async with self._producer_lock:
            if self.producer is None:
                producer = AIOKafkaProducer(
                    bootstrap_servers=settings.KAFKA_URL,
                    value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                    # Optimize producer settings as needed
                    linger_ms=5,  # Batch messages for better throughput
                    acks="all",
                )
                await producer.start()
                self.producer = producer

        return self.producer

    async def start(self):
        await self._get_or_create_producer()

    async def stop(self):
        if self.producer:
            await self.producer.stop()
            self.producer = None
        if self.consumer:
            await self.consumer.stop()
            self.consumer = None

    async def send_message(self, topic, message):
        producer = await self._get_or_create_producer()
        await producer.send_and_wait(topic, message)

    async def consume_messages(self, topic, message_handler):
        self.consumer = AIOKafkaConsumer(
            topic,
            bootstrap_servers=settings.KAFKA_URL,
            value_deserializer=lambda m: json.loads(m.decode("utf-8")),
            group_id=f"{topic}_group",
            enable_auto_commit=True,
            auto_offset_reset="earliest",
        )
        await self.consumer.start()
        try:
            async for msg in self.consumer:
                asyncio.create_task(message_handler(msg))
        finally:
            await self.consumer.stop()


kafka_service = KafkaService()
