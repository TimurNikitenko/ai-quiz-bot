import os
import pytest
import redis.asyncio as redis
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from models.base import Base
# Import all models so metadata is complete
from models.user import User
from models.post import Post
from models.digest import Digest
from models.quiz import Quiz
from models.user_answers import UserAnswer

load_dotenv()


@pytest.fixture(scope="session")
def db_url():
    user = os.getenv("DB_USER", "somerandname")
    password = os.getenv("DB_PASSWORD", "not22so33rand22pass")
    db = os.getenv("DB_NAME", "ai_digest_db")
    host = os.getenv("TEST_DB_HOST", "localhost")
    port = os.getenv("TEST_DB_PORT", "5434")
    os.environ["TEST_DB_PORT"] = port
    os.environ["TEST_DB_HOST"] = host
    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{db}"


@pytest.fixture(scope="session")
def redis_url():
    host = os.getenv("TEST_REDIS_HOST", "localhost")
    port = int(os.getenv("TEST_REDIS_PORT", "6380"))
    password = os.getenv("REDIS_PASSWORD", "")
    return host, port, password


@pytest.fixture
async def db_engine(db_url):
    engine = create_async_engine(db_url, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def db_session(db_engine):
    async_session = async_sessionmaker(db_engine, expire_on_commit=False)
    async with async_session() as session:
        yield session


@pytest.fixture
async def redis_client(redis_url):
    host, port, password = redis_url
    client = redis.Redis(
        host=host,
        port=port,
        password=password,
        decode_responses=True
    )
    yield client
    await client.flushdb()
    await client.aclose()
