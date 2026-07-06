import os
import random
import asyncio
import logging
from typing import Optional
from aiogram import Bot
from aiogram.types import Poll, InlineKeyboardMarkup, InlineKeyboardButton, LinkPreviewOptions
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import select
from models import Digest, Quiz, PublishedDigest
from dotenv import load_dotenv
import re
import html
import sys

logger = logging.getLogger(__name__)

def split_text(text: str, limit: int = 4000):
    """Нарезает текст на куски, стараясь не рвать строки."""
    chunks = []
    while len(text) > limit:
        split_at = text.rfind('\n', 0, limit)
        if split_at == -1: split_at = limit
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip()
    chunks.append(text)
    return chunks


def markdown_to_html(text: str) -> str:
    # Экранируем сырые HTML символы, чтобы не ломать парсинг Telegram
    text = html.escape(text, quote=False)
    
    # Заголовки (### Текст) -> Жирный текст
    text = re.sub(r'^#{1,6}\s+(.+)$', r'<b>\1</b>', text, flags=re.MULTILINE)
    
    # Жирный (**текст**) -> <b>текст</b>
    text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
    
    # Ссылки ([текст](ссылка)) -> <a href="ссылка">текст</a>
    def replace_link(match):
        return f'<a href="{html.unescape(match.group(2))}">{match.group(1)}</a>'
    text = re.sub(r'\[(.*?)\]\((.*?)\)', replace_link, text)
    
    # Курсив (*текст*) -> <i>текст</i>
    text = re.sub(r'\*(.*?)\*', r'<i>\1</i>', text)
    
    # Код (`код`) -> <code>код</code>
    text = re.sub(r'`(.*?)`', r'<code>\1</code>', text)
    
    return text

async def publish_digest_by_id(digest_id: Optional[int] = None, photo_path: Optional[str] = None):
    load_dotenv()
    bot = Bot(token=os.getenv("BOT_TOKEN"))
    try:
        channel_id = os.getenv("CHANNEL_ID")

        # Инициализация БД
        db_user, db_pass, db_name = os.getenv("DB_USER"), os.getenv("DB_PASSWORD"), os.getenv("DB_NAME")
        db_host = os.getenv("DB_HOST", "localhost")
        
        db_url = f"postgresql+asyncpg://{db_user}:{db_pass}@{db_host}:5432/{db_name}"
        engine = create_async_engine(db_url)
        AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

        async with AsyncSessionLocal() as session:
            if digest_id:
                stmt = select(Digest).where(Digest.id == digest_id)
                result = await session.execute(stmt)
                digest = result.scalar()
                
                if digest:
                    pub_stmt = select(PublishedDigest).where(
                        PublishedDigest.digest_id == digest.id,
                        PublishedDigest.chat_id == str(channel_id)
                    )
                    existing_pub = (await session.execute(pub_stmt)).scalar()
                    if existing_pub:
                        logger.info(f"Дайджест #{digest.id} уже был опубликован в канале {channel_id}. Пропускаем.")
                        return
            else:
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

            content_chunks = split_text(digest.content)
            
            if photo_path and os.path.exists(photo_path):
                from aiogram.types import FSInputFile
                try:
                    photo_file = FSInputFile(photo_path)
                    await bot.send_photo(
                        chat_id=channel_id,
                        photo=photo_file
                    )
                    logger.info(f"Фото {photo_path} успешно опубликовано к дайджесту #{digest.id}")
                except Exception as photo_err:
                    logger.error(f"Ошибка при публикации фото {photo_path} к дайджесту #{digest.id}: {photo_err}")
    
            # Ищем квиз заранее, чтобы прикрепить кнопку к последнему сообщению
            stmt_quiz = select(Quiz).where(Quiz.digest_id == digest.id)
            res_quiz = await session.execute(stmt_quiz)
            quiz = res_quiz.scalar()

            keyboard = None

            last_message_id = None
            for i, chunk in enumerate(content_chunks):
                html_chunk = markdown_to_html(chunk)
                reply_markup = keyboard if (i == len(content_chunks) - 1) else None
                
                msg = await bot.send_message(
                    chat_id=channel_id,
                    text=html_chunk,
                    parse_mode="HTML",
                    reply_markup=reply_markup,
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

            # Помечаем дайджест как опубликованный в БД для конкретного канала
            pub_record = PublishedDigest(digest_id=digest.id, chat_id=str(channel_id))
            session.add(pub_record)
            
            # Помечаем также общий флаг
            digest.is_published = True
            await session.commit()
            logger.info(f"Дайджест #{digest.id} успешно помечен как опубликованный в БД для канала {channel_id}.")

    except Exception as e:
        logger.error(f"Ошибка при публикации: {e}")
    finally:
        await bot.session.close()
        logger.info("Сессия бота закрыта.")

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