"""Saved-report and follow-up tracking handlers exposed to the agent."""

from __future__ import annotations

from engine.analysis.stock_pipeline import StockPipeline
from engine.analysis.tracking import TrackingService
from engine.data.market_data import MarketData
from engine.data.news_data import NewsData
from engine.data.normalize import normalize_symbol
from engine.storage.db import Database


class ReportTools:
    """Implement report lookup, tracking, and fixed stock-analysis tools."""

    def __init__(self, db: Database, market_data: MarketData, news_data: NewsData):
        """Reuse shared persistence and data clients across tool calls."""
        self.db = db
        self.market_data = market_data
        self.news_data = news_data

    def last_report(self, args: dict) -> dict | None:
        """Return the most recently saved report for a symbol."""
        symbol = normalize_symbol(args["symbol"]).display
        return self.db.get_last_report(symbol)

    def tracking(self, args: dict) -> list[dict]:
        """Return current tracking outcomes, optionally filtered by symbol."""
        symbol = normalize_symbol(args["symbol"]).display if args.get("symbol") else None
        return TrackingService(self.db, self.market_data).snapshot(symbol)

    def run_stock_report(self, args: dict) -> dict:
        """Run the fixed stock pipeline and persist its report and tracking task."""
        return StockPipeline(self.db, self.market_data, self.news_data).analyze(
            args["symbol"],
            save=True,
        )
