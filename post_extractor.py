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
                        post_date=post_data["date"],
                        media_path=post_data.get("media_path")
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

        from datetime import datetime, timedelta, timezone
        tz = timezone(timedelta(hours=3))
        seven_days_ago = datetime.now(tz) - timedelta(days=7)

        # Ищем посты, которые мы еще не анализировали и которые не старше 7 дней
        stmt = select(Post).where(
            Post.is_ad_or_trash.is_(None),
            Post.post_date >= seven_days_ago
        )
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

        from datetime import datetime, timedelta, timezone
        tz = timezone(timedelta(hours=3))
        seven_days_ago = datetime.now(tz) - timedelta(days=7)

        stmt = select(Post).where(
            Post.is_ad_or_trash == False,
            Post.digest_id.is_(None),
            Post.post_date >= seven_days_ago
        ).order_by(Post.post_date.desc()).limit(max_posts_in_digest)
        
        result = await self.db_session.execute(stmt)
        ready_posts = result.scalars().all()

        if not ready_posts:
            logger.info("Нет готовых постов для сборки дайджеста.")
            return

        logger.info(f"Собираем дайджест из {len(ready_posts)} постов.")

        all_facts = []
        easy_medium_questions = [] 
        hard_questions = []
        total_tokens = 0

        for post in ready_posts:
            for fact in post.facts:
                fact_with_link = f"{fact} [Источник]({post.link})"
                all_facts.append(fact_with_link)
                
            for question in post.questions:
                if question.get("difficulty_level") == "hard":
                    hard_questions.append(question)
                else:
                    easy_medium_questions.append(question)

            if post.tokens:
                total_tokens += post.tokens

        selected_questions = []

        if hard_questions:
            selected_questions.append(random.choice(hard_questions))

        needed = max_questions - len(selected_questions)

        if easy_medium_questions:
            selected_questions.extend(
                random.sample(easy_medium_questions, min(len(easy_medium_questions), needed))
            )

        random.shuffle(selected_questions)       

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

            # Уведомляем админа, если задан ADMIN_TELEGRAM_ID
            import os
            admin_id_str = os.getenv("ADMIN_TELEGRAM_ID")
            bot_token = os.getenv("BOT_TOKEN")
            if admin_id_str and bot_token:
                try:
                    from aiogram import Bot
                    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto, FSInputFile
                    
                    admin_id = int(admin_id_str)
                    temp_bot = Bot(token=bot_token)
                    
                    # Сбор прикрепленных фото
                    photos = [p.media_path for p in ready_posts if p.media_path and os.path.exists(p.media_path)]
                    
                    buttons = []
                    if photos:
                        # Отправляем фото альбомом
                        media_group = []
                        for idx, photo_path in enumerate(photos, 1):
                            media_group.append(InputMediaPhoto(media=FSInputFile(photo_path), caption=f"Фото {idx}"))
                        
                        await temp_bot.send_message(
                            chat_id=admin_id,
                            text=f"🖼 *К черновику Дайджеста #{new_digest.id} прикреплены изображения ({len(photos)} шт.):*"
                        )
                        await temp_bot.send_media_group(chat_id=admin_id, media=media_group)
                        
                        # Кнопка публикации без фото
                        buttons.append([InlineKeyboardButton(
                            text="✅ Опубликовать без фото",
                            callback_data=f"approve_digest:{new_digest.id}:no_photo"
                        )])
                        
                        # Кнопки для каждого фото
                        photo_buttons = []
                        for idx in range(len(photos)):
                            photo_buttons.append(InlineKeyboardButton(
                                text=f"🖼 С Фото {idx + 1}",
                                callback_data=f"approve_digest:{new_digest.id}:photo_{idx}"
                            ))
                        # Разделяем по две кнопки в ряд
                        for i in range(0, len(photo_buttons), 2):
                            buttons.append(photo_buttons[i:i+2])
                    else:
                        buttons.append([InlineKeyboardButton(
                            text="✅ Одобрить и опубликовать",
                            callback_data=f"approve_digest:{new_digest.id}:no_photo"
                        )])
                        
                    # Кнопка удаления черновика
                    buttons.append([InlineKeyboardButton(
                        text="❌ Удалить",
                        callback_data=f"delete_digest:{new_digest.id}"
                    )])
                    
                    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
                    
                    # Разрезаем текст на куски, если превышает лимиты Telegram
                    from bot import split_text
                    chunks = split_text(digest_content, limit=3500)
                    
                    await temp_bot.send_message(
                        chat_id=admin_id,
                        text=f"📝 *Черновик Дайджеста #{new_digest.id} готов для проверки!*"
                    )
                    
                    for idx, chunk in enumerate(chunks):
                        is_last = (idx == len(chunks) - 1)
                        await temp_bot.send_message(
                            chat_id=admin_id,
                            text=chunk,
                            reply_markup=keyboard if is_last else None
                        )
                    await temp_bot.session.close()
                    logger.info(f"Черновик дайджеста #{new_digest.id} успешно отправлен админу {admin_id}")
                except Exception as admin_err:
                    logger.error(f"Ошибка при отправке черновика админу: {admin_err}")

        except Exception as e:
            logger.error(f"Ошибка при сборке дайджеста: {e}")
            await self.db_session.rollback()