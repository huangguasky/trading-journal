from __future__ import annotations

from dataclasses import dataclass


@dataclass
class WatchlistItem:
    """Persisted watchlist entry."""
    symbol: str
    name: str = ""
    enabled: bool = True
    notes: str = ""


@dataclass
class TrackingTask:
    """Persisted report follow-up task and its target levels."""
    report_id: int
    symbol: str
    base_price: float
    target_price: float | None
    stop_price: float | None
    status: str = "open"
