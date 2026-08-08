"""Сервис сбора и персистентности сырых постов из Telegram каналов."""

import asyncio
import hashlib
import logging
import random
from typing import List

import redis.asyncio as redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.post import Post
from parser.telegram_parser import TGParser
from core.constants import DEFAULT_CACHE_TTL_DAYS

logger = logging.getLogger(__name__)


class PostIngestionService:
    def __init__(
        self,
        tg_sources: List[str],
        tg_parser: TGParser,
        db_session: AsyncSession,
        redis_client: redis.Redis,
        cache_ttl_days: int = DEFAULT_CACHE_TTL_DAYS,
    ):
        self.tg_sources = tg_sources
        self.tg_parser = tg_parser
        self.db_session = db_session
        self.redis = redis_client
        self.cache_ttl_seconds = cache_ttl_days * 24 * 60 * 60

    def _get_url_hash(self, url: str) -> str:
        return hashlib.md5(url.encode("utf-8")).hexdigest()

    async def _is_cached(self, url: str) -> bool:
        """Проверяет наличие ссылки в Redis."""
        try:
            key = f"tg_post:{self._get_url_hash(url)}"
            return await self.redis.exists(key) > 0
        except Exception as e:
            logger.error(f"Ошибка Redis при чтении {url}: {e}")
            return False

    async def _cache_url(self, url: str):
        """Сохраняет ссылку в Redis."""
        try:
            key = f"tg_post:{self._get_url_hash(url)}"
            await self.redis.set(key, "processed", ex=self.cache_ttl_seconds)
        except Exception as e:
            logger.error(f"Ошибка Redis при записи {url}: {e}")

    async def _is_in_db(self, link: str) -> bool:
        """Проверяет наличие поста в БД."""
        stmt = select(Post.id).where(Post.link == link).limit(1)
        res = await self.db_session.execute(stmt)
        return res.scalar() is not None

    async def run_parsing_job(self):
        """Пробегает по каналам и сохраняет новые сообщения в БД."""
        logger.info("Запуск джобы парсинга Telegram...")

        try:
            await self.tg_parser.start()
            for idx, channel in enumerate(self.tg_sources):
                if idx > 0:
                    delay = random.uniform(5.0, 10.0)
                    logger.info(f"Спим {delay:.2f} секунд перед парсингом следующего канала...")
                    await asyncio.sleep(delay)
                logger.info(f"Парсим канал: {channel}")

                try:
                    posts = await self.tg_parser.parse_channel(channel)

                    for post_data in posts:
                        link = post_data["link"]

                        if await self._is_cached(link):
                            continue

                        if await self._is_in_db(link):
                            await self._cache_url(link)
                            continue

                        new_post = Post(
                            link=link,
                            title=f"Post from {channel}",
                            content=post_data["text"],
                            post_date=post_data["date"],
                            media_path=post_data.get("media_path")
                        )
                        self.db_session.add(new_post)

                        await self.db_session.commit()
                        await self._cache_url(link)
                        logger.info(f"Сохранен новый сырой пост: {link}")
                except Exception as channel_err:
                    logger.error(f"Ошибка при обработке канала {channel}: {channel_err}")
                    await self.db_session.rollback()

        except Exception as e:
            logger.error(f"Ошибка во время парсинга: {e}")
            await self.db_session.rollback()
        finally:
            await self.tg_parser.close()
