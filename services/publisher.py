"""Сервис публикации сформированных дайджестов и квизов в Telegram-каналы."""

import os
import re
import html
import asyncio
import logging
from typing import Optional, List

from aiogram import Bot
from aiogram.types import LinkPreviewOptions, FSInputFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from models import Digest, Quiz, PublishedDigest
from tg_bot.bot_instance import get_bot
from core.config import get_settings

logger = logging.getLogger(__name__)


def split_text(text: str, limit: int = 3500) -> List[str]:
    """Нарезает текст на куски, стараясь не рвать строки."""
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
    """Конвертирует базовую Markdown-разметку в HTML-теги для Telegram."""
    text = html.escape(text, quote=False)

    text = re.sub(r'^#{1,6}\s+(.+)$', r'<b>\1</b>', text, flags=re.MULTILINE)
    text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)

    def replace_link(match):
        return f'<a href="{html.unescape(match.group(2))}">{match.group(1)}</a>'

    text = re.sub(r'\[(.*?)\]\((.*?)\)', replace_link, text)
    text = re.sub(r'\*(.*?)\*', r'<i>\1</i>', text)
    text = re.sub(r'`(.*?)`', r'<code>\1</code>', text)

    return text


class DigestPublisherService:
    def __init__(self, bot: Optional[Bot] = None):
        self.settings = get_settings()
        self.bot = bot

    async def publish_digest_by_id(self, digest_id: Optional[int] = None, photo_path: Optional[str] = None):
        bot = self.bot or get_bot()
        try:
            db_url = self.settings.database_url
            engine = create_async_engine(db_url)
            AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

            async with AsyncSessionLocal() as session:
                if digest_id:
                    stmt = select(Digest).where(Digest.id == digest_id)
                    result = await session.execute(stmt)
                    digest = result.scalar()

                    if digest:
                        channel_id = self.settings.get_channel_id_for_type(digest.digest_type)
                        pub_stmt = select(PublishedDigest).where(
                            PublishedDigest.digest_id == digest.id,
                            PublishedDigest.chat_id == str(channel_id)
                        )
                        existing_pub = (await session.execute(pub_stmt)).scalar()
                        if existing_pub:
                            logger.info(f"Дайджест #{digest.id} ({digest.digest_type}) уже был опубликован в канале {channel_id}. Пропускаем.")
                            return
                else:
                    channel_id = self.settings.channel_id
                    stmt = (
                        select(Digest)
                        .outerjoin(PublishedDigest, (Digest.id == PublishedDigest.digest_id) & (PublishedDigest.chat_id == str(channel_id)))
                        .where(PublishedDigest.id.is_(None))
                        .order_by(Digest.created_at.desc())
                        .limit(1)
                    )
                    result = await session.execute(stmt)
                    digest = result.scalar()

                if not digest:
                    if digest_id:
                        logger.error(f"Дайджест с ID #{digest_id} не найден в базе.")
                    else:
                        logger.info("Нет неопубликованных дайджестов в базе.")
                    return

                channel_id = self.settings.get_channel_id_for_type(digest.digest_type)
                content_chunks = split_text(digest.content)

                if photo_path and os.path.exists(photo_path):
                    try:
                        photo_file = FSInputFile(photo_path)
                        await bot.send_photo(
                            chat_id=channel_id,
                            photo=photo_file
                        )
                        logger.info(f"Фото {photo_path} успешно опубликовано к дайджесту #{digest.id}")
                    except Exception as photo_err:
                        logger.error(f"Ошибка при публикации фото {photo_path} к дайджесту #{digest.id}: {photo_err}")

                stmt_quiz = select(Quiz).where(Quiz.digest_id == digest.id)
                res_quiz = await session.execute(stmt_quiz)
                quiz = res_quiz.scalar()

                last_message_id = None
                for i, chunk in enumerate(content_chunks):
                    html_chunk = markdown_to_html(chunk)

                    msg = await bot.send_message(
                        chat_id=channel_id,
                        text=html_chunk,
                        parse_mode="HTML",
                        link_preview_options=LinkPreviewOptions(is_disabled=True)
                    )
                    last_message_id = msg.message_id
                    if len(content_chunks) > 1:
                        await asyncio.sleep(0.5)

                logger.info(f"Дайджест #{digest.id} отправлен ({len(content_chunks)} ч.)")

                if quiz and quiz.questions and last_message_id:
                    current_info = dict(quiz.poll_info) if quiz.poll_info else {}
                    current_info["telegram_message_id"] = last_message_id
                    quiz.poll_info = current_info
                    session.add(quiz)
                    logger.info(f"Квиз для дайджеста #{digest.id} привязан к сообщению в канале (ID: {last_message_id}).")

                pub_record = PublishedDigest(digest_id=digest.id, chat_id=str(channel_id))
                session.add(pub_record)

                digest.is_published = True
                await session.commit()
                logger.info(f"Дайджест #{digest.id} успешно помечен как опубликованный в БД для канала {channel_id}.")

            await engine.dispose()

        except Exception as e:
            logger.error(f"Ошибка при публикации: {e}")
            raise e
        finally:
            await bot.session.close()
            logger.info("Сессия бота закрыта.")


async def publish_digest_by_id(digest_id: Optional[int] = None, photo_path: Optional[str] = None):
    publisher = DigestPublisherService()
    await publisher.publish_digest_by_id(digest_id, photo_path)
