import logging

import socketio
from app.dependencies import get_current_user
from app.services.caching.cache import get_redis_client
from app.services.tracking.tracking_service import TrackingService
from circuitbreaker import circuit
from fastapi import WebSocket, WebSocketDisconnect, status
from opentelemetry import trace
from pydantic import BaseModel, ValidationError


class LocationUpdate(BaseModel):
    driver_id: str
    latitude: float
    longitude: float

from app.services.tracking.tracking_service import TrackingService
from circuitbreaker import circuit
from fastapi import WebSocket, WebSocketDisconnect, status
from opentelemetry import trace
from pydantic import ValidationError

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins="*",
    client_manager=None,  # We'll use Redis for scaling
)
app_sio = socketio.ASGIApp(sio)

sio.redis = socketio.RedisManager("redis://localhost:6379")


class ConnectionManager:
    def __init__(self):
        self.sio = sio
        self.tracking_service = TrackingService(self)
        self.active_drivers = {}  # driver_id: sid
        self.active_users = {}  # user_id: sid

    async def broadcast_to_users(self, event, message):
        await self.sio.emit(event, message, namespace="/")

    async def send_message_to_driver(self, driver_id: str, event, message):
        sid = self.active_drivers.get(driver_id)
        if sid:
            await self.sio.emit(event, message, room=driver_id, namespace="/")
        else:
            logger.warning(f"Attempted to send message to inactive driver: {driver_id}")

    async def send_personal_message(self, event, message, target_sid: str):
        await self.sio.emit(event, message, room=target_sid, namespace="/")

    async def connect_driver(self, driver_id: str, sid: str):
        self.active_drivers[driver_id] = sid
        logger.info(f"Driver {driver_id} connected with session ID {sid}")

    async def disconnect_driver(self, driver_id: str):
        if driver_id in self.active_drivers:
            del self.active_drivers[driver_id]
            logger.info(f"Driver {driver_id} disconnected")

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
        user = await get_current_user(token_value)
        if not user:
            raise ValueError("Invalid token")
        if is_driver and not user.get("is_driver"):
            raise ValueError("User is not a driver")
        logger.info(f"Authenticated {'driver' if is_driver else 'user'}: {user['id']}")
        return user
    except (ValueError, IndexError) as e:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        logger.warning(f"WebSocket connection closed due to authentication error: {e}")
        return None


@sio.event
async def connect(sid, environ):
    token = environ.get("HTTP_AUTHORIZATION")
    if not token:
        await sio.disconnect(sid)
        logger.warning("Socket.IO connection closed due to missing token.")
        return
    try:
        token_type, token_value = token.split()
        if token_type.lower() != "bearer":
            raise ValueError("Invalid token type")
        user = await get_current_user(token_value)
        if not user:
            raise ValueError("Invalid token")
        sio.environ[sid] = {"user": user}
        room = f"driver_{user['id']}" if user.get("is_driver") else f"user_{user['id']}"
        sio.enter_room(sid, room)
        logger.info(
            f"Authenticated {'driver' if user.get('is_driver') else 'user'}: {user['id']}"
        )
        if user.get("is_driver"):
            await manager.connect_driver(str(user["id"]), sid)
        else:
            await manager.connect_user(str(user["id"]), sid)
    except (ValueError, IndexError) as e:
        await sio.disconnect(sid)
        logger.warning(f"Socket.IO connection closed due to authentication error: {e}")


@sio.event
async def disconnect(sid):
    user = sio.environ.get(sid, {}).get("user")
    if user:
        user_id = user["id"]
        if user.get("is_driver"):
            await manager.disconnect_driver(str(user_id))
            logger.info(f"Driver {user_id} disconnected.")
        else:
            await manager.disconnect_user(str(user_id))
            logger.info(f"User {user_id} disconnected.")
    else:
        logger.info(f"Client {sid} disconnected without authenticated user.")


@sio.event
async def update_location(sid, data):
    user = sio.environ.get(sid, {}).get("user")
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


@sio.event
async def assign_booking(sid, booking):
    user = sio.environ.get(sid, {}).get("user")
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
    await manager.connect_driver(driver_id, websocket.client)
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
                    "error", error_message, websocket.client
                )
                logger.error(f"Validation error from driver {driver_id}: {e}")
    except WebSocketDisconnect:
        await manager.disconnect_driver(driver_id)
    except Exception as e:
        logger.error(f"Error in handle_driver_connection: {str(e)}")
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR)


async def handle_user_connection(websocket: WebSocket):
    user = await authenticate_websocket(websocket)
    if not user:
        return

    user_id = str(user["id"])
    await manager.connect_user(user_id, websocket.client)
    try:
        redis = await get_redis_client()
        pubsub = redis.pubsub()
        await pubsub.subscribe("driver_locations")
        logger.info(f"User {user_id} subscribed to 'driver_locations' channel.")
        async for message in pubsub.listen():
            if message["type"] == "message":
                await manager.send_personal_message(
                    "driver_location_update", message["data"], websocket.client
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
    await manager.connect_driver(driver_id, websocket.client)
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
                            "error", error_message, websocket.client
                        )
                        logger.error(
                            f"Batch validation error from driver {driver_id}: {e}"
                        )
            else:
                error_message = (
                    "Invalid data format. Expected a list of location updates."
                )
                await manager.send_personal_message(
                    "error", error_message, websocket.client
                )
                logger.warning(f"Driver {driver_id} sent invalid batch data.")
    except WebSocketDisconnect:
        await manager.disconnect_driver(driver_id)
    except Exception as e:
        logger.error(f"Error in handle_driver_batch_connection: {str(e)}")
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
