import asyncio
import json
import logging
import time
from datetime import datetime, timedelta
from typing import Any, Dict

import redis.asyncio as redis_asyncio
from app.models import Booking, BookingStatusEnum, Driver, User
from celery import Celery
from celery.signals import worker_process_init, worker_process_shutdown
from db.database import engine
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings

# Setup basic configuration for logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

app = Celery("tasks", broker=settings.CELERY_BROKER_URL)

KAFKA_TOPIC_DEMAND_UPDATES = "demand_updates"
H3_INDEXES = ["8928308280fffff", "8928308283fffff"]
_worker_loop: asyncio.AbstractEventLoop | None = None


@worker_process_init.connect
def init_worker_event_loop(**kwargs):
    global _worker_loop
    _worker_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_worker_loop)
    _worker_loop.run_until_complete(engine.dispose())


@worker_process_shutdown.connect
def shutdown_worker_event_loop(**kwargs):
    global _worker_loop
    if _worker_loop is not None:
        _worker_loop.close()
        _worker_loop = None


def run_async_in_worker(coro):
    if _worker_loop is None:
        raise RuntimeError("Celery worker event loop is not initialized")

    return _worker_loop.run_until_complete(coro)


async def get_redis_client():
    return redis_asyncio.from_url(settings.REDIS_URL, decode_responses=True)


@app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    sender.add_periodic_task(3600.0, compute_analytics.s(), name="compute every hour")


async def update_demand():
    from app.services.messaging.kafka_service import kafka_service

    while True:
        for h3_index in H3_INDEXES:
            demand = 1.0 + (time.time() % 3600) / 3600
            demand = min(demand, 2.5)
            demand_data: Dict[str, Any] = {
                "h3_index": h3_index,
                "demand": demand,
                "timestamp": int(time.time()),
            }
            await kafka_service.send_message(KAFKA_TOPIC_DEMAND_UPDATES, demand_data)

        await asyncio.sleep(60)


@app.task(bind=True, max_retries=3, default_retry_delay=60)
async def compute_analytics(self):
    async with AsyncSession(engine) as db:
        try:
            redis = await get_redis_client()

            # Fetch incrementally updated data
            total_bookings = int(await redis.get("analytics:total_bookings") or 0)
            total_revenue = float(await redis.get("analytics:total_revenue") or 0.0)
            recent_prices = json.loads(
                await redis.get("analytics:recent_prices") or "[]"
            )
            active_drivers = int(await redis.get("analytics:active_drivers") or 0)

            avg_price = (
                sum(recent_prices) / len(recent_prices) if recent_prices else 0.0
            )

            # New users in the last 24 hours
            last_24_hours = datetime.utcnow() - timedelta(hours=24)
            new_users = await db.scalar(
                select(func.count(User.id)).where(User.created_at >= last_24_hours)
            )

            # Popular pickup locations
            popular_locations_result = await db.execute(
                select(Booking.pickup_location, func.count(Booking.id).label("count"))
                .where(Booking.date >= last_24_hours)
                .group_by(Booking.pickup_location)
                .order_by(desc("count"))
                .limit(5)
            )
            popular_pickup_locations = [
                {"pickup_location": row.pickup_location, "count": row.count}
                for row in popular_locations_result
            ]

            # Store the final computed analytics
            analytics_data = {
                "timestamp": datetime.utcnow().isoformat(),
                "total_bookings": total_bookings,
                "total_revenue": total_revenue,
                "average_price": avg_price,
                "active_drivers": active_drivers,
                "new_users": new_users or 0,
                "popular_pickup_locations": popular_pickup_locations,
            }
            await redis.set("analytics_data", json.dumps(analytics_data))

            logging.info("Analytics computed and stored successfully")
            return "Analytics computed and stored successfully"

        except Exception as e:
            logging.error(f"Error in compute_analytics: {e}")
            self.retry(exc=e)


@app.task(bind=True, max_retries=3, default_retry_delay=60)
def handle_booking_completion(self, booking_id: int):
    async def _handle():
        async with AsyncSession(engine) as db:
            booking = await db.get(Booking, booking_id)
            if not booking:
                logging.error(f"Booking not found for ID: {booking_id}")
                return

            if booking.status in [
                BookingStatusEnum.cancelled,
                BookingStatusEnum.completed,
            ]:
                driver = await db.get(Driver, booking.driver_id)
                if driver:
                    driver.is_available = True
                    await db.commit()
                    await db.refresh(driver)

                await compute_analytics()

            logging.info(f"Handled completion for booking ID: {booking_id}")
            return "Booking completion handled successfully."

    try:
        return run_async_in_worker(_handle())
    except Exception as e:
        logging.error(f"Error handling booking completion for {booking_id}: {e}")
        self.retry(exc=e)


async def process_immediate_booking(booking_id: int):
    from app.services.booking.immediate_booking import process_immediate_booking as service_process_immediate_booking

    await service_process_immediate_booking(booking_id)


@app.task
def schedule_booking_processing(booking_id: int, scheduled_time: datetime):
    countdown = max((scheduled_time - datetime.utcnow()).total_seconds(), 0)
    process_scheduled_booking.apply_async(args=[booking_id], countdown=countdown)


@app.task(bind=True, max_retries=3, default_retry_delay=60)
def process_scheduled_booking(self, booking_id: int):
    from app.services.booking.scheduler import process_scheduled_booking as service_process_scheduled_booking

    try:
        return run_async_in_worker(service_process_scheduled_booking(booking_id))
    except Exception as e:
        logging.error(f"Error processing scheduled booking {booking_id}: {e}")
        self.retry(exc=e)
