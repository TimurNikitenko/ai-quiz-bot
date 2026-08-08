"""Централизованные настройки приложения."""

import os
from functools import lru_cache
from typing import Optional
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from core.constants import DEFAULT_CHEAP_MODEL, DEFAULT_EXPENSIVE_MODEL

load_dotenv()


class Settings(BaseModel):
    # Database Settings
    db_user: str = Field(default_factory=lambda: os.getenv("DB_USER", "postgres"))
    db_password: str = Field(default_factory=lambda: os.getenv("DB_PASSWORD", "postgres"))
    db_name: str = Field(default_factory=lambda: os.getenv("DB_NAME", "ai_quiz_bot"))
    db_host: str = Field(default_factory=lambda: os.getenv("TEST_DB_HOST") or os.getenv("DB_HOST", "localhost"))
    db_port: int = Field(default_factory=lambda: int(os.getenv("TEST_DB_PORT") or os.getenv("DB_PORT", "5432")))

    # Redis Settings
    redis_host: str = Field(default_factory=lambda: os.getenv("REDIS_HOST", "localhost"))
    redis_port: int = Field(default_factory=lambda: int(os.getenv("REDIS_PORT", "6379")))
    redis_password: Optional[str] = Field(default_factory=lambda: os.getenv("REDIS_PASSWORD"))

    # Proxy Settings
    proxy_host: Optional[str] = Field(default_factory=lambda: os.getenv("PROXY_HOST"))
    proxy_port: int = Field(default_factory=lambda: int(os.getenv("PROXY_PORT", "1080")))

    # Telegram API & Bot Settings
    telegram_api_id: int = Field(default_factory=lambda: int(os.getenv("TELEGRAM_API_ID", "0")))
    telegram_api_hash: str = Field(default_factory=lambda: os.getenv("TELEGRAM_API_HASH", ""))
    bot_token: str = Field(default_factory=lambda: os.getenv("BOT_TOKEN", ""))
    channel_id: Optional[str] = Field(default_factory=lambda: os.getenv("CHANNEL_ID"))
    channel_id_tech: Optional[str] = Field(default_factory=lambda: os.getenv("CHANNEL_ID_TECH"))
    channel_id_simple: Optional[str] = Field(default_factory=lambda: os.getenv("CHANNEL_ID_SIMPLE"))
    admin_telegram_id: Optional[str] = Field(default_factory=lambda: os.getenv("ADMIN_TELEGRAM_ID"))

    # LLM Settings
    openrouter_api_key: str = Field(default_factory=lambda: (os.getenv("OPENROUTER_API_KEY") or "").strip("'\""))
    llm_cheap_model: str = Field(default_factory=lambda: os.getenv("LLM_CHEAP_MODEL", DEFAULT_CHEAP_MODEL))
    llm_expensive_model: str = Field(default_factory=lambda: os.getenv("LLM_EXPENSIVE_MODEL", DEFAULT_EXPENSIVE_MODEL))
    max_posts_to_process_llm: Optional[int] = Field(
        default_factory=lambda: int(os.getenv("MAX_POSTS_TO_PROCESS_LLM")) if os.getenv("MAX_POSTS_TO_PROCESS_LLM") else None
    )

    # General Behavior
    download_media: bool = Field(
        default_factory=lambda: os.getenv("DOWNLOAD_MEDIA", "False").lower() in ("true", "1", "yes")
    )
    auto_publish: bool = Field(
        default_factory=lambda: os.getenv("AUTO_PUBLISH", "True").lower() in ("true", "1", "yes")
    )

    @property
    def database_url(self) -> str:
        """Собирает URL для подключения к PostgreSQL через asyncpg."""
        return f"postgresql+asyncpg://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"

    @property
    def proxy_url(self) -> Optional[str]:
        """Возвращает URL SOCKS5 прокси, если хост задан."""
        if self.proxy_host:
            return f"socks5://{self.proxy_host}:{self.proxy_port}"
        return None

    def get_channel_id_for_type(self, digest_type: str) -> Optional[str]:
        """Возвращает ID канала Telegram для конкретного типа дайджеста с фолбэком на общий CHANNEL_ID."""
        if digest_type == "simple":
            return self.channel_id_simple or self.channel_id
        return self.channel_id_tech or self.channel_id


@lru_cache
def get_settings() -> Settings:
    """Возвращает синглтон настроек с кэшированием."""
    return Settings()
