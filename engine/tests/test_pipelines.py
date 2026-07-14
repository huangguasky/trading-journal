from engine.analysis.market_pipeline import MarketPipeline
from engine.analysis.stock_pipeline import StockPipeline
from engine.storage.db import Database
from engine.data.enrichment import EnrichmentBundle
from engine.data.news_data import NewsBundle


def test_stock_pipeline_creates_structured_report(tmp_path):
    report = StockPipeline(Database(tmp_path / "test.db")).analyze("600519")
    assert report["type"] == "stock_report"
    assert report["symbol"] == "SH600519"
    assert report["score"] > 0
    assert report["tracking_task_id"] > 0
    assert "operation_plan" in report
    assert report["confidence"]["level"] == "low"
    assert report["action"].startswith("数据不足")
    assert report["news"] == []
    assert report["decision_limits"]


def test_stock_pipeline_consumes_optional_enrichment(tmp_path):
    class FakeMarketData:
        def history_bundle(self, symbol):
            from engine.data.market_data import DataQuality, HistoryBundle, ProviderAttempt, sample_history

            quality = DataQuality("fixture", "ok", "high", [ProviderAttempt("fixture", "ok")], [])
            return HistoryBundle(sample_history(symbol), quality)

    class FakeNewsData:
        def stock_news_bundle(self, symbol):
            items = [{"title": "公司业绩增长并获批新项目", "source": "fixture", "date": "2026-07-14"}]
            return NewsBundle(items, {"source": "fixture", "status": "ok", "confidence": "high", "attempts": [], "notes": []})

        def social_sentiment(self, symbol, market):
            return EnrichmentBundle({"score": 60, "mentions": 5}, {"source": "fixture", "status": "ok", "confidence": "low", "attempts": [], "notes": []})

    class FakeEnrichment:
        def realtime_quote(self, symbol):
            return EnrichmentBundle(
                {"price": 123.0, "change_pct": 2.5, "name": "测试公司", "as_of": "2026-07-14 10:00:00", "is_partial_bar": True},
                {"source": "fixture", "status": "ok", "confidence": "high", "attempts": [], "notes": []},
            )

        def fundamentals(self, symbol):
            return EnrichmentBundle(
                {"growth": {"revenue_yoy": 0.2}, "quality": {"roe": 0.15}, "valuation": {"pe_ttm": 20}},
                {"source": "fixture", "status": "ok", "confidence": "high", "attempts": [], "notes": []},
            )

        def chip_distribution(self, symbol):
            return EnrichmentBundle({}, {"source": "fixture", "status": "unavailable", "confidence": "low", "attempts": [], "notes": []})

    report = StockPipeline(
        Database(tmp_path / "enhanced.db"),
        market_data=FakeMarketData(),
        news_data=FakeNewsData(),
        enrichment_data=FakeEnrichment(),
    ).analyze("600519", save=False)

    assert report["quote"]["price"] == 123.0
    assert report["quote"]["is_partial_bar"] is True
    assert report["coverage"] == {"technical": True, "realtime": True, "news": True, "fundamentals": True}
    assert report["confidence"]["level"] == "high"
    assert report["intelligence"]["metrics"]["catalyst_count"] == 1
    assert report["fundamentals"]["growth"]["revenue_yoy"] == 0.2


def test_delete_report_also_deletes_tracking_task(tmp_path):
    db = Database(tmp_path / "delete.db")
    report = StockPipeline(db).analyze("600519")

    assert db.delete_report(report["id"]) is True
    assert db.list_reports(limit=None) == []
    assert db.list_tracking() == []


def test_watchlist_replaces_previous_items_and_preserves_order(tmp_path):
    db = Database(tmp_path / "watchlist.db")
    db.upsert_watchlist(["600519", "HK0700", "AAPL"])
    db.upsert_watchlist(["AAPL", "600519", "AAPL"])

    assert [item["symbol"] for item in db.list_watchlist()] == ["AAPL", "600519"]


def test_market_pipeline_schema(tmp_path):
    report = MarketPipeline(Database(tmp_path / "test.db")).analyze("us")
    assert report["market"] == "us"
    assert report["market_regime"] in {"risk_on", "neutral", "risk_off", "volatile"}
    assert isinstance(report["indices"], list)
    assert "sector_rotation" in report
    assert "strategy_bias" in report
    assert report["market_dimensions"]["index_alignment"]["available"] is True
    assert report["market_dimensions"]["breadth"]["is_estimated"] is True
    assert report["trading_plan"]["stance"] in {"进攻", "均衡", "防守"}
    assert report["trading_plan"]["position_range"]
    assert "失效条件" in report["markdown"]
    assert "代表性资产估算" in report["markdown"]
