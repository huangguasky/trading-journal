from __future__ import annotations

import concurrent.futures
import time
from dataclasses import asdict
from typing import Any

from engine.analysis.market_pipeline import MarketPipeline
from engine.analysis.stock_pipeline import StockPipeline
from engine.analysis.tracking import TrackingService
from engine.data.market_data import MarketData
from engine.data.news_data import NewsData
from engine.data.normalize import normalize_symbol
from engine.indicators import compute_indicators
from engine.storage.db import Database

from .schema import Tool


class ToolRegistry:
    def __init__(self, db: Database, tool_timeout_s: float = 8):
        self.db = db
        self.timeout_s = tool_timeout_s
        self.market_data = MarketData()
        self.news_data = NewsData()
        self.tools = self._build()
        self.non_retriable_cache: set[str] = set()

    def allowed(self, names: list[str] | None = None) -> list[Tool]:
        if not names:
            return list(self.tools.values())
        return [self.tools[name] for name in names if name in self.tools]

    def execute(self, name: str, arguments: dict[str, Any], allowed_tools: list[str] | None = None) -> dict:
        if allowed_tools and name not in allowed_tools:
            return {"error": "tool_not_allowed", "tool": name}
        tool = self.tools.get(name)
        if not tool:
            return {"error": "tool_not_found", "tool": name}
        cache_key = f"{name}:{arguments}"
        if cache_key in self.non_retriable_cache:
            return {"error": "cached_non_retriable_error", "tool": name}
        started = time.time()
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(tool.handler, arguments)
                result = future.result(timeout=tool.timeout_s)
            return {"ok": True, "tool": name, "elapsed_ms": round((time.time() - started) * 1000), "result": result}
        except ValueError as exc:
            self.non_retriable_cache.add(cache_key)
            return {"ok": False, "tool": name, "error": str(exc), "non_retriable": True}
        except Exception as exc:
            return {"ok": False, "tool": name, "error": str(exc)}

    def _build(self) -> dict[str, Tool]:
        return {
            "get_quote": Tool("get_quote", "Get latest quote for a stock symbol.", {"symbol": "string"}, self._quote, self.timeout_s),
            "get_history": Tool("get_history", "Get recent daily bars for a stock symbol.", {"symbol": "string", "days": "integer"}, self._history, self.timeout_s),
            "get_indicators": Tool("get_indicators", "Compute technical indicators for a stock symbol.", {"symbol": "string"}, self._indicators, self.timeout_s),
            "search_news": Tool("search_news", "Search local/synthetic news for a stock or market.", {"symbol": "string"}, self._news, self.timeout_s),
            "get_last_report": Tool("get_last_report", "Get the last saved stock report.", {"symbol": "string"}, self._last_report, self.timeout_s),
            "get_signal_tracking": Tool("get_signal_tracking", "Get follow-up tracking state for a symbol.", {"symbol": "string"}, self._tracking, self.timeout_s),
            "get_market_context": Tool("get_market_context", "Get market review context.", {"market": "cn|hk|us"}, self._market, self.timeout_s),
            "run_stock_report": Tool("run_stock_report", "Run the fixed stock pipeline for a symbol.", {"symbol": "string"}, self._run_stock_report, self.timeout_s),
        }

    def _quote(self, args: dict) -> dict:
        return asdict(self.market_data.quote(args["symbol"]))

    def _history(self, args: dict) -> dict:
        days = int(args.get("days", 60))
        bars = self.market_data.history(args["symbol"], days)
        return {"bars": [asdict(bar) for bar in bars[-days:]]}

    def _indicators(self, args: dict) -> dict:
        bars = self.market_data.history(args["symbol"])
        return compute_indicators(bars)

    def _news(self, args: dict) -> dict:
        symbol = args.get("symbol") or args.get("market") or ""
        if symbol in {"cn", "hk", "us"}:
            return {"items": self.news_data.market_news(symbol)}
        normalized = normalize_symbol(symbol)
        return {"items": self.news_data.stock_news(normalized.display)}

    def _last_report(self, args: dict) -> dict | None:
        symbol = normalize_symbol(args["symbol"]).display
        return self.db.get_last_report(symbol)

    def _tracking(self, args: dict) -> list[dict]:
        symbol = normalize_symbol(args["symbol"]).display if args.get("symbol") else None
        return TrackingService(self.db, self.market_data).snapshot(symbol)

    def _market(self, args: dict) -> dict:
        return MarketPipeline(self.db, self.market_data, self.news_data).analyze(args.get("market", "cn"), save=False)

    def _run_stock_report(self, args: dict) -> dict:
        return StockPipeline(self.db, self.market_data, self.news_data).analyze(args["symbol"], save=True)

