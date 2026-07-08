from __future__ import annotations

from engine.data.market_data import MarketData
from engine.data.news_data import NewsData
from engine.storage.db import Database
from engine.strategies.registry import StrategyRegistry

from .report_builder import build_market_report


class MarketPipeline:
    def __init__(self, db: Database, market_data: MarketData | None = None, news_data: NewsData | None = None, strategies: StrategyRegistry | None = None):
        self.db = db
        self.market_data = market_data or MarketData()
        self.news_data = news_data or NewsData()
        self.strategies = strategies or StrategyRegistry()

    def analyze(self, market: str, save: bool = True) -> dict:
        market = market if market in {"cn", "hk", "us"} else "cn"
        snapshot = self.market_data.market_snapshot(market)
        news = self.news_data.market_news(market)
        score = market_score(snapshot)
        payload = {
            "market": market,
            "market_regime": regime_for_score(score, snapshot),
            "score": score,
            "indices": snapshot["indices"],
            "breadth": snapshot["breadth"],
            "sector_rotation": snapshot["sector_rotation"],
            "macro_news": news,
            "risk_flags": market_risks(score, snapshot),
            "tomorrow_watch": tomorrow_watch(market, snapshot),
            "strategy_bias": self.strategies.select_market_bias(snapshot, news),
        }
        report, markdown = build_market_report(payload)
        if save:
            report["id"] = self.db.save_report("market", f"{market.upper()} Market Review", report["score"], report, markdown, market=market, regime=report["market_regime"])
        report["markdown"] = markdown
        return report


def market_score(snapshot: dict) -> float:
    index_scores = [50 + item["change_pct"] * 8 for item in snapshot["indices"]]
    breadth = snapshot["breadth"]
    breadth_score = breadth["advancers"] / max(1, breadth["advancers"] + breadth["decliners"]) * 100
    return round(max(0, min(100, sum(index_scores) / len(index_scores) * 0.55 + breadth_score * 0.45)), 1)


def regime_for_score(score: float, snapshot: dict) -> str:
    turnover = snapshot["breadth"].get("turnover_billion", 0)
    if score >= 65:
        return "risk_on"
    if score <= 40:
        return "risk_off"
    if turnover > 700:
        return "volatile"
    return "neutral"


def market_risks(score: float, snapshot: dict) -> list[str]:
    risks = []
    if score < 45:
        risks.append("Weak breadth: avoid expanding risk before recovery.")
    if snapshot["breadth"].get("decliners", 0) > snapshot["breadth"].get("advancers", 0):
        risks.append("Decliners outnumber advancers.")
    if not risks:
        risks.append("Watch for reversal after strong index gaps.")
    return risks


def tomorrow_watch(market: str, snapshot: dict) -> list[str]:
    leaders = snapshot["sector_rotation"]["leaders"]
    return [
        f"Confirm whether leaders sustain: {', '.join(leaders[:3])}",
        "Check if breadth improves or diverges from index performance.",
        "Review overnight macro and liquidity signals before open.",
    ]

