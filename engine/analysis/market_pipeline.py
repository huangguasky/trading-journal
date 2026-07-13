from __future__ import annotations

from engine.data.market_data import MarketData
from engine.data.news_data import NewsData
from engine.storage.db import Database
from engine.strategies.registry import StrategyRegistry

from .report_builder import build_market_report


class MarketPipeline:
    """Coordinate market data, news, scoring, reporting, and persistence."""
    def __init__(self, db: Database, market_data: MarketData | None = None, news_data: NewsData | None = None, strategies: StrategyRegistry | None = None):
        """Initialize the pipeline with injectable services for testing or customization."""
        self.db = db
        self.market_data = market_data or MarketData()
        self.news_data = news_data or NewsData()
        self.strategies = strategies or StrategyRegistry()

    def analyze(self, market: str, save: bool = True) -> dict:
        """Analyze one market and optionally persist the structured report."""
        market = market if market in {"cn", "hk", "us"} else "cn"
        snapshot = self.market_data.market_snapshot(market)
        news_bundle = self.news_data.market_news_bundle(market)
        score = market_score(snapshot)
        context = build_market_context(market, snapshot, score)
        payload = {
            "market": market,
            "market_regime": regime_for_score(score, snapshot),
            "score": score,
            "indices": snapshot["indices"],
            "breadth": snapshot["breadth"],
            "sector_rotation": snapshot["sector_rotation"],
            "macro_news": news_bundle.items,
            "risk_flags": market_risks(score, snapshot, news_bundle.quality),
            "tomorrow_watch": tomorrow_watch(market, snapshot, context),
            "strategy_bias": self.strategies.select_market_bias(snapshot, news_bundle.items),
            "data_quality": merge_market_quality(snapshot.get("data_quality", {}), news_bundle.quality),
            "market_context": context,
        }
        report, markdown = build_market_report(payload)
        if save:
            title = {"cn": "A股市场复盘", "hk": "港股市场复盘", "us": "美股市场复盘"}.get(market, f"{market.upper()} 市场复盘")
            report["id"] = self.db.save_report("market", title, report["score"], report, markdown, market=market, regime=report["market_regime"])
        report["markdown"] = markdown
        return report


def market_score(snapshot: dict) -> float:
    """Calculate a bounded market score from trend, breadth, and index changes."""
    index_scores = [50 + item["change_pct"] * 8 for item in snapshot["indices"]]
    breadth = snapshot["breadth"]
    breadth_score = breadth["advancers"] / max(1, breadth["advancers"] + breadth["decliners"]) * 100
    limit_score = 50
    if breadth.get("limit_up") is not None:
        limit_score += min(18, breadth.get("limit_up", 0) * 0.35)
        limit_score -= min(12, breadth.get("limit_down", 0) * 0.7)
    raw = sum(index_scores) / len(index_scores) * 0.48 + breadth_score * 0.37 + limit_score * 0.15
    if snapshot.get("data_quality", {}).get("confidence") == "low":
        raw -= 6
    return round(max(0, min(100, raw)), 1)


def regime_for_score(score: float, snapshot: dict) -> str:
    """Classify the market regime from score and breadth conditions."""
    turnover = snapshot["breadth"].get("turnover_billion", 0)
    decliners = snapshot["breadth"].get("decliners", 0)
    advancers = snapshot["breadth"].get("advancers", 0)
    if score >= 66 and advancers > decliners:
        return "risk_on"
    if score <= 42:
        return "risk_off"
    if turnover > 700 or abs(advancers - decliners) < (advancers + decliners) * 0.08:
        return "volatile"
    return "neutral"


def build_market_context(market: str, snapshot: dict, score: float) -> dict:
    """Build the concise market context consumed by reports and strategies."""
    breadth = snapshot["breadth"]
    total = max(1, breadth.get("advancers", 0) + breadth.get("decliners", 0))
    adv_ratio = round(breadth.get("advancers", 0) / total * 100, 1)
    sentiment = "偏强" if score >= 62 else "偏弱" if score <= 42 else "分歧"
    return {
        "market": market,
        "advancer_ratio": adv_ratio,
        "sentiment": sentiment,
        "liquidity": "活跃" if breadth.get("turnover_billion", 0) >= 650 else "普通",
        "leader_count": len(snapshot["sector_rotation"]["leaders"]),
        "watch_assets": snapshot.get("watch_assets", []),
    }


def market_risks(score: float, snapshot: dict, news_quality: dict) -> list[str]:
    """Describe material score, breadth, volatility, and news-quality risks."""
    risks = []
    breadth = snapshot["breadth"]
    if score < 45:
        risks.append("市场宽度偏弱，在修复确认前不宜扩大风险敞口。")
    if breadth.get("decliners", 0) > breadth.get("advancers", 0):
        risks.append("下跌家数多于上涨家数，指数表现可能掩盖个股压力。")
    if breadth.get("limit_down") and breadth.get("limit_down", 0) > breadth.get("limit_up", 0) * 0.4:
        risks.append("跌停数量相对偏高，短线情绪有扩散风险。")
    if snapshot.get("data_quality", {}).get("confidence") == "low":
        risks.append("市场快照存在数据降级，本次复盘应降低置信度。")
    if news_quality.get("confidence") == "low":
        risks.append("宏观新闻源降级，需在交易前补充核对重大事件。")
    if not risks:
        risks.append("指数强势后仍需警惕高开回落和板块轮动过快。")
    return risks


def tomorrow_watch(market: str, snapshot: dict, context: dict) -> list[str]:
    """Build the next-session checklist from the current market context."""
    leaders = snapshot["sector_rotation"]["leaders"]
    return [
        f"确认领先方向是否延续：{'、'.join(leaders[:3])}",
        f"观察上涨家数占比是否继续改善，当前约 {context['advancer_ratio']}%。",
        "开盘前复核隔夜宏观、流动性和风险事件。",
    ]


def merge_market_quality(snapshot_quality: dict, news_quality: dict) -> dict:
    """Merge market-price and news provenance into one quality assessment."""
    confidence = "low" if snapshot_quality.get("confidence") == "low" or news_quality.get("confidence") == "low" else "medium"
    status = "fallback" if snapshot_quality.get("status") == "fallback" or news_quality.get("status") == "fallback" else "ok"
    return {
        "source": ",".join(snapshot_quality.get("sources", [])) or "mixed",
        "status": status,
        "confidence": confidence,
        "attempts": snapshot_quality.get("items", [])[:3] + [news_quality],
        "notes": (snapshot_quality.get("notes") or []) + (news_quality.get("notes") or []),
    }
