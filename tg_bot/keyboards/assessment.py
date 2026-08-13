"""Генерация клавиатур (InlineKeyboards) для оценки форматов дайджеста."""

from typing import Optional
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_assessment_keyboard(
    digest_id: int,
    format_variant: str,
    selected_rating: Optional[int] = None
) -> InlineKeyboardMarkup:
    """Генерирует 1-5 звездную клавиатуру для оценки конкретного формата дайджеста."""
    if selected_rating is not None:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(
                    text=f"✅ Ваша оценка: {'⭐' * selected_rating} ({selected_rating}/5)",
                    callback_data=f"assess_done:{digest_id}"
                )]
            ]
        )

    buttons = []
    star_row = []
    for star in range(1, 6):
        star_row.append(
            InlineKeyboardButton(
                text=f"⭐ {star}",
                callback_data=f"assess_vote:{digest_id}:{format_variant}:{star}"
            )
        )
    buttons.append(star_row)

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_feedback_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура после завершения оценки всех форматов."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✍️ Оставить комментарий",
                    callback_data="assess_comment_prompt"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🏁 Завершить",
                    callback_data="assess_finish"
                )
            ]
        ]
    )
