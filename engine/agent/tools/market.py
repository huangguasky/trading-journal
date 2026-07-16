"""Market-data and market-analysis handlers exposed to the agent."""

from __future__ import annotations

from dataclasses import asdict

from engine.analysis.market_pipeline import MarketPipeline
from engine.data.market_data import MarketData
from engine.data.enrichment import EnrichmentData
from engine.data.news_data import NewsData
from engine.data.normalize import normalize_symbol
from engine.indicators import compute_indicators
from engine.storage.db import Database


class MarketTools:
    """Implement read-only quote, history, indicator, news, and market tools."""

    def __init__(self, db: Database, market_data: MarketData, news_data: NewsData):
        """Reuse shared persistence and data clients across tool calls."""
        self.db = db
        self.market_data = market_data
        self.news_data = news_data
        self.enrichment_data = EnrichmentData(timeout_s=market_data.timeout_s)

    def quote(self, args: dict) -> dict:
        """Fetch a normalized quote for the requested symbol."""
        return asdict(self.market_data.quote(args["symbol"]))

    def history(self, args: dict) -> dict:
        """Fetch recent normalized price bars for the requested symbol."""
        days = int(args.get("days", 60))
        bars = self.market_data.history(args["symbol"], days)
        return {"bars": [asdict(bar) for bar in bars[-days:]]}

    def indicators(self, args: dict) -> dict:
        """Compute technical indicators from the requested symbol's history."""
        bars = self.market_data.history(args["symbol"])
        return compute_indicators(bars)

    def fundamentals(self, args: dict) -> dict:
        """Fetch normalized fundamental evidence for the requested symbol."""
        symbol = normalize_symbol(args["symbol"])
        bundle = self.enrichment_data.fundamentals(symbol)
        if not bundle.data:
            notes = bundle.quality.get("notes") or []
            raise ValueError(str(notes[0]) if notes else "基本面数据不可用")
        return {**bundle.data, "data_quality": bundle.quality}

    def news(self, args: dict) -> dict:
        """Fetch stock or market news according to the supplied arguments."""
        symbol = args.get("symbol") or args.get("market") or ""
        if symbol in {"cn", "hk", "us"}:
            return {"items": self.news_data.market_news(symbol)}
        normalized = normalize_symbol(symbol)
        return {"items": self.news_data.stock_news(normalized.display)}

    def market_context(self, args: dict) -> dict:
        """Run and return a market analysis without persisting it."""
        return MarketPipeline(self.db, self.market_data, self.news_data).analyze(
            args.get("market", "cn"),
            save=False,
        )
