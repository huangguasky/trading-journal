from __future__ import annotations

from collections.abc import Callable
from typing import Any

from engine.data.normalize import normalize_symbol
from engine.storage.db import Database


class WatchlistService:
    """Manage canonical watchlist entries and their latest saved reports."""

    def __init__(self, db: Database, analyze: Callable[[str], dict[str, Any]] | None = None):
        self.db = db
        self.analyze = analyze

    def list_items(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in self.db.list_watchlist():
            symbol = normalize_symbol(row["symbol"]).display
            if symbol in seen:
                continue
            seen.add(symbol)
            items.append({"symbol": symbol, "latest_report": compact_report(self.db.get_last_report(symbol))})
        return items

    def add(self, value: str) -> dict[str, Any]:
        symbol = normalize_symbol(value).display
        existing = {normalize_symbol(row["symbol"]).display for row in self.db.list_watchlist()}
        if symbol not in existing:
            self.db.add_watchlist(symbol)

        report = self.db.get_last_report(symbol)
        created_report = report is None
        if created_report:
            if self.analyze is None:
                raise RuntimeError("watchlist analyzer is required to create a report")
            self.analyze(symbol)
            report = self.db.get_last_report(symbol)

        return {
            "symbol": symbol,
            "created_report": created_report,
            "latest_report": compact_report(report),
            "items": self.list_items(),
        }

    def remove(self, value: str) -> list[dict[str, Any]]:
        symbol = normalize_symbol(value).display
        for row in self.db.list_watchlist():
            if normalize_symbol(row["symbol"]).display == symbol:
                self.db.remove_watchlist(row["symbol"])
        return self.list_items()


def compact_report(report: dict[str, Any] | None) -> dict[str, Any] | None:
    """Merge persisted report metadata into its payload for direct UI use."""
    if not report:
        return None
    return {
        **report["payload"],
        "id": report["id"],
        "created_at": report["created_at"],
    }
