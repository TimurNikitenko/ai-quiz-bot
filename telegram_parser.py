import asyncio
import logging
from telethon import TelegramClient
from telethon.network.connection import ConnectionTcpObfuscated
from telethon.tl.functions.channels import GetFullChannelRequest
from datetime import timedelta, timezone

logger = logging.getLogger(__name__)


class TGParser:
    def __init__(self, api_id: int, api_hash: str, session_name: str = "event_session"):
        proxy_tuple = ("socks5", "xray-client", 1080)

        self.client = TelegramClient(
            session_name,
            api_id,
            api_hash,
            proxy=proxy_tuple,
            connection=ConnectionTcpObfuscated,
            use_ipv6=False,
        )

    async def start(self):
        await self.client.start()
        me = await self.client.get_me()
        logger.info(f"Подключён: {me.first_name}")

    async def parse_channel(self, channel_username: str):
        """Парсинг отдельного телеграм-канала"""
        channel_username = (channel_username or "").strip()
        logger.info(f"Парсим канал: @{channel_username}")

        try:
            entity = await self.client.get_entity(channel_username)
            full_entity = await self.client(GetFullChannelRequest(channel=entity))
            channel_title = entity.title or ""
            channel_about = full_entity.full_chat.about or ""
        except Exception as e:
            logger.error(f"Нет доступа к @{channel_username}: {e}")
            return []

        posts = []
        total_msgs = 0

        async for message in self.client.iter_messages(channel_username, limit=30):
            total_msgs += 1

            text_raw = message.text or ""
            extra_urls: list[str] = []

            for entity in message.entities or []:
                url_value = getattr(entity, "url", None)
                if url_value:
                    extra_urls.append(url_value)

                offset = getattr(entity, "offset", None)
                length = getattr(entity, "length", None)
                if (
                    isinstance(offset, int)
                    and isinstance(length, int)
                    and offset >= 0
                    and length > 0
                    and offset + length <= len(text_raw)
                ):
                    candidate = text_raw[offset : offset + length]
                    if candidate.startswith(("http://", "https://")):
                        extra_urls.append(candidate)

            extra_urls = list(dict.fromkeys(extra_urls))
            text_for_llm = text_raw

            msg_date = message.date
            if msg_date:
                msg_date = msg_date.astimezone(timezone(timedelta(hours=3)))

            post_data = {
                "text": text_for_llm,
                "link": f"https://t.me/{channel_username}/{message.id}",
                "date": msg_date,
            }
            posts.append(post_data)

        logger.info(f"Суммарно: {len(posts)} постов из {total_msgs} сообщений")
        return posts

    async def close(self):
        try:
            if self.client.is_connected():
                await self.client.disconnect()
                logger.info("Telegram клиент отключён")
        except Exception as e:
            logger.warning(f"Ошибка при отключении Telegram клиента: {e}")
