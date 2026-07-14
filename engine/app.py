from __future__ import annotations

import json
import re
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from engine.agent.loop import run_agent_loop
from engine.agent.tools import ToolRegistry
from engine.analysis.market_pipeline import MarketPipeline
from engine.analysis.stock_pipeline import StockPipeline
from engine.analysis.tracking import TrackingService
from engine.config import get_settings
from engine.data.market_data import MarketData
from engine.data.news_data import NewsData
from engine.storage.db import Database
from engine.strategies.registry import StrategyRegistry

settings = get_settings()
db = Database(settings.db_path)


class Handler(BaseHTTPRequestHandler):
    """Serve the local JSON API consumed by the desktop application."""
    server_version = "TradingJournalEngine/0.2"

    def do_OPTIONS(self) -> None:
        """Answer CORS preflight requests."""
        self.send_json({"ok": True})

    def do_GET(self) -> None:
        """Route read-only API requests and serialize failures as JSON."""
        path = urlparse(self.path).path
        query = parse_qs(urlparse(self.path).query)
        try:
            if path == "/health":
                self.send_json({"ok": True, "service": "trading-journal-engine"})
            elif path == "/reports":
                limit = int(query["limit"][0]) if "limit" in query else None
                self.send_json({"items": db.list_reports(limit=limit)})
            elif path == "/watchlist":
                self.send_json({"items": db.list_watchlist()})
            elif path == "/tracking":
                symbol = query.get("symbol", [None])[0]
                self.send_json({"items": TrackingService(db).snapshot(symbol)})
            elif path == "/strategies":
                self.send_json({"items": [item.__dict__ for item in StrategyRegistry().all()]})
            elif path == "/dashboard":
                self.send_json(build_dashboard())
            elif path == "/settings":
                self.send_json({"settings": db.get_system_settings(), "llm_ready": is_llm_ready(db.get_system_settings())})
            else:
                self.send_json({"error": "not_found"}, 404)
        except Exception as exc:
            self.send_json({"error": str(exc)}, 500)

    def do_DELETE(self) -> None:
        """Delete persisted reports and their dependent tracking tasks."""
        path = urlparse(self.path).path
        try:
            match = re.fullmatch(r"/reports/(\d+)", path)
            if match:
                deleted = db.delete_report(int(match.group(1)))
                self.send_json({"deleted": deleted}, 200 if deleted else 404)
            else:
                self.send_json({"error": "not_found"}, 404)
        except Exception as exc:
            self.send_json({"error": str(exc)}, 500)

    def do_POST(self) -> None:
        """Route state-changing and analysis API requests."""
        path = urlparse(self.path).path
        body = self.read_json()
        try:
            if path == "/analyze/stock":
                self.send_json(build_stock_pipeline().analyze(body["symbol"], save=bool(body.get("save", True))))
            elif path == "/analyze/watchlist":
                self.send_json(build_stock_pipeline().analyze_watchlist(list(body.get("symbols", [])), save=bool(body.get("save", True))))
            elif path == "/analyze/market":
                self.send_json(build_market_pipeline().analyze(body.get("market", "cn"), save=bool(body.get("save", True))))
            elif path == "/chat":
                result = run_agent_loop(str(body.get("message", "")), ToolRegistry(db, effective_settings().tool_timeout_s), effective_settings())
                self.send_json(result.__dict__)
            elif path == "/watchlist":
                db.upsert_watchlist(list(body.get("symbols", [])))
                self.send_json({"items": db.list_watchlist()})
            elif path == "/settings":
                updated = db.update_system_settings(body)
                self.send_json({"settings": updated, "llm_ready": is_llm_ready(updated)})
            else:
                self.send_json({"error": "not_found"}, 404)
        except Exception as exc:
            self.send_json({"error": str(exc)}, 500)

    def read_json(self) -> dict[str, Any]:
        """Decode the request body as a JSON object, or return an empty object."""
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def send_json(self, payload: Any, status: int = 200) -> None:
        """Send a UTF-8 JSON response with permissive local CORS headers."""
        raw = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress the standard library's per-request console logging."""
        return


def build_dashboard() -> dict:
    """Assemble recent reports, tracking state, and risk alerts for the dashboard."""
    reports = db.list_reports(limit=8)
    tracking = TrackingService(db).snapshot()
    latest_market = next((item for item in reports if item["kind"] == "market"), None)
    return {
        "market": latest_market,
        "risk_alerts": [item for item in tracking if item["computed_status"] in {"stop_hit", "target_hit"}],
        "latest_reports": reports,
        "tracking": tracking[:10],
    }


def build_stock_pipeline() -> StockPipeline:
    """Create a stock pipeline using provider settings persisted in the database."""
    values = db.get_system_settings()
    market_data = MarketData(
        provider_order=resolve_provider_order(values),
        api_keys=provider_keys(values),
        timeout_s=parse_float(values.get("tool_timeout_s"), settings.tool_timeout_s),
    )
    news_data = NewsData(values.get("news_api_key", ""), timeout_s=parse_float(values.get("tool_timeout_s"), settings.tool_timeout_s))
    return StockPipeline(db, market_data=market_data, news_data=news_data)


def build_market_pipeline() -> MarketPipeline:
    """Create a market pipeline using provider settings persisted in the database."""
    values = db.get_system_settings()
    market_data = MarketData(
        provider_order=resolve_provider_order(values),
        api_keys=provider_keys(values),
        timeout_s=parse_float(values.get("tool_timeout_s"), settings.tool_timeout_s),
    )
    news_data = NewsData(values.get("news_api_key", ""), timeout_s=parse_float(values.get("tool_timeout_s"), settings.tool_timeout_s))
    return MarketPipeline(db, market_data=market_data, news_data=news_data)


def provider_keys(values: dict[str, str]) -> dict[str, str]:
    """Extract market-provider credentials from persisted settings."""
    return {
        "tushare_token": values.get("tushare_token", ""),
        "alpha_vantage_key": values.get("alpha_vantage_key", ""),
    }


def resolve_provider_order(values: dict[str, str]) -> str:
    """Resolve an explicit provider choice or fall back to the configured order."""
    selected = (values.get("data_provider") or "auto").strip().lower()
    if selected and selected != "auto":
        return selected
    return values.get("data_provider_order") or "auto"


def effective_settings():
    """Merge environment defaults with mutable database-backed LLM settings."""
    values = db.get_system_settings()
    llm_enabled = values.get("llm_enabled") == "true"
    api_key = values.get("openai_api_key") or settings.llm_api_key or ""
    return replace(
        settings,
        llm_api_key=api_key if llm_enabled and api_key else None,
        llm_base_url=values.get("openai_base_url") or settings.llm_base_url,
        llm_model=values.get("openai_model") or settings.llm_model,
        tool_timeout_s=parse_float(values.get("tool_timeout_s"), settings.tool_timeout_s),
        agent_max_steps=parse_int(values.get("agent_max_steps"), settings.agent_max_steps),
    )


def is_llm_ready(values: dict[str, str]) -> bool:
    """Return whether LLM use is enabled and has a non-empty API key."""
    return values.get("llm_enabled") == "true" and bool(values.get("openai_api_key", "").strip())


def parse_float(value: str | None, fallback: float) -> float:
    """Parse a float setting, returning the fallback for missing or invalid input."""
    try:
        return float(value) if value is not None else fallback
    except ValueError:
        return fallback


def parse_int(value: str | None, fallback: int) -> int:
    """Parse an integer setting, returning the fallback for missing or invalid input."""
    try:
        return int(value) if value is not None else fallback
    except ValueError:
        return fallback


def main() -> None:
    """Start the threaded local HTTP server and serve until interrupted."""
    server = ThreadingHTTPServer((settings.host, settings.port), Handler)
    print(f"Trading Journal Engine listening on http://{settings.host}:{settings.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
