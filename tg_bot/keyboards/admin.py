"""Генерация клавиатур (InlineKeyboards) для административной панели бота."""

from typing import List
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_digest_review_keyboard(digest_id: int, photos: List[str]) -> InlineKeyboardMarkup:
    """Генерирует клавиатуру для ручной проверки и публикации черновика дайджеста."""
    buttons = []

    if photos:
        # Кнопка публикации без фото
        buttons.append([InlineKeyboardButton(
            text="✅ Опубликовать без фото",
            callback_data=f"approve_digest:{digest_id}:no_photo"
        )])

        # Кнопки для каждого фото
        photo_buttons = []
        for idx in range(len(photos)):
            photo_buttons.append(InlineKeyboardButton(
                text=f"🖼 С Фото {idx + 1}",
                callback_data=f"approve_digest:{digest_id}:photo_{idx}"
            ))

        # Разделяем по две кнопки в ряд
        for i in range(0, len(photo_buttons), 2):
            buttons.append(photo_buttons[i:i+2])
    else:
        buttons.append([InlineKeyboardButton(
            text="✅ Одобрить и опубликовать",
            callback_data=f"approve_digest:{digest_id}:no_photo"
        )])

    # Кнопка удаления черновика
    buttons.append([InlineKeyboardButton(
        text="❌ Удалить",
        callback_data=f"delete_digest:{digest_id}"
    )])

    return InlineKeyboardMarkup(inline_keyboard=buttons)
