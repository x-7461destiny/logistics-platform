"""Run inside the Compose network: python tests/p0_messaging_smoke.py."""
import asyncio
import json
import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
import socketio
import uvicorn
import websockets

from app.main import app_asgi
from app.models import Driver
from app.services.caching.cache import get_redis_client
from app.services.messaging.kafka_service import kafka_service


async def main():
    marker = uuid.uuid4().hex
    driver_id = str(900000000 + int(marker[:6], 16))
    driver = Driver(id=int(driver_id), vehicle_type="van", is_available=True)
    server = uvicorn.Server(uvicorn.Config(app_asgi, host="127.0.0.1", port=8011, log_level="warning"))
    socket = socketio.AsyncClient()
    received = asyncio.Queue()
    socket.on("assignment", lambda data: received.put_nowait(data))
    redis = await get_redis_client()
    keys = [f"driver:availability:{driver_id}", f"booking:status:{marker}", f"demand:{marker}"]
    with patch("app.services.communication.websocket_service.resolve_principal_from_token",
               new=AsyncMock(return_value=driver)):
        task = asyncio.create_task(server.serve())
        try:
            for _ in range(200):
                if server.started:
                    break
                if task.done():
                    await task
                    raise RuntimeError("Server stopped before startup")
                await asyncio.sleep(0.1)
            assert server.started
            async with httpx.AsyncClient() as client:
                assert (await client.get("http://127.0.0.1:8011/")).status_code == 200
            await socket.connect("http://127.0.0.1:8011", headers={"Authorization": "Bearer smoke"})
            async with websockets.connect(
                "ws://127.0.0.1:8011/api/v1/ws/drivers",
                additional_headers={"Authorization": "Bearer smoke"},
            ) as native:
                await kafka_service.send_message("driver_availability_updates", {
                    "driver_id": driver_id, "is_available": False,
                })
                await kafka_service.send_message("booking_updates", {
                    "booking_id": marker, "status": "pending",
                })
                await kafka_service.send_message("demand_updates", {
                    "h3_index": marker, "demand": 1.7,
                })
                message = {"type": "assignment", "data": {"booking_id": marker}}
                await kafka_service.send_message("driver_assignments", {
                    "driver_id": driver_id, "message": message,
                })
                assert await asyncio.wait_for(received.get(), 30) == message
                assert json.loads(await asyncio.wait_for(native.recv(), 30)) == {
                    "event": "assignment", "data": message,
                }
                for _ in range(300):
                    values = await redis.mget(keys)
                    if values == ["False", "pending", "1.7"]:
                        break
                    await asyncio.sleep(0.1)
                assert values == ["False", "pending", "1.7"], values
                print("PASS: API, availability, booking, demand, Socket.IO and native WebSocket delivery", flush=True)
        finally:
            if socket.connected:
                await socket.disconnect()
            server.should_exit = True
            await asyncio.wait_for(task, 20)
            await redis.delete(*keys)
            await redis.aclose()
    assert not kafka_service.consumers
    assert not kafka_service.consumer_tasks
    print("PASS: graceful shutdown closed all Kafka consumers", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
