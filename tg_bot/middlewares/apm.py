import re
import elasticapm
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update
from typing import Callable, Awaitable, Any

_CMD_RE = re.compile(r'^/[a-zA-Z_]{1,32}$')
_MAX_CALLBACK_LEN = 64


class APMMiddleware(BaseMiddleware):
    """Wraps each aiogram update into an Elastic APM transaction if configured."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict], Awaitable[Any]],
        event: TelegramObject,
        data: dict,
    ) -> Any:
        client = elasticapm.get_client()
        if client is None:
            return await handler(event, data)

        update: Update = data.get("event_update") or event
        name = self._transaction_name(update)

        client.begin_transaction("aiogram")
        try:
            result = await handler(event, data)
            client.end_transaction(name, "success")
            return result
        except Exception:
            client.capture_exception()
            client.end_transaction(name, "error")
            raise

    @staticmethod
    def _transaction_name(update: Any) -> str:
        if hasattr(update, "message") and update.message:
            text = update.message.text or ""
            token = text.split()[0] if text else ""
            cmd = token if _CMD_RE.match(token) else "message"
            return f"message {cmd}"
        if hasattr(update, "callback_query") and update.callback_query:
            raw = update.callback_query.data or "unknown"
            safe = re.sub(r'[^\x20-\x7E]', '', raw)[:_MAX_CALLBACK_LEN]
            return f"callback {safe or 'unknown'}"
        return type(update).__name__
