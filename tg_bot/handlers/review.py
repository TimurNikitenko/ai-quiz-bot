import logging
import random
import asyncio
from aiogram import Router, Bot
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from models import User, UserAnswer, Quiz, PollMapping

router = Router()
logger = logging.getLogger(__name__)

@router.message(Command("review"))
async def handle_review(message: Message, session: AsyncSession, bot: Bot):
    tg_user_id = message.from_user.id
    username = message.from_user.username

    # 1. Получаем пользователя
    user_stmt = select(User).where(User.telegram_id == tg_user_id)
    user = (await session.execute(user_stmt)).scalar_one_or_none()
    
    if not user:
        # Если пользователя нет в базе, значит он еще ничего не проходил
        await message.answer(
            "👋 *Привет!*\n\nУ вас пока нет истории ответов и ошибок. Начните проходить квизы в канале!",
            parse_mode="Markdown"
        )
        return

    # 2. Находим неверные ответы с привязанным индексом вопроса
    stmt = (
        select(UserAnswer, PollMapping, Quiz)
        .join(PollMapping, UserAnswer.telegram_poll_id == PollMapping.poll_id)
        .join(Quiz, PollMapping.quiz_id == Quiz.id)
        .where(
            UserAnswer.user_id == user.id,
            UserAnswer.is_correct == False,
            PollMapping.question_index != None
        )
    )
    results = (await session.execute(stmt)).all()

    if not results:
        await message.answer(
            "🎉 *Отлично!* У вас нет неисправленных ошибок. Вы молодец!",
            parse_mode="Markdown"
        )
        return

    # 3. Выбираем до 5 случайных уникальных ошибок
    # Для уникальности группируем по (quiz_id, question_index)
    unique_mistakes = {}
    for user_answer, poll_mapping, quiz in results:
        key = (poll_mapping.quiz_id, poll_mapping.question_index)
        if key not in unique_mistakes:
            unique_mistakes[key] = (user_answer, poll_mapping, quiz)
            
    mistake_list = list(unique_mistakes.values())
    selected_mistakes = random.sample(mistake_list, min(len(mistake_list), 5))

    await message.answer(
        f"🔄 *Работа над ошибками (выслано вопросов: {len(selected_mistakes)}):*\n"
        f"Ответьте правильно, чтобы исправить ошибку и получить балл!",
        parse_mode="Markdown"
    )
    await asyncio.sleep(0.5)

    for user_answer, poll_mapping, quiz in selected_mistakes:
        q_idx = poll_mapping.question_index
        if q_idx >= len(quiz.questions):
            continue
            
        q = quiz.questions[q_idx]
        correct_text = q["correct_answer"]
        shuffled_options = q["options"].copy()
        random.shuffle(shuffled_options)
        new_correct_id = shuffled_options.index(correct_text)

        poll_message = await bot.send_poll(
            chat_id=tg_user_id,
            question=q["question"],
            options=shuffled_options,
            type="quiz",
            correct_option_id=new_correct_id,
            is_anonymous=False,
            explanation=q.get("explanation", "Подробности в тексте дайджеста.")[:200]
        )

        # Сохраняем маппинг для ревью-опроса
        new_mapping = PollMapping(
            poll_id=poll_message.poll.id,
            quiz_id=quiz.id,
            correct_option_id=new_correct_id,
            question_index=q_idx,
            original_user_answer_id=user_answer.id
        )
        session.add(new_mapping)
        await asyncio.sleep(0.5)

    await session.commit()
    logger.info(f"User {tg_user_id} requested mistake review (sent {len(selected_mistakes)} questions)")
