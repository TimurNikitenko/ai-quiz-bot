"""Управление подключениями к Redis."""

from typing import Optional, AsyncGenerator
from contextlib import asynccontextmanager
import redis.asyncio as redis
from core.config import get_settings


def get_redis_client(
    host: Optional[str] = None,
    port: Optional[int] = None,
    password: Optional[str] = None
) -> redis.Redis:
    """Возвращает клиент redis.Redis."""
    settings = get_settings()
    h = host or settings.redis_host
    p = port or settings.redis_port
    pwd = password if password is not None else settings.redis_password

    return redis.Redis(
        host=h,
        port=p,
        password=pwd,
        decode_responses=True
    )


@asynccontextmanager
async def get_redis_session() -> AsyncGenerator[redis.Redis, None]:
    """Асинхронный контекстный менеджер для работы с Redis клиентом."""
    client = get_redis_client()
    try:
        yield client
    finally:
        await client.close()
