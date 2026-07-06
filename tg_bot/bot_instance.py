import os
import logging
from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession

logger = logging.getLogger(__name__)

def get_bot() -> Bot:
    bot_token = os.getenv("BOT_TOKEN")
    proxy_host = os.getenv("PROXY_HOST")
    proxy_port = os.getenv("PROXY_PORT", "1080")
    
    if proxy_host:
        proxy_url = f"socks5://{proxy_host}:{proxy_port}"
        logger.info(f"Using SOCKS5 proxy for Bot: {proxy_url}")
        session = AiohttpSession(proxy=proxy_url)
        return Bot(token=bot_token, session=session)
    else:
        logger.info("Initializing Bot without proxy")
        return Bot(token=bot_token)
