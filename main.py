import os
import asyncio
import logging
from dotenv import load_dotenv
import time

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
import redis.asyncio as redis

from telegram_parser import TGParser
from llm_layer import MessageExtractor
from post_extractor import DigestPipeline
from prompts import post_schema 
from sources import TG_SOURCES


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

async def main():
    load_dotenv()

    tg_api_id = int(os.getenv("TELEGRAM_API_ID"))
    tg_api_hash = os.getenv("TELEGRAM_API_HASH")
    openrouter_key = os.getenv("OPENROUTER_API_KEY")
    
    db_user = os.getenv("DB_USER")
    db_pass = os.getenv("DB_PASSWORD")
    db_name = os.getenv("DB_NAME")
    redis_pass = os.getenv("REDIS_PASSWORD")
    proxy_host = os.getenv("PROXY_HOST", "127.0.0.1")
    proxy_port = int(os.getenv("PROXY_PORT", 1080))

    db_host = os.getenv("DB_HOST", "localhost")
    redis_host = os.getenv("REDIS_HOST", "localhost")

    db_url = f"postgresql+asyncpg://{db_user}:{db_pass}@{db_host}:5432/{db_name}"
    engine = create_async_engine(db_url, echo=False)
    AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    redis_client = redis.Redis(
        host=redis_host, 
        port=6379, 
        password=redis_pass, 
        decode_responses=True 
    )

    tg_parser = TGParser(
        api_id=tg_api_id, 
        api_hash=tg_api_hash,
        proxy_host=proxy_host,
        proxy_port=proxy_port
    )
    
    extractor = MessageExtractor(
        model_names=["openai/gpt-5.4-nano"], 
        api_keys=[openrouter_key],
        proxy=None
    )

    interval = int(os.getenv("PARSING_INTERVAL_SECONDS", 14400))
    while True:
        async with AsyncSessionLocal() as session:
            pipeline = DigestPipeline(
                tg_sources=TG_SOURCES,
                tg_parser=tg_parser,
                extractor=extractor,
                db_session=session,
                redis_client=redis_client
            )

            logger.info("--- СТАРТ ЦИКЛА ---")
            await pipeline.run_parsing_job()
            await pipeline.run_llm_processing_job(schema=post_schema)
            await pipeline.run_digest_assembly_job()
            logger.info("--- ЦИКЛ ЗАВЕРШЕН ---")
        
        logger.info(f"Ожидание следующего запуска ({interval} секунд)...")
        await asyncio.sleep(interval)

if __name__ == "__main__":
    asyncio.run(main())