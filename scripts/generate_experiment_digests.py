"""Скрипт для однократного / периодического генерации 4 экспериментальных форматов дайджеста."""

import asyncio
import logging
import sys
import os

# Ensure app directory is on path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.database import get_db_session
from core.config import get_settings
from parser.llm_layer import MessageExtractor
from services.digest_builder import DigestBuilderService

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


async def main():
    settings = get_settings()
    model_names = [settings.llm_expensive_model, settings.llm_cheap_model]
    api_keys = [settings.openrouter_api_key] if settings.openrouter_api_key else ["dummy"]

    extractor = MessageExtractor(
        model_names=model_names,
        api_keys=api_keys,
        proxy=""
    )

    async with get_db_session() as db_session:
        builder = DigestBuilderService(extractor=extractor, db_session=db_session)
        logger.info("Запуск пре-генерации 4 экспериментальных форматов дайджеста...")
        digests = await builder.run_experiment_digest_assembly_job()
        logger.info(f"Сгенерировано дайджестов: {len(digests)}")
        for d in digests:
            logger.info(f"  - Digest #{d.id} | format={d.digest_type} | length={len(d.content or '')} chars")


if __name__ == "__main__":
    asyncio.run(main())
