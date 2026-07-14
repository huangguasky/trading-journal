from engine.config import get_settings
from engine.data.market_data import Bar, MarketData
from engine.data.news_data import NewsData


def test_environment_does_not_configure_llm(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-be-read")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.invalid")
    settings = get_settings()
    assert settings.llm_api_key is None
    assert settings.llm_base_url is None


def test_market_data_skips_missing_credentials_and_never_uses_sample(monkeypatch):
    market = MarketData(api_keys={})
    monkeypatch.setattr(market, "_load_akshare", lambda symbol, days: [])
    monkeypatch.setattr(market, "_load_yfinance", lambda symbol, days: [])
    bundle = market.history_bundle("600519")
    assert bundle.bars == []
    assert bundle.quality.source == "none"
    assert bundle.quality.status == "unavailable"
    assert all(item.provider != "sample" for item in bundle.quality.attempts)
    assert bundle.quality.attempts[0].status == "not_configured"


def test_market_data_accepts_first_valid_provider(monkeypatch):
    market = MarketData(api_keys={"tushare_token": "configured"})
    bars = [Bar(str(index), 1, 2, 0.5, 1.5, 100) for index in range(30)]
    monkeypatch.setattr(market, "_load_tushare", lambda symbol, days: bars)
    monkeypatch.setattr(market, "_load_akshare", lambda symbol, days: (_ for _ in ()).throw(AssertionError("must not fall through")))
    bundle = market.history_bundle("600519")
    assert bundle.quality.source == "tushare"
    assert bundle.bars == bars


def test_news_failure_returns_empty_not_template(monkeypatch):
    news = NewsData()
    monkeypatch.setattr(news, "_announcements", lambda symbol: [])
    monkeypatch.setattr(news, "_yfinance_news", lambda symbol: [])
    bundle = news.stock_news_bundle("AAPL")
    assert bundle.items == []
    assert bundle.quality["status"] == "unavailable"
    assert bundle.quality["source"] == "none"
