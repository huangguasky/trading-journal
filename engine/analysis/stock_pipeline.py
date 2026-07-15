from __future__ import annotations

from dataclasses import asdict
from concurrent.futures import ThreadPoolExecutor
import time

from engine.data.market_data import MarketData
from engine.data.news_data import NewsData
from engine.data.enrichment import EnrichmentData, EnrichmentBundle
from engine.data.normalize import normalize_symbol
from engine.indicators import compute_indicators
from engine.storage.db import Database
from engine.strategies.registry import StrategyRegistry

from .evidence import build_stock_evidence
from .llm_enhancement import NaturalLanguageEnhancer
from .report_builder import build_stock_report
from .tracking import TrackingService


class StockPipeline:
    """Coordinate stock data, indicators, strategies, reporting, and persistence."""
    def __init__(self, db: Database, market_data: MarketData | None = None, news_data: NewsData | None = None, strategies: StrategyRegistry | None = None, enrichment_data: EnrichmentData | None = None, language_enhancer: NaturalLanguageEnhancer | None = None):
        """Initialize the pipeline with injectable services for testing or customization."""
        self.db = db
        self.market_data = market_data or MarketData()
        self.news_data = news_data or NewsData()
        self.strategies = strategies or StrategyRegistry()
        self.enrichment_data = enrichment_data
        self.language_enhancer = language_enhancer
        self.tracking = TrackingService(db, self.market_data)

    def analyze(self, code: str, save: bool = True) -> dict:
        """Analyze one stock and optionally save its report and tracking task."""
        symbol = normalize_symbol(code)
        started_at = time.monotonic()
        history_started = time.monotonic()
        history_bundle = self.market_data.history_bundle(symbol)
        if len(history_bundle.bars) < 30:
            return self._unavailable_report(symbol, history_bundle, save)
        quote = quote_from_history(symbol, history_bundle)
        indicators = compute_indicators(history_bundle.bars)
        diagnostics = {"history_ms": elapsed_ms(history_started)}
        enrichment_started = time.monotonic()
        realtime_bundle, fundamental_bundle, chip_bundle, social_bundle, news_bundle = self._collect_enrichment(symbol)
        diagnostics["enrichment_ms"] = elapsed_ms(enrichment_started)
        quote = overlay_realtime_quote(quote, realtime_bundle)
        if chip_bundle.data:
            indicators["chips"] = chip_bundle.data
        news = news_bundle.items
        intelligence = news_bundle.intelligence
        intelligence["social_sentiment"] = social_bundle.data
        market_context = self._latest_market_context(symbol.market)
        strategy_context = build_strategy_context(fundamental_bundle.data, intelligence, market_context)
        strategy_results = [asdict(item) for item in self.strategies.select_for_stock(indicators, news, strategy_context)]
        data_quality = {
            "history": quality_to_dict(history_bundle.quality),
            "price": quality_to_dict(history_bundle.quality),
            "news": news_bundle.quality,
            "realtime": realtime_bundle.quality,
            "fundamentals": fundamental_bundle.quality,
            "social_sentiment": social_bundle.quality,
            "chips": chip_bundle.quality if chip_bundle.data or symbol.market != "cn" else {
                "source": "historical-close-estimate", "status": "estimated", "confidence": "low",
                "attempts": [], "notes": ["筹码指标由近期收盘价估算，不代表真实持仓成本分布。"],
            },
        }
        language_analysis = self._enhance_language_analysis(
            symbol.display, news, intelligence, social_bundle.data, fundamental_bundle.data,
            market_context, indicators, strategy_results,
        )
        intelligence["language_analysis"] = language_analysis
        evidence = build_stock_evidence(symbol.display, quote, indicators, news, strategy_results, data_quality)
        apply_stock_language_evidence(evidence, language_analysis)
        report, markdown = build_stock_report(
            {
                "symbol": symbol.display,
                "market": symbol.market,
                "quote": quote,
                "indicators": indicators,
                "news": news,
                "intelligence": intelligence,
                "fundamentals": fundamental_bundle.data,
                "market_context": market_context,
                "diagnostics": diagnostics,
                "strategies": strategy_results,
                "evidence": evidence,
            }
        )
        diagnostics["analysis_ms"] = elapsed_ms(started_at)
        if save:
            report_id = self.db.save_report("stock", f"{symbol.display} 个股分析报告", report["score"], report, markdown, symbol.display, symbol.market, report["rating"])
            report["id"] = report_id
            report["tracking_task_id"] = self.tracking.create_for_report(report_id, report)
        report["markdown"] = markdown
        return report

    def _enhance_language_analysis(self, symbol: str, news: list[dict], intelligence: dict, social: dict, fundamentals: dict, market_context: dict, indicators: dict, strategies: list[dict]) -> dict:
        """Run optional semantic analysis while keeping rule evidence authoritative."""
        if self.language_enhancer is None:
            return {"status": "disabled", "mode": "规则分析", "provider": "none", "analysis": {}, "notes": ["未启用 LLM 自然语言增强。"]}
        return self.language_enhancer.enhance_stock({
            "symbol": symbol,
            "news": news,
            "rule_intelligence": intelligence,
            "social_sentiment": social,
            "fundamentals": fundamentals,
            "market_context": market_context,
            "technical_summary": {
                "trend": indicators.get("trend", {}),
                "momentum": indicators.get("momentum", {}),
                "volume": indicators.get("volume", {}),
                "levels": indicators.get("levels", {}),
            },
            "strategies": strategies,
        })

    def _unavailable_report(self, symbol, history_bundle, save: bool) -> dict:
        """Persist an explicit diagnostic report when no real history is usable."""
        quality = quality_to_dict(history_bundle.quality)
        attempts = quality.get("attempts", [])
        details = [f"{item['provider']}: {item.get('message') or item['status']}" for item in attempts]
        suggestions = quality.get("notes", [])
        report = {
            "type": "stock_report", "symbol": symbol.display, "market": symbol.market,
            "date": __import__("engine.time_utils", fromlist=["today_cn"]).today_cn(),
            "score": 0, "rating": "数据不足", "action": "未取得真实行情，无法生成交易判断",
            "core_conclusion": "未取得真实行情，当前只能等待数据恢复，不能据此制定买入计划。",
            "confidence": {"level": "low", "reason": "全部真实行情源均不可用。"},
            "coverage": {"technical": False, "realtime": False, "news": False, "fundamentals": False},
            "decision_limits": ["缺少真实历史行情，未计算指标、评分、交易计划或追踪任务。", *suggestions],
            "quote": {"symbol": symbol.display, "market": symbol.market, "name": symbol.display, "price": 0, "change_pct": 0, "currency": {"cn": "CNY", "hk": "HKD", "us": "USD"}[symbol.market], "source": "none"},
            "evidence": {"data_quality": {"history": quality, "price": quality}}, "strategies": [], "selected_strategies": [],
            "news": [], "intelligence": {}, "fundamentals": {}, "market_context": {}, "diagnostics": {},
            "data_quality": {"history": quality, "price": quality},
            "risk_flags": ["真实行情源缺失，任何价格与趋势判断都不可用。", *details],
            "operation_plan": {"entry": "请先在设置页完成数据源配置并确认可调用。", "ideal_buy": None, "stop": None, "target": None, "position": "观望", "watch_conditions": suggestions},
            "tracking": {"base_price": None, "target_price": None, "stop_price": None, "review_after_days": 0, "watch_conditions": suggestions},
        }
        markdown = "\n".join([f"# {symbol.display} 数据不足报告", "", "未取得任何可验证的真实行情，因此未生成交易结论。", "", "## 数据源诊断", *[f"- {item}" for item in details], "", "## 建议", *[f"- {item}" for item in suggestions]])
        if save:
            report["id"] = self.db.save_report("stock", f"{symbol.display} 数据不足报告", 0, report, markdown, symbol.display, symbol.market, "数据不足")
        report["markdown"] = markdown
        return report

    def _collect_enrichment(self, symbol) -> tuple[EnrichmentBundle, EnrichmentBundle, EnrichmentBundle, object, object]:
        """Fetch independent optional inputs concurrently and degrade per source."""
        unavailable = EnrichmentBundle({}, {
            "source": "disabled", "status": "unavailable", "confidence": "low",
            "attempts": [], "notes": ["增强数据源未启用。"],
        })
        if self.enrichment_data is None:
            return unavailable, unavailable, unavailable, self.news_data.social_sentiment(symbol.display, symbol.market), self.news_data.stock_news_bundle(symbol.display)
        with ThreadPoolExecutor(max_workers=5) as pool:
            realtime = pool.submit(self.enrichment_data.realtime_quote, symbol)
            fundamentals = pool.submit(self.enrichment_data.fundamentals, symbol)
            chips = pool.submit(self.enrichment_data.chip_distribution, symbol)
            social = pool.submit(self.news_data.social_sentiment, symbol.display, symbol.market)
            news = pool.submit(self.news_data.stock_news_bundle, symbol.display)
            return realtime.result(), fundamentals.result(), chips.result(), social.result(), news.result()

    def _latest_market_context(self, market: str) -> dict:
        """Reuse the latest persisted market report without recomputing market data."""
        reports = self.db.list_reports(limit=10, kind="market")
        row = next((item for item in reports if item.get("market") == market), None)
        if not row:
            return {"status": "unavailable", "note": "暂无可复用的大盘报告。"}
        payload = row.get("payload") or {}
        return {
            "status": "ok",
            "report_id": row.get("id"),
            "date": payload.get("date"),
            "market_regime": payload.get("market_regime"),
            "score": payload.get("score"),
            "strategy_bias": payload.get("strategy_bias"),
        }

    def analyze_watchlist(self, symbols: list[str], save: bool = True) -> dict:
        """Analyze each watchlist symbol and summarize resulting risk alerts."""
        self.db.upsert_watchlist(symbols)
        items = [self.analyze(symbol, save=save) for symbol in symbols]
        return {
            "count": len(items),
            "items": sorted(items, key=lambda item: item["score"], reverse=True),
            "risk_alerts": [risk_alert(item) for item in items if item["risk_flags"]],
        }


def risk_alert(report: dict) -> dict:
    """Extract a compact risk-alert view from a full stock report."""
    return {"symbol": report["symbol"], "score": report["score"], "top_risk": report["risk_flags"][0]}


def quality_to_dict(quality) -> dict:
    """Serialize history quality metadata for the stock report payload."""
    return {
        "source": quality.source,
        "status": quality.status,
        "confidence": quality.confidence,
        "attempts": [asdict(item) for item in quality.attempts],
        "notes": quality.notes,
    }


def quote_from_history(symbol, history_bundle) -> dict:
    """Derive a quote dictionary from the last two normalized history bars."""
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
        "as_of": bars[-1].date,
        "is_partial_bar": False,
    }


def overlay_realtime_quote(quote: dict, bundle: EnrichmentBundle) -> dict:
    """Overlay verified realtime fields while keeping historical provenance."""
    if not bundle.data.get("price"):
        return quote
    merged = dict(quote)
    for key in ("name", "price", "change_pct", "open", "high", "low", "volume", "market_cap", "as_of", "is_partial_bar", "is_stale"):
        if bundle.data.get(key) is not None:
            merged[key] = bundle.data[key]
    merged["source"] = bundle.quality.get("source", quote["source"])
    merged["history_source"] = quote["source"]
    return merged


def build_strategy_context(fundamentals: dict, intelligence: dict, market_context: dict) -> dict:
    """Expose normalized enhancement metrics to existing declarative strategies."""
    metrics = intelligence.get("metrics", {})
    growth = fundamentals.get("growth", {})
    quality = fundamentals.get("quality", {})
    return {
        "intelligence": metrics,
        "fundamentals": {
            "revenue_yoy": growth.get("revenue_yoy"),
            "profit_yoy": growth.get("profit_yoy"),
            "roe": quality.get("roe"),
        },
        "market": {
            "risk_off": market_context.get("market_regime") == "risk_off",
            "score": market_context.get("score"),
        },
    }


def elapsed_ms(started_at: float) -> int:
    return int((time.monotonic() - started_at) * 1000)


def apply_stock_language_evidence(evidence: dict, enhancement: dict) -> None:
    """Merge validated semantic insights into narrative evidence, never numeric inputs."""
    if enhancement.get("status") != "enhanced":
        return
    analysis = enhancement.get("analysis") or {}
    evidence["conflicts"] = list(dict.fromkeys([*evidence.get("conflicts", []), *analysis.get("conflicts", [])]))[:8]
    evidence["confirmations"] = list(dict.fromkeys([*evidence.get("confirmations", []), *analysis.get("confirmations", [])]))[:8]
