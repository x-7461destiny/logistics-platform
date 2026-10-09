import asyncio
import logging
import os

import socketio
from app.middleware.rate_limiter import RateLimiterMiddleware
from app.models import Base, Role, RoleEnum
from app.routes import (admin, analytics, auth, bookings, drivers, pricing,
                        tracking, users, websockets)
from app.services.analytics.analytics_consumer import start_analytics_consumer
from app.services.booking.booking_consumer import start_booking_consumer
from app.services.driver_availability.driver_availability_consumer import \
    start_driver_availability_consumer
from app.services.messaging.kafka_service import kafka_service
from app.services.tracking.location_consumer import start_location_consumer
from app.tasks import update_demand
from app.services.communication.assignment_consumer import start_assignment_consumer
from app.services.communication.websocket_service import sio, listen_native_notifications
from app.services.demand.demand_consumer import start_demand_consumer
from db.database import async_session, engine
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy.future import select
from sqlalchemy import text
import redis.asyncio as redis_asyncio

from .config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("app")

# Retain background tasks until shutdown so errors and cancellation are observed.
background_tasks = set()


def start_background(coro):
    task = asyncio.create_task(coro)
    background_tasks.add(task)
    def report_result(done):
        if not done.cancelled() and done.exception() is not None:
            logger.error("Background task failed", exc_info=(
                type(done.exception()), done.exception(), done.exception().__traceback__
            ))
    task.add_done_callback(report_result)
    return task

app = FastAPI()

# Wrap FastAPI with Socket.IO
app_asgi = socketio.ASGIApp(sio, app)

# Add CORS middleware if necessary
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin for origin in os.getenv("CORS_ORIGINS", "").split(",") if origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(RateLimiterMiddleware)
app.include_router(admin.router, prefix="/api/v1", tags=["admin"])
app.include_router(auth.router, prefix="/api/v1", tags=["auth"])
app.include_router(bookings.router, prefix="/api/v1", tags=["bookings"])
app.include_router(websockets.router, prefix="/api/v1", tags=["websockets"])
app.include_router(tracking.router, prefix="/api/v1", tags=["tracking"])
app.include_router(pricing.router, prefix="/api/v1", tags=["pricing"])
app.include_router(analytics.router, prefix="/api/v1", tags=["analytics"])
app.include_router(drivers.router, prefix="/api/v1", tags=["drivers"])
app.include_router(users.router, prefix="/api/v1", tags=["users"])

instrumentator = Instrumentator()
instrumentator.instrument(app).expose(app)


# Socket.IO handlers are registered on the shared communication server.


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
            if os.getenv("AUTO_CREATE_TABLES", "1") == "1":
                async with engine.begin() as conn:
                    await conn.run_sync(Base.metadata.create_all)
            else:
                async with engine.connect() as conn:
                    await conn.execute(text("SELECT 1"))
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
    await connect_to_db()
    await create_roles()
    await kafka_service.start()
    ready = asyncio.Event()
    listener = start_background(listen_native_notifications(ready))
    waiter = asyncio.create_task(ready.wait())
    try:
        done, _ = await asyncio.wait(
            [listener, waiter], timeout=15, return_when=asyncio.FIRST_COMPLETED
        )
        if listener in done:
            await listener
        if not ready.is_set():
            raise RuntimeError("Notification listener did not become ready")
    except BaseException:
        await shutdown_event()
        raise
    finally:
        waiter.cancel()
        await asyncio.gather(waiter, return_exceptions=True)
    start_background(update_demand())
    start_background(start_assignment_consumer())
    start_background(start_demand_consumer())

    # Start Kafka consumers
    start_background(start_booking_consumer())
    start_background(start_driver_availability_consumer())
    start_background(start_location_consumer())
    start_background(start_analytics_consumer())


@app.on_event("shutdown")
async def shutdown_event():
    for task in background_tasks:
        task.cancel()
    await asyncio.gather(*background_tasks, return_exceptions=True)
    background_tasks.clear()
    await kafka_service.stop()
    await engine.dispose()


@app.get("/")
async def root():
    return {"message": "Welcome to the Logistics Platform API"}


@app.get("/health/live", include_in_schema=False)
async def health_live():
    return {"status": "ok"}


@app.get("/health/ready", include_in_schema=False)
async def health_ready():
    from fastapi import HTTPException

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        redis = redis_asyncio.from_url(settings.REDIS_URL)
        try:
            await redis.ping()
        finally:
            await redis.aclose()
        if kafka_service.producer is None:
            raise RuntimeError("Kafka producer is not ready")
    except Exception:
        logger.exception("Readiness check failed")
        raise HTTPException(status_code=503, detail="Service unavailable")
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app_asgi, host="0.0.0.0", port=8000)
