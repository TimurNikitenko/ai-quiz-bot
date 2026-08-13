"""Хэндлеры интерактивной оценки форматов дайджеста для коллег."""

import logging
from typing import List, Optional

from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import User, Digest, DigestAssessment
from tg_bot.keyboards.assessment import get_assessment_keyboard, get_feedback_keyboard
from utils.text_helpers import split_text, markdown_to_html

router = Router()
logger = logging.getLogger(__name__)


class AssessmentState(StatesGroup):
    waiting_for_comment = State()


async def present_digest_for_assessment(chat_id: int, digest: Digest, bot: Bot):
    """Отправляет полный форматированный пост дайджеста с клавиатурой 1-5 звезд."""
    variant_name = digest.digest_type.split(":")[-1] if ":" in digest.digest_type else digest.digest_type
    variant_labels = {
        "micro_tldr": "⚡ Вариант 1: Micro TL;DR (1 минута)",
        "tldr_plus_highlights": "📌 Вариант 2: Hybrid (TL;DR + Highlights)",
        "standard_grouped": "💡 Вариант 3: Standard Grouped (По категориям)",
        "bullet_feed": "🔹 Вариант 4: Bullet Feed (Лента)",
    }
    label = variant_labels.get(variant_name, f"Вариант: {variant_name}")
    header_text = f"━━━━━ {label} ━━━━━\n\n"

    full_content = header_text + (digest.content or "")
    keyboard = get_assessment_keyboard(digest.id, variant_name)

    chunks = split_text(full_content, limit=3500)

    for idx, chunk in enumerate(chunks):
        is_last = (idx == len(chunks) - 1)
        html_text = markdown_to_html(chunk)
        await bot.send_message(
            chat_id=chat_id,
            text=html_text,
            parse_mode="HTML",
            reply_markup=keyboard if is_last else None,
            disable_web_page_preview=True
        )


@router.message(Command("assess"))
async def handle_assess_command(message: Message, session: AsyncSession, state: FSMContext):
    """Запускает процесс оценки 4 экспериментальных форматов дайджеста."""
    tg_user_id = message.from_user.id
    username = message.from_user.username

    # 1. Получаем или создаем пользователя
    user_stmt = select(User).where(User.telegram_id == tg_user_id)
    user = (await session.execute(user_stmt)).scalar_one_or_none()
    if not user:
        user = User(telegram_id=tg_user_id, username=username)
        session.add(user)
        await session.flush()

    # 2. Ищем экспериментальные дайджесты в БД
    stmt = select(Digest).where(Digest.digest_type.like("simple:%")).order_by(Digest.created_at.desc()).limit(12)
    res = await session.execute(stmt)
    digests = res.scalars().all()

    if not digests:
        # Fallback к обычным simple-дайджестам
        stmt_fb = select(Digest).where(Digest.digest_type == "simple").order_by(Digest.created_at.desc()).limit(4)
        digests = (await session.execute(stmt_fb)).scalars().all()

    if not digests:
        await message.answer(
            "❌ *Дайджесты для оценки пока не сформированы.*\n"
            "Запустите скрипт генерации `python scripts/generate_experiment_digests.py`.",
            parse_mode="Markdown"
        )
        return

    # Группируем варианты
    variant_map = {}
    for d in digests:
        v_name = d.digest_type.split(":")[-1] if ":" in d.digest_type else d.digest_type
        if v_name not in variant_map:
            variant_map[v_name] = d

    items_to_assess = list(variant_map.values())[:4]
    digest_ids = [d.id for d in items_to_assess]

    await state.update_data(digest_ids=digest_ids, current_index=0)

    await message.answer(
        "📊 *Оценка экспериментальных форматов дайджеста*\n\n"
        "Мы подготовили 4 различных формата дайджеста новостей ИИ для менеджеров и нетехнических коллег.\n"
        "Оцените каждый вариант по шкале от 1 до 5 звезд под текстом каждого дайджеста.",
        parse_mode="Markdown"
    )

    # Показываем первый формат
    await present_digest_for_assessment(message.chat.id, items_to_assess[0], message.bot)


@router.callback_query(F.data.startswith("assess_vote:"))
async def handle_assess_vote(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    """Обрабатывает нажатие звезды 1-5 для формата дайджеста."""
    parts = callback.data.split(":")
    digest_id = int(parts[1])
    format_variant = parts[2]
    rating = int(parts[3])

    tg_user_id = callback.from_user.id
    username = callback.from_user.username

    # Получаем или создаем пользователя
    user_stmt = select(User).where(User.telegram_id == tg_user_id)
    user = (await session.execute(user_stmt)).scalar_one_or_none()
    if not user:
        user = User(telegram_id=tg_user_id, username=username)
        session.add(user)
        await session.flush()

    # Сохраняем или обновляем оценку
    stmt = select(DigestAssessment).where(
        DigestAssessment.user_id == user.id,
        DigestAssessment.digest_id == digest_id
    )
    assessment = (await session.execute(stmt)).scalar_one_or_none()
    if not assessment:
        assessment = DigestAssessment(
            user_id=user.id,
            digest_id=digest_id,
            format_variant=format_variant,
            rating=rating
        )
        session.add(assessment)
    else:
        assessment.rating = rating

    await session.commit()

    # Обновляем клавиатуру текущего сообщения
    await callback.message.edit_reply_markup(
        reply_markup=get_assessment_keyboard(digest_id, format_variant, selected_rating=rating)
    )
    await callback.answer(f"Оценка {rating}/5 сохранена!")

    # Отправляем следующий вариант
    state_data = await state.get_data()
    digest_ids = state_data.get("digest_ids", [])
    current_index = state_data.get("current_index", 0) + 1
    await state.update_data(current_index=current_index)

    if current_index < len(digest_ids):
        next_digest_id = digest_ids[current_index]
        next_digest = (await session.execute(select(Digest).where(Digest.id == next_digest_id))).scalar_one_or_none()
        if next_digest:
            await present_digest_for_assessment(callback.message.chat.id, next_digest, callback.bot)
    else:
        # Все варианты оценены
        await callback.message.answer(
            "🎉 *Спасибо! Вы оценили все варианты дайджеста.*\n\n"
            "Ваши оценки помогут нам выбрать идеальный формат для всей команды.",
            parse_mode="Markdown",
            reply_markup=get_feedback_keyboard()
        )


@router.callback_query(F.data == "assess_comment_prompt")
async def handle_comment_prompt(callback: CallbackQuery, state: FSMContext):
    """Переводит в состояние ожидания текстового отзыва."""
    await state.set_state(AssessmentState.waiting_for_comment)
    await callback.message.answer(
        "✍️ *Напишите ваш комментарий или пожелание в ответном сообщении:*",
        parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data == "assess_finish")
async def handle_assess_finish(callback: CallbackQuery, state: FSMContext):
    """Завершает сессию оценки."""
    await state.clear()
    await callback.message.answer("👍 Оценка завершена. Благодарим за участие!")
    await callback.answer()


@router.message(AssessmentState.waiting_for_comment)
async def handle_comment_input(message: Message, session: AsyncSession, state: FSMContext):
    """Принимает текстовый комментарий пользователя и прикрепляет его к последней оценке."""
    comment_text = message.text
    tg_user_id = message.from_user.id

    user = (await session.execute(select(User).where(User.telegram_id == tg_user_id))).scalar_one_or_none()
    if user:
        latest_stmt = (
            select(DigestAssessment)
            .where(DigestAssessment.user_id == user.id)
            .order_by(DigestAssessment.created_at.desc())
            .limit(1)
        )
        assessment = (await session.execute(latest_stmt)).scalar_one_or_none()
        if assessment:
            assessment.comment = comment_text
            await session.commit()

    await state.clear()
    await message.answer("✅ *Ваш отзыв успешно сохранен! Спасибо за обратную связь.*", parse_mode="Markdown")
