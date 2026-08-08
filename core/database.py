"""Управление подключениями и сессиями базы данных PostgreSQL."""

from typing import Optional, AsyncGenerator
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession, AsyncEngine
from core.config import get_settings


def get_async_engine(database_url: Optional[str] = None) -> AsyncEngine:
    """Создает AsyncEngine для подключения к БД."""
    url = database_url or get_settings().database_url
    return create_async_engine(url, echo=False)


def get_session_factory(engine: Optional[AsyncEngine] = None) -> async_sessionmaker[AsyncSession]:
    """Создает фабрику сессий async_sessionmaker."""
    target_engine = engine or get_async_engine()
    return async_sessionmaker(target_engine, expire_on_commit=False)


@asynccontextmanager
async def get_db_session(
    session_factory: Optional[async_sessionmaker[AsyncSession]] = None
) -> AsyncGenerator[AsyncSession, None]:
    """Асинхронный контекстный менеджер для получения сессии БД."""
    factory = session_factory or get_session_factory()
    async with factory() as session:
        yield session
