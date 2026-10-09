import asyncio
import json
import logging
import os

from app.config import settings

import socketio
from app.dependencies import resolve_principal_from_token
from app.models import Driver, User
from app.services.caching.cache import get_redis_client
from app.services.tracking.tracking_service import TrackingService
from circuitbreaker import circuit
from db.database import async_session
from fastapi import HTTPException, WebSocket, WebSocketDisconnect, status
from opentelemetry import trace
from pydantic import BaseModel, ValidationError


class LocationUpdate(BaseModel):
    driver_id: str
    latitude: float
    longitude: float

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins=([origin for origin in os.getenv("CORS_ORIGINS", "").split(",") if origin] or None),
    client_manager=socketio.AsyncRedisManager(settings.REDIS_URL),
)
app_sio = socketio.ASGIApp(sio)

NATIVE_NOTIFICATIONS_CHANNEL = "native_driver_notifications"


class ConnectionManager:
    def __init__(self):
        self.sio = sio
        self.tracking_service = TrackingService(self)
        self.active_drivers = {}  # driver_id: sid
        self.active_users = {}  # user_id: sid
        self.native_drivers = {}

    async def broadcast_to_users(self, event, message):
        await self.sio.emit(event, message, namespace="/")

    async def send_message_to_driver(self, driver_id: str, event, message):
        await self.sio.emit(event, message, room=f"driver_{driver_id}", namespace="/")
        redis = await get_redis_client()
        try:
            await redis.publish(NATIVE_NOTIFICATIONS_CHANNEL, json.dumps({
                "driver_id": driver_id, "event": event, "data": message,
            }))
        finally:
            await redis.aclose()

    async def send_personal_message(self, event, message, target_sid: str):
        if isinstance(target_sid, WebSocket):
            await target_sid.send_json({"event": event, "data": message})
        else:
            await self.sio.emit(event, message, room=target_sid, namespace="/")

    async def connect_driver(self, driver_id: str, sid: str):
        if isinstance(sid, WebSocket):
            self.native_drivers[driver_id] = sid
        else:
            self.active_drivers[driver_id] = sid
        logger.info(f"Driver {driver_id} connected with session ID {sid}")

    async def disconnect_driver(self, driver_id: str, connection=None):
        for connections in (self.native_drivers, self.active_drivers):
            if connection is None or connections.get(driver_id) == connection:
                connections.pop(driver_id, None)

    async def connect_user(self, user_id: str, sid: str):
        self.active_users[user_id] = sid
        logger.info(f"User {user_id} connected with session ID {sid}")

    async def disconnect_user(self, user_id: str):
        if user_id in self.active_users:
            del self.active_users[user_id]
            logger.info(f"User {user_id} disconnected")


manager = ConnectionManager()
tracking_service = TrackingService(manager)


@circuit(failure_threshold=5, recovery_timeout=30)
async def get_redis_connection_with_circuit_breaker():
    return await get_redis_client()


def serialize_principal(principal):
    is_driver = isinstance(principal, Driver)
    return {
        "id": principal.id,
        "is_driver": is_driver,
        "vehicle_type": getattr(principal, "vehicle_type", None),
        "is_available": getattr(principal, "is_available", False),
    }


async def authenticate_websocket(websocket: WebSocket, is_driver: bool = False):
    token = websocket.headers.get("Authorization")
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        logger.warning("WebSocket connection closed due to missing token.")
        return None

    try:
        token_type, token_value = token.split()
        if token_type.lower() != "bearer":
            raise ValueError("Invalid token type")

        async with async_session() as db:
            principal = await resolve_principal_from_token(token_value, db)

        if is_driver and not isinstance(principal, Driver):
            raise ValueError("User is not a driver")
        if not is_driver and not isinstance(principal, User):
            raise ValueError("Driver token not allowed")

        user = serialize_principal(principal)
        logger.info(f"Authenticated {'driver' if is_driver else 'user'}: {user['id']}")
        return user
    except (ValueError, IndexError, HTTPException) as e:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        logger.warning(f"WebSocket connection closed due to authentication error: {e}")
        return None


@sio.event
async def connect(sid, environ, auth=None):
    token = environ.get("HTTP_AUTHORIZATION")
    if not token:
        return False
    try:
        token_type, token_value = token.split()
        if token_type.lower() != "bearer":
            raise ValueError("Invalid token type")

        async with async_session() as db:
            principal = await resolve_principal_from_token(token_value, db)

        user = serialize_principal(principal)
        await sio.save_session(sid, {"user": user})
        room = f"driver_{user['id']}" if user.get("is_driver") else f"user_{user['id']}"
        await sio.enter_room(sid, room)
        logger.info(
            f"Authenticated {'driver' if user.get('is_driver') else 'user'}: {user['id']}"
        )
        if user.get("is_driver"):
            await manager.connect_driver(str(user["id"]), sid)
        else:
            await manager.connect_user(str(user["id"]), sid)
    except (ValueError, IndexError, HTTPException) as e:
        logger.warning(f"Socket.IO connection closed due to authentication error: {e}")
        return False


@sio.event
async def disconnect(sid, reason=None):
    user = (await sio.get_session(sid)).get("user")
    if user:
        user_id = user["id"]
        if user.get("is_driver"):
            await manager.disconnect_driver(str(user_id), sid)
            logger.info(f"Driver {user_id} disconnected.")
        else:
            await manager.disconnect_user(str(user_id))
            logger.info(f"User {user_id} disconnected.")
    else:
        logger.info(f"Client {sid} disconnected without authenticated user.")


@sio.event
async def update_location(sid, data):
    user = (await sio.get_session(sid)).get("user")
    if not user or not user.get("is_driver"):
        await sio.emit("error", {"message": "Unauthorized"}, room=sid)
        logger.warning(f"Unauthorized location update attempt from SID: {sid}")
        return
    try:
        location = LocationUpdate(**data)
        await manager.tracking_service.update_driver_location(
            location.driver_id,
            location.latitude,
            location.longitude,
            user["vehicle_type"],
            user["is_available"],
        )
        logger.info(f"Location updated for driver {location.driver_id}")
    except ValidationError as e:
        error_message = f"Invalid data format: {str(e)}"
        await manager.send_personal_message("error", {"message": error_message}, sid)
        logger.error(f"Validation error from driver {user['id']}: {e}")


# Assignment notifications are produced by trusted booking services only.
async def assign_booking(sid, booking):
    user = (await sio.get_session(sid)).get("user")
    if not user or not user.get("is_driver"):
        await sio.emit("error", {"message": "Unauthorized"}, room=sid)
        logger.warning(f"Unauthorized booking assignment attempt from SID: {sid}")
        return
    try:
        message = {
            "type": "assignment",
            "data": {
                "booking_id": booking["id"],
                "message": "You have been assigned a new booking.",
            },
        }
        await manager.send_message_to_driver(
            str(booking["driver_id"]), "assignment", message
        )
        logger.info(f"Processed booking assignment for driver {booking['driver_id']}")
    except Exception as e:
        await manager.send_personal_message(
            "error", {"message": "Failed to assign booking."}, sid
        )
        logger.error(f"Error assigning booking to driver {booking['driver_id']}: {e}")


async def handle_driver_connection(websocket: WebSocket):
    user = await authenticate_websocket(websocket, is_driver=True)
    if not user:
        return

    driver_id = str(user["id"])
    await websocket.accept()
    await manager.connect_driver(driver_id, websocket)
    try:
        while True:
            data = await websocket.receive_text()
            try:
                location = LocationUpdate.parse_raw(data)
                await manager.tracking_service.update_driver_location(
                    location.driver_id,
                    location.latitude,
                    location.longitude,
                    user["vehicle_type"],
                    user["is_available"],
                )
            except ValidationError as e:
                error_message = f"Invalid data format: {str(e)}"
                await manager.send_personal_message(
                    "error", error_message, websocket
                )
                logger.error(f"Validation error from driver {driver_id}: {e}")
    except WebSocketDisconnect:
        await manager.disconnect_driver(driver_id, websocket)
    except Exception as e:
        logger.error(f"Error in handle_driver_connection: {str(e)}")
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR)


async def handle_user_connection(websocket: WebSocket):
    user = await authenticate_websocket(websocket)
    if not user:
        return

    user_id = str(user["id"])
    await websocket.accept()
    await manager.connect_user(user_id, websocket)
    try:
        redis = await get_redis_client()
        pubsub = redis.pubsub()
        await pubsub.subscribe("driver_locations")
        logger.info(f"User {user_id} subscribed to 'driver_locations' channel.")
        async for message in pubsub.listen():
            if message["type"] == "message":
                await manager.send_personal_message(
                    "driver_location_update", message["data"], websocket
                )
    except WebSocketDisconnect:
        await manager.disconnect_user(user_id)
    except Exception as e:
        logger.error(f"Error in handle_user_connection: {str(e)}")
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
    finally:
        await pubsub.unsubscribe("driver_locations")
        await pubsub.close()
        logger.info(f"User {user_id} unsubscribed and connection closed.")


async def handle_driver_batch_connection(websocket: WebSocket):
    user = await authenticate_websocket(websocket, is_driver=True)
    if not user:
        return

    driver_id = str(user["id"])
    await websocket.accept()
    await manager.connect_driver(driver_id, websocket)
    try:
        while True:
            data = await websocket.receive_json()
            if isinstance(data, list):
                for location in data:
                    try:
                        location_update = LocationUpdate(**location)
                        await manager.tracking_service.update_driver_location(
                            location_update.driver_id,
                            location_update.latitude,
                            location_update.longitude,
                            user["vehicle_type"],
                            user["is_available"],
                        )
                    except ValidationError as e:
                        error_message = f"Invalid data format: {str(e)}"
                        await manager.send_personal_message(
                            "error", error_message, websocket
                        )
                        logger.error(
                            f"Batch validation error from driver {driver_id}: {e}"
                        )
            else:
                error_message = (
                    "Invalid data format. Expected a list of location updates."
                )
                await manager.send_personal_message(
                    "error", error_message, websocket
                )
                logger.warning(f"Driver {driver_id} sent invalid batch data.")
    except WebSocketDisconnect:
        await manager.disconnect_driver(driver_id, websocket)
    except Exception as e:
        logger.error(f"Error in handle_driver_batch_connection: {str(e)}")
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR)

async def listen_native_notifications(ready: asyncio.Event):
    redis = await get_redis_client()
    try:
        async with redis.pubsub() as pubsub:
            await pubsub.subscribe(NATIVE_NOTIFICATIONS_CHANNEL)
            ready.set()
            async for item in pubsub.listen():
                if item["type"] != "message":
                    continue
                data = json.loads(item["data"])
                websocket = manager.native_drivers.get(str(data["driver_id"]))
                if websocket is not None:
                    try:
                        await websocket.send_json({"event": data["event"], "data": data["data"]})
                    except Exception:
                        logger.exception("Failed to send native driver notification")
    finally:
        await redis.aclose()
