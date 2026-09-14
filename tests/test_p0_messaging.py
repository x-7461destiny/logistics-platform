import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiokafka.structs import TopicPartition
from app.services.messaging.kafka_service import KafkaService
from app.services.driver_availability.driver_availability_consumer import handle_driver_availability_update
from app.services.communication.assignment_consumer import handle_driver_assignment
from app.services.communication.websocket_service import ConnectionManager


class Consumer:
    def __init__(self, topic, **kwargs):
        assert kwargs["enable_auto_commit"] is False
        self.topic = topic
        self.start = AsyncMock()
        self.stop = AsyncMock()
        self.commit = AsyncMock()
        self.sent = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.sent:
            raise StopAsyncIteration
        self.sent = True
        return SimpleNamespace(topic=self.topic, partition=0, offset=7,
                               value=b'{"driver_id":12,"is_available":false}')


def test_decode_retry_then_commit():
    async def run():
        service = KafkaService()
        consumer = Consumer("availability", enable_auto_commit=False)
        attempts = []

        async def handler(data):
            assert consumer.commit.await_count == 0
            attempts.append(data)
            if len(attempts) == 1:
                raise RuntimeError("temporary Redis failure")

        with patch("app.services.messaging.kafka_service.AIOKafkaConsumer", return_value=consumer), patch(
            "app.services.messaging.kafka_service.asyncio.sleep", new=AsyncMock()
        ):
            await service._consume("availability", handler)
        assert attempts == [{"driver_id": 12, "is_available": False}] * 2
        consumer.commit.assert_awaited_once_with({TopicPartition("availability", 0): 8})
        consumer.stop.assert_awaited_once()
        assert not service.consumers
    asyncio.run(run())


def test_failed_message_cancelled_without_commit():
    async def run():
        service = KafkaService()
        consumer = Consumer("availability", enable_auto_commit=False)
        failed = asyncio.Event()

        async def handler(data):
            failed.set()
            raise RuntimeError("Redis unavailable")

        with patch("app.services.messaging.kafka_service.AIOKafkaConsumer", return_value=consumer):
            task = asyncio.create_task(service.consume_messages("availability", handler))
            await asyncio.wait_for(failed.wait(), 1)
            await service.stop()
        assert task.cancelled()
        consumer.commit.assert_not_awaited()
        consumer.stop.assert_awaited_once()
        assert not service.consumer_tasks
    asyncio.run(run())


def test_consumers_have_independent_lifetimes():
    async def run():
        instances = []
        service = KafkaService()
        ready = asyncio.Event()

        class WaitingConsumer(Consumer):
            async def __anext__(self):
                if len(instances) == 2:
                    ready.set()
                await asyncio.Event().wait()

        def factory(*args, **kwargs):
            item = WaitingConsumer(*args, **kwargs)
            instances.append(item)
            return item

        with patch("app.services.messaging.kafka_service.AIOKafkaConsumer", side_effect=factory):
            tasks = [asyncio.create_task(service.consume_messages(topic, AsyncMock()))
                     for topic in ["first", "second"]]
            await asyncio.wait_for(ready.wait(), 1)
            assert len(service.consumers) == 2
            await service.stop()
        assert all(task.cancelled() for task in tasks)
        for item in instances:
            item.stop.assert_awaited_once()
    asyncio.run(run())


def test_availability_accepts_dictionary_and_propagates_failure():
    async def run():
        with patch("app.services.driver_availability.driver_availability_consumer.cache_driver_availability",
                   new=AsyncMock()) as cache:
            await handle_driver_availability_update({"driver_id": 12, "is_available": False})
            cache.assert_awaited_once_with(12, False)
    asyncio.run(run())


def test_assignment_reaches_shared_room_and_native_channel():
    async def run():
        manager = ConnectionManager()
        manager.sio = SimpleNamespace(emit=AsyncMock())
        redis = AsyncMock()
        with patch("app.services.communication.assignment_consumer.manager", manager), patch(
            "app.services.communication.websocket_service.get_redis_client", new=AsyncMock(return_value=redis)
        ):
            await handle_driver_assignment({"driver_id": 12, "message": {"booking_id": 7}})
        manager.sio.emit.assert_awaited_once_with(
            "assignment", {"booking_id": 7}, room="driver_12", namespace="/"
        )
        payload = json.loads(redis.publish.call_args.args[1])
        assert payload == {"driver_id": "12", "event": "assignment", "data": {"booking_id": 7}}
        redis.aclose.assert_awaited_once()
    asyncio.run(run())


def test_analytics_uses_validated_payload_and_database_session():
    from app.services.analytics.analytics_consumer import handle_analytics_update

    async def run():
        session = AsyncMock()
        context = AsyncMock()
        context.__aenter__.return_value = session
        with patch("app.services.analytics.analytics_consumer.async_session", return_value=context), patch(
            "app.services.analytics.analytics_consumer.create_analytics_service", new=AsyncMock()
        ) as create:
            await handle_analytics_update({"metric": "test", "value": 2.0})
            payload, db = create.call_args.args
            assert payload.metric == "test"
            assert payload.value == 2.0
            assert db is session
    asyncio.run(run())


def test_consumer_start_failure_closes_instance():
    async def run():
        service = KafkaService()
        consumer = Consumer("topic", enable_auto_commit=False)
        consumer.start.side_effect = RuntimeError("broker unavailable")
        with patch("app.services.messaging.kafka_service.AIOKafkaConsumer", return_value=consumer):
            try:
                await service._consume("topic", AsyncMock())
            except RuntimeError:
                pass
            else:
                raise AssertionError("startup failure must propagate")
        consumer.stop.assert_awaited_once()
        assert not service.consumers
    asyncio.run(run())
