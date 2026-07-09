import json
import logging
from contextvars import ContextVar
from datetime import datetime, timezone
from contextlib import contextmanager

# Context variables for tracing user requests in the bot
_telegram_id_ctx: ContextVar[int | None] = ContextVar("telegram_id", default=None)
_user_id_ctx: ContextVar[int | None] = ContextVar("user_id", default=None)
_user_username_ctx: ContextVar[str | None] = ContextVar("user_username", default=None)
_handler_name_ctx: ContextVar[str | None] = ContextVar("handler_name", default=None)
_callback_data_ctx: ContextVar[str | None] = ContextVar("callback_data", default=None)

# Context variables for tracking parsing jobs
_parser_run_id_ctx: ContextVar[str | None] = ContextVar("parser_run_id", default=None)
_crawler_source_ctx: ContextVar[str | None] = ContextVar("crawler_source", default=None)
_current_url_ctx: ContextVar[str | None] = ContextVar("current_url", default=None)
_parser_phase_ctx: ContextVar[str | None] = ContextVar("parser_phase", default=None)


def set_user_context(
    telegram_id: int | None, username: str | None, user_id: int | None = None
) -> None:
    _telegram_id_ctx.set(telegram_id)
    _user_id_ctx.set(user_id)
    _user_username_ctx.set(username)


def set_handler_context(handler_name: str | None, callback_data: str | None) -> None:
    _handler_name_ctx.set(handler_name)
    _callback_data_ctx.set(callback_data)


@contextmanager
def parser_context(
    run_id: str | None = None,
    source: str | None = None,
    url: str | None = None,
    phase: str | None = None,
):
    tokens = []
    if run_id is not None:
        tokens.append((_parser_run_id_ctx, _parser_run_id_ctx.set(run_id)))
    if source is not None:
        tokens.append((_crawler_source_ctx, _crawler_source_ctx.set(source)))
    if url is not None:
        tokens.append((_current_url_ctx, _current_url_ctx.set(url)))
    if phase is not None:
        tokens.append((_parser_phase_ctx, _parser_phase_ctx.set(phase)))
    try:
        yield
    finally:
        for var, token in reversed(tokens):
            var.reset(token)


class UserContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        telegram_id = _telegram_id_ctx.get()
        user_id = _user_id_ctx.get()
        user_username = _user_username_ctx.get()
        handler_name = _handler_name_ctx.get()
        callback_data = _callback_data_ctx.get()

        parser_run_id = _parser_run_id_ctx.get()
        crawler_source = _crawler_source_ctx.get()
        current_url = _current_url_ctx.get()
        parser_phase = _parser_phase_ctx.get()

        if telegram_id is not None:
            record.telegram_id = telegram_id
        if user_id is not None:
            record.user_id = user_id
        if user_username is not None:
            record.user_username = user_username
        if handler_name is not None:
            record.handler_name = handler_name
        if callback_data is not None:
            record.callback_data = callback_data

        if parser_run_id is not None:
            record.parser_run_id = parser_run_id
        if crawler_source is not None:
            record.crawler_source = crawler_source
        if current_url is not None:
            record.current_url = current_url
        if parser_phase is not None:
            record.parser_phase = parser_phase

        return True


RESERVED_LOG_RECORD_ATTRS = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "message",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
    "taskName",
}


class JSONFormatter(logging.Formatter):
    def __init__(self, service_name: str = "ai-quiz-bot"):
        super().__init__()
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "time": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
            "service": self.service_name,
        }

        if record.exc_info:
            exc_type, exc_value, exc_tb = record.exc_info
            log_data["exception"] = {
                "type": exc_type.__name__ if exc_type else None,
                "message": str(exc_value) if exc_value else None,
                "stacktrace": self.formatException(record.exc_info),
            }

        # Include custom context attributes from UserContextFilter / extra fields
        for key, value in record.__dict__.items():
            if key not in RESERVED_LOG_RECORD_ATTRS:
                log_data[key] = value

        return json.dumps(log_data, ensure_ascii=False)


def setup_json_logging(level=logging.INFO, service_name="ai-quiz-bot"):
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.handlers.clear()
    
    handler = logging.StreamHandler()
    handler.setLevel(level)
    handler.setFormatter(JSONFormatter(service_name=service_name))
    handler.addFilter(UserContextFilter())
    root_logger.addHandler(handler)
    
    # Mute noisy internal logs
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    logging.getLogger("telethon").setLevel(logging.WARNING)
    
    logging.info(f"JSON logging initialized for service: {service_name}")


logger = logging.getLogger("bot")
