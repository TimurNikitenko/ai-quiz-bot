import os
import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from models import Digest
from bot import publish_digest_by_id

router = Router()
logger = logging.getLogger(__name__)

def is_admin(user_id: int) -> bool:
    admin_id_str = os.getenv("ADMIN_TELEGRAM_ID")
    if not admin_id_str:
        return False
    try:
        return user_id == int(admin_id_str)
    except ValueError:
        return False

@router.callback_query(F.data.startswith("approve_digest:"))
async def approve_digest_callback(callback: CallbackQuery, session: AsyncSession):
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав администратора!", show_alert=True)
        return
        
    digest_id = int(callback.data.split(":")[1])
    await callback.answer("Публикация...")
    
    try:
        # Публикуем дайджест в канал
        await publish_digest_by_id(digest_id)
        
        # Обновляем сообщение для админа
        await callback.message.edit_text(
            f"✅ *Дайджест #{digest_id} успешно опубликован в канале!*",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Ошибка при одобрении дайджеста #{digest_id}: {e}")
        await callback.message.answer(f"❌ Ошибка при публикации дайджеста #{digest_id}: {e}")

@router.callback_query(F.data.startswith("delete_digest:"))
async def delete_digest_callback(callback: CallbackQuery, session: AsyncSession):
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав администратора!", show_alert=True)
        return
        
    digest_id = int(callback.data.split(":")[1])
    await callback.answer("Удаление...")
    
    try:
        # Находим и удаляем дайджест
        stmt = select(Digest).where(Digest.id == digest_id)
        digest = (await session.execute(stmt)).scalar_one_or_none()
        if digest:
            await session.delete(digest)
            await session.commit()
            
        await callback.message.edit_text(
            f"❌ *Дайджест #{digest_id} удален из базы.*",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Ошибка при удалении дайджеста #{digest_id}: {e}")
        await callback.message.answer(f"❌ Ошибка при удалении дайджеста #{digest_id}: {e}")
