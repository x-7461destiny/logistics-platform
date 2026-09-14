import json

import redis.asyncio as redis_asyncio
from app.config import settings

REDIS_URL = settings.REDIS_URL


async def get_redis_client():
    return redis_asyncio.from_url(REDIS_URL, encoding="utf-8", decode_responses=True)


class Cache:
    async def get(self, key):
        redis = await get_redis_client()
        value = await redis.get(key)
        if value is None:
            return None
        try:
            return json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return value

    async def set(self, key, value, expire=None):
        redis = await get_redis_client()
        serialized_value = json.dumps(value) if isinstance(value, (dict, list)) else value
        await redis.set(key, serialized_value, ex=expire)


cache = Cache()


async def cache_driver_availability(driver_id: int, is_available: bool):
    redis = await get_redis_client()
    await redis.set(f"driver:availability:{driver_id}", str(is_available))
    await redis.expire(f"driver:availability:{driver_id}", 3600)  # Cache for 1 hour


async def get_driver_availability(driver_id: int) -> bool:
    redis = await get_redis_client()
    availability = await redis.get(f"driver:availability:{driver_id}")
    return availability == "True" if availability else False


async def cache_booking_status(booking_id: int, status: str):
    redis = await get_redis_client()
    await redis.set(f"booking:status:{booking_id}", status)
    await redis.expire(f"booking:status:{booking_id}", 3600)  # Cache for 1 hour


async def get_booking_status(booking_id: int) -> str:
    redis = await get_redis_client()
    status = await redis.get(f"booking:status:{booking_id}")
    return status if status else "Unknown"
