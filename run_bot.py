import asyncio
import logging
import os
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from tg_bot.middlewares.db import DbSessionMiddleware
from tg_bot.middlewares.apm import APMMiddleware
from tg_bot.bot_instance import get_bot
from tg_bot.handlers import polls_router, quiz_router, leaderboard_router, review_router, admin_review_router, comments_router
from utils.logger import setup_json_logging

async def main():
    load_dotenv()
    
    # Initialize structured JSON logging
    setup_json_logging(service_name="ai-quiz-bot")
    logger = logging.getLogger(__name__)

    # Initialize Elastic APM if configured
    apm_server_url = os.getenv("ELASTIC_APM_SERVER_URL")
    if apm_server_url:
        try:
            import elasticapm
            elasticapm.Client(
                server_url=apm_server_url,
                service_name=os.getenv("ELASTIC_APM_SERVICE_NAME", "ai-quiz-bot"),
                environment=os.getenv("ELASTIC_APM_ENVIRONMENT", "production"),
                secret_token=os.getenv("ELASTIC_APM_SECRET_TOKEN") or None,
            )
            elasticapm.instrument()
            logger.info("Elastic APM client initialized successfully")
        except Exception as apm_err:
            logger.warning(f"Failed to initialize Elastic APM: {apm_err}")
    
    bot = get_bot()
    dp = Dispatcher()
    
    # Register APM middleware first to trace all incoming updates
    dp.update.outer_middleware(APMMiddleware())

    # Register bot commands menu
    await bot.set_my_commands([
        BotCommand(command="start", description="Запустить бота / Приветствие"),
        BotCommand(command="help", description="Справка по командам и возможностям"),
        BotCommand(command="leaderboard", description="Показать рейтинг участников"),
        BotCommand(command="review", description="Работа над ошибками (до 5 вопросов)"),
    ])


    # Инициализация БД
    db_user = os.getenv('DB_USER')
    db_pass = os.getenv('DB_PASSWORD')
    db_host = os.getenv('DB_HOST')
    db_name = os.getenv('DB_NAME')
    db_port = os.getenv('DB_PORT', '5432')

    db_url = f"postgresql+asyncpg://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}"
    engine = create_async_engine(db_url)
    session_pool = async_sessionmaker(engine, expire_on_commit=False)

    # Подключаем миддлварь
    dp.update.middleware(DbSessionMiddleware(session_pool))

    # Подключаем роутеры
    dp.include_router(polls_router)
    dp.include_router(quiz_router)
    dp.include_router(leaderboard_router)
    dp.include_router(review_router)
    dp.include_router(admin_review_router)
    dp.include_router(comments_router)

    logger.info("Бот запущен и готов ловить ответы!")
    # Запускаем поллинг (бот работает бесконечно)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())