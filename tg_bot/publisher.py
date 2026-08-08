"""Модуль публикации дайджестов (проксирует сервисы из services.publisher)."""

import sys
import asyncio
import logging
from services.publisher import (
    split_text,
    markdown_to_html,
    publish_digest_by_id,
    DigestPublisherService
)

logger = logging.getLogger(__name__)

__all__ = [
    "split_text",
    "markdown_to_html",
    "publish_digest_by_id",
    "DigestPublisherService",
]

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    digest_id = None
    if len(sys.argv) > 1:
        try:
            digest_id = int(sys.argv[1])
        except ValueError:
            logger.error("Неверный ID дайджеста (должен быть числом).")
            sys.exit(1)

    asyncio.run(publish_digest_by_id(digest_id))
