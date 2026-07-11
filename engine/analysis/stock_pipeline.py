from __future__ import annotations

from dataclasses import asdict

from engine.data.market_data import MarketData
from engine.data.news_data import NewsData
from engine.data.normalize import normalize_symbol
from engine.indicators import compute_indicators
from engine.storage.db import Database
from engine.strategies.registry import StrategyRegistry

from .evidence import build_stock_evidence
from .report_builder import build_stock_report
from .tracking import TrackingService


class StockPipeline:
    def __init__(self, db: Database, market_data: MarketData | None = None, news_data: NewsData | None = None, strategies: StrategyRegistry | None = None):
        self.db = db
        self.market_data = market_data or MarketData()
        self.news_data = news_data or NewsData()
        self.strategies = strategies or StrategyRegistry()
        self.tracking = TrackingService(db, self.market_data)

    def analyze(self, code: str, save: bool = True) -> dict:
        symbol = normalize_symbol(code)
        history_bundle = self.market_data.history_bundle(symbol)
        quote = quote_from_history(symbol, history_bundle)
        indicators = compute_indicators(history_bundle.bars)
        news_bundle = self.news_data.stock_news_bundle(symbol.display)
        news = news_bundle.items
        strategy_results = [asdict(item) for item in self.strategies.select_for_stock(indicators, news)]
        data_quality = {
            "history": quality_to_dict(history_bundle.quality),
            "price": quality_to_dict(history_bundle.quality),
            "news": news_bundle.quality,
        }
        evidence = build_stock_evidence(symbol.display, quote, indicators, news, strategy_results, data_quality)
        report, markdown = build_stock_report(
            {
                "symbol": symbol.display,
                "market": symbol.market,
                "quote": quote,
                "indicators": indicators,
                "news": news,
                "strategies": strategy_results,
                "evidence": evidence,
            }
        )
        if save:
            report_id = self.db.save_report("stock", f"{symbol.display} 个股分析报告", report["score"], report, markdown, symbol.display, symbol.market, report["rating"])
            report["id"] = report_id
            report["tracking_task_id"] = self.tracking.create_for_report(report_id, report)
        report["markdown"] = markdown
        return report

    def analyze_watchlist(self, symbols: list[str], save: bool = True) -> dict:
        self.db.upsert_watchlist(symbols)
        items = [self.analyze(symbol, save=save) for symbol in symbols]
        return {
            "count": len(items),
            "items": sorted(items, key=lambda item: item["score"], reverse=True),
            "risk_alerts": [risk_alert(item) for item in items if item["risk_flags"]],
        }


def risk_alert(report: dict) -> dict:
    return {"symbol": report["symbol"], "score": report["score"], "top_risk": report["risk_flags"][0]}


def quality_to_dict(quality) -> dict:
    return {
        "source": quality.source,
        "status": quality.status,
        "confidence": quality.confidence,
        "attempts": [asdict(item) for item in quality.attempts],
        "notes": quality.notes,
    }


def quote_from_history(symbol, history_bundle) -> dict:
    bars = history_bundle.bars
    last = bars[-1]
    prev = bars[-2]
    currency = {"cn": "CNY", "hk": "HKD", "us": "USD"}[symbol.market]
    return {
        "symbol": symbol.display,
        "market": symbol.market,
        "name": symbol.display,
        "price": round(last.close, 3),
        "change_pct": round((last.close / prev.close - 1) * 100, 2),
        "currency": currency,
        "source": history_bundle.quality.source,
    }
