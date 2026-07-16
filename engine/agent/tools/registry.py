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

    def __init__(self, db: Database, tool_timeout_s: float = 8, market_data: MarketData | None = None, news_data: NewsData | None = None):
        """Initialize shared services, domain handlers, and the tool lookup table."""
        self.db = db
        self.timeout_s = tool_timeout_s
        self.market_data = market_data or MarketData()
        self.news_data = news_data or NewsData()
        self.market = MarketTools(db, self.market_data, self.news_data)
        self.reports = ReportTools(db, self.market_data)
        self.tools = self._build()

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
        if allowed_tools is not None and name not in allowed_tools:
            return {"ok": False, "error": "tool_not_allowed", "tool": name}
        tool = self.tools.get(name)
        if not tool:
            return {"ok": False, "error": "tool_not_found", "tool": name}

        started = time.time()
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = pool.submit(tool.handler, arguments)
        try:
            # A dedicated worker gives each blocking provider call a hard timeout
            # without making domain handlers responsible for execution policy.
            result = future.result(timeout=tool.timeout_s)
            pool.shutdown(wait=False)
            return {
                "ok": True,
                "tool": name,
                "elapsed_ms": round((time.time() - started) * 1000),
                "result": result,
            }
        except concurrent.futures.TimeoutError:
            future.cancel()
            pool.shutdown(wait=False, cancel_futures=True)
            return {"ok": False, "tool": name, "error": f"工具执行超过 {tool.timeout_s:g} 秒", "timeout": True}
        except ValueError as exc:
            pool.shutdown(wait=False, cancel_futures=True)
            return {
                "ok": False,
                "tool": name,
                "error": str(exc),
                "non_retriable": True,
            }
        except Exception as exc:
            pool.shutdown(wait=False, cancel_futures=True)
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
            "get_fundamentals": Tool(
                "get_fundamentals",
                "Get valuation, growth, quality, earnings, and industry evidence.",
                {"symbol": "string"},
                self.market.fundamentals,
                timeout,
            ),
            "search_news": Tool(
                "search_news",
                "Search configured real news sources for a stock or market.",
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
        }
