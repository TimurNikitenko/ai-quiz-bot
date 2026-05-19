import os
import random
import asyncio
import logging
from aiogram import Bot
from aiogram.types import Poll
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import select, update, set
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
        db_host = os.getenv("DB_HOST", "localhost")
        
        db_url = f"postgresql+asyncpg://{db_user}:{db_pass}@{db_host}:5432/{db_name}"
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

            polls_data = {}
            # 3. Отправляем вопросы квиза как нативные опросы
            if quiz and quiz.questions:
                for q in quiz.questions:
                    correct_text = q["correct_answer"]
                    
                    shuffled_options = q["options"].copy()
                    random.shuffle(shuffled_options)
                    
                    new_correct_id = shuffled_options.index(correct_text)

                    poll_message = await bot.send_poll(
                        chat_id=channel_id,
                        question=q["question"],
                        options=shuffled_options, 
                        type="quiz",
                        correct_option_id=new_correct_id,
                        is_anonymous=False, 
                        explanation=q.get("explanation", "Подробности в тексте дайджеста.")[:200]
                    )

                    polls_data[poll_message.poll.id] = new_correct_id
                    await asyncio.sleep(0.5) 
                
                quiz.poll_info = polls_data
                await session.commit()
                logger.info(f"Квиз для дайджеста #{digest.id} отправлен.")

    except Exception as e:
        logger.error(f"Ошибка при публикации: {e}")
    finally:
        await bot.session.close()
        logger.info("Сессия бота закрыта.")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(publish_latest_digest())