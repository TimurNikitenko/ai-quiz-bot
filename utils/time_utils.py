"""Вспомогательные утилиты для работы с датами и часовыми поясами."""

from datetime import datetime, timedelta, timezone
from typing import Optional
from core.constants import DEFAULT_CUTOFF_HOURS, DEFAULT_WEEKLY_QUIZ_DAYS

MOSCOW_TZ = timezone(timedelta(hours=3))


def get_moscow_now() -> datetime:
    """Возвращает текущее время по московскому часовому поясу (MSK)."""
    return datetime.now(MOSCOW_TZ)


def get_seven_days_ago() -> datetime:
    """Возвращает время 7 дней назад в MSK."""
    return get_moscow_now() - timedelta(days=DEFAULT_WEEKLY_QUIZ_DAYS)


def get_cutoff_time(last_published_date: Optional[datetime] = None, hours: int = DEFAULT_CUTOFF_HOURS) -> datetime:
    """Вычисляет граничную дату cutoff (не ранее чем hours назад или дата последнего опубликованного дайджеста)."""
    now_utc = datetime.now(timezone.utc)
    cutoff_boundary = now_utc - timedelta(hours=hours)

    if last_published_date:
        if last_published_date.tzinfo is None:
            last_published_date = last_published_date.replace(tzinfo=timezone.utc)
        return max(last_published_date, cutoff_boundary)
    return cutoff_boundary
