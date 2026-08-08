"""Планировщик задач (Scheduler) ежедневного сбора постов, формирования дайджестов и снимков метрик."""

import asyncio
import logging
import signal
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import func, select

from core.config import get_settings
from core.database import get_async_engine, get_session_factory, get_db_session
from core.redis import get_redis_client
from services.pipeline import DigestPipeline
from .telegram_parser import TGParser
from .llm_layer import MessageExtractor
from .prompts import post_schema
from .sources import TG_SOURCES

from models.user import User
from models.user_answers import UserAnswer
from models.post import Post
from models.digest import Digest
from utils.logger import setup_json_logging

logger = logging.getLogger(__name__)


async def run_daily_digest_cycle():
    """Ежедневный полный цикл: Парсинг TG -> LLM-обработка постов -> Сборка и публикация дайджеста."""
    logger.info("Запуск ежедневного цикла парсинга, обработки LLM и сборки дайджеста...")
    settings = get_settings()
    try:
        engine = get_async_engine()
        session_factory = get_session_factory(engine)
        redis_client = get_redis_client()

        tg_parser = TGParser(
            api_id=settings.telegram_api_id,
            api_hash=settings.telegram_api_hash,
            proxy_host=settings.proxy_host,
            proxy_port=settings.proxy_port,
            download_media=settings.download_media
        )

        extractor = MessageExtractor(
            model_names=[settings.llm_cheap_model, settings.llm_expensive_model],
            api_keys=[settings.openrouter_api_key],
            proxy=settings.proxy_url
        )

        moscow_tz = timezone(timedelta(hours=3))
        now_moscow = datetime.now(moscow_tz)
        is_sunday = (now_moscow.weekday() == 6)

        async with session_factory() as session:
            pipeline = DigestPipeline(
                tg_sources=TG_SOURCES,
                tg_parser=tg_parser,
                extractor=extractor,
                db_session=session,
                redis_client=redis_client
            )

            # 1. Parsing TG
            await pipeline.run_parsing_job()

            # 2. LLM Processing
            await pipeline.run_llm_processing_job(
                schema=post_schema,
                max_posts=settings.max_posts_to_process_llm,
                model_name=settings.llm_cheap_model
            )

            # 3. Assemble Daily Digest (tech & simple)
            try:
                logger.info("Запуск сборки tech-дайджеста...")
                await pipeline.run_digest_assembly_job(
                    digest_type="tech",
                    is_sunday_quiz=is_sunday,
                    max_posts_in_digest=None,
                    model_name=settings.llm_expensive_model
                )
            except Exception as tech_err:
                logger.error(f"Ошибка при сборке tech-дайджеста: {tech_err}", exc_info=True)

            try:
                logger.info("Запуск сборки simple-дайджеста...")
                await pipeline.run_digest_assembly_job(
                    digest_type="simple",
                    is_sunday_quiz=is_sunday,
                    max_posts_in_digest=None,
                    model_name=settings.llm_expensive_model
                )
            except Exception as simple_err:
                logger.error(f"Ошибка при сборке simple-дайджеста: {simple_err}", exc_info=True)

        today = now_moscow.date().isoformat()
        await redis_client.set("parser:last_daily_digest_date", today, ex=172800)
        logger.info(f"Ежедневный цикл за {today} (is_sunday={is_sunday}) успешно завершен и записан в стейт Redis")

        await redis_client.close()
        await engine.dispose()
        logger.info("Ежедневный цикл успешно завершен.")
    except Exception as e:
        logger.error(f"Ошибка во время ежедневного цикла: {e}", exc_info=True)


async def run_metrics_snapshot():
    logger.info("Запуск сбора метрик базы данных...")
    try:
        async with get_db_session() as session:
            total_users = await session.scalar(select(func.count(User.id))) or 0
            total_answers = await session.scalar(select(func.count(UserAnswer.id))) or 0
            correct_answers = await session.scalar(select(func.count(UserAnswer.id)).where(UserAnswer.is_correct == True)) or 0
            accuracy_rate = (correct_answers / total_answers * 100) if total_answers > 0 else 0.0

            total_posts = await session.scalar(select(func.count(Post.id))) or 0
            ad_trash_posts = await session.scalar(select(func.count(Post.id)).where(Post.is_ad_or_trash == True)) or 0
            clean_posts = await session.scalar(select(func.count(Post.id)).where(Post.is_ad_or_trash == False)) or 0
            unprocessed_posts = await session.scalar(select(func.count(Post.id)).where(Post.is_ad_or_trash.is_(None))) or 0

            total_digests = await session.scalar(select(func.count(Digest.id))) or 0

            post_tokens = await session.scalar(select(func.sum(Post.tokens))) or 0
            digest_tokens = await session.scalar(select(func.sum(Digest.total_tokens))) or 0
            total_tokens = (post_tokens or 0) + (digest_tokens or 0)

            logger.info(
                "Ежедневный снимок метрик базы данных успешно собран.",
                extra={
                    "event_type": "db_metrics_snapshot",
                    "metric_users_total": total_users,
                    "metric_answers_total": total_answers,
                    "metric_answers_correct": correct_answers,
                    "metric_accuracy_percentage": round(accuracy_rate, 2),
                    "metric_posts_total": total_posts,
                    "metric_posts_ad_trash": ad_trash_posts,
                    "metric_posts_clean": clean_posts,
                    "metric_posts_unprocessed": unprocessed_posts,
                    "metric_digests_total": total_digests,
                    "metric_tokens_posts_sum": post_tokens or 0,
                    "metric_tokens_digests_sum": digest_tokens or 0,
                    "metric_tokens_total": total_tokens,
                }
            )
    except Exception as e:
        logger.error(f"Ошибка во время сбора метрик: {e}", exc_info=True)


async def check_and_catchup():
    logger.info("Проверка необходимости catch-up...")
    try:
        redis_client = get_redis_client()
        moscow_tz = timezone(timedelta(hours=3))
        now_moscow = datetime.now(moscow_tz)
        today = now_moscow.date().isoformat()

        last_daily_digest_date = await redis_client.get("parser:last_daily_digest_date")
        if not last_daily_digest_date:
            last_daily_digest_date = await redis_client.get("parser:last_success_date")

        await redis_client.close()

        if not last_daily_digest_date or last_daily_digest_date != today:
            logger.info("Сегодняшний цикл парсинга и дайджеста не выполнялся. Запускаем фоновый catch-up...")
            asyncio.create_task(run_daily_digest_cycle())
        else:
            logger.info(f"Ежедневный цикл на сегодня ({today}) уже был успешно выполнен ранее.")

    except Exception as e:
        logger.error(f"Ошибка при проверке catch-up: {e}", exc_info=True)


async def main():
    setup_json_logging(service_name="ai-quiz-bot-scheduler")
    await check_and_catchup()

    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

    scheduler.add_job(
        run_daily_digest_cycle,
        trigger=CronTrigger(hour=17, minute=0, timezone="Europe/Moscow"),
        id="daily_digest_cycle_job",
        name="Daily Telegram parsing, LLM processing and digest assembly (17:00 MSK)",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=3600,
    )

    scheduler.add_job(
        run_metrics_snapshot,
        trigger=CronTrigger(hour=0, minute=5, timezone="Europe/Moscow"),
        id="db_metrics_snapshot_job",
        name="Daily database metrics snapshot (0:05 MSK)",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=3600,
    )

    scheduler.start()
    logger.info("Scheduler started.")
    logger.info("Next Daily Digest cycle run: %s", scheduler.get_job("daily_digest_cycle_job").next_run_time)
    logger.info("Next DB metrics snapshot run: %s", scheduler.get_job("db_metrics_snapshot_job").next_run_time)

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop_event.set)

    await stop_event.wait()
    logger.info("Shutdown signal received, stopping scheduler...")
    scheduler.shutdown(wait=True)
    logger.info("Scheduler stopped gracefully")


if __name__ == "__main__":
    asyncio.run(main())
