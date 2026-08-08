"""Вспомогательные утилиты для обработки медиафайлов и изображений."""

import os
from typing import List, Optional, Any


def extract_valid_media_paths(posts: List[Any]) -> List[str]:
    """Извлекает существующие пути к изображениям из списка объектов Post."""
    valid_paths = []
    for post in posts:
        media_path = getattr(post, "media_path", None)
        if media_path and os.path.exists(media_path):
            valid_paths.append(media_path)
    return valid_paths
