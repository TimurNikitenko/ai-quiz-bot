import logging
from aiogram import Router, Bot
from aiogram.types import PollAnswer
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from models import User, UserAnswer, Quiz, PollMapping
from tg_bot.handlers.quiz import send_quiz_question

router = Router()
logger = logging.getLogger(__name__)

@router.poll_answer()
async def handle_poll_answer(poll_answer: PollAnswer, session: AsyncSession, bot: Bot):
    # 1. Извлекаем данные из ответа Telegram
    tg_user_id = poll_answer.user.id
    username = poll_answer.user.username
    poll_id = poll_answer.poll_id
    
    # Telegram присылает массив option_ids (поскольку в викторине можно выбрать только 1 ответ, берем нулевой элемент)
    if not poll_answer.option_ids:
        return
    selected_option = poll_answer.option_ids[0]

    # 2. Получаем или создаем пользователя (User) с блокировкой строки для предотвращения race conditions
    user_stmt = select(User).where(User.telegram_id == tg_user_id).with_for_update()
    user = (await session.execute(user_stmt)).scalar_one_or_none()
    
    if not user:
        user = User(telegram_id=tg_user_id, username=username)
        session.add(user)
        await session.flush() # Делаем flush, чтобы получить user.id для дальнейших связей

    # 3. Ищем PollMapping, которому принадлежит этот опрос
    mapping_stmt = select(PollMapping).where(PollMapping.poll_id == poll_id)
    mapping = (await session.execute(mapping_stmt)).scalar_one_or_none()

    if not mapping:
        logger.warning(f"Пришел ответ на неизвестный poll_id: {poll_id}")
        return

    # Обработка ответов на работу над ошибками (/review)
    if mapping.original_user_answer_id is not None:
        existing_answer_stmt = select(UserAnswer).where(
            UserAnswer.telegram_poll_id == poll_id,
            UserAnswer.user_id == user.id
        )
        if (await session.execute(existing_answer_stmt)).scalar_one_or_none():
            return

        is_correct = (selected_option == mapping.correct_option_id)
        
        # Сохраняем временную запись ответа, чтобы избежать повторного прохождения этого же ревью-опроса
        new_answer = UserAnswer(
            user_id=user.id,
            quiz_id=mapping.quiz_id,
            telegram_poll_id=poll_id,
            is_correct=is_correct
        )
        session.add(new_answer)

        if is_correct:
            # Обновляем оригинальный неверный ответ на верный
            orig_stmt = select(UserAnswer).where(UserAnswer.id == mapping.original_user_answer_id)
            orig_answer = (await session.execute(orig_stmt)).scalar_one_or_none()
            if orig_answer:
                orig_answer.is_correct = True
            
            user.global_score += 1
            await session.commit()
            
            await bot.send_message(
                chat_id=tg_user_id,
                text=f"🎉 *Правильно!* Ошибка исправлена, вам начислен *1* балл!\n🏆 Ваш рейтинг: *{user.global_score}* баллов.",
                parse_mode="Markdown"
            )
        else:
            await session.commit()
            await bot.send_message(
                chat_id=tg_user_id,
                text="❌ *Неверно.* Попробуйте еще раз в следующий раз!",
                parse_mode="Markdown"
            )
        return

    # 4. Проверяем, не отвечал ли юзер на этот вопрос ранее (включая комментарии/бот)
    duplicate_stmt = (
        select(UserAnswer)
        .join(PollMapping, UserAnswer.telegram_poll_id == PollMapping.poll_id)
        .where(
            UserAnswer.user_id == user.id,
            UserAnswer.quiz_id == mapping.quiz_id,
            PollMapping.question_index == mapping.question_index
        )
    )
    if (await session.execute(duplicate_stmt)).scalar_one_or_none():
        logger.info(f"User {username} already answered question index {mapping.question_index} of quiz {mapping.quiz_id}")
        return

    # Если это публичный опрос из комментариев канала
    if mapping.is_comments_poll:
        is_correct = (selected_option == mapping.correct_option_id)
        new_answer = UserAnswer(
            user_id=user.id,
            quiz_id=mapping.quiz_id,
            telegram_poll_id=poll_id,
            is_correct=is_correct
        )
        session.add(new_answer)

        if is_correct:
            user.global_score += 1
            if user.username != username:
                user.username = username

        await session.commit()
        logger.info(f"User {username} answered comments poll {poll_id}. Correct: {is_correct}. Score: {user.global_score}")
        return

    # 5. Проверяем правильность ответа
    is_correct = (selected_option == mapping.correct_option_id)

    # 6. Сохраняем ответ в историю
    new_answer = UserAnswer(
        user_id=user.id,
        quiz_id=mapping.quiz_id,
        telegram_poll_id=poll_id,
        is_correct=is_correct
    )
    session.add(new_answer)

    # 7. Начисляем глобальный балл, если ответ верный
    if is_correct:
        user.global_score += 1
        # Обновляем username, если он сменился
        if user.username != username:
            user.username = username

    # Фиксируем все изменения в БД (создание юзера, ответ, баллы) одной транзакцией
    await session.commit()
    logger.info(f"User {username} answered poll {poll_id}. Correct: {is_correct}. Score: {user.global_score}")

    # 8. Проверяем завершение квиза
    # Получаем исходный квиз, чтобы узнать общее число вопросов
    quiz_stmt = select(Quiz).where(Quiz.id == mapping.quiz_id)
    quiz = (await session.execute(quiz_stmt)).scalar_one_or_none()
    
    if quiz and quiz.questions:
        total_questions = len(quiz.questions)
        
        # Считаем количество ответов пользователя на этот квиз
        answers_count_stmt = (
            select(func.count(UserAnswer.id))
            .join(PollMapping, UserAnswer.telegram_poll_id == PollMapping.poll_id)
            .where(
                UserAnswer.user_id == user.id,
                UserAnswer.quiz_id == quiz.id,
                PollMapping.original_user_answer_id.is_(None)
            )
        )
        answered_count = (await session.execute(answers_count_stmt)).scalar() or 0
        
        if answered_count < total_questions:
            # Отправляем следующий вопрос
            await send_quiz_question(tg_user_id, quiz, answered_count, bot, session)
            await session.commit()
        elif answered_count == total_questions:
            # Квиз полностью пройден, получаем все ответы пользователя по этому квизу
            all_answers_stmt = (
                select(UserAnswer)
                .join(PollMapping, UserAnswer.telegram_poll_id == PollMapping.poll_id)
                .where(
                    UserAnswer.user_id == user.id,
                    UserAnswer.quiz_id == quiz.id,
                    PollMapping.original_user_answer_id.is_(None)
                )
            )
            all_answers = (await session.execute(all_answers_stmt)).scalars().all()
            correct_count = sum(1 for ans in all_answers if ans.is_correct)
            
            try:
                await bot.send_message(
                    chat_id=tg_user_id,
                    text=f"🎉 *Вы прошли квиз!*\n\n"
                         f"📊 Результат: *{correct_count}* из *{total_questions}* правильных ответов.\n"
                         f"🏆 Ваш общий рейтинг: *{user.global_score}* баллов.",
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Ошибка при отправке сообщения о завершении квиза юзеру {tg_user_id}: {e}")