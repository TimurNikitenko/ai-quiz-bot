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

async def send_welcome_message(message: Message):
    text = (
        "👋 *Привет! Добро пожаловать в AI Digest & Quiz Bot!*\n\n"
        "Я помогаю проверять знания и глубже погружаться в мир искусственного интеллекта на основе дайджестов нашего канала.\n\n"
        "📌 *Какая тема у наших дайджестов и квизов?*\n"
        "Мы пишем о самых важных новостях из мира **AI, LLM, нейросетей и машинного обучения**. Каждый дайджест сочетает в себе:\n"
        "• ⚙️ *Глубокие технические детали* для разработчиков (архитектура, оптимизации, бенчмарки).\n"
        "• 💼 *Бизнес-ценность* для менеджеров и аналитиков (влияние на процессы, стоимость интеграции, экономия ресурсов).\n\n"
        "🎮 *Как проходить квизы?*\n"
        "1️⃣ Перейдите по ссылке *«🧠 Пройти квиз»* под любым дайджестом в нашем канале.\n"
        "2️⃣ Бот будет присылать вам вопросы **по очереди**, один за другим.\n"
        "3️⃣ За каждый правильный ответ вы получаете **1 балл** к вашему глобальному рейтингу.\n"
        "4️⃣ После ответа вы сразу увидите пояснение к вопросу.\n\n"
        "🛠 *Доступные команды:*\n"
        "• `/start` — Начало работы и краткое приветствие.\n"
        "• `/help` — Подробное руководство по возможностям бота и темам.\n"
        "• `/leaderboard` — Посмотреть топ участников и свое место в рейтинге.\n"
        "• `/review` — Работа над ошибками (бот пришлет до 5 вопросов, на которые вы ответили неверно, чтобы вы могли исправить результат).\n\n"
        "🧠 *Готовы проверить себя?* Переходите к последнему дайджесту в канале и жмите кнопку прохождения!"
    )
    await message.answer(text, parse_mode="Markdown")

async def send_quiz_question(
    chat_id: int,
    quiz: Quiz,
    question_index: int,
    bot: Bot,
    session: AsyncSession
):
    if not quiz.questions or question_index >= len(quiz.questions):
        return

    q = quiz.questions[question_index]
    question_text = clean_poll_text(q["question"])
    correct_text = clean_poll_text(q["correct_answer"])
    shuffled_options = [clean_poll_text(opt) for opt in q["options"]]
    random.shuffle(shuffled_options)
    new_correct_id = shuffled_options.index(correct_text)

    raw_explanation = q.get("explanation", "Подробности в тексте дайджеста.")
    cleaned_explanation = clean_poll_text(raw_explanation)
    explanation_text = f"Объяснение: {cleaned_explanation}"[:200]

    poll_message = await bot.send_poll(
        chat_id=chat_id,
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
        question_index=question_index
    )
    session.add(poll_mapping)

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
        await send_welcome_message(message)
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
    existing_answers_stmt = (
        select(UserAnswer)
        .join(PollMapping, UserAnswer.telegram_poll_id == PollMapping.poll_id)
        .where(
            UserAnswer.user_id == user.id,
            UserAnswer.quiz_id == quiz.id,
            PollMapping.original_user_answer_id.is_(None)
        )
    )
    existing_answers = (await session.execute(existing_answers_stmt)).scalars().all()
    total_count = len(quiz.questions)

    if existing_answers:
        answered_count = len(existing_answers)
        if answered_count >= total_count:
            correct_count = sum(1 for ans in existing_answers if ans.is_correct)
            await message.answer(
                f"ℹ️ *Вы уже прошли этот квиз!*\n\n"
                f"📊 Ваш результат: *{correct_count}* из *{total_count}* правильных ответов.\n"
                f"🏆 Ваш общий рейтинг: *{user.global_score}* баллов.",
                parse_mode="Markdown"
            )
            return
        else:
            # Started but not finished, resume
            await message.answer(
                f"ℹ️ *Вы уже начали этот квиз!*\n"
                f"Продолжаем прохождение. Вопрос *{answered_count + 1}* из *{total_count}*:",
                parse_mode="Markdown"
            )
            await send_quiz_question(tg_user_id, quiz, answered_count, bot, session)
            await session.commit()
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

    # Send the first question
    await send_quiz_question(tg_user_id, quiz, 0, bot, session)
    await session.commit()
    logger.info(f"User {tg_user_id} started quiz for digest #{digest_id}")

@router.message(Command("help"))
async def handle_help(message: Message, session: AsyncSession):
    # Simply send the welcome/help message
    await send_welcome_message(message)
