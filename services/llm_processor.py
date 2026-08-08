"""Сервис LLM-обработки и обогащения сырых постов."""

import asyncio
import logging
from typing import Optional, Dict, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.post import Post
from parser.llm_layer import MessageExtractor
from utils.time_utils import get_seven_days_ago

logger = logging.getLogger(__name__)


class PostLLMProcessorService:
    def __init__(
        self,
        extractor: MessageExtractor,
        db_session: AsyncSession,
    ):
        self.extractor = extractor
        self.db_session = db_session

    async def run_llm_processing_job(
        self,
        schema: Dict[str, Any],
        max_posts: Optional[int] = None,
        model_name: Optional[str] = None
    ):
        """Берет сырые посты из БД и прогоняет через LLM."""
        logger.info("Запуск джобы обработки LLM...")

        seven_days_ago = get_seven_days_ago()

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

                post.facts = post.tech_facts or post.simple_facts or llm_data.get("facts", [])
                post.questions = post.tech_questions or post.simple_questions or llm_data.get("questions", [])

                post.tokens = tokens
                post.model_name = model_name or (self.extractor.model_names[0] if self.extractor.model_names else "deepseek/deepseek-v4-pro")

                await self.db_session.commit()
                logger.info(f"Пост {post_link} успешно обработан (tech={is_tech}, simple={is_simple}). Токенов: {tokens}")

                await asyncio.sleep(2)

            except Exception as e:
                logger.error(f"Ошибка при обработке поста {post_id} LLM: {e}")
                await self.db_session.rollback()
