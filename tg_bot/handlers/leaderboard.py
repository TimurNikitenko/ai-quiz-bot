import logging
import html
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from models import User

router = Router()
logger = logging.getLogger(__name__)

@router.message(Command("leaderboard"))
async def show_leaderboard(message: Message, session: AsyncSession):
    stmt = select(User).order_by(User.global_score.desc()).limit(10)
    result = await session.execute(stmt)
    users = result.scalars().all()
    
    if not users:
        await message.answer("🏆 <b>Рейтинг игроков пока пуст!</b> Будьте первыми!", parse_mode="HTML")
        return
        
    text = "🏆 <b>Рейтинг участников квиза:</b>\n\n"
    for idx, u in enumerate(users, 1):
        medal = "🥇" if idx == 1 else "🥈" if idx == 2 else "🥉" if idx == 3 else f"{idx}."
        username_str = f"@{u.username}" if u.username else f"Игрок {u.telegram_id}"
        escaped_username = html.escape(username_str)
        text += f"{medal} {escaped_username} — <b>{u.global_score}</b> баллов\n"
        
    await message.answer(text, parse_mode="HTML")
