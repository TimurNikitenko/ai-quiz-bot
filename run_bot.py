import asyncio
import logging
import os
from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand

from core.config import get_settings
from core.database import get_async_engine, get_session_factory
from tg_bot.middlewares.db import DbSessionMiddleware
from tg_bot.middlewares.apm import APMMiddleware
from tg_bot.bot_instance import get_bot
from tg_bot.handlers import (
    polls_router,
    quiz_router,
    leaderboard_router,
    review_router,
    admin_review_router,
    comments_router,
    assessment_router,
)
from utils.logger import setup_json_logging


async def main():
    setup_json_logging(service_name="ai-quiz-bot")
    logger = logging.getLogger(__name__)
    settings = get_settings()

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

    dp.update.outer_middleware(APMMiddleware())

    await bot.set_my_commands([
        BotCommand(command="start", description="Запустить бота / Приветствие"),
        BotCommand(command="help", description="Справка по командам и возможностям"),
        BotCommand(command="assess", description="Оценить форматы дайджестов (1-5 звезд)"),
        BotCommand(command="leaderboard", description="Показать рейтинг участников"),
        BotCommand(command="review", description="Работа над ошибками (до 5 вопросов)"),
    ])

    engine = get_async_engine(settings.database_url)
    session_pool = get_session_factory(engine)

    dp.update.middleware(DbSessionMiddleware(session_pool))

    dp.include_router(polls_router)
    dp.include_router(quiz_router)
    dp.include_router(leaderboard_router)
    dp.include_router(review_router)
    dp.include_router(admin_review_router)
    dp.include_router(comments_router)
    dp.include_router(assessment_router)

    logger.info("Бот запущен и готов ловить ответы!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())