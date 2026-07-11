from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from engine.time_utils import now_cn_text

from .migrations import SCHEMA_SQL


DEFAULT_SYSTEM_SETTINGS = {
    "llm_enabled": "false",
    "openai_api_key": "",
    "openai_base_url": "",
    "openai_model": "gpt-4o-mini",
    "data_provider": "auto",
    "data_provider_order": "tushare,akshare,yfinance,alpha_vantage,sample",
    "tushare_token": "",
    "alpha_vantage_key": "",
    "news_api_key": "",
    "tool_timeout_s": "8",
    "agent_max_steps": "5",
}


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.migrate()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def migrate(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA_SQL)
            for key, value in DEFAULT_SYSTEM_SETTINGS.items():
                conn.execute(
                    "insert or ignore into system_settings(key, value, updated_at) values(?,?,?)",
                    (key, value, now_cn_text()),
                )

    def upsert_watchlist(self, symbols: list[str]) -> None:
        with self.connect() as conn:
            for symbol in symbols:
                conn.execute(
                    "insert into watchlist(symbol, enabled, created_at) values(?, 1, ?) "
                    "on conflict(symbol) do update set enabled=1",
                    (symbol, now_cn_text()),
                )

    def list_watchlist(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("select * from watchlist where enabled=1 order by created_at desc").fetchall()
            return [dict(row) for row in rows]

    def save_report(self, kind: str, title: str, score: float, payload: dict[str, Any], markdown: str, symbol: str | None = None, market: str | None = None, regime: str | None = None) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                "insert into reports(kind, symbol, market, title, score, regime, payload_json, markdown, created_at) values(?,?,?,?,?,?,?,?,?)",
                (kind, symbol, market, title, score, regime, json.dumps(payload, ensure_ascii=False), markdown, now_cn_text()),
            )
            return int(cur.lastrowid)

    def list_reports(self, limit: int = 50, kind: str | None = None, symbol: str | None = None) -> list[dict[str, Any]]:
        sql = "select * from reports"
        params: list[Any] = []
        clauses: list[str] = []
        if kind:
            clauses.append("kind=?")
            params.append(kind)
        if symbol:
            clauses.append("symbol=?")
            params.append(symbol)
        if clauses:
            sql += " where " + " and ".join(clauses)
        sql += " order by id desc limit ?"
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_inflate_report(dict(row)) for row in rows]

    def get_last_report(self, symbol: str) -> dict[str, Any] | None:
        reports = self.list_reports(limit=1, kind="stock", symbol=symbol)
        return reports[0] if reports else None

    def create_tracking_task(self, report_id: int, symbol: str, base_price: float, target_price: float | None, stop_price: float | None) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                "insert into tracking_tasks(report_id, symbol, base_price, target_price, stop_price, created_at) values(?,?,?,?,?,?)",
                (report_id, symbol, base_price, target_price, stop_price, now_cn_text()),
            )
            return int(cur.lastrowid)

    def list_tracking(self, symbol: str | None = None) -> list[dict[str, Any]]:
        sql = "select * from tracking_tasks"
        params: list[Any] = []
        if symbol:
            sql += " where symbol=?"
            params.append(symbol)
        sql += " order by id desc"
        with self.connect() as conn:
            return [dict(row) for row in conn.execute(sql, params).fetchall()]

    def get_system_settings(self) -> dict[str, str]:
        with self.connect() as conn:
            rows = conn.execute("select key, value from system_settings").fetchall()
        values = dict(DEFAULT_SYSTEM_SETTINGS)
        values.update({str(row["key"]): str(row["value"]) for row in rows})
        return values

    def update_system_settings(self, values: dict[str, Any]) -> dict[str, str]:
        allowed = set(DEFAULT_SYSTEM_SETTINGS)
        with self.connect() as conn:
            for key, value in values.items():
                if key not in allowed:
                    continue
                conn.execute(
                    "insert into system_settings(key, value, updated_at) values(?,?,?) "
                    "on conflict(key) do update set value=excluded.value, updated_at=excluded.updated_at",
                    (key, normalize_setting_value(key, value), now_cn_text()),
                )
        return self.get_system_settings()


def _inflate_report(row: dict[str, Any]) -> dict[str, Any]:
    row["payload"] = json.loads(row.pop("payload_json"))
    return row


def normalize_setting_value(key: str, value: Any) -> str:
    if key == "llm_enabled":
        return "true" if value in {True, "true", "1", 1, "on", "yes"} else "false"
    return str(value or "").strip()
