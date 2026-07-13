import asyncio
import logging
import os
import signal
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import redis.asyncio as redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from .telegram_parser import TGParser
from .llm_layer import MessageExtractor
from .post_extractor import DigestPipeline
from .prompts import post_schema
from .sources import TG_SOURCES

from models.user import User
from models.user_answers import UserAnswer
from models.post import Post
from models.digest import Digest
from utils.logger import setup_json_logging

logger = logging.getLogger(__name__)


async def run_daily_parsing():
    logger.info("Запуск ежедневного парсинга Telegram...")
    try:
        db_user = os.getenv("DB_USER")
        db_pass = os.getenv("DB_PASSWORD")
        db_name = os.getenv("DB_NAME")
        db_host = os.getenv("DB_HOST", "localhost")
        db_port = os.getenv("DB_PORT", "5432")
        redis_host = os.getenv("REDIS_HOST", "localhost")
        redis_pass = os.getenv("REDIS_PASSWORD")
        proxy_host = os.getenv("PROXY_HOST", "127.0.0.1")
        proxy_port = int(os.getenv("PROXY_PORT", 1080))
        
        db_url = f"postgresql+asyncpg://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}"
        engine = create_async_engine(db_url, echo=False)
        AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)
        
        redis_client = redis.Redis(
            host=redis_host, 
            port=6379, 
            password=redis_pass, 
            decode_responses=True 
        )
        
        download_media = os.getenv("DOWNLOAD_MEDIA", "False").lower() in ("true", "1", "yes")
        
        tg_api_id = int(os.getenv("TELEGRAM_API_ID"))
        tg_api_hash = os.getenv("TELEGRAM_API_HASH")
        openrouter_key = os.getenv("OPENROUTER_API_KEY")
        
        tg_parser = TGParser(
            api_id=tg_api_id, 
            api_hash=tg_api_hash,
            proxy_host=proxy_host,
            proxy_port=proxy_port,
            download_media=download_media
        )
        
        proxy_url = f"socks5://{proxy_host}:{proxy_port}" if proxy_host else None
        
        extractor = MessageExtractor(
            model_names=["deepseek/deepseek-v4-pro"], 
            api_keys=[openrouter_key],
            proxy=proxy_url
        )
        
        async with AsyncSessionLocal() as session:
            pipeline = DigestPipeline(
                tg_sources=TG_SOURCES,
                tg_parser=tg_parser,
                extractor=extractor,
                db_session=session,
                redis_client=redis_client
            )
            await pipeline.run_parsing_job()
            
        # Set Redis key on success
        today = datetime.now().date().isoformat()
        await redis_client.set("parser:last_success_date", today, ex=172800)
        logger.info(f"Парсинг за {today} успешно завершен и записан в стейт Redis")

        await redis_client.close()
        await engine.dispose()
        logger.info("Ежедневный парсинг успешно завершен.")
    except Exception as e:
        logger.error(f"Ошибка во время ежедневного парсинга: {e}", exc_info=True)


async def run_weekly_digest():
    logger.info("Запуск еженедельной обработки LLM и сборки дайджеста...")
    try:
        db_user = os.getenv("DB_USER")
        db_pass = os.getenv("DB_PASSWORD")
        db_name = os.getenv("DB_NAME")
        db_host = os.getenv("DB_HOST", "localhost")
        db_port = os.getenv("DB_PORT", "5432")
        redis_host = os.getenv("REDIS_HOST", "localhost")
        redis_pass = os.getenv("REDIS_PASSWORD")
        proxy_host = os.getenv("PROXY_HOST", "127.0.0.1")
        proxy_port = int(os.getenv("PROXY_PORT", 1080))
        
        db_url = f"postgresql+asyncpg://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}"
        engine = create_async_engine(db_url, echo=False)
        AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)
        
        redis_client = redis.Redis(
            host=redis_host, 
            port=6379, 
            password=redis_pass, 
            decode_responses=True 
        )
        
        download_media = os.getenv("DOWNLOAD_MEDIA", "False").lower() in ("true", "1", "yes")
        
        tg_api_id = int(os.getenv("TELEGRAM_API_ID"))
        tg_api_hash = os.getenv("TELEGRAM_API_HASH")
        openrouter_key = os.getenv("OPENROUTER_API_KEY")
        
        tg_parser = TGParser(
            api_id=tg_api_id, 
            api_hash=tg_api_hash,
            proxy_host=proxy_host,
            proxy_port=proxy_port,
            download_media=download_media
        )
        
        proxy_url = f"socks5://{proxy_host}:{proxy_port}" if proxy_host else None
        
        extractor = MessageExtractor(
            model_names=["deepseek/deepseek-v4-pro"], 
            api_keys=[openrouter_key],
            proxy=proxy_url
        )
        
        max_posts_env = os.getenv("MAX_POSTS_TO_PROCESS_LLM")
        max_posts = int(max_posts_env) if max_posts_env else None
        
        async with AsyncSessionLocal() as session:
            pipeline = DigestPipeline(
                tg_sources=TG_SOURCES,
                tg_parser=tg_parser,
                extractor=extractor,
                db_session=session,
                redis_client=redis_client
            )
            
            # First run LLM processing
            await pipeline.run_llm_processing_job(schema=post_schema, max_posts=max_posts)
            # Then assemble digest and publish
            await pipeline.run_digest_assembly_job()
            
        # Set Redis key on success
        today = datetime.now().date().isoformat()
        await redis_client.set("parser:last_weekly_digest_success_date", today, ex=604800 * 2)
        logger.info(f"Еженедельная обработка LLM и сборка дайджеста за {today} успешно завершена и записана в стейт Redis")

        await redis_client.close()
        await engine.dispose()
        logger.info("Еженедельная обработка LLM и сборка дайджеста успешно завершена.")
    except Exception as e:
        logger.error(f"Ошибка во время еженедельной сборки дайджеста: {e}", exc_info=True)


async def run_metrics_snapshot():
    logger.info("Запуск сбора метрик базы данных...")
    try:
        db_user = os.getenv("DB_USER")
        db_pass = os.getenv("DB_PASSWORD")
        db_name = os.getenv("DB_NAME")
        db_host = os.getenv("DB_HOST", "localhost")
        db_port = os.getenv("DB_PORT", "5432")
        
        db_url = f"postgresql+asyncpg://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}"
        engine = create_async_engine(db_url, echo=False)
        AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)
        
        async with AsyncSessionLocal() as session:
            # 1. Users count
            total_users = await session.scalar(select(func.count(User.id))) or 0
            
            # 2. Answers stats
            total_answers = await session.scalar(select(func.count(UserAnswer.id))) or 0
            correct_answers = await session.scalar(select(func.count(UserAnswer.id)).where(UserAnswer.is_correct == True)) or 0
            accuracy_rate = (correct_answers / total_answers * 100) if total_answers > 0 else 0.0
            
            # 3. Posts stats
            total_posts = await session.scalar(select(func.count(Post.id))) or 0
            ad_trash_posts = await session.scalar(select(func.count(Post.id)).where(Post.is_ad_or_trash == True)) or 0
            clean_posts = await session.scalar(select(func.count(Post.id)).where(Post.is_ad_or_trash == False)) or 0
            unprocessed_posts = await session.scalar(select(func.count(Post.id)).where(Post.is_ad_or_trash.is_(None))) or 0
            
            # 4. Digest count
            total_digests = await session.scalar(select(func.count(Digest.id))) or 0
            
            # 5. Token consumption
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

        await engine.dispose()
    except Exception as e:
        logger.error(f"Ошибка во время сбора метрик: {e}", exc_info=True)


async def check_and_catchup():
    """Проверяет по ключам в редисе, были ли прогоны парсинга и еженедельного дайджеста, и запускает catch-up при необходимости."""
    logger.info("Проверка необходимости catch-up...")
    try:
        redis_host = os.getenv("REDIS_HOST", "localhost")
        redis_pass = os.getenv("REDIS_PASSWORD")
        redis_client = redis.Redis(
            host=redis_host,
            port=6379,
            password=redis_pass,
            decode_responses=True
        )
        
        from datetime import timedelta, timezone
        moscow_tz = timezone(timedelta(hours=3))
        now_moscow = datetime.now(moscow_tz)
        today = now_moscow.date().isoformat()
        
        last_success_date = await redis_client.get("parser:last_success_date")
        last_weekly_success_date = await redis_client.get("parser:last_weekly_digest_success_date")
        await redis_client.close()

        # 1. Catch-up check for Daily Parsing
        if not last_success_date or last_success_date != today:
            logger.info("Сегодняшний парсинг не выполнялся. Запускаем фоновый catch-up...")
            asyncio.create_task(run_daily_parsing())
        else:
            logger.info(f"Парсинг на сегодня ({today}) уже был успешно выполнен ранее.")

        # 2. Catch-up check for Weekly LLM / Digest job
        # Находим дату последнего запланированного запуска в воскресенье в 12:00 MSK
        days_since_sunday = (now_moscow.weekday() - 6) % 7
        last_sunday = now_moscow - timedelta(days=days_since_sunday)
        last_sunday_target = last_sunday.replace(hour=12, minute=0, second=0, microsecond=0)
        
        if now_moscow.weekday() == 6 and now_moscow < last_sunday_target:
            last_sunday_target -= timedelta(days=7)
            
        last_scheduled_date = last_sunday_target.date()
        
        need_weekly_catchup = False
        if not last_weekly_success_date:
            need_weekly_catchup = True
        else:
            try:
                success_date = datetime.fromisoformat(last_weekly_success_date).date()
                if success_date < last_scheduled_date:
                    need_weekly_catchup = True
            except ValueError:
                need_weekly_catchup = True
                
        if need_weekly_catchup:
            logger.info(f"Еженедельный дайджест за последний цикл (от {last_scheduled_date}) не выполнялся. Запускаем фоновый catch-up...")
            asyncio.create_task(run_weekly_digest())
        else:
            logger.info(f"Еженедельный дайджест за последний цикл (последний запуск/чек: {last_weekly_success_date}) уже выполнен.")
            
    except Exception as e:
        logger.error(f"Ошибка при проверке catch-up: {e}", exc_info=True)


async def main():
    from dotenv import load_dotenv
    load_dotenv()
    
    # Initialize structured JSON logging
    setup_json_logging(service_name="ai-quiz-bot-scheduler")
    
    # Run catch-up check asynchronously on startup
    await check_and_catchup()
    
    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
    
    # Daily parsing at 3 am Moscow time
    scheduler.add_job(
        run_daily_parsing,
        trigger=CronTrigger(hour=3, minute=0, timezone="Europe/Moscow"),
        id="daily_parsing_job",
        name="Daily Telegram channels parsing (3:00 MSK)",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=3600,
    )
    
    # Weekly digest at Sunday 12:00 PM Moscow time
    scheduler.add_job(
        run_weekly_digest,
        trigger=CronTrigger(day_of_week="sun", hour=12, minute=0, timezone="Europe/Moscow"),
        id="weekly_digest_job",
        name="Weekly LLM processing and digest assembly (Sunday 12:00 MSK)",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=3600,
    )
    
    # Daily DB metrics snapshot at 0:05 am Moscow time
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
    logger.info("Next Daily parsing run: %s", scheduler.get_job("daily_parsing_job").next_run_time)
    logger.info("Next Weekly digest run: %s", scheduler.get_job("weekly_digest_job").next_run_time)
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
