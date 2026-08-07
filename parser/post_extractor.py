import logging
import hashlib
import asyncio
import random
import os

from typing import Optional
from datetime import datetime

import redis.asyncio as redis
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, and_

from models import Post, Digest, Quiz
from .telegram_parser import TGParser
from .llm_layer import MessageExtractor
from tg_bot.bot_instance import get_bot

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

        try:
            await self.tg_parser.start()
            for idx, channel in enumerate(self.tg_sources):
                if idx > 0:
                    delay = random.uniform(5.0, 10.0)
                    logger.info(f"Спим {delay:.2f} секунд перед парсингом следующего канала для избежания Flood Wait...")
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

    async def run_llm_processing_job(self, schema: dict, max_posts: Optional[int] = None, model_name: Optional[str] = None):
        """Берет сырые посты из БД и прогоняет через LLM."""
        logger.info("Запуск джобы обработки LLM...")

        from datetime import datetime, timedelta, timezone
        tz = timezone(timedelta(hours=3))
        seven_days_ago = datetime.now(tz) - timedelta(days=7)

        # Ищем ID постов, которые мы еще не анализировали и которые не старше 7 дней
        # Сортируем по убыванию даты, чтобы в первую очередь обрабатывать самые новые посты
        stmt = select(Post.id).where(
            Post.is_ad_or_trash.is_(None),
            Post.content.is_not(None),
            Post.content != "",
            Post.post_date >= seven_days_ago
        ).order_by(Post.post_date.desc())

        if max_posts is not None:
            stmt = stmt.limit(max_posts)

        result = await self.db_session.execute(stmt)
        unprocessed_post_ids = result.scalars().all()

        if not unprocessed_post_ids:
            logger.info("Нет новых постов для обработки.")
            return

        logger.info(f"Найдено {len(unprocessed_post_ids)} постов для анализа.")

        for post_id in unprocessed_post_ids:
            # Получаем свежий объект Post из сессии по его ID.
            post = await self.db_session.get(Post, post_id)
            if not post:
                continue

            if not post.content or len(post.content.strip()) < 30:
                logger.info(f"Пост #{post.id} содержит пустой или слишком короткий текст ({len(post.content or '')} симв.). Метим как мусор.")
                post.is_ad_or_trash = True
                await self.db_session.commit()
                continue

            post_link = post.link
            try:
                # Генерируем промпт из твоего llm_layer
                prompt = self.extractor.build_message_extraction_prompt(
                    text=post.content, 
                    url=post_link, 
                    reference_date=post.post_date
                )
                
                response = await asyncio.to_thread(
                    self.extractor.call_llm, 
                    user_prompt=prompt, 
                    schema=schema,
                    model_name=model_name
                )

                if not response:
                    logger.warning(f"LLM вернула пустой ответ для {post_link}")
                    post.is_ad_or_trash = True
                    await self.db_session.commit()
                    continue

                llm_data, tokens = response

                # Обновляем запись в БД для двух форматов
                is_tech = llm_data.get("is_tech_relevant", False)
                is_simple = llm_data.get("is_simple_relevant", False)
                is_trash = llm_data.get("is_ad_or_trash", True) or (not is_tech and not is_simple)

                post.is_ad_or_trash = is_trash
                post.is_tech_relevant = is_tech
                post.is_simple_relevant = is_simple
                post.llm_analysis = llm_data.get("analysis", "")
                
                post.tech_facts = llm_data.get("tech_facts", [])
                post.simple_facts = llm_data.get("simple_facts", [])
                post.tech_questions = llm_data.get("tech_questions", [])
                post.simple_questions = llm_data.get("simple_questions", [])

                # Совместимость с наследуемыми полями
                post.facts = post.tech_facts or post.simple_facts or llm_data.get("facts", [])
                post.questions = post.tech_questions or post.simple_questions or llm_data.get("questions", [])

                post.tokens = tokens
                post.model_name = model_name or (self.extractor.model_names[0] if self.extractor.model_names else "deepseek/deepseek-v4-pro")

                await self.db_session.commit()
                logger.info(f"Пост {post_link} успешно обработан (tech={is_tech}, simple={is_simple}). Токенов: {tokens}")
                
                # Задержка, чтобы не биться в Rate Limits
                await asyncio.sleep(2) 

            except Exception as e:
                logger.error(f"Ошибка при обработке поста {post_id} LLM: {e}")
                await self.db_session.rollback()

    async def run_digest_assembly_job(
        self,
        digest_type: str = "tech",
        is_sunday_quiz: bool = False,
        max_posts_in_digest: Optional[int] = None,
        max_questions: int = 5,
        model_name: Optional[str] = None
    ):
        """Собирает готовые посты в дайджест заданного формата (tech/simple) и формирует квиз."""
        logger.info(f"Запуск джобы сборки дайджеста format={digest_type} (is_sunday_quiz={is_sunday_quiz})...")

        from datetime import datetime, timedelta, timezone
        tz = timezone(timedelta(hours=3))
        seven_days_ago = datetime.now(tz) - timedelta(days=7)

        if digest_type == "simple":
            stmt = select(Post).where(
                or_(
                    Post.is_simple_relevant == True,
                    and_(Post.is_ad_or_trash == False, Post.is_simple_relevant.is_(None))
                ),
                Post.simple_digest_id.is_(None)
            ).order_by(Post.post_date.desc())
        else:
            stmt = select(Post).where(
                or_(
                    Post.is_tech_relevant == True,
                    and_(Post.is_ad_or_trash == False, Post.is_tech_relevant.is_(None))
                ),
                Post.tech_digest_id.is_(None)
            ).order_by(Post.post_date.desc())
        
        if max_posts_in_digest is not None:
            stmt = stmt.limit(max_posts_in_digest)
        
        result = await self.db_session.execute(stmt)
        ready_posts = result.scalars().all()

        if not ready_posts:
            logger.info(f"Нет готовых постов для сборки {digest_type}-дайджеста.")
            return

        logger.info(f"Собираем {digest_type}-дайджест из {len(ready_posts)} постов.")

        all_facts = []
        total_tokens = 0

        for post in ready_posts:
            p_facts = (post.simple_facts if digest_type == "simple" else post.tech_facts) or post.facts
            for fact in p_facts:
                fact_with_link = f"{fact} [Источник]({post.link})"
                all_facts.append(fact_with_link)

            if post.tokens:
                total_tokens += post.tokens

        selected_questions = []
        if is_sunday_quiz:
            logger.info(f"Сбор кандидатов для еженедельного {digest_type}-квиза за последние 7 дней...")
            if digest_type == "simple":
                quiz_posts_stmt = select(Post).where(
                    or_(
                        Post.is_simple_relevant == True,
                        and_(Post.is_ad_or_trash == False, Post.is_simple_relevant.is_(None))
                    ),
                    Post.post_date >= seven_days_ago
                )
            else:
                quiz_posts_stmt = select(Post).where(
                    or_(
                        Post.is_tech_relevant == True,
                        and_(Post.is_ad_or_trash == False, Post.is_tech_relevant.is_(None))
                    ),
                    Post.post_date >= seven_days_ago
                )

            quiz_posts_res = await self.db_session.execute(quiz_posts_stmt)
            weekly_posts = quiz_posts_res.scalars().all()

            candidate_questions = []
            for wp in weekly_posts:
                q_list = (wp.simple_questions if digest_type == "simple" else wp.tech_questions) or wp.questions
                if q_list:
                    candidate_questions.extend(q_list)

            if candidate_questions:
                models_to_try = []
                if model_name:
                    models_to_try.append(model_name)
                for m in self.extractor.model_names:
                    if m not in models_to_try:
                        models_to_try.append(m)
                if not models_to_try:
                    models_to_try = ["deepseek/deepseek-v4-pro", "google/gemini-2.5-flash"]

                for m in models_to_try:
                    try:
                        from .prompts import weekly_quiz_selection_schema
                        quiz_prompt = self.extractor.build_weekly_quiz_selection_prompt(candidate_questions)
                        quiz_response = await asyncio.to_thread(
                            self.extractor.call_llm,
                            user_prompt=quiz_prompt,
                            schema=weekly_quiz_selection_schema,
                            model_name=m
                        )
                        if quiz_response and quiz_response[0]:
                            quiz_data, quiz_tokens = quiz_response
                            total_tokens += quiz_tokens
                            candidate_sel = quiz_data.get("questions", [])
                            if candidate_sel:
                                selected_questions = candidate_sel
                                logger.info(f"LLM ({m}) успешно отобрала {len(selected_questions)} вопросов для {digest_type}-квиза.")
                                break
                    except Exception as q_err:
                        logger.error(f"Ошибка при LLM-отборе {digest_type}-квиза моделью {m}: {q_err}", exc_info=True)

            if not selected_questions:
                logger.warning(f"Все попытки LLM-отбора вопросов для {digest_type}-квиза вернули пустой результат.")

        try:
            facts = "\n\n".join([f"• {fact}" for fact in all_facts])
            prompt = self.extractor.build_message_extraction_prompt(
                text=facts, 
                digest=True,
                has_quiz=is_sunday_quiz,
                digest_type=digest_type
            )
                
            models_to_try = []
            if model_name:
                models_to_try.append(model_name)
            for fallback_m in self.extractor.model_names:
                if fallback_m not in models_to_try:
                    models_to_try.append(fallback_m)

            response = None
            used_model = model_name
            for m in models_to_try:
                try:
                    res = await asyncio.to_thread(
                        self.extractor.call_llm, 
                        user_prompt=prompt, 
                        model_name=m
                    )
                    if res and res[0] and res[0].strip():
                        response = res
                        used_model = m
                        break
                except Exception as d_err:
                    logger.warning(f"Модель {m} при генерации {digest_type}-дайджеста вернула ошибку: {d_err}")

            if not response or not response[0] or not response[0].strip():
                logger.warning(f"Все попытки LLM сгенерировать {digest_type}-дайджест вернули пустой контент.")
                return

            digest_content, tokens = response

            new_digest = Digest(
                total_tokens=total_tokens + tokens,
                content=digest_content,
                facts=all_facts,
                digest_type=digest_type,
                model_name=used_model or (self.extractor.model_names[0] if self.extractor.model_names else "google/gemini-2.5-flash")
            )
            self.db_session.add(new_digest)
            await self.db_session.flush() 

            for post in ready_posts:
                post.digest_id = new_digest.id
                if digest_type == "simple":
                    post.simple_digest_id = new_digest.id
                else:
                    post.tech_digest_id = new_digest.id

            if is_sunday_quiz and selected_questions:
                new_quiz = Quiz(
                    digest_id=new_digest.id,
                    questions=selected_questions
                )
                self.db_session.add(new_quiz)

            await self.db_session.commit()
            logger.info(f"Успешно создан Дайджест #{new_digest.id} ({digest_type}) (Квиз вопросов: {len(selected_questions)}).")

            # Auto-publishing flow
            auto_publish = os.getenv("AUTO_PUBLISH", "True").lower() in ("true", "1", "yes")
            photo_path = None
            photos = [p.media_path for p in ready_posts if p.media_path and os.path.exists(p.media_path)]
            
            if auto_publish:
                logger.info(f"Запуск автопубликации для дайджеста #{new_digest.id}...")
                try:
                    if photos:
                        photo_path = photos[0]
                    from tg_bot.publisher import publish_digest_by_id
                    await publish_digest_by_id(new_digest.id, photo_path=photo_path)
                    logger.info(f"Дайджест #{new_digest.id} успешно опубликован автоматически.")
                except Exception as pub_err:
                    logger.error(f"Ошибка автопубликации дайджеста #{new_digest.id}: {pub_err}", exc_info=True)

            # Уведомляем админа, если задан ADMIN_TELEGRAM_ID
            admin_id_str = os.getenv("ADMIN_TELEGRAM_ID")
            bot_token = os.getenv("BOT_TOKEN")
            if admin_id_str and bot_token:
                try:
                    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto, FSInputFile
                    
                    admin_id = int(admin_id_str)
                    temp_bot = get_bot()
                    
                    if auto_publish:
                        # Send a simple notification about automatic publishing
                        await temp_bot.send_message(
                            chat_id=admin_id,
                            text=f"🚀 *Дайджест #{new_digest.id} был успешно сформирован и автоматически опубликован в канале!*"
                        )
                    else:
                        # Send manual review options
                        buttons = []
                        if photos:
                            # Отправляем фото альбомом
                            media_group = []
                            for idx, p_path in enumerate(photos, 1):
                                media_group.append(InputMediaPhoto(media=FSInputFile(p_path), caption=f"Фото {idx}"))
                            
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
                        from tg_bot.publisher import split_text
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
                    logger.info(f"Уведомление о дайджесте #{new_digest.id} успешно отправлено админу {admin_id}")
                except Exception as admin_err:
                    logger.error(f"Ошибка при отправке уведомления админу: {admin_err}")

        except Exception as e:
            logger.error(f"Ошибка при сборке дайджеста: {e}")
            await self.db_session.rollback()
