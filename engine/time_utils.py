from __future__ import annotations

from datetime import datetime, timezone, timedelta


CN_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")


def now_cn() -> datetime:
    return datetime.now(CN_TZ)


def today_cn() -> str:
    return now_cn().date().isoformat()


def now_cn_iso() -> str:
    return now_cn().isoformat(timespec="seconds")


def now_cn_text() -> str:
    return now_cn().strftime("%Y-%m-%d %H:%M:%S")
