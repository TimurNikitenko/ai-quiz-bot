import logging
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
        await message.answer("🏆 *Рейтинг игроков пока пуст!* Будьте первыми!", parse_mode="Markdown")
        return
        
    text = "🏆 *Рейтинг участников квиза:*\n\n"
    for idx, u in enumerate(users, 1):
        medal = "🥇" if idx == 1 else "🥈" if idx == 2 else "🥉" if idx == 3 else f"{idx}."
        username_str = f"@{u.username}" if u.username else f"Игрок {u.telegram_id}"
        text += f"{medal} {username_str} — *{u.global_score}* баллов\n"
        
    await message.answer(text, parse_mode="Markdown")
