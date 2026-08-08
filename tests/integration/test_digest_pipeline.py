import pytest
from datetime import datetime, timedelta, timezone
from sqlalchemy import select

from models.post import Post
from models.digest import Digest
from models.quiz import Quiz
from parser.post_extractor import DigestPipeline
from parser.llm_layer import MessageExtractor


@pytest.fixture(autouse=True)
def mock_publisher(mocker):
    return mocker.patch("tg_bot.publisher.publish_digest_by_id")


@pytest.fixture
def mock_extractor(mocker):
    extractor = MessageExtractor(
        model_names=["google/gemini-2.5-flash", "deepseek/deepseek-v4-pro"],
        api_keys=["fake_key"],
        proxy=""
    )
    return extractor


from parser.prompts import post_schema


async def test_run_llm_processing_job(db_session, redis_client, mock_extractor, mocker):
    tz = timezone(timedelta(hours=3))
    post = Post(
        id=101,
        title="Тестовый заголовок",
        content="Интересный пост про ИИ архитектуры",
        post_date=datetime.now(tz),
        is_ad_or_trash=None
    )
    db_session.add(post)
    await db_session.commit()

    # Mock call_llm response with dual format output
    llm_response = ({
        "is_ad_or_trash": False,
        "is_tech_relevant": True,
        "is_simple_relevant": True,
        "analysis": "Пост про архитектуру с понятным выхлопом.",
        "tech_facts": ["В модели применен MLA-аттеншн."],
        "simple_facts": ["Модель работает на 50% быстрее для пользователей."],
        "tech_questions": [{
            "question": "В чем плюс MLA?",
            "options": ["А", "Б", "В", "Г"],
            "correct_answer": "А",
            "explanation": "Объяснение",
            "difficulty_level": "hard"
        }],
        "simple_questions": [{
            "question": "На сколько быстрее работает модель?",
            "options": ["50%", "10%", "20%", "100%"],
            "correct_answer": "50%",
            "explanation": "Объяснение",
            "difficulty_level": "easy"
        }]
    }, 150)
    
    mocker.patch.object(mock_extractor, "call_llm", return_value=llm_response)

    pipeline = DigestPipeline(
        tg_sources=[],
        tg_parser=None,
        extractor=mock_extractor,
        db_session=db_session,
        redis_client=redis_client
    )

    await pipeline.run_llm_processing_job(schema=post_schema)

    updated_post = await db_session.get(Post, post.id)
    assert updated_post.is_ad_or_trash is False
    assert updated_post.is_tech_relevant is True
    assert updated_post.is_simple_relevant is True
    assert len(updated_post.tech_facts) == 1
    assert len(updated_post.simple_facts) == 1
    assert updated_post.tokens == 150


async def test_run_digest_assembly_tech_and_simple(db_session, redis_client, mock_extractor, mocker):
    tz = timezone(timedelta(hours=3))
    post = Post(
        id=102,
        title="Заголовок будни",
        content="Пост буднего дня",
        post_date=datetime.now(tz),
        is_ad_or_trash=False,
        is_tech_relevant=True,
        is_simple_relevant=True,
        tech_facts=["Технический факт"],
        simple_facts=["Простой факт"],
        link="https://t.me/test_chan/102"
    )
    db_session.add(post)
    await db_session.commit()

    mocker.patch.object(mock_extractor, "call_llm", return_value=("Дайджест за день", 200))

    pipeline = DigestPipeline(
        tg_sources=[],
        tg_parser=None,
        extractor=mock_extractor,
        db_session=db_session,
        redis_client=redis_client
    )

    # 1. Run Tech assembly
    await pipeline.run_digest_assembly_job(digest_type="tech", is_sunday_quiz=False)
    
    # 2. Run Simple assembly
    await pipeline.run_digest_assembly_job(digest_type="simple", is_sunday_quiz=False)

    digests = (await db_session.execute(select(Digest))).scalars().all()
    assert len(digests) == 2
    types = [d.digest_type for d in digests]
    assert "tech" in types
    assert "simple" in types

    updated_post = await db_session.get(Post, post.id)
    assert updated_post.tech_digest_id is not None
    assert updated_post.simple_digest_id is not None


async def test_run_digest_assembly_sunday(db_session, redis_client, mock_extractor, mocker):
    tz = timezone(timedelta(hours=3))
    sample_question = {
        "question": "Вопрос недели?",
        "options": ["1", "2", "3", "4"],
        "correct_answer": "1",
        "explanation": "Пояснение",
        "difficulty_level": "medium"
    }

    post = Post(
        id=103,
        title="Заголовок воскресенье",
        content="Воскресный пост",
        post_date=datetime.now(tz),
        is_ad_or_trash=False,
        facts=["Воскресный факт"],
        questions=[sample_question],
        link="https://t.me/test_chan/103"
    )
    db_session.add(post)
    await db_session.commit()

    # Mock call_llm for quiz selection & digest creation
    def side_effect(user_prompt, schema=None, model_name=None):
        if schema is not None:
            return ({"questions": [sample_question]}, 100)
        return ("Дайджест с призывом к квизу", 250)

    mocker.patch.object(mock_extractor, "call_llm", side_effect=side_effect)

    pipeline = DigestPipeline(
        tg_sources=[],
        tg_parser=None,
        extractor=mock_extractor,
        db_session=db_session,
        redis_client=redis_client
    )

    await pipeline.run_digest_assembly_job(is_sunday_quiz=True)

    digests = (await db_session.execute(select(Digest))).scalars().all()
    assert len(digests) == 1
    new_digest = digests[0]

    quizzes = (await db_session.execute(select(Quiz))).scalars().all()
    assert len(quizzes) == 1
    assert quizzes[0].digest_id == new_digest.id
    assert len(quizzes[0].questions) == 1


async def test_run_digest_assembly_sunday_llm_fallback(db_session, redis_client, mock_extractor, mocker):
    tz = timezone(timedelta(hours=3))
    sample_question = {
        "question": "Сложный вопрос?",
        "options": ["A", "B", "C", "D"],
        "correct_answer": "A",
        "explanation": "Пояснение",
        "difficulty_level": "hard"
    }

    post = Post(
        id=104,
        title="Заголовок фолбэк",
        content="Пост для фолбэка",
        post_date=datetime.now(tz),
        is_ad_or_trash=False,
        facts=["Факт"],
        questions=[sample_question],
        link="https://t.me/test_chan/104"
    )
    db_session.add(post)
    await db_session.commit()

    call_history = []

    def side_effect(user_prompt, schema=None, model_name=None):
        if schema is not None:
            call_history.append(model_name)
            # First model fails / returns empty questions
            if model_name == "google/gemini-2.5-flash":
                return ({"questions": []}, 50)
            # Second model succeeds
            return ({"questions": [sample_question]}, 120)
        return ("Дайджест после фолбэка", 200)

    mocker.patch.object(mock_extractor, "call_llm", side_effect=side_effect)

    pipeline = DigestPipeline(
        tg_sources=[],
        tg_parser=None,
        extractor=mock_extractor,
        db_session=db_session,
        redis_client=redis_client
    )

    await pipeline.run_digest_assembly_job(is_sunday_quiz=True)

    # Verify first model was tried, failed, and second model succeeded
    assert "google/gemini-2.5-flash" in call_history
    assert "deepseek/deepseek-v4-pro" in call_history

    quizzes = (await db_session.execute(select(Quiz))).scalars().all()
    assert len(quizzes) == 1
    assert len(quizzes[0].questions) == 1


async def test_digest_assembly_cutoff_filter(db_session, redis_client, mock_extractor, mocker):
    tz = timezone(timedelta(hours=3))
    now = datetime.now(tz)

    # 1. Post older than 24 hours (2 days ago)
    old_post = Post(
        id=201,
        title="Старый пост",
        content="Пост двухдневной давности",
        post_date=now - timedelta(days=2),
        is_ad_or_trash=False,
        is_tech_relevant=True,
        tech_facts=["Старый факт"],
        link="https://t.me/test_chan/201"
    )

    # 2. Fresh post (2 hours ago)
    fresh_post = Post(
        id=202,
        title="Свежий пост",
        content="Свежий пост за последние 24 часа",
        post_date=now - timedelta(hours=2),
        is_ad_or_trash=False,
        is_tech_relevant=True,
        tech_facts=["Свежий факт"],
        link="https://t.me/test_chan/202"
    )

    db_session.add_all([old_post, fresh_post])
    await db_session.commit()

    mocker.patch.object(mock_extractor, "call_llm", return_value=("Дайджест только из свежих постов", 100))

    pipeline = DigestPipeline(
        tg_sources=[],
        tg_parser=None,
        extractor=mock_extractor,
        db_session=db_session,
        redis_client=redis_client
    )

    await pipeline.run_digest_assembly_job(digest_type="tech", is_sunday_quiz=False)

    # Verify only fresh_post got assigned to digest
    updated_old = await db_session.get(Post, old_post.id)
    updated_fresh = await db_session.get(Post, fresh_post.id)

    assert updated_old.tech_digest_id is None, "Старый пост не должен входить в дайджест"
    assert updated_fresh.tech_digest_id is not None, "Свежий пост должен войти в дайджест"


