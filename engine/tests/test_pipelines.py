from engine.analysis.market_pipeline import MarketPipeline
from engine.analysis.stock_pipeline import StockPipeline
from engine.storage.db import Database


def test_stock_pipeline_creates_structured_report(tmp_path):
    report = StockPipeline(Database(tmp_path / "test.db")).analyze("600519")
    assert report["type"] == "stock_report"
    assert report["symbol"] == "SH600519"
    assert report["score"] > 0
    assert report["tracking_task_id"] > 0
    assert "operation_plan" in report


def test_market_pipeline_schema(tmp_path):
    report = MarketPipeline(Database(tmp_path / "test.db")).analyze("us")
    assert report["market"] == "us"
    assert report["market_regime"] in {"risk_on", "neutral", "risk_off", "volatile"}
    assert isinstance(report["indices"], list)
    assert "sector_rotation" in report
    assert "strategy_bias" in report

