from engine.data.news_data import NewsData, deduplicate_articles
from engine.data.enrichment import EnrichmentData
from engine.data.normalize import normalize_symbol


def test_news_deduplication_preserves_first_provider():
    items = [
        {"title": "Company earnings growth", "source": "announcement"},
        {"title": " Company  earnings growth ", "source": "search"},
        {"title": "New contract approved", "source": "search"},
    ]
    assert [item["source"] for item in deduplicate_articles(items)] == ["announcement", "search"]


def test_social_sentiment_marks_non_us_markets_unsupported():
    result = NewsData(social_enabled=True).social_sentiment("SH600519", "cn")
    assert result.data == {}
    assert result.quality["status"] == "not_supported"


def test_real_chip_provider_marks_unsupported_market():
    result = EnrichmentData().chip_distribution(normalize_symbol("AAPL"))
    assert result.data == {}
    assert result.quality["status"] == "not_supported"


def test_realtime_quote_uses_yahoo_chart_metadata(monkeypatch):
    enrichment = EnrichmentData()
    monkeypatch.setattr(enrichment, "_yahoo_chart_meta", lambda symbol: {
        "regularMarketPrice": 471.6,
        "chartPreviousClose": 456.2,
        "regularMarketDayHigh": 475.8,
        "regularMarketDayLow": 455.4,
        "regularMarketVolume": 19_434_769,
        "longName": "Tencent Holdings Limited",
    })

    result = enrichment.realtime_quote(normalize_symbol("HK00700"))

    assert result.data["price"] == 471.6
    assert result.data["name"] == "Tencent Holdings Limited"
    assert result.quality["source"] == "yahoo-chart"
    assert result.quality["status"] == "ok"


def test_realtime_quote_prefers_derived_previous_day_over_chart_window_close(monkeypatch):
    enrichment = EnrichmentData()
    monkeypatch.setattr(enrichment, "_yahoo_chart_meta", lambda symbol: {
        "regularMarketPrice": 9.04,
        "derivedPreviousClose": 8.37,
        "chartPreviousClose": 9.26,
    })

    result = enrichment.realtime_quote(normalize_symbol("HK00917"))

    assert result.data["previous_close"] == 8.37
    assert result.data["change_pct"] == 8.0


def test_yahoo_chart_meta_derives_previous_close_from_daily_bars(monkeypatch):
    enrichment = EnrichmentData()
    payload = {
        "chart": {"result": [{
            "meta": {"regularMarketPrice": 9.04, "chartPreviousClose": 9.26},
            "indicators": {"quote": [{"close": [8.30, 8.29, 8.37, 9.04]}]},
        }]},
    }

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return __import__("json").dumps(payload).encode()

    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout: Response())
    meta = enrichment._yahoo_chart_meta(normalize_symbol("HK00917"))
    assert meta["derivedPreviousClose"] == 8.37


def test_hk_fundamentals_use_dedicated_akshare_sources(monkeypatch):
    import akshare as ak
    import pandas as pd

    monkeypatch.setattr(ak, "stock_hk_financial_indicator_em", lambda symbol: pd.DataFrame([{
        "市盈率": 15.7, "市净率": 3.2, "港股市值(港元)": 4.1e12,
        "股息率TTM(%)": 1.2, "股东权益回报率(%)": 20.0, "销售净利率(%)": 30.0,
    }]))
    monkeypatch.setattr(ak, "stock_financial_hk_analysis_indicator_em", lambda symbol, indicator: pd.DataFrame([{
        "REPORT_DATE": "2025-12-31", "OPERATE_INCOME_YOY": 13.8,
        "HOLDER_PROFIT_YOY": 15.9, "SECURITY_NAME_ABBR": "腾讯控股",
    }]))
    monkeypatch.setattr(ak, "stock_hk_company_profile_em", lambda symbol: pd.DataFrame([{"公司名称": "腾讯控股有限公司", "所属行业": "软件服务"}]))

    result = EnrichmentData().fundamentals(normalize_symbol("HK00700"))

    assert result.quality["source"] == "akshare-hk-f10"
    assert result.quality["status"] == "ok"
    assert result.data["valuation"]["pe_ttm"] == 15.7
    assert result.data["growth"]["revenue_yoy"] == 0.138
