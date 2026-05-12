import os
import asyncio
import logging
from aiogram import Bot
from aiogram.types import Poll
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import select
from models import Digest, Quiz 
from dotenv import load_dotenv

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

async def publish_latest_digest():
    load_dotenv()
    bot = Bot(token=os.getenv("BOT_TOKEN"))
    try:
        channel_id = os.getenv("CHANNEL_ID")

        # Инициализация БД
        db_user, db_pass, db_name = os.getenv("DB_USER"), os.getenv("DB_PASSWORD"), os.getenv("DB_NAME")
        db_url = f"postgresql+asyncpg://{db_user}:{db_pass}@localhost:5432/{db_name}"
        engine = create_async_engine(db_url)
        AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

        async with AsyncSessionLocal() as session:
            # 1. Получаем последний дайджест и его квиз
            stmt = (
                select(Digest)
                .order_by(Digest.created_at.desc())
                .limit(1)
            )
            result = await session.execute(stmt)
            digest = result.scalar()

            if not digest:
                logger.error("Дайджесты не найдены в базе.")
                return

            content_chunks = split_text(digest.content)
    
            for i, chunk in enumerate(content_chunks):
                await bot.send_message(
                    chat_id=channel_id,
                    text=chunk,
                    parse_mode="Markdown"
                )
                if len(content_chunks) > 1:
                    await asyncio.sleep(0.5)
                    
            logger.info(f"Дайджест #{digest.id} отправлен ({len(content_chunks)} ч.)")


            stmt_quiz = select(Quiz).where(Quiz.digest_id == digest.id)
            res_quiz = await session.execute(stmt_quiz)
            quiz = res_quiz.scalar()
            # 3. Отправляем вопросы квиза как нативные опросы
            if quiz and quiz.questions:
                for q in quiz.questions:
                    # Находим индекс правильного ответа
                    try:
                        correct_id = q["options"].index(q["correct_answer"])
                    except ValueError:
                        logger.error(f"Правильный ответ не найден в опциях для вопроса: {q['question']}")
                        continue

                    await bot.send_poll(
                        chat_id=channel_id,
                        question=q["question"],
                        options=q["options"],
                        type="quiz", # Режим викторины
                        correct_option_id=correct_id,
                        is_anonymous=True,
                        explanation=f"Сложность: {q.get('difficulty_level', 'medium')}" #
                    )
                    await asyncio.sleep(0.5) # Пауза, чтобы ТГ не забанил за спам
                
                logger.info(f"Квиз для дайджеста #{digest.id} отправлен.")

    except Exception as e:
        logger.error(f"Ошибка при публикации: {e}")
    finally:
        await bot.session.close()
        logger.info("Сессия бота закрыта.")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(publish_latest_digest())