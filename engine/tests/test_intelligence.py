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


def test_social_sentiment_skips_non_us_markets():
    result = NewsData(social_enabled=True).social_sentiment("SH600519", "cn")
    assert result.data == {}
    assert result.quality["status"] == "skipped"


def test_real_chip_provider_marks_unsupported_market():
    result = EnrichmentData().chip_distribution(normalize_symbol("AAPL"))
    assert result.data == {}
    assert result.quality["status"] == "not_supported"
