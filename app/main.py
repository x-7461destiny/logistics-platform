import asyncio
import logging

import socketio
from app.middleware.rate_limiter import RateLimiterMiddleware
from app.models import Base, Role, RoleEnum
from app.routes import (admin, analytics, bookings, drivers, pricing, tracking,
                        users, websockets)
from app.services.analytics.analytics_consumer import start_analytics_consumer
from app.services.booking.booking_consumer import start_booking_consumer
from app.services.driver_availability.driver_availability_consumer import \
    start_driver_availability_consumer
from app.services.messaging.kafka_service import kafka_service
from app.tasks import update_demand
from db.database import async_session, engine
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy.future import select

from .config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("app")

# Initialize Socket.IO with Redis adapter
sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins=["*"],
    adapter=socketio.RedisManager(settings.REDIS_URL),
)

app = FastAPI()

# Wrap FastAPI with Socket.IO
app_asgi = socketio.ASGIApp(sio, app)

# Add CORS middleware if necessary
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust as needed
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(RateLimiterMiddleware)
app.include_router(admin.router, prefix="/api/v1", tags=["admin"])
app.include_router(bookings.router, prefix="/api/v1", tags=["bookings"])
app.include_router(tracking.router, prefix="/api/v1", tags=["tracking"])
app.include_router(pricing.router, prefix="/api/v1", tags=["pricing"])
app.include_router(analytics.router, prefix="/api/v1", tags=["analytics"])
app.include_router(drivers.router, prefix="/api/v1", tags=["drivers"])
app.include_router(users.router, prefix="/api/v1", tags=["users"])
app.include_router(websockets.router, prefix="/api/v1", tags=["websockets"])

instrumentator = Instrumentator()
instrumentator.instrument(app).expose(app)


# Socket.IO Event Handlers
@sio.event
async def connect(sid, environ):
    logger.info(f"Client connected: {sid}")


@sio.event
async def disconnect(sid):
    logger.info(f"Client disconnected: {sid}")


# Add other Socket.IO event handlers as needed


async def create_roles():
    async with async_session() as session:
        async with session.begin():
            for role_name in RoleEnum:
                result = await session.execute(
                    select(Role).where(Role.name == role_name)
                )
                role = result.scalar_one_or_none()
                if not role:
                    session.add(Role(name=role_name))
        await session.commit()
    logger.info("Roles ensured.")


async def connect_to_db():
    retries = 5
    while retries > 0:
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.info("Successfully connected to the database.")
            break
        except Exception as e:
            logger.error(f"Failed to connect to the database: {e}")
            retries -= 1
            await asyncio.sleep(5)
    if retries == 0:
        logger.error("Failed to connect to the database after multiple attempts.")
        raise Exception("Could not connect to the database")


@app.on_event("startup")
async def startup_event():
    asyncio.create_task(update_demand())
    await connect_to_db()
    await create_roles()
    await kafka_service.start()

    # Start Kafka consumers
    asyncio.create_task(start_booking_consumer())
    asyncio.create_task(start_driver_availability_consumer())
    asyncio.create_task(start_analytics_consumer())


@app.on_event("shutdown")
async def shutdown_event():
    await kafka_service.stop()


@app.get("/")
async def root():
    return {"message": "Welcome to the Logistics Platform API"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app_asgi, host="0.0.0.0", port=8000)
