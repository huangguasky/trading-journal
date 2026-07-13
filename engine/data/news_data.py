from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass, asdict
from typing import Any

from engine.time_utils import today_cn


@dataclass
class NewsBundle:
    """News items paired with provenance and quality metadata."""
    items: list[dict[str, Any]]
    quality: dict[str, Any]


class NewsData:
    """Load real news when configured and deterministic samples otherwise."""
    def __init__(self, news_api_key: str = "", timeout_s: float = 8):
        """Configure NewsAPI credentials and network timeout."""
        self.news_api_key = news_api_key.strip()
        self.timeout_s = timeout_s

    def stock_news(self, symbol: str) -> list[dict]:
        """Return only the news items for a stock symbol."""
        return self.stock_news_bundle(symbol).items

    def stock_news_bundle(self, symbol: str) -> NewsBundle:
        """Return stock news with fallback attempts and quality metadata."""
        attempts = []
        if self.news_api_key:
            try:
                items = self._newsapi(f"{symbol} stock", language="zh")
                if items:
                    return NewsBundle(items, quality("newsapi", "ok", "medium", attempts + [{"provider": "newsapi", "status": "ok", "message": f"取得 {len(items)} 条新闻"}]))
                attempts.append({"provider": "newsapi", "status": "empty", "message": "未返回相关新闻"})
            except Exception as exc:
                attempts.append({"provider": "newsapi", "status": "failed", "message": str(exc)[:160]})
        else:
            attempts.append({"provider": "newsapi", "status": "skipped", "message": "未配置 NewsAPI Key"})

        return NewsBundle(
            [
                {"title": f"{symbol} 近期价格结构与成交量变化值得跟踪", "source": "local-risk-template", "date": today_cn(), "risk_level": "medium"},
                {"title": f"{symbol} 交易前建议复核财报、公告、政策或行业催化因素", "source": "local-risk-template", "date": today_cn(), "risk_level": "low"},
            ],
            quality("local-risk-template", "fallback", "low", attempts, ["新闻源不可用，资讯部分以风险核对清单代替。"]),
        )

    def market_news(self, market: str) -> list[dict]:
        """Return only the news items for a market."""
        return self.market_news_bundle(market).items

    def market_news_bundle(self, market: str) -> NewsBundle:
        """Return market news with fallback attempts and quality metadata."""
        labels = {"cn": "A股", "hk": "港股", "us": "美股"}
        label = labels.get(market, market)
        attempts = []
        if self.news_api_key:
            try:
                items = self._newsapi(f"{label} market macro", language="zh")
                if items:
                    return NewsBundle(items, quality("newsapi", "ok", "medium", attempts + [{"provider": "newsapi", "status": "ok", "message": f"取得 {len(items)} 条新闻"}]))
                attempts.append({"provider": "newsapi", "status": "empty", "message": "未返回市场新闻"})
            except Exception as exc:
                attempts.append({"provider": "newsapi", "status": "failed", "message": str(exc)[:160]})
        else:
            attempts.append({"provider": "newsapi", "status": "skipped", "message": "未配置 NewsAPI Key"})

        return NewsBundle(
            [
                {"title": f"{label}市场的流动性与风险偏好仍是核心变量", "source": "local-risk-template", "date": today_cn()},
                {"title": f"{label}投资者关注宏观利率、政策信号与板块轮动", "source": "local-risk-template", "date": today_cn()},
            ],
            quality("local-risk-template", "fallback", "low", attempts, ["新闻源不可用，宏观资讯以复盘核对清单代替。"]),
        )

    def _newsapi(self, query: str, language: str = "zh") -> list[dict[str, Any]]:
        """Request and normalize recent articles from NewsAPI."""
        params = urllib.parse.urlencode({"q": query, "language": language, "pageSize": 5, "sortBy": "publishedAt", "apiKey": self.news_api_key})
        with urllib.request.urlopen(f"https://newsapi.org/v2/everything?{params}", timeout=self.timeout_s) as response:
            payload = json.loads(response.read().decode("utf-8"))
        articles = payload.get("articles") or []
        return [
            {
                "title": item.get("title") or "未命名资讯",
                "source": (item.get("source") or {}).get("name") or "newsapi",
                "date": str(item.get("publishedAt") or "")[:10] or today_cn(),
                "url": item.get("url"),
            }
            for item in articles[:5]
        ]


def quality(source: str, status: str, confidence: str, attempts: list[dict[str, str]], notes: list[str] | None = None) -> dict[str, Any]:
    """Build the common source-quality payload used by news responses."""
    return {"source": source, "status": status, "confidence": confidence, "attempts": attempts, "notes": notes or []}
