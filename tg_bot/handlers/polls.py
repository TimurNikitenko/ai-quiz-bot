import logging
from aiogram import Router
from aiogram.types import PollAnswer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from models import User, UserAnswer, Quiz 

router = Router()
logger = logging.getLogger(__name__)

@router.poll_answer()
async def handle_poll_answer(poll_answer: PollAnswer, session: AsyncSession):
    # 1. Извлекаем данные из ответа Telegram
    tg_user_id = poll_answer.user.id
    username = poll_answer.user.username
    poll_id = poll_answer.poll_id
    
    # Telegram присылает массив option_ids (поскольку в викторине можно выбрать только 1 ответ, берем нулевой элемент)
    if not poll_answer.option_ids:
        return
    selected_option = poll_answer.option_ids[0]

    # 2. Получаем или создаем пользователя (User)
    user_stmt = select(User).where(User.telegram_id == tg_user_id)
    user = (await session.execute(user_stmt)).scalar_one_or_none()
    
    if not user:
        user = User(telegram_id=tg_user_id, username=username)
        session.add(user)
        await session.flush() # Делаем flush, чтобы получить user.id для дальнейших связей

    # 3. Ищем Quiz, которому принадлежит этот опрос
    # В PostgreSQL JSONB оператор has_key позволяет мгновенно найти нужную запись
    quiz_stmt = select(Quiz).where(Quiz.poll_info.has_key(poll_id))
    quiz = (await session.execute(quiz_stmt)).scalar_one_or_none()

    if not quiz:
        logger.warning(f"Пришел ответ на неизвестный poll_id: {poll_id}")
        return

    # 4. Проверяем, не отвечал ли юзер на этот вопрос ранее 
    # (Защита от дублей, если Telegram пришлет событие дважды при лагах сети)
    existing_answer_stmt = select(UserAnswer).where(
        UserAnswer.telegram_poll_id == poll_id, 
        UserAnswer.user_id == user.id
    )
    if (await session.execute(existing_answer_stmt)).scalar_one_or_none():
        return # Уже обработали

    # 5. Проверяем правильность ответа
    correct_option_id = quiz.poll_info[poll_id]
    is_correct = (selected_option == correct_option_id)

    # 6. Сохраняем ответ в историю
    new_answer = UserAnswer(
        user_id=user.id,
        quiz_id=quiz.id,
        telegram_poll_id=poll_id,
        is_correct=is_correct
    )
    session.add(new_answer)

    # 7. Начисляем глобальный балл, если ответ верный
    if is_correct:
        user.global_score += 1
        # По желанию: здесь же можно обновлять username, если он сменился у старого юзера
        if user.username != username:
            user.username = username

    # Фиксируем все изменения в БД (создание юзера, ответ, баллы) одной транзакцией
    await session.commit()
    logger.info(f"User {username} answered poll {poll_id}. Correct: {is_correct}. Score: {user.global_score}")