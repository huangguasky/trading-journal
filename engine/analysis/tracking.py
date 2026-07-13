from __future__ import annotations

from engine.data.market_data import MarketData
from engine.storage.db import Database


class TrackingService:
    """Create report tracking tasks and evaluate their latest price outcomes."""
    def __init__(self, db: Database, market_data: MarketData | None = None):
        """Initialize tracking with the database and an optional market-data service."""
        self.db = db
        self.market_data = market_data or MarketData()

    def create_for_report(self, report_id: int, report: dict) -> int:
        """Create a tracking task from a persisted report's operation plan."""
        tracking = report["tracking"]
        return self.db.create_tracking_task(report_id, report["symbol"], tracking["base_price"], tracking["target_price"], tracking["stop_price"])

    def snapshot(self, symbol: str | None = None) -> list[dict]:
        """Evaluate active tracking tasks against current quotes and price targets."""
        rows = self.db.list_tracking(symbol)
        out = []
        for row in rows:
            quote = self.market_data.quote(row["symbol"])
            pnl = round((quote.price / row["base_price"] - 1) * 100, 2) if row["base_price"] else 0
            status = "open"
            if row["target_price"] and quote.price >= row["target_price"]:
                status = "target_hit"
            if row["stop_price"] and quote.price <= row["stop_price"]:
                status = "stop_hit"
            out.append({**row, "current_price": quote.price, "pnl_pct": pnl, "computed_status": status})
        return out
