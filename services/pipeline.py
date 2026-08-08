"""Фасад пайплайна сбора постов, обработки LLM и формирования дайджестов."""

from typing import Optional, List, Dict, Any
import redis.asyncio as redis
from sqlalchemy.ext.asyncio import AsyncSession

from parser.telegram_parser import TGParser
from parser.llm_layer import MessageExtractor
from services.ingestion import PostIngestionService
from services.llm_processor import PostLLMProcessorService
from services.digest_builder import DigestBuilderService
from models import Digest
from core.constants import DEFAULT_CACHE_TTL_DAYS, DEFAULT_MAX_QUESTIONS_PER_QUIZ


class DigestPipeline:
    """Фасад, связывающий PostIngestionService, PostLLMProcessorService и DigestBuilderService."""

    def __init__(
        self,
        tg_sources: List[str],
        tg_parser: TGParser,
        extractor: MessageExtractor,
        db_session: AsyncSession,
        redis_client: redis.Redis,
        cache_ttl_days: int = DEFAULT_CACHE_TTL_DAYS,
    ):
        self.ingestion_service = PostIngestionService(
            tg_sources=tg_sources,
            tg_parser=tg_parser,
            db_session=db_session,
            redis_client=redis_client,
            cache_ttl_days=cache_ttl_days
        )
        self.llm_processor_service = PostLLMProcessorService(
            extractor=extractor,
            db_session=db_session
        )
        self.digest_builder_service = DigestBuilderService(
            extractor=extractor,
            db_session=db_session
        )

    async def run_parsing_job(self):
        """Делегирует сбор постов из Telegram в PostIngestionService."""
        await self.ingestion_service.run_parsing_job()

    async def run_llm_processing_job(
        self,
        schema: Dict[str, Any],
        max_posts: Optional[int] = None,
        model_name: Optional[str] = None
    ):
        """Делегирует LLM-обработку постов в PostLLMProcessorService."""
        await self.llm_processor_service.run_llm_processing_job(
            schema=schema,
            max_posts=max_posts,
            model_name=model_name
        )

    async def run_digest_assembly_job(
        self,
        digest_type: str = "tech",
        is_sunday_quiz: bool = False,
        max_posts_in_digest: Optional[int] = None,
        max_questions: int = DEFAULT_MAX_QUESTIONS_PER_QUIZ,
        model_name: Optional[str] = None
    ) -> Optional[Digest]:
        """Делегирует сборку дайджеста и отбор квиза в DigestBuilderService."""
        return await self.digest_builder_service.run_digest_assembly_job(
            digest_type=digest_type,
            is_sunday_quiz=is_sunday_quiz,
            max_posts_in_digest=max_posts_in_digest,
            max_questions=max_questions,
            model_name=model_name
        )
