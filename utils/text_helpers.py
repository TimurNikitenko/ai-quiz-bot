"""Вспомогательные утилиты для работы с текстом и HTML-форматированием."""

import re
import html
from typing import List, Any


def split_text(text: str, limit: int = 3500) -> List[str]:
    """Нарезает текст на куски заданной длины, стараясь не разрывать абзацы."""
    chunks = []
    if not text:
        return chunks
    while len(text) > limit:
        split_at = text.rfind('\n', 0, limit)
        if split_at == -1:
            split_at = limit
        chunk = text[:split_at].strip()
        if chunk:
            chunks.append(chunk)
        text = text[split_at:].lstrip()
    if text.strip():
        chunks.append(text.strip())
    return chunks


def markdown_to_html(text: str) -> str:
    """Конвертирует базовую Markdown-разметку в HTML-теги для Telegram API."""
    text = html.escape(text, quote=False)

    text = re.sub(r'^#{1,6}\s+(.+)$', r'<b>\1</b>', text, flags=re.MULTILINE)
    text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)

    def replace_link(match):
        return f'<a href="{html.unescape(match.group(2))}">{match.group(1)}</a>'

    text = re.sub(r'\[(.*?)\]\((.*?)\)', replace_link, text)
    text = re.sub(r'\*(.*?)\*', r'<i>\1</i>', text)
    text = re.sub(r'`(.*?)`', r'<code>\1</code>', text)

    return text


def deep_clean(data: Any) -> Any:
    """Рекурсивно очищает строки данных от битых байтов и непечатных символов."""
    if isinstance(data, dict):
        return {k: deep_clean(v) for k, v in data.items()}
    if isinstance(data, list):
        return [deep_clean(i) for i in data]
    if isinstance(data, str):
        try:
            data = data.encode('latin1').decode('utf-8')
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
        cleaned = "".join(ch for ch in data if ch.isprintable() or ch in "\n\r\t")
        return cleaned.strip()
    return data
