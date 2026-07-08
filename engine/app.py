from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from engine.agent.loop import run_agent_loop
from engine.agent.tools import ToolRegistry
from engine.analysis.market_pipeline import MarketPipeline
from engine.analysis.stock_pipeline import StockPipeline
from engine.analysis.tracking import TrackingService
from engine.config import get_settings
from engine.storage.db import Database

settings = get_settings()
db = Database(settings.db_path)
stock_pipeline = StockPipeline(db)
market_pipeline = MarketPipeline(db)
tool_registry = ToolRegistry(db, settings.tool_timeout_s)


class Handler(BaseHTTPRequestHandler):
    server_version = "TradingJournalEngine/0.2"

    def do_OPTIONS(self) -> None:
        self.send_json({"ok": True})

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        query = parse_qs(urlparse(self.path).query)
        try:
            if path == "/health":
                self.send_json({"ok": True, "service": "trading-journal-engine"})
            elif path == "/reports":
                self.send_json({"items": db.list_reports(limit=int(query.get("limit", ["30"])[0]))})
            elif path == "/tracking":
                symbol = query.get("symbol", [None])[0]
                self.send_json({"items": TrackingService(db).snapshot(symbol)})
            elif path == "/strategies":
                self.send_json({"items": [item.__dict__ for item in stock_pipeline.strategies.all()]})
            elif path == "/dashboard":
                self.send_json(build_dashboard())
            else:
                self.send_json({"error": "not_found"}, 404)
        except Exception as exc:
            self.send_json({"error": str(exc)}, 500)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        body = self.read_json()
        try:
            if path == "/analyze/stock":
                self.send_json(stock_pipeline.analyze(body["symbol"], save=bool(body.get("save", True))))
            elif path == "/analyze/watchlist":
                self.send_json(stock_pipeline.analyze_watchlist(list(body.get("symbols", [])), save=bool(body.get("save", True))))
            elif path == "/analyze/market":
                self.send_json(market_pipeline.analyze(body.get("market", "cn"), save=bool(body.get("save", True))))
            elif path == "/chat":
                result = run_agent_loop(str(body.get("message", "")), tool_registry, settings)
                self.send_json(result.__dict__)
            elif path == "/watchlist":
                db.upsert_watchlist(list(body.get("symbols", [])))
                self.send_json({"items": db.list_watchlist()})
            else:
                self.send_json({"error": "not_found"}, 404)
        except Exception as exc:
            self.send_json({"error": str(exc)}, 500)

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def send_json(self, payload: Any, status: int = 200) -> None:
        raw = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, format: str, *args: Any) -> None:
        return


def build_dashboard() -> dict:
    reports = db.list_reports(limit=8)
    tracking = TrackingService(db).snapshot()
    latest_market = next((item for item in reports if item["kind"] == "market"), None)
    return {
        "market": latest_market,
        "risk_alerts": [item for item in tracking if item["computed_status"] in {"stop_hit", "target_hit"}],
        "latest_reports": reports,
        "tracking": tracking[:10],
    }


def main() -> None:
    server = ThreadingHTTPServer((settings.host, settings.port), Handler)
    print(f"Trading Journal Engine listening on http://{settings.host}:{settings.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()

