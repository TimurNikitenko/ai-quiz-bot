import os
import random
import asyncio
import logging
from aiogram import Router, F, Bot
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from models import Quiz, PollMapping
from tg_bot.handlers.quiz import clean_poll_text

router = Router()
logger = logging.getLogger(__name__)

@router.message(F.forward_from_chat)
async def handle_forwarded_post(message: Message, session: AsyncSession, bot: Bot):
    channel_id_str = os.getenv("CHANNEL_ID")
    if not channel_id_str:
        return
    try:
        channel_id = int(channel_id_str)
    except ValueError:
        return

    # Check if the forwarded message is from our channel
    if message.forward_from_chat.id != channel_id:
        return

    logger.info(f"Received forwarded message {message.forward_from_message_id} in discussion group {message.chat.id}")

    # Retry querying the Quiz up to 3 times to ensure the publishing transaction is committed
    quiz = None
    for attempt in range(3):
        stmt = select(Quiz).where(Quiz.poll_info["telegram_message_id"].as_integer() == message.forward_from_message_id)
        quiz = (await session.execute(stmt)).scalar_one_or_none()
        if quiz:
            break
        await asyncio.sleep(1.0)

    if not quiz:
        logger.info(f"Forwarded message {message.forward_from_message_id} did not match any quiz in database.")
        return

    logger.info(f"Found quiz {quiz.id} for forwarded message {message.forward_from_message_id}. Posting polls...")

    if not quiz.questions:
        logger.warning(f"Quiz {quiz.id} has no questions to post.")
        return

    # Post polls to the comments (discussion group)
    for idx, q in enumerate(quiz.questions):
        question_text = clean_poll_text(q["question"])
        correct_text = clean_poll_text(q["correct_answer"])
        shuffled_options = [clean_poll_text(opt) for opt in q["options"]]
        random.shuffle(shuffled_options)
        new_correct_id = shuffled_options.index(correct_text)

        raw_explanation = q.get("explanation", "Подробности в тексте дайджеста.")
        cleaned_explanation = clean_poll_text(raw_explanation)
        explanation_text = f"Объяснение: {cleaned_explanation}"[:200]

        try:
            poll_message = await bot.send_poll(
                chat_id=message.chat.id,
                question=question_text,
                options=shuffled_options,
                type="quiz",
                correct_option_id=new_correct_id,
                is_anonymous=False,
                explanation=explanation_text,
                reply_to_message_id=message.message_id
            )

            # Store poll mapping as comments poll
            poll_mapping = PollMapping(
                poll_id=poll_message.poll.id,
                quiz_id=quiz.id,
                correct_option_id=new_correct_id,
                question_index=idx,
                is_comments_poll=True
            )
            session.add(poll_mapping)
            logger.info(f"Created comments poll mapping {idx} for quiz {quiz.id} (poll_id: {poll_message.poll.id})")
        except Exception as poll_err:
            logger.error(f"Error posting comments poll {idx} for quiz {quiz.id}: {poll_err}")

    # Update the reply markup on the channel message to add the comments button
    try:
        group_id_str = str(message.chat.id)
        if group_id_str.startswith("-100"):
            clean_group_id = group_id_str[4:]
        else:
            clean_group_id = group_id_str

        comments_link = f"https://t.me/c/{clean_group_id}/{message.message_id}"

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="💬 Пройти в комментариях",
                        url=comments_link
                    )
                ]
            ]
        )
        await bot.edit_message_reply_markup(
            chat_id=channel_id,
            message_id=message.forward_from_message_id,
            reply_markup=keyboard
        )
        logger.info(f"Updated channel message reply markup with comments link: {comments_link}")
    except Exception as edit_err:
        logger.error(f"Failed to update channel message reply markup: {edit_err}")

    await session.commit()
