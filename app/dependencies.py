import json
import time
from datetime import datetime, timedelta
from functools import wraps

import redis.asyncio as redis_asyncio
import httpx
from app.models import Driver, RoleEnum, User
from db.database import get_db
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from pydantic import BaseSettings
from sqlalchemy.orm import Session

from .config import settings

redis = redis_asyncio.from_url(
    settings.REDIS_URL, decode_responses=True, max_connections=10
)


class Settings(BaseSettings):
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    GOOGLE_MAPS_API_KEY: str

    class Config:
        env_file = ".env"


settings = Settings()


class Cache:
    async def get(self, key):
        value = await redis.get(key)
        return json.loads(value) if value else None

    async def set(self, key, value, expire=None):
        serialized_value = json.dumps(value)
        await redis.set(key, serialized_value, ex=expire)


cache = Cache()


class RateLimiter:
    def __init__(self, redis_client):
        self.redis = redis_client

    async def is_rate_limited(self, key, max_calls, time_frame):
        current = await self.redis.incr(key)
        if current == 1:
            await self.redis.expire(key, time_frame)
        if current > max_calls:
            return True
        return False


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


async def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    user = db.query(User).filter(User.email == username).first()
    if user is None:
        raise credentials_exception
    return user


async def get_current_driver(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials for driver",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        user_id: int = payload.get("user_id")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    driver = db.query(Driver).filter(Driver.id == user_id).first()
    if driver is None:
        raise credentials_exception
    return driver


async def get_current_user_object(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
):
    return await get_current_user(token, db)


async def get_current_admin(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
):
    user = await get_current_user(token, db)
    if user.role.name != RoleEnum.admin:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return user


class SlidingWindowRateLimiter:
    def __init__(self, max_requests, window_size):
        self.max_requests = max_requests
        self.window_size = window_size
        self.requests = []

    async def is_rate_limited(self, key):
        current_time = time.time()
        self.requests = [
            req for req in self.requests if current_time - req < self.window_size
        ]
        if len(self.requests) >= self.max_requests:
            return True
        self.requests.append(current_time)
        return False


rate_limiter = SlidingWindowRateLimiter(max_requests=100, window_size=60)


def rate_limit(max_calls=None, time_frame=None):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            request = kwargs.get("request")
            if request is None:
                for arg in args:
                    if isinstance(arg, Request):
                        request = arg
                        break

            if request is not None:
                client_ip = request.client.host
                if await rate_limiter.is_rate_limited(client_ip):
                    raise HTTPException(status_code=429, detail="Rate limit exceeded")

            return await func(*args, **kwargs)

        return wrapper

    return decorator


SECRET_KEY = "your-secret-key"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30


def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


async def fetch_external_data(url: str, params: dict = None) -> dict:
    async with httpx.AsyncClient() as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        return response.json()
