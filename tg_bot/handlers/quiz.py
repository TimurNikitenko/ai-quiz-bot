import logging
import random
import asyncio
from aiogram import Router, Bot
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from models import User, Quiz, UserAnswer, PollMapping

router = Router()
logger = logging.getLogger(__name__)

def clean_poll_text(text: str) -> str:
    if not text:
        return ""
    return text.replace("**", "").replace("*", "").replace("_", "").replace("`", "")

@router.message(Command("start"))
async def handle_start(message: Message, command: CommandObject, session: AsyncSession, bot: Bot):
    tg_user_id = message.from_user.id
    username = message.from_user.username
    args = command.args

    # 1. Get or create user
    user_stmt = select(User).where(User.telegram_id == tg_user_id)
    user = (await session.execute(user_stmt)).scalar_one_or_none()
    if not user:
        user = User(telegram_id=tg_user_id, username=username)
        session.add(user)
        await session.flush()
    else:
        # Update username if it has changed
        if user.username != username:
            user.username = username
            await session.flush()

    # 2. Check if there are arguments
    if not args or not args.startswith("quiz_"):
        await message.answer(
            "👋 *Привет!*\n\n"
            "Я бот для прохождения квизов по материалам дайджестов.\n\n"
            "Чтобы запустить квиз, пожалуйста, перейдите по ссылке под дайджестом в нашем канале.",
            parse_mode="Markdown"
        )
        return

    # 3. Extract digest_id
    try:
        digest_id = int(args.split("_")[1])
    except (IndexError, ValueError):
        await message.answer("❌ Некорректный формат ссылки на квиз.")
        return

    # 4. Fetch the quiz
    quiz_stmt = select(Quiz).where(Quiz.digest_id == digest_id)
    quiz = (await session.execute(quiz_stmt)).scalar_one_or_none()
    if not quiz:
        await message.answer("❌ Квиз не найден или еще не создан.")
        return

    # 5. Check if the user already took this quiz
    existing_answers_stmt = select(UserAnswer).where(
        UserAnswer.user_id == user.id,
        UserAnswer.quiz_id == quiz.id
    )
    existing_answers = (await session.execute(existing_answers_stmt)).scalars().all()
    if existing_answers:
        correct_count = sum(1 for ans in existing_answers if ans.is_correct)
        total_count = len(quiz.questions)
        await message.answer(
            f"ℹ️ *Вы уже проходили этот квиз!*\n\n"
            f"📊 Ваш результат: *{correct_count}* из *{total_count}* правильных ответов.\n"
            f"🏆 Ваш общий рейтинг: *{user.global_score}* баллов.",
            parse_mode="Markdown"
        )
        return

    # 6. Send quiz questions
    await message.answer(
        "🧠 *Начинаем квиз!*\n"
        "Ответьте на следующие вопросы. Удачи!",
        parse_mode="Markdown"
    )
    await asyncio.sleep(0.5)

    if not quiz.questions:
        await message.answer("❌ В этом квизе нет вопросов.")
        return

    for i, q in enumerate(quiz.questions):
        question_text = clean_poll_text(q["question"])
        correct_text = clean_poll_text(q["correct_answer"])
        shuffled_options = [clean_poll_text(opt) for opt in q["options"]]
        random.shuffle(shuffled_options)
        new_correct_id = shuffled_options.index(correct_text)

        raw_explanation = q.get("explanation", "Подробности в тексте дайджеста.")
        cleaned_explanation = clean_poll_text(raw_explanation)
        explanation_text = f"Объяснение: {cleaned_explanation}"[:200]

        poll_message = await bot.send_poll(
            chat_id=tg_user_id,
            question=question_text,
            options=shuffled_options,
            type="quiz",
            correct_option_id=new_correct_id,
            is_anonymous=False,
            explanation=explanation_text
        )

        # Store poll mapping
        poll_mapping = PollMapping(
            poll_id=poll_message.poll.id,
            quiz_id=quiz.id,
            correct_option_id=new_correct_id,
            question_index=i
        )
        session.add(poll_mapping)
        await asyncio.sleep(0.5)

    await session.commit()
    logger.info(f"User {tg_user_id} started quiz for digest #{digest_id}")
