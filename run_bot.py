import asyncio
import logging
import os
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from tg_bot.middlewares.db import DbSessionMiddleware
from tg_bot.handlers import polls_router

async def main():
    load_dotenv()
    logging.basicConfig(level=logging.INFO)

    logger = logging.getLogger(__name__)
    
    bot = Bot(token=os.getenv("BOT_TOKEN"))
    dp = Dispatcher()

    # Инициализация БД
    db_user = os.getenv('DB_USER')
    db_pass = os.getenv('DB_PASSWORD')
    db_host = os.getenv('DB_HOST')
    db_name = os.getenv('DB_NAME')

    db_url = f"postgresql+asyncpg://{db_user}:{db_pass}@{db_host}:5432/{db_name}"
    engine = create_async_engine(db_url)
    session_pool = async_sessionmaker(engine, expire_on_commit=False)

    # Подключаем миддлварь
    dp.update.middleware(DbSessionMiddleware(session_pool))
    
    # Подключаем роутер с хэндлером
    dp.include_router(polls_router)

    logger.info("Бот запущен и готов ловить ответы!")
    # Запускаем поллинг (бот работает бесконечно)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())