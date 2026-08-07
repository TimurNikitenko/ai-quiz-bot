import os
import logging
import socket
from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession

logger = logging.getLogger(__name__)


def is_proxy_available(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def get_bot() -> Bot:
    bot_token = os.getenv("BOT_TOKEN")
    proxy_host = os.getenv("PROXY_HOST")
    proxy_port_str = os.getenv("PROXY_PORT", "1080")
    
    try:
        proxy_port = int(proxy_port_str)
    except ValueError:
        proxy_port = 1080

    if proxy_host and is_proxy_available(proxy_host, proxy_port):
        proxy_url = f"socks5://{proxy_host}:{proxy_port}"
        logger.info(f"Using SOCKS5 proxy for Bot: {proxy_url}")
        session = AiohttpSession(proxy=proxy_url)
        return Bot(token=bot_token, session=session)
    else:
        if proxy_host:
            logger.info(f"Proxy {proxy_host}:{proxy_port} недоступен, подключаем бота напрямую.")
        else:
            logger.info("Инициализация бота без прокси.")
        return Bot(token=bot_token)
