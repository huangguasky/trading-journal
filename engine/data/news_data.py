from __future__ import annotations

import json
import urllib.parse
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from dataclasses import dataclass, asdict
from typing import Any

from engine.time_utils import today_cn


@dataclass
class NewsBundle:
    """News items paired with provenance and quality metadata."""
    items: list[dict[str, Any]]
    quality: dict[str, Any]

    @property
    def intelligence(self) -> dict[str, Any]:
        """Classify real articles into decision-oriented intelligence groups."""
        return classify_intelligence(self.items)


class NewsData:
    """Load verified real news through a capability-ordered fallback chain."""
    def __init__(self, news_api_key: str = "", timeout_s: float = 8, tavily_api_key: str = "", brave_api_key: str = "", social_enabled: bool = True):
        """Configure NewsAPI credentials and network timeout."""
        self.news_api_key = news_api_key.strip()
        self.timeout_s = timeout_s
        self.tavily_api_key = tavily_api_key.strip()
        self.brave_api_key = brave_api_key.strip()
        self.social_enabled = social_enabled

    def stock_news(self, symbol: str) -> list[dict]:
        """Return only the news items for a stock symbol."""
        return self.stock_news_bundle(symbol).items

    def stock_news_bundle(self, symbol: str) -> NewsBundle:
        """Return stock news with fallback attempts and quality metadata."""
        attempts = []
        providers = [
            ("exchange-announcement", None, self._announcements),
            ("newsapi", self.news_api_key, lambda value: self._newsapi(f"{value} stock", language="zh")),
            ("tavily", self.tavily_api_key, self._tavily),
            ("brave", self.brave_api_key, self._brave),
            ("yfinance-news", None, self._yfinance_news),
        ]
        for provider, credential, loader in providers:
            if provider in {"newsapi", "tavily", "brave"} and not credential:
                attempts.append({"provider": provider, "status": "not_configured", "message": f"请在设置页填写 {provider} Key"})
                continue
            try:
                items = loader(symbol)
                if items:
                    normalized = deduplicate_articles(items)[:20]
                    attempts.append({"provider": provider, "status": "ok", "message": f"取得 {len(normalized)} 条"})
                    confidence = "high" if provider == "exchange-announcement" else "medium"
                    return NewsBundle(normalized, quality(provider, "ok", confidence, attempts))
                attempts.append({"provider": provider, "status": "empty", "message": "返回为空或格式不正确"})
            except Exception as exc:
                attempts.append({"provider": provider, "status": "failed", "message": str(exc)[:160]})

        return NewsBundle([], quality("none", "unavailable", "low", attempts, [
            "新闻源不可用；未生成虚构资讯。",
            f"请在设置页补充新闻源 Key，并检查 {symbol} 的交易所公告、财报和监管信息。",
        ]))

    def market_news(self, market: str) -> list[dict]:
        """Return only the news items for a market."""
        return self.market_news_bundle(market).items

    def market_news_bundle(self, market: str) -> NewsBundle:
        """Return market news with fallback attempts and quality metadata."""
        attempts = []
        if self.news_api_key:
            queries = market_news_queries(market)
            collected: list[dict[str, Any]] = []
            for topic, query, language in queries:
                try:
                    found = self._newsapi(query, language=language)
                    for item in found:
                        item["topic"] = topic
                    collected.extend(found)
                    attempts.append({"provider": f"newsapi:{topic}", "status": "ok" if found else "empty", "message": f"取得 {len(found)} 条新闻"})
                except Exception as exc:
                    attempts.append({"provider": f"newsapi:{topic}", "status": "failed", "message": str(exc)[:160]})
            items = deduplicate_news(collected)[:8]
            if items:
                return NewsBundle(items, quality("newsapi", "ok", "medium", attempts, ["新闻按市场、政策/宏观、资金/行业主题分组检索并去重。"] ))
        else:
            attempts.append({"provider": "newsapi", "status": "skipped", "message": "未配置 NewsAPI Key"})

        for provider, credential, loader in (("tavily", self.tavily_api_key, self._tavily), ("brave", self.brave_api_key, self._brave)):
            if not credential:
                attempts.append({"provider": provider, "status": "not_configured", "message": f"请在设置页填写 {provider} Key"})
                continue
            try:
                items = deduplicate_news(loader(f"{label_for_market(market)} stock market"))[:8]
                if items:
                    attempts.append({"provider": provider, "status": "ok", "message": f"取得 {len(items)} 条新闻"})
                    return NewsBundle(items, quality(provider, "ok", "medium", attempts))
                attempts.append({"provider": provider, "status": "empty", "message": "返回为空或格式不正确"})
            except Exception as exc:
                attempts.append({"provider": provider, "status": "failed", "message": str(exc)[:160]})
        return NewsBundle([], quality("none", "unavailable", "low", attempts, ["没有可用的真实新闻源，未生成模板资讯；请在设置页配置新闻源。"] ))

    def _newsapi(self, query: str, language: str = "zh") -> list[dict[str, Any]]:
        """Request and normalize recent articles from NewsAPI."""
        params = urllib.parse.urlencode({"q": query, "language": language, "pageSize": 5, "sortBy": "publishedAt", "apiKey": self.news_api_key})
        with urllib.request.urlopen(f"https://newsapi.org/v2/everything?{params}", timeout=self.timeout_s) as response:
            payload = json.loads(response.read().decode("utf-8"))
        articles = payload.get("articles") or []
        return [
            {
                "title": item.get("title") or "未命名资讯",
                "summary": item.get("description") or "",
                "source": (item.get("source") or {}).get("name") or "newsapi",
                "date": str(item.get("publishedAt") or "")[:10] or today_cn(),
                "url": item.get("url"),
            }
            for item in articles[:5]
        ]

    def social_sentiment(self, symbol: str, market: str) -> EnrichmentLike:
        """Load lightweight Reddit sentiment for US symbols only."""
        if not self.social_enabled or market != "us":
            return EnrichmentLike({}, quality("reddit", "skipped", "low", [], ["社交情绪未启用或当前市场不适用。"]))
        try:
            req = urllib.request.Request(
                f"https://www.reddit.com/search.json?{urllib.parse.urlencode({'q': symbol, 'sort': 'new', 'limit': 20, 't': 'week'})}",
                headers={"User-Agent": "trading-journal/0.2"},
            )
            with urllib.request.urlopen(req, timeout=self.timeout_s) as response:
                children = json.loads(response.read().decode("utf-8")).get("data", {}).get("children", [])
            titles = [str(item.get("data", {}).get("title", "")) for item in children]
            positive = sum(any(word in title.lower() for word in ("buy", "bull", "beat", "growth", "upgrade")) for title in titles)
            negative = sum(any(word in title.lower() for word in ("sell", "bear", "miss", "risk", "downgrade")) for title in titles)
            score = round(50 + (positive - negative) / max(1, len(titles)) * 50, 1)
            data = {"score": max(0, min(100, score)), "mentions": len(titles), "positive": positive, "negative": negative, "window": "7d"}
            return EnrichmentLike(data, quality("reddit", "ok", "low", [{"provider": "reddit", "status": "ok", "message": f"取得 {len(titles)} 条讨论"}], ["社交情绪仅作低权重辅助证据。"]))
        except Exception as exc:
            return EnrichmentLike({}, quality("reddit", "unavailable", "low", [{"provider": "reddit", "status": "failed", "message": str(exc)[:160]}]))

    def _tavily(self, symbol: str) -> list[dict[str, Any]]:
        if not self.tavily_api_key:
            return []
        payload = json.dumps({"api_key": self.tavily_api_key, "query": f"{symbol} stock latest news announcement earnings", "topic": "news", "max_results": 8}).encode()
        req = urllib.request.Request("https://api.tavily.com/search", data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout_s) as response:
            data = json.loads(response.read().decode())
        return [{"title": item.get("title"), "source": "tavily", "date": str(item.get("published_date") or today_cn())[:10], "url": item.get("url"), "kind": "news"} for item in data.get("results", []) if item.get("title")]

    def _brave(self, symbol: str) -> list[dict[str, Any]]:
        if not self.brave_api_key:
            return []
        params = urllib.parse.urlencode({"q": f"{symbol} stock announcement earnings", "count": 8, "freshness": "pw"})
        req = urllib.request.Request(f"https://api.search.brave.com/res/v1/web/search?{params}", headers={"X-Subscription-Token": self.brave_api_key, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout_s) as response:
            data = json.loads(response.read().decode())
        return [{"title": item.get("title"), "source": "brave", "date": str(item.get("age") or today_cn())[:10], "url": item.get("url"), "kind": "news"} for item in data.get("web", {}).get("results", []) if item.get("title")]

    def _yfinance_news(self, symbol: str) -> list[dict[str, Any]]:
        import yfinance as yf
        from engine.data.normalize import normalize_symbol
        data = yf.Ticker(normalize_symbol(symbol).provider_code).news or []
        output = []
        for item in data[:8]:
            content = item.get("content", item)
            output.append({"title": content.get("title"), "source": (content.get("provider") or {}).get("displayName", "yfinance"), "date": str(content.get("pubDate") or today_cn())[:10], "url": (content.get("canonicalUrl") or {}).get("url"), "kind": "news"})
        return [item for item in output if item.get("title")]

    def _announcements(self, symbol: str) -> list[dict[str, Any]]:
        from engine.data.normalize import normalize_symbol
        normalized = normalize_symbol(symbol)
        if normalized.market == "us":
            return self._sec_filings(normalized.display)
        if normalized.market != "cn":
            return []
        import akshare as ak
        frame = ak.stock_zh_a_disclosure_report_cninfo(symbol=normalized.display[2:], market="沪深京", category="")
        if frame is None or frame.empty:
            return []
        output = []
        for _, row in frame.head(10).iterrows():
            output.append({"title": row.get("公告标题"), "source": "cninfo", "date": str(row.get("公告时间") or today_cn())[:10], "url": row.get("公告链接"), "kind": "announcement"})
        return [item for item in output if item.get("title")]

    def _sec_filings(self, ticker: str) -> list[dict[str, Any]]:
        """Load recent official SEC filing entries for a US ticker."""
        params = urllib.parse.urlencode({"action": "getcompany", "CIK": ticker, "type": "8-K,10-Q,10-K", "owner": "exclude", "count": 10, "output": "atom"})
        req = urllib.request.Request(
            f"https://www.sec.gov/cgi-bin/browse-edgar?{params}",
            headers={"User-Agent": "trading-journal research contact@example.invalid"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout_s) as response:
            root = ET.fromstring(response.read())
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        output = []
        for entry in root.findall("atom:entry", ns):
            link = entry.find("atom:link", ns)
            output.append({
                "title": entry.findtext("atom:title", default="SEC filing", namespaces=ns),
                "source": "sec-edgar",
                "date": str(entry.findtext("atom:updated", default=today_cn(), namespaces=ns))[:10],
                "url": link.get("href") if link is not None else None,
                "kind": "announcement",
            })
        return output


@dataclass
class EnrichmentLike:
    data: dict[str, Any]
    quality: dict[str, Any]


def quality(source: str, status: str, confidence: str, attempts: list[dict[str, str]], notes: list[str] | None = None) -> dict[str, Any]:
    """Build the common source-quality payload used by news responses."""
    return {"source": source, "status": status, "confidence": confidence, "attempts": attempts, "notes": notes or []}


def market_news_queries(market: str) -> list[tuple[str, str, str]]:
    """Return focused market-review queries instead of one overly broad query."""
    return {
        "cn": [
            ("market", "A股 OR 沪深股市", "zh"),
            ("macro_policy", "中国 央行 OR 证监会 OR 财政 政策 股市", "zh"),
            ("liquidity_sector", "A股 成交额 OR 板块 资金 主线", "zh"),
        ],
        "hk": [
            ("market", "港股 OR 恒生指数", "zh"),
            ("macro_policy", "香港 金融市场 OR 中国政策 港股", "zh"),
            ("liquidity_sector", "港股 南向资金 OR 科技股 板块", "zh"),
        ],
        "us": [
            ("market", "US stock market OR S&P 500 OR Nasdaq", "en"),
            ("macro_policy", "Federal Reserve OR US inflation OR Treasury yields stocks", "en"),
            ("liquidity_sector", "Wall Street sector rotation OR VIX market breadth", "en"),
        ],
    }.get(market, [("market", f"{market} stock market", "en")])


def label_for_market(market: str) -> str:
    """Return a search label for a normalized market code."""
    return {"cn": "A股", "hk": "港股", "us": "US"}.get(market, market)


def deduplicate_news(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate articles by URL or normalized title while preserving query order."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in items:
        key = str(item.get("url") or "").strip() or " ".join(str(item.get("title") or "").lower().split())
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def classify_intelligence(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Deterministically classify article titles while preserving source facts."""
    risk_words = ("风险", "处罚", "调查", "诉讼", "亏损", "下调", "减持", "违约", "召回")
    catalyst_words = ("增长", "中标", "回购", "增持", "上调", "突破", "合作", "获批", "盈利")
    earnings_words = ("财报", "业绩", "营收", "利润", "earnings", "revenue")
    risks, catalysts, earnings = [], [], []
    for item in items:
        title = str(item.get("title", "")).lower()
        if any(word in title for word in risk_words):
            risks.append(item)
        if any(word in title for word in catalyst_words):
            catalysts.append(item)
        if any(word in title for word in earnings_words):
            earnings.append(item)
    return {
        "items": items,
        "risk_events": risks,
        "catalysts": catalysts,
        "earnings_expectations": earnings,
        "metrics": {
            "news_count": len(items),
            "risk_event_count": len(risks),
            "catalyst_count": len(catalysts),
            "earnings_news_count": len(earnings),
        },
    }


def deduplicate_articles(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate articles by normalized title while retaining provider order."""
    out, seen = [], set()
    for item in items:
        title = "".join(str(item.get("title", "")).lower().split())
        if not title or title in seen:
            continue
        seen.add(title)
        out.append(item)
    return out
