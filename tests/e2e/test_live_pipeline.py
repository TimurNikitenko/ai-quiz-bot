import os
import pytest
from dotenv import load_dotenv
from sqlalchemy import select

from models.post import Post
from models.digest import Digest
from models.quiz import Quiz
from parser.telegram_parser import TGParser
from parser.llm_layer import MessageExtractor
from parser.post_extractor import DigestPipeline
from parser.prompts import post_schema
from parser.sources import TG_SOURCES
from tg_bot.publisher import publish_digest_by_id

load_dotenv()


@pytest.mark.e2e
async def test_live_full_pipeline(db_session, redis_client):
    """Сквозной живой тест: Парсинг реального канала -> Запрос к OpenRouter LLM -> Сборка дайджеста и квиза -> Публикация в тестовый TG-канал."""
    
    # 1. Проверка наличия ключей
    tg_api_id = os.getenv("TELEGRAM_API_ID")
    tg_api_hash = os.getenv("TELEGRAM_API_HASH")
    openrouter_key = (os.getenv("OPENROUTER_API_KEY") or "").strip("'\"")
    test_channel_id = os.getenv("TEST_CHANNEL_ID") or os.getenv("CHANNEL_ID")
    
    if not all([tg_api_id, tg_api_hash, openrouter_key, test_channel_id]):
        pytest.skip("Пропуск E2E теста: отсутствуют необходимые API ключи в .env")

    # Проверка валидности OpenRouter API ключа
    from openai import OpenAI
    try:
        check_client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=openrouter_key)
        check_client.chat.completions.create(
            model=os.getenv("LLM_CHEAP_MODEL", "google/gemini-2.5-flash"),
            messages=[{"role": "user", "content": "ping"}]
        )
    except Exception as key_err:
        pytest.skip(f"Пропуск E2E теста: OpenRouter API ключ недействителен ({key_err})")

    proxy_host = os.getenv("PROXY_HOST", "127.0.0.1")
    proxy_port = int(os.getenv("PROXY_PORT", 1080))
    
    # Проверяем доступность прокси порта, если локально не запущен — подключаемся напрямую
    import socket
    proxy_available = False
    if proxy_host and proxy_port:
        try:
            with socket.create_connection((proxy_host, proxy_port), timeout=1.0):
                proxy_available = True
        except Exception:
            proxy_available = False

    use_proxy_host = proxy_host if proxy_available else None
    use_proxy_port = proxy_port if proxy_available else None
    proxy_url = f"socks5://{use_proxy_host}:{use_proxy_port}" if proxy_available else None

    # 2. Инициализация реального парсера и LLM
    tg_parser = TGParser(
        api_id=int(tg_api_id),
        api_hash=tg_api_hash,
        proxy_host=use_proxy_host,
        proxy_port=use_proxy_port,
        download_media=False
    )

    cheap_model = os.getenv("LLM_CHEAP_MODEL", "google/gemini-2.5-flash")
    expensive_model = os.getenv("LLM_EXPENSIVE_MODEL", "deepseek/deepseek-v4-pro")

    extractor = MessageExtractor(
        model_names=[cheap_model, expensive_model],
        api_keys=[openrouter_key],
        proxy=proxy_url
    )

    test_sources = ["MLunderhood", "ai_machinelearning_big_data", "llm_under_hood"]
    pipeline = DigestPipeline(
        tg_sources=test_sources,
        tg_parser=tg_parser,
        extractor=extractor,
        db_session=db_session,
        redis_client=redis_client
    )

    # 3. Реальный парсинг последних постов
    await pipeline.run_parsing_job()

    # 4. Реальная обработка сырых постов через OpenRouter LLM
    await pipeline.run_llm_processing_job(schema=post_schema, max_posts=20, model_name=cheap_model)

    # Проверяем наличие хотя бы одного пригодного (не мусорного) поста
    valid_posts = (await db_session.execute(select(Post).where(Post.is_ad_or_trash == False))).scalars().all()
    if not valid_posts:
        pytest.skip("E2E тест пропущен: все спарсенные посты были отфильтрованы как реклама/мусор")

    # Сохраняем существующих ID дайджестов в БД до сборки
    initial_digest_ids = set((await db_session.execute(select(Digest.id))).scalars().all())

    # Перенаправляем CHANNEL_ID на TEST_CHANNEL_ID для автопубликации во время сборки
    os.environ["CHANNEL_ID"] = test_channel_id

    # 5. Реальная сборка ежедневного дайджеста и еженедельного квиза
    await pipeline.run_digest_assembly_job(is_sunday_quiz=True, max_posts_in_digest=5, model_name=expensive_model)

    # Проверяем, что в БД создан НОВЫЙ дайджест конкретно в текущем прогоне
    all_digests = (await db_session.execute(select(Digest))).scalars().all()
    new_digests = [d for d in all_digests if d.id not in initial_digest_ids]
    assert len(new_digests) > 0, "Новый дайджест не был создан в текущей сессии E2E-теста"
    
    created_digest = new_digests[-1]
    assert created_digest.content is not None and len(created_digest.content) > 0

    quizzes = (await db_session.execute(select(Quiz).where(Quiz.digest_id == created_digest.id))).scalars().all()
    assert len(quizzes) > 0, "Еженедельный квиз не был создан для нового дайджеста"
