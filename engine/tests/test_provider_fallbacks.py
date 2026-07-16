from datetime import date
import time

from engine.config import get_settings
from engine.data.enrichment import EnrichmentBundle
from engine.data.market_data import Bar, MarketData, yfinance_date_window
from engine.data.normalize import normalize_symbol
from engine.data.news_data import NewsData
from engine.agent.tools import ToolRegistry
from engine.storage.db import Database


def test_environment_does_not_configure_llm(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-be-read")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.invalid")
    settings = get_settings()
    assert settings.llm_api_key is None
    assert settings.llm_base_url is None


def test_market_data_skips_missing_credentials_and_never_uses_sample(monkeypatch):
    market = MarketData(api_keys={})
    monkeypatch.setattr(market, "_load_akshare", lambda symbol, days: [])
    monkeypatch.setattr(market, "_load_yahoo", lambda symbol, days: [])
    bundle = market.history_bundle("600519")
    assert bundle.bars == []
    assert bundle.quality.source == "none"
    assert bundle.quality.status == "unavailable"
    assert all(item.provider != "sample" for item in bundle.quality.attempts)
    assert bundle.quality.attempts[0].provider == "yahoo"


def test_market_data_accepts_first_valid_provider(monkeypatch):
    market = MarketData()
    bars = [Bar(str(index), 1, 2, 0.5, 1.5, 100) for index in range(30)]
    monkeypatch.setattr(market, "_load_yahoo", lambda symbol, days: bars)
    monkeypatch.setattr(market, "_load_akshare", lambda symbol, days: (_ for _ in ()).throw(AssertionError("must not fall through")))
    bundle = market.history_bundle("600519")
    assert bundle.quality.source == "yahoo"
    assert bundle.bars == bars


def test_quote_prefers_realtime_chart_metadata(monkeypatch):
    market = MarketData()
    monkeypatch.setattr("engine.data.enrichment.EnrichmentData.realtime_quote", lambda self, symbol: EnrichmentBundle(
        {"price": 482.0, "change_pct": 1.2, "name": "Tencent Holdings Limited"},
        {"source": "yahoo-chart", "status": "ok", "confidence": "high"},
    ))
    monkeypatch.setattr(market, "history_bundle", lambda symbol, days=260: (_ for _ in ()).throw(AssertionError("daily fallback must not run")))

    quote = market.quote("HK0700")

    assert quote.price == 482.0
    assert quote.source == "yahoo-chart"
    assert quote.name == "Tencent Holdings Limited"
    assert quote.is_delayed is True


def test_news_failure_returns_empty_not_template(monkeypatch):
    news = NewsData()
    monkeypatch.setattr(news, "_announcements", lambda symbol: [])
    monkeypatch.setattr(news, "_yfinance_news", lambda symbol: [])
    bundle = news.stock_news_bundle("AAPL")
    assert bundle.items == []
    assert bundle.quality["status"] == "unavailable"
    assert bundle.quality["source"] == "none"


def test_yfinance_uses_calendar_window_for_arbitrary_trading_days():
    start, end = yfinance_date_window(260, date(2026, 7, 15))

    assert start == "2025-02-11"
    assert end == "2026-07-16"


def test_market_index_symbols_keep_exchange_and_provider_identity():
    assert normalize_symbol("SH000001").provider_code == "000001.SS"
    assert normalize_symbol("SZ399006").provider_code == "399006.SZ"
    hang_seng = normalize_symbol("HK800000")
    assert (hang_seng.market, hang_seng.display, hang_seng.provider_code) == ("hk", "HK恒生指数", "^HSI")


def test_market_snapshot_fetches_each_symbol_only_once(monkeypatch):
    market = MarketData()
    bars = [Bar(str(index), 10, 11, 9, 10 + index / 100, 100) for index in range(30)]
    calls = []

    def load(symbol, days):
        calls.append(symbol.provider_code)
        return bars

    monkeypatch.setattr(market, "_load_yahoo", load)
    snapshot = market.market_snapshot("hk")

    assert len(calls) == 5
    assert len(set(calls)) == 5
    assert len(snapshot["indices"]) == 3
    assert snapshot["indices"][0]["symbol"] == "HK恒生指数"


def test_tool_registry_empty_allowlist_denies_execution(tmp_path):
    registry = ToolRegistry(Database(tmp_path / "deny.db"))
    result = registry.execute("get_quote", {"symbol": "AAPL"}, [])
    assert result == {"ok": False, "error": "tool_not_allowed", "tool": "get_quote"}


def test_tool_timeout_returns_without_waiting_for_handler_completion(tmp_path):
    registry = ToolRegistry(Database(tmp_path / "timeout.db"), tool_timeout_s=0.01)
    registry.tools["get_quote"].handler = lambda args: time.sleep(0.2)
    started = time.monotonic()
    result = registry.execute("get_quote", {"symbol": "AAPL"}, ["get_quote"])
    elapsed = time.monotonic() - started
    assert result["timeout"] is True
    assert elapsed < 0.1


def test_transient_value_error_is_retried_on_next_call(tmp_path):
    registry = ToolRegistry(Database(tmp_path / "retry.db"))
    attempts = []

    def flaky(args):
        attempts.append(args)
        if len(attempts) == 1:
            raise ValueError("temporary")
        return {"price": 10}

    registry.tools["get_quote"].handler = flaky
    first = registry.execute("get_quote", {"symbol": "AAPL"}, ["get_quote"])
    second = registry.execute("get_quote", {"symbol": "AAPL"}, ["get_quote"])
    assert first["ok"] is False
    assert second["ok"] is True
    assert len(attempts) == 2
