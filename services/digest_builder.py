"""Сервис сборки дайджестов и отбора вопросов для еженедельного квиза."""

import os
import asyncio
import logging
from typing import Optional, List
from datetime import datetime

from sqlalchemy import select, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession

from models import Post, Digest, Quiz, PublishedDigest
from parser.llm_layer import MessageExtractor
from tg_bot.bot_instance import get_bot
from tg_bot.keyboards import get_digest_review_keyboard
from core.config import get_settings
from core.constants import DEFAULT_MAX_QUESTIONS_PER_QUIZ, DEFAULT_CUTOFF_HOURS
from utils.text_helpers import split_text
from utils.time_utils import get_seven_days_ago, get_cutoff_time
from utils.media_helpers import extract_valid_media_paths

logger = logging.getLogger(__name__)


class DigestBuilderService:
    def __init__(
        self,
        extractor: MessageExtractor,
        db_session: AsyncSession,
    ):
        self.extractor = extractor
        self.db_session = db_session
        self.settings = get_settings()

    async def _get_cutoff_date(self, digest_type: str) -> datetime:
        """Вычисляет cutoff времени для постов (не более 24 часов или с момента последнего опубликованного дайджеста)."""
        last_published_stmt = (
            select(PublishedDigest.created_at)
            .join(Digest, PublishedDigest.digest_id == Digest.id)
            .where(Digest.digest_type == digest_type)
            .order_by(PublishedDigest.created_at.desc())
            .limit(1)
        )
        last_pub_res = await self.db_session.execute(last_published_stmt)
        last_pub_date = last_pub_res.scalar()

        if not last_pub_date:
            last_digest_stmt = (
                select(Digest.created_at)
                .where(Digest.digest_type == digest_type, Digest.is_published == True)
                .order_by(Digest.created_at.desc())
                .limit(1)
            )
            last_pub_date = (await self.db_session.execute(last_digest_stmt)).scalar()

        return get_cutoff_time(last_pub_date, hours=DEFAULT_CUTOFF_HOURS)

    async def run_digest_assembly_job(
        self,
        digest_type: str = "tech",
        is_sunday_quiz: bool = False,
        max_posts_in_digest: Optional[int] = None,
        max_questions: int = DEFAULT_MAX_QUESTIONS_PER_QUIZ,
        model_name: Optional[str] = None
    ) -> Optional[Digest]:
        """Собирает готовые посты в дайджест заданного формата (tech/simple) и формирует квиз."""
        logger.info(f"Запуск джобы сборки дайджеста format={digest_type} (is_sunday_quiz={is_sunday_quiz})...")

        seven_days_ago = get_seven_days_ago()
        cutoff_date = await self._get_cutoff_date(digest_type)

        if digest_type == "simple":
            stmt = select(Post).where(
                or_(
                    Post.is_simple_relevant == True,
                    and_(Post.is_ad_or_trash == False, Post.is_simple_relevant.is_(None))
                ),
                Post.simple_digest_id.is_(None),
                Post.post_date >= cutoff_date
            ).order_by(Post.post_date.desc())
        else:
            stmt = select(Post).where(
                or_(
                    Post.is_tech_relevant == True,
                    and_(Post.is_ad_or_trash == False, Post.is_tech_relevant.is_(None))
                ),
                Post.tech_digest_id.is_(None),
                Post.post_date >= cutoff_date
            ).order_by(Post.post_date.desc())

        if max_posts_in_digest is not None:
            stmt = stmt.limit(max_posts_in_digest)

        result = await self.db_session.execute(stmt)
        ready_posts = result.scalars().all()

        if not ready_posts:
            logger.info(f"Нет готовых постов для сборки {digest_type}-дайджеста.")
            return None

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
                    models_to_try = [self.settings.llm_expensive_model, self.settings.llm_cheap_model]

                for m in models_to_try:
                    try:
                        from parser.prompts import weekly_quiz_selection_schema
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
                return None

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

            auto_publish = self.settings.auto_publish
            photos = extract_valid_media_paths(ready_posts)
            photo_path = photos[0] if photos else None

            if auto_publish:
                logger.info(f"Запуск автопубликации для дайджеста #{new_digest.id}...")
                try:
                    from tg_bot.publisher import publish_digest_by_id
                    await publish_digest_by_id(new_digest.id, photo_path=photo_path)
                    logger.info(f"Дайджест #{new_digest.id} успешно опубликован автоматически.")
                except Exception as pub_err:
                    logger.error(f"Ошибка автопубликации дайджеста #{new_digest.id}: {pub_err}", exc_info=True)

            admin_id_str = self.settings.admin_telegram_id
            bot_token = self.settings.bot_token
            if admin_id_str and bot_token:
                try:
                    from aiogram.types import InputMediaPhoto, FSInputFile

                    admin_id = int(admin_id_str)
                    temp_bot = get_bot()

                    if auto_publish:
                        await temp_bot.send_message(
                            chat_id=admin_id,
                            text=f"🚀 *Дайджест #{new_digest.id} ({digest_type}) был успешно сформирован и автоматически опубликован в канале!*"
                        )
                    else:
                        if photos:
                            media_group = [InputMediaPhoto(media=FSInputFile(p), caption=f"Фото {i}") for i, p in enumerate(photos, 1)]
                            await temp_bot.send_message(
                                chat_id=admin_id,
                                text=f"🖼 *К черновику Дайджеста #{new_digest.id} ({digest_type}) прикреплены изображения ({len(photos)} шт.):*"
                            )
                            await temp_bot.send_media_group(chat_id=admin_id, media=media_group)

                        keyboard = get_digest_review_keyboard(new_digest.id, photos)
                        chunks = split_text(digest_content, limit=3500)

                        await temp_bot.send_message(
                            chat_id=admin_id,
                            text=f"📝 *Черновик Дайджеста #{new_digest.id} ({digest_type}) готов для проверки!*"
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

            return new_digest

        except Exception as e:
            logger.error(f"Ошибка при сборке дайджеста: {e}")
            await self.db_session.rollback()
            return None

    async def run_experiment_digest_assembly_job(
        self,
        variants: Optional[List[str]] = None,
        model_name: Optional[str] = None
    ) -> List[Digest]:
        """Генерирует варианты дайджеста для экспериментов из одних и тех же фактов."""
        if variants is None:
            variants = ["micro_tldr", "tldr_plus_highlights", "standard_grouped", "bullet_feed"]

        logger.info(f"Запуск джобы сборки экспериментальных дайджестов (варианты: {variants})...")
        cutoff_date = await self._get_cutoff_date("simple")
        stmt = select(Post).where(
            or_(
                Post.is_simple_relevant == True,
                and_(Post.is_ad_or_trash == False, Post.is_simple_relevant.is_(None))
            ),
            Post.post_date >= cutoff_date
        ).order_by(Post.post_date.desc()).limit(15)

        result = await self.db_session.execute(stmt)
        ready_posts = result.scalars().all()

        if not ready_posts:
            # Fallback: get recent posts without cutoff filter if cutoff yields none
            stmt_fallback = select(Post).where(
                Post.is_ad_or_trash == False
            ).order_by(Post.post_date.desc()).limit(15)
            ready_posts = (await self.db_session.execute(stmt_fallback)).scalars().all()

        if not ready_posts:
            logger.info("Нет постов для экспериментальной сборки дайджестов.")
            return []

        all_facts = []
        for post in ready_posts:
            p_facts = post.simple_facts or post.facts or []
            for fact in p_facts:
                all_facts.append(f"{fact} [Источник]({post.link})")

        if not all_facts:
            logger.warning("У выбранных постов отсутствуют факты.")
            return []

        facts_text = "\n\n".join([f"• {fact}" for fact in all_facts])
        created_digests = []

        models_to_try = []
        if model_name:
            models_to_try.append(model_name)
        for fallback_m in self.extractor.model_names:
            if fallback_m not in models_to_try:
                models_to_try.append(fallback_m)

        for variant in variants:
            prompt = self.extractor.build_message_extraction_prompt(
                text=facts_text,
                digest=True,
                digest_type="simple",
                format_variant=variant
            )

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
                    logger.warning(f"Модель {m} при генерации экспериментального дайджеста {variant} вернула ошибку: {d_err}")

            if response and response[0]:
                digest_content, tokens = response
                new_digest = Digest(
                    total_tokens=tokens,
                    content=digest_content,
                    facts=all_facts,
                    digest_type=f"simple:{variant}",
                    model_name=used_model or (self.extractor.model_names[0] if self.extractor.model_names else "google/gemini-2.5-flash")
                )
                self.db_session.add(new_digest)
                created_digests.append(new_digest)

        await self.db_session.commit()
        logger.info(f"Успешно создано {len(created_digests)} экспериментальных дайджестов.")
        return created_digests

