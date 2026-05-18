import logging
import hashlib
import asyncio
import random

from typing import Optional
from datetime import datetime

import redis.asyncio as redis
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from models import Post, Digest, Quiz
from telegram_parser import TGParser
from llm_layer import MessageExtractor

logger = logging.getLogger(__name__)

class DigestPipeline:
    def __init__(
        self,
        tg_sources: list[str],
        tg_parser: TGParser,
        extractor: MessageExtractor,
        db_session: AsyncSession,
        redis_client: redis.Redis,
        cache_ttl_days: int = 30,
    ):
        self.tg_sources = tg_sources
        self.tg_parser = tg_parser
        self.extractor = extractor
        self.db_session = db_session
        self.redis = redis_client
        self.cache_ttl_seconds = cache_ttl_days * 24 * 60 * 60

    def _get_url_hash(self, url: str) -> str:
        return hashlib.md5(url.encode("utf-8")).hexdigest()

    async def _is_cached(self, url: str) -> bool:
        """Проверяет наличие абсолютной ссылки в Redis."""
        try:
            key = f"tg_post:{self._get_url_hash(url)}"
            return await self.redis.exists(key) > 0
        except Exception as e:
            logger.error(f"Ошибка Redis при чтении {url}: {e}")
            return False # Fallback: если редис упал, идем дальше

    async def _cache_url(self, url: str):
        """Сохраняет ссылку в Redis на месяц."""
        try:
            key = f"tg_post:{self._get_url_hash(url)}"
            await self.redis.set(key, "processed", ex=self.cache_ttl_seconds)
        except Exception as e:
            logger.error(f"Ошибка Redis при записи {url}: {e}")

    async def _is_in_db(self, link: str) -> bool:
        """Проверка дубликата в самой БД на всякий случай."""
        stmt = select(Post.id).where(Post.link == link).limit(1)
        res = await self.db_session.execute(stmt)
        return res.scalar() is not None

    async def run_parsing_job(self):
        """Пробегает по каналам и сохраняет новые сообщения в БД."""
        logger.info("Запуск джобы парсинга Telegram...")
        await self.tg_parser.start()

        try:
            for channel in self.tg_sources:
                logger.info(f"Парсим канал: {channel}")
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
                        post_date=post_data["date"]
                    )
                    self.db_session.add(new_post)
                    
                    await self.db_session.commit() 
                    await self._cache_url(link)
                    logger.info(f"Сохранен новый сырой пост: {link}")

        except Exception as e:
            logger.error(f"Ошибка во время парсинга: {e}")
            await self.db_session.rollback()
        finally:
            await self.tg_parser.close()

    async def run_llm_processing_job(self, schema: dict):
        """Берет сырые посты из БД и прогоняет через LLM."""
        logger.info("Запуск джобы обработки LLM...")

        # Ищем посты, которые мы еще не анализировали
        stmt = select(Post).where(Post.is_ad_or_trash.is_(None))
        result = await self.db_session.execute(stmt)
        unprocessed_posts = result.scalars().all()

        if not unprocessed_posts:
            logger.info("Нет новых постов для обработки.")
            return

        logger.info(f"Найдено {len(unprocessed_posts)} постов для анализа.")

        for post in unprocessed_posts:
            try:
                # Генерируем промпт из твоего llm_layer
                prompt = self.extractor.build_message_extraction_prompt(
                    text=post.content, 
                    url=post.link, 
                    reference_date=post.post_date
                )
                
                # В llm_layer.call_llm у тебя нет async, поэтому оборачиваем в to_thread,
                # если библиотека OpenAI вызывается синхронно.
                response = await asyncio.to_thread(
                    self.extractor.call_llm, 
                    user_prompt=prompt, 
                    schema=schema
                )

                if not response:
                    logger.warning(f"LLM вернула пустой ответ для {post.link}")
                    post.is_ad_or_trash = True # Помечаем как мусор, чтобы не зацикливаться
                    await self.db_session.commit()
                    continue

                llm_data, tokens = response

                # Обновляем запись в БД
                post.is_ad_or_trash = llm_data.get("is_ad_or_trash", True)
                post.llm_analysis = llm_data.get("analysis", "")
                post.facts = llm_data.get("facts", [])
                post.questions = llm_data.get("questions", [])
                post.tokens = tokens
                # Записываем, какая модель это обработала (берем первый ключ из пула)
                post.model_name = self.extractor.model_names[0]

                await self.db_session.commit()
                logger.info(f"Пост {post.link} успешно обработан. Токенов: {tokens}")
                
                # Задержка, чтобы не биться в Rate Limits
                await asyncio.sleep(2) 

            except Exception as e:
                logger.error(f"Ошибка при обработке поста {post.id} LLM: {e}")
                await self.db_session.rollback()

    async def run_digest_assembly_job(self, max_posts_in_digest: int = 5, max_questions: int = 5):
        """Собирает готовые посты в дайджест и формирует квиз."""
        logger.info("Запуск джобы сборки дайджеста...")

        stmt = select(Post).where(
            Post.is_ad_or_trash == False,
            Post.digest_id.is_(None)
        ).order_by(Post.post_date.desc()).limit(max_posts_in_digest)
        
        result = await self.db_session.execute(stmt)
        ready_posts = result.scalars().all()

        if not ready_posts:
            logger.info("Нет готовых постов для сборки дайджеста.")
            return

        logger.info(f"Собираем дайджест из {len(ready_posts)} постов.")

        # 2. Собираем факты и вопросы
        all_facts = []
        all_questions = []
        total_tokens = 0

        for post in ready_posts:
            all_facts.extend(post.facts)
            all_questions.extend(post.questions)
            if post.tokens:
                total_tokens += post.tokens

        selected_questions = random.sample(
            all_questions, 
            min(len(all_questions), max_questions)
        )

        try:
 
            facts = "\n\n".join([f"• {fact}" for fact in all_facts])
            prompt = self.extractor.build_message_extraction_prompt(
                    text=facts, 
                    digest=True
                )
                

            response = await asyncio.to_thread(
                    self.extractor.call_llm, 
                    user_prompt=prompt, 
                ) 
            
            if not response:
                logger.warning(f"LLM вернула пустой ответ для дайджеста")
                return

            digest_content, tokens = response

            
            new_digest = Digest(
                total_tokens=total_tokens + tokens,
                content=digest_content,
                facts=all_facts
            )
            self.db_session.add(new_digest)
            await self.db_session.flush() 

            for post in ready_posts:
                post.digest_id = new_digest.id

            new_quiz = Quiz(
                digest_id=new_digest.id,
                questions=selected_questions
            )
            self.db_session.add(new_quiz)

            await self.db_session.commit()
            logger.info(f"Успешно создан Дайджест #{new_digest.id} и Квиз на {len(selected_questions)} вопросов.")

        except Exception as e:
            logger.error(f"Ошибка при сборке дайджеста: {e}")
            await self.db_session.rollback()