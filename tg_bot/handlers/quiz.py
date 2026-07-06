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
        "1️⃣ Перейдите по ссылке *«💬 Пройти в комментариях»* под любым дайджестом в нашем канале.\n"
        "2️⃣ Отвечайте на вопросы викторины прямо в комментариях к посту.\n"
        "3️⃣ За каждый правильный ответ вы получаете **1 балл** к вашему глобальному рейтингу.\n"
        "4️⃣ После выбора ответа вы сразу увидите правильный вариант и пояснение.\n\n"
        "🛠 *Доступные команды:*\n"
        "• `/start` — Начало работы и краткое приветствие.\n"
        "• `/help` — Подробное руководство по возможностям бота и темам.\n"
        "• `/leaderboard` — Посмотреть топ участников и свое место в рейтинге.\n"
        "• `/review` — Работа над ошибками (бот пришлет до 5 вопросов из комментариев, на которые вы ответили неверно, чтобы вы могли исправить результат).\n\n"
        "🧠 *Готовы проверить себя?* Переходите к последнему дайджесту в канале и оставляйте свои ответы в комментариях!"
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
    if args and args.startswith("quiz_"):
        await message.answer(
            "❌ *Прохождение квизов в боте отключено.*\n\n"
            "Все квизы теперь проходят прямо в комментариях под дайджестами в канале! Перейдите в канал и нажмите кнопку *«💬 Пройти в комментариях»* под интересующим вас дайджестом.",
            parse_mode="Markdown"
        )
        return

    await send_welcome_message(message)

@router.message(Command("help"))
async def handle_help(message: Message, session: AsyncSession):
    # Simply send the welcome/help message
    await send_welcome_message(message)
