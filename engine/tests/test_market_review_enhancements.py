from engine.analysis.market_pipeline import build_market_dimensions, classify_market_news
from engine.data.market_data import combine_quality
from engine.data.news_data import NewsData, deduplicate_news, market_news_queries


def test_market_news_queries_cover_distinct_review_topics():
    topics = {topic for topic, _, _ in market_news_queries("cn")}
    assert topics == {"market", "macro_policy", "liquidity_sector"}


def test_market_news_are_deduplicated_by_url():
    items = [
        {"title": "first", "url": "https://example.test/a"},
        {"title": "duplicate", "url": "https://example.test/a"},
    ]
    assert deduplicate_news(items) == [items[0]]


def test_market_dimensions_keep_estimation_boundary_visible():
    snapshot = {
        "indices": [{"change_pct": 1.0}, {"change_pct": -0.2}],
        "breadth": {"advancers": 60, "decliners": 40, "limit_up": 8, "limit_down": 2, "turnover_billion": 100, "is_estimated": True},
        "sector_rotation": {"leaders": ["科技"], "laggards": ["地产"], "is_estimated": True},
    }
    dimensions = build_market_dimensions(snapshot)
    assert dimensions["index_alignment"]["label"] == "指数分化"
    assert dimensions["breadth"] == {"available": True, "advancer_ratio": 60.0, "is_estimated": True}
    assert dimensions["limit_sentiment"]["spread"] == 6


def test_market_news_classification_uses_topic_and_content():
    news = [
        {"title": "央行发布政策信号", "topic": "macro_policy"},
        {"title": "半导体板块走强", "topic": "liquidity_sector"},
    ]
    intelligence = classify_market_news(news)
    assert intelligence["metrics"]["news_count"] == 2
    assert intelligence["metrics"]["macro_policy_count"] == 1
    assert intelligence["metrics"]["sector_theme_count"] == 1


def test_market_quality_is_not_low_when_some_representative_assets_succeed():
    quality = combine_quality([
        {"source": "yahoo", "status": "ok", "confidence": "high"},
        {"source": "none", "status": "unavailable", "confidence": "low"},
    ])
    assert quality["status"] == "partial"
    assert quality["confidence"] == "medium"
    assert quality["coverage"] == {"available": 1, "total": 2}


def test_market_news_uses_public_rss_before_marking_unavailable(monkeypatch):
    news = NewsData()
    monkeypatch.setattr(news, "_google_market_news_rss", lambda market: [{
        "title": "央行发布最新政策信号", "source": "fixture", "topic": "macro_policy"
    }])
    bundle = news.market_news_bundle("cn")
    assert bundle.quality["status"] == "ok"
    assert bundle.quality["source"] == "google-news-rss"
