from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.main import health_live, health_ready


@pytest.mark.asyncio
async def test_liveness_does_not_depend_on_backends():
    assert await health_live() == {"status": "ok"}


@pytest.mark.asyncio
async def test_readiness_rejects_unavailable_database():
    engine = MagicMock()
    engine.connect.side_effect = RuntimeError("db down")
    with patch("app.main.engine", engine):
        with pytest.raises(HTTPException) as error:
            await health_ready()
    assert error.value.status_code == 503


@pytest.mark.asyncio
async def test_readiness_requires_kafka_producer():
    connection = AsyncMock()
    connection.__aenter__.return_value = connection
    engine = MagicMock()
    engine.connect.return_value = connection
    redis = AsyncMock()
    with patch("app.main.engine", engine), patch(
        "app.main.redis_asyncio.from_url", return_value=redis
    ), patch("app.main.kafka_service.producer", None):
        with pytest.raises(HTTPException) as error:
            await health_ready()
    assert error.value.status_code == 503


@pytest.mark.asyncio
async def test_readiness_accepts_healthy_backends():
    connection = AsyncMock()
    connection.__aenter__.return_value = connection
    engine = MagicMock()
    engine.connect.return_value = connection
    redis = AsyncMock()
    with patch("app.main.engine", engine), patch(
        "app.main.redis_asyncio.from_url", return_value=redis
    ), patch("app.main.kafka_service.producer", object()):
        assert await health_ready() == {"status": "ok"}
    redis.ping.assert_awaited_once()
    redis.aclose.assert_awaited_once()
