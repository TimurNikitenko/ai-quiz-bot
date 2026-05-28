import os
import random
import asyncio
import logging
from aiogram import Bot
from aiogram.types import Poll, InlineKeyboardMarkup, InlineKeyboardButton, LinkPreviewOptions
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import select
from models import Digest, Quiz 
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

async def publish_latest_digest():
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
            # 1. Получаем ID дайджеста из аргументов командной строки, если передан
            digest_id = None
            if len(sys.argv) > 1:
                try:
                    digest_id = int(sys.argv[1])
                except ValueError:
                    logger.error("Неверный ID дайджеста (должен быть числом).")
                    return

            if digest_id:
                stmt = select(Digest).where(Digest.id == digest_id)
            else:
                stmt = (
                    select(Digest)
                    .order_by(Digest.created_at.desc())
                    .limit(1)
                )
            result = await session.execute(stmt)
            digest = result.scalar()

            if not digest:
                if digest_id:
                    logger.error(f"Дайджест с ID #{digest_id} не найден в базе.")
                else:
                    logger.error("Дайджесты не найдены в базе.")
                return

            content_chunks = split_text(digest.content)
    
            for i, chunk in enumerate(content_chunks):
                html_chunk = markdown_to_html(chunk)
                await bot.send_message(
                    chat_id=channel_id,
                    text=html_chunk,
                    parse_mode="HTML",
                    link_preview_options=LinkPreviewOptions(is_disabled=True)
                )
                if len(content_chunks) > 1:
                    await asyncio.sleep(0.5)
                    
            logger.info(f"Дайджест #{digest.id} отправлен ({len(content_chunks)} ч.)")


            stmt_quiz = select(Quiz).where(Quiz.digest_id == digest.id)
            res_quiz = await session.execute(stmt_quiz)
            quiz = res_quiz.scalar()

            if quiz and quiz.questions:
                bot_info = await bot.get_me()
                quiz_link = f"https://t.me/{bot_info.username}?start=quiz_{digest.id}"
                
                keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="🧠 Пройти квиз",
                                url=quiz_link
                            )
                        ]
                    ]
                )
                
                await bot.send_message(
                    chat_id=channel_id,
                    text="📚 *Пройдите квиз по материалам дайджеста!*\nПроверьте свои знания и заработайте баллы.",
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
                logger.info(f"Ссылка на квиз для дайджеста #{digest.id} отправлена.")

    except Exception as e:
        logger.error(f"Ошибка при публикации: {e}")
    finally:
        await bot.session.close()
        logger.info("Сессия бота закрыта.")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(publish_latest_digest())