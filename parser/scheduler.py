import asyncio
import logging
import os
import signal
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import redis.asyncio as redis
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from .telegram_parser import TGParser
from .llm_layer import MessageExtractor
from .post_extractor import DigestPipeline
from .prompts import post_schema
from .sources import TG_SOURCES

logger = logging.getLogger(__name__)


async def run_daily_parsing():
    logger.info("Запуск ежедневного парсинга Telegram...")
    try:
        db_user = os.getenv("DB_USER")
        db_pass = os.getenv("DB_PASSWORD")
        db_name = os.getenv("DB_NAME")
        db_host = os.getenv("DB_HOST", "localhost")
        redis_host = os.getenv("REDIS_HOST", "localhost")
        redis_pass = os.getenv("REDIS_PASSWORD")
        proxy_host = os.getenv("PROXY_HOST", "127.0.0.1")
        proxy_port = int(os.getenv("PROXY_PORT", 1080))
        
        db_url = f"postgresql+asyncpg://{db_user}:{db_pass}@{db_host}:5432/{db_name}"
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
        
        extractor = MessageExtractor(
            model_names=["deepseek/deepseek-v4-pro"], 
            api_keys=[openrouter_key],
            proxy=None
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
        redis_host = os.getenv("REDIS_HOST", "localhost")
        redis_pass = os.getenv("REDIS_PASSWORD")
        proxy_host = os.getenv("PROXY_HOST", "127.0.0.1")
        proxy_port = int(os.getenv("PROXY_PORT", 1080))
        
        db_url = f"postgresql+asyncpg://{db_user}:{db_pass}@{db_host}:5432/{db_name}"
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
        
        extractor = MessageExtractor(
            model_names=["deepseek/deepseek-v4-pro"], 
            api_keys=[openrouter_key],
            proxy=None
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
            
        await redis_client.close()
        await engine.dispose()
        logger.info("Еженедельная обработка LLM и сборка дайджеста успешно завершена.")
    except Exception as e:
        logger.error(f"Ошибка во время еженедельной сборки дайджеста: {e}", exc_info=True)


async def main():
    from dotenv import load_dotenv
    load_dotenv()
    
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
    
    scheduler.start()
    logger.info("Scheduler started.")
    logger.info("Next Daily parsing run: %s", scheduler.get_job("daily_parsing_job").next_run_time)
    logger.info("Next Weekly digest run: %s", scheduler.get_job("weekly_digest_job").next_run_time)
    
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop_event.set)
        
    await stop_event.wait()
    logger.info("Shutdown signal received, stopping scheduler...")
    scheduler.shutdown(wait=True)
    logger.info("Scheduler stopped gracefully")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    asyncio.run(main())
