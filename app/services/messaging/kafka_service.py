import asyncio
import json
import logging

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from aiokafka.structs import TopicPartition
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
        self.consumers = set()
        self.consumer_tasks = set()
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
                try:
                    await producer.start()
                except BaseException:
                    await producer.stop()
                    raise
                self.producer = producer

        return self.producer

    async def start(self):
        for attempt in range(5):
            try:
                await self._get_or_create_producer()
                return
            except Exception:
                if attempt == 4:
                    raise
                await asyncio.sleep(2 ** attempt)

    async def stop(self):
        tasks = list(self.consumer_tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self.producer:
            await self.producer.stop()
            self.producer = None

    async def send_message(self, topic, message):
        producer = await self._get_or_create_producer()
        await producer.send_and_wait(topic, message)

    async def consume_messages(self, topic, message_handler):
        task = asyncio.current_task()
        self.consumer_tasks.add(task)
        try:
            while True:
                try:
                    await self._consume(topic, message_handler)
                except Exception:
                    logging.exception("Consumer failed for %s; reconnecting", topic)
                    await asyncio.sleep(5)
        finally:
            self.consumer_tasks.discard(task)

    async def _consume(self, topic, message_handler):
        consumer = AIOKafkaConsumer(
            topic,
            bootstrap_servers=settings.KAFKA_URL,
            group_id=f"{topic}_group",
            enable_auto_commit=False,
            auto_offset_reset="earliest",
        )
        self.consumers.add(consumer)
        try:
            await consumer.start()
            async for msg in consumer:
                attempt = 0
                while True:
                    try:
                        data = json.loads(msg.value.decode("utf-8"))
                        if not isinstance(data, dict):
                            raise ValueError("Kafka event must be a JSON object")
                        await message_handler(data)
                        break
                    except Exception:
                        attempt += 1
                        logging.exception(
                            "Event failed topic=%s partition=%s offset=%s attempt=%s",
                            msg.topic, msg.partition, msg.offset, attempt,
                        )
                        await asyncio.sleep(min(2 ** min(attempt, 5), 30))
                await consumer.commit({TopicPartition(msg.topic, msg.partition): msg.offset + 1})
        finally:
            await consumer.stop()
            self.consumers.discard(consumer)


kafka_service = KafkaService()
