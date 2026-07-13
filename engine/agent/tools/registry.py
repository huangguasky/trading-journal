"""Tool registration, authorization, timeout, and error handling."""

from __future__ import annotations

import concurrent.futures
import time
from typing import Any

from engine.agent.schema import Tool
from engine.data.market_data import MarketData
from engine.data.news_data import NewsData
from engine.storage.db import Database

from .market import MarketTools
from .reports import ReportTools


class ToolRegistry:
    """Register and safely dispatch the analysis tools available to the agent."""

    def __init__(self, db: Database, tool_timeout_s: float = 8):
        """Initialize shared services, domain handlers, and the tool lookup table."""
        self.db = db
        self.timeout_s = tool_timeout_s
        self.market_data = MarketData()
        self.news_data = NewsData()
        self.market = MarketTools(db, self.market_data, self.news_data)
        self.reports = ReportTools(db, self.market_data, self.news_data)
        self.tools = self._build()
        self.non_retriable_cache: set[str] = set()

    def allowed(self, names: list[str] | None = None) -> list[Tool]:
        """Return all tools or the subset whose names are explicitly allowed."""
        if not names:
            return list(self.tools.values())
        return [self.tools[name] for name in names if name in self.tools]

    def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        allowed_tools: list[str] | None = None,
    ) -> dict:
        """Validate and execute one tool call, returning a JSON-compatible result."""
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
            # A dedicated worker gives each blocking provider call a hard timeout
            # without making domain handlers responsible for execution policy.
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(tool.handler, arguments)
                result = future.result(timeout=tool.timeout_s)
            return {
                "ok": True,
                "tool": name,
                "elapsed_ms": round((time.time() - started) * 1000),
                "result": result,
            }
        except ValueError as exc:
            self.non_retriable_cache.add(cache_key)
            return {
                "ok": False,
                "tool": name,
                "error": str(exc),
                "non_retriable": True,
            }
        except Exception as exc:
            return {"ok": False, "tool": name, "error": str(exc)}

    def _build(self) -> dict[str, Tool]:
        """Construct tool schemas and bind them to domain-specific handlers."""
        timeout = self.timeout_s
        return {
            "get_quote": Tool(
                "get_quote",
                "Get latest quote for a stock symbol.",
                {"symbol": "string"},
                self.market.quote,
                timeout,
            ),
            "get_history": Tool(
                "get_history",
                "Get recent daily bars for a stock symbol.",
                {"symbol": "string", "days": "integer"},
                self.market.history,
                timeout,
            ),
            "get_indicators": Tool(
                "get_indicators",
                "Compute technical indicators for a stock symbol.",
                {"symbol": "string"},
                self.market.indicators,
                timeout,
            ),
            "search_news": Tool(
                "search_news",
                "Search local/synthetic news for a stock or market.",
                {"symbol": "string"},
                self.market.news,
                timeout,
            ),
            "get_last_report": Tool(
                "get_last_report",
                "Get the last saved stock report.",
                {"symbol": "string"},
                self.reports.last_report,
                timeout,
            ),
            "get_signal_tracking": Tool(
                "get_signal_tracking",
                "Get follow-up tracking state for a symbol.",
                {"symbol": "string"},
                self.reports.tracking,
                timeout,
            ),
            "get_market_context": Tool(
                "get_market_context",
                "Get market review context.",
                {"market": "cn|hk|us"},
                self.market.market_context,
                timeout,
            ),
            "run_stock_report": Tool(
                "run_stock_report",
                "Run the fixed stock pipeline for a symbol.",
                {"symbol": "string"},
                self.reports.run_stock_report,
                timeout,
            ),
        }
