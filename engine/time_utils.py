from __future__ import annotations

from datetime import datetime, timezone, timedelta


CN_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")


def now_cn() -> datetime:
    """Return the current timezone-aware time in China Standard Time."""
    return datetime.now(CN_TZ)


def today_cn() -> str:
    """Return today's China Standard Time date in ISO format."""
    return now_cn().date().isoformat()


def now_cn_iso() -> str:
    """Return the current China Standard Time as an ISO 8601 string."""
    return now_cn().isoformat(timespec="seconds")


def now_cn_text() -> str:
    """Return the current China Standard Time formatted for database display."""
    return now_cn().strftime("%Y-%m-%d %H:%M:%S")
