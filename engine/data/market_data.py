from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Any, Callable

from .normalize import Symbol, normalize_symbol


@dataclass
class Bar:
    """One normalized OHLCV price bar."""
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class Quote:
    """Latest normalized quote presented to analysis consumers."""
    symbol: str
    market: str
    name: str
    price: float
    change_pct: float
    currency: str
    source: str


@dataclass
class ProviderAttempt:
    """Outcome of one provider attempt in the fallback chain."""
    provider: str
    status: str
    message: str = ""


@dataclass
class DataQuality:
    """Provenance, confidence, and fallback details for market data."""
    source: str
    status: str
    confidence: str
    attempts: list[ProviderAttempt]
    notes: list[str]


@dataclass
class HistoryBundle:
    """Normalized price history paired with quality metadata."""
    bars: list[Bar]
    quality: DataQuality


class MarketData:
    """Load market data through an ordered provider fallback chain."""
    def __init__(self, provider_order: str | list[str] = "auto", api_keys: dict[str, str] | None = None, timeout_s: float = 8):
        """Configure provider priority, credentials, and network timeout."""
        self.provider_order = parse_provider_order(provider_order)
        self.api_keys = api_keys or {}
        self.timeout_s = timeout_s
        self.last_quality: dict[str, DataQuality] = {}

    def history(self, symbol_or_code: Symbol | str, days: int = 260) -> list[Bar]:
        """Return normalized history bars without quality metadata."""
        return self.history_bundle(symbol_or_code, days).bars

    def history_bundle(self, symbol_or_code: Symbol | str, days: int = 260) -> HistoryBundle:
        """Try compatible real providers in capability order, never synthetic data."""
        symbol = symbol_or_code if isinstance(symbol_or_code, Symbol) else normalize_symbol(symbol_or_code)
        attempts: list[ProviderAttempt] = []
        # A provider is accepted only when it returns enough bars for the
        # downstream moving averages; otherwise the next provider is tried.
        for provider in self.providers_for(symbol):
            missing = self.missing_configuration(provider)
            if missing:
                attempts.append(ProviderAttempt(provider, "not_configured", missing))
                continue
            loader = self.loader_for(provider)
            if loader is None:
                attempts.append(ProviderAttempt(provider, "skipped", "当前版本未启用该数据源"))
                continue
            try:
                bars = loader(symbol, days)
                if len(bars) >= 30:
                    quality = DataQuality(provider, "ok", "high", attempts + [ProviderAttempt(provider, "ok", f"取得 {len(bars)} 根K线")], [])
                    self.last_quality[symbol.display] = quality
                    return HistoryBundle(bars[-days:], quality)
                attempts.append(ProviderAttempt(provider, "empty", f"仅返回 {len(bars)} 根K线，至少需要 30 根"))
            except Exception as exc:
                attempts.append(ProviderAttempt(provider, "failed", compact_error(exc)))

        quality = DataQuality(
            "none",
            "unavailable",
            "low",
            attempts,
            ["没有可用的真实行情源，未生成样本数据。", provider_advice(attempts)],
        )
        self.last_quality[symbol.display] = quality
        return HistoryBundle([], quality)

    def quote(self, symbol_or_code: Symbol | str) -> Quote:
        """Return the latest quote derived from normalized history."""
        symbol = symbol_or_code if isinstance(symbol_or_code, Symbol) else normalize_symbol(symbol_or_code)
        bundle = self.history_bundle(symbol, 260)
        bars = bundle.bars
        if len(bars) < 2:
            raise ValueError(bundle.quality.notes[-1])
        last = bars[-1]
        prev = bars[-2]
        currency = {"cn": "CNY", "hk": "HKD", "us": "USD"}[symbol.market]
        return Quote(symbol.display, symbol.market, symbol.display, round(last.close, 3), round((last.close / prev.close - 1) * 100, 2), currency, bundle.quality.source)

    def quote_with_quality(self, symbol_or_code: Symbol | str) -> tuple[Quote, DataQuality]:
        """Return the latest quote together with its source-quality metadata."""
        symbol = symbol_or_code if isinstance(symbol_or_code, Symbol) else normalize_symbol(symbol_or_code)
        bundle = self.history_bundle(symbol, 260)
        bars = bundle.bars
        if len(bars) < 2:
            raise ValueError(bundle.quality.notes[-1])
        last = bars[-1]
        prev = bars[-2]
        currency = {"cn": "CNY", "hk": "HKD", "us": "USD"}[symbol.market]
        quote = Quote(symbol.display, symbol.market, symbol.display, round(last.close, 3), round((last.close / prev.close - 1) * 100, 2), currency, bundle.quality.source)
        return quote, bundle.quality

    def market_snapshot(self, market: str) -> dict:
        """Build a market-wide snapshot from representative index histories."""
        symbols = {
            "cn": [("SH000001", True), ("SZ399001", True), ("SZ399006", True), ("SH000300", True)],
            "hk": [("HK800000", True), ("HK800700", True), ("HK800100", True), ("HK00700", False), ("HK09988", False)],
            "us": [("SPY", True), ("QQQ", True), ("DIA", True), ("VIXY", True), ("TLT", True), ("UUP", True), ("AAPL", False), ("MSFT", False), ("NVDA", False)],
        }.get(market, [("SPY", True)])
        indices: list[dict[str, Any]] = []
        leaders_universe: list[dict[str, Any]] = []
        qualities: list[dict[str, Any]] = []
        for code, is_index in symbols:
            normalized = normalize_symbol(code)
            bundle = self.history_bundle(normalized)
            qualities.append(quality_to_dict(bundle.quality))
            if len(bundle.bars) < 2:
                continue
            last, prev = bundle.bars[-1], bundle.bars[-2]
            currency = {"cn": "CNY", "hk": "HKD", "us": "USD"}[normalized.market]
            quote = asdict(Quote(normalized.display, normalized.market, normalized.display, round(last.close, 3), round((last.close / prev.close - 1) * 100, 2), currency, bundle.quality.source))
            (indices if is_index else leaders_universe).append(quote)
        leaders_universe = leaders_universe or indices
        scores = [max(0, min(100, 50 + item["change_pct"] * 8)) for item in indices]
        breadth = synthetic_breadth(market, scores) if scores else {"advancers": 0, "decliners": 0, "limit_up": None, "limit_down": None, "turnover_billion": None, "basis": "unavailable", "is_estimated": False}
        sector_rotation = synthetic_sector_rotation(market, scores, leaders_universe) if scores else {"leaders": [], "laggards": [], "basis": "unavailable", "is_estimated": False}
        return {
            "market": market,
            "indices": indices,
            "breadth": breadth,
            "sector_rotation": sector_rotation,
            "watch_assets": leaders_universe,
            "data_quality": combine_quality(qualities),
        }

    def providers_for(self, symbol: Symbol) -> list[str]:
        """Return configured providers that support the symbol's market."""
        selected = self.provider_order
        if selected == ["auto"]:
            selected = ["yahoo", "akshare", "alpha_vantage"] if symbol.market == "cn" else ["yahoo", "alpha_vantage"]
        allowed = {
            "cn": {"akshare", "yahoo", "alpha_vantage"},
            "hk": {"yahoo", "alpha_vantage"},
            "us": {"yahoo", "alpha_vantage"},
        }[symbol.market]
        return [item for item in selected if item in allowed]

    def missing_configuration(self, provider: str) -> str | None:
        """Return the required setting that is absent before attempting a call."""
        required = {"alpha_vantage": ("alpha_vantage_key", "请在设置中填写 Alpha Vantage Key")}
        item = required.get(provider)
        return item[1] if item and not self.api_keys.get(item[0], "").strip() else None

    def loader_for(self, provider: str) -> Callable[[Symbol, int], list[Bar]] | None:
        """Resolve a provider name to its history-loading method."""
        return {
            "akshare": self._load_akshare,
            "yahoo": self._load_yahoo,
            "alpha_vantage": self._load_alpha_vantage,
        }.get(provider)

    def _load_yahoo(self, symbol: Symbol, days: int) -> list[Bar]:
        """Load Yahoo's public chart JSON without cookie/crumb rate-limit state."""
        ticker = urllib.parse.quote(symbol.provider_code, safe="")
        query = urllib.parse.urlencode({"range": f"{max(3, (days * 2 + 364) // 365)}y", "interval": "1d", "events": "history"})
        request = urllib.request.Request(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?{query}",
            headers={"User-Agent": "Mozilla/5.0 (TradingJournal/0.2)"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
            payload = json.loads(response.read().decode("utf-8"))
        result = ((payload.get("chart") or {}).get("result") or [])
        if not result:
            return []
        result = result[0]
        timestamps = result.get("timestamp") or []
        quote = (((result.get("indicators") or {}).get("quote") or [{}])[0])
        bars: list[Bar] = []
        for idx, stamp in enumerate(timestamps):
            close = safe_float(value_at(quote.get("close"), idx))
            if close <= 0:
                continue
            day = __import__("datetime").datetime.fromtimestamp(stamp, __import__("datetime").timezone.utc).date().isoformat()
            bars.append(Bar(day, safe_float(value_at(quote.get("open"), idx) or close), safe_float(value_at(quote.get("high"), idx) or close), safe_float(value_at(quote.get("low"), idx) or close), close, safe_float(value_at(quote.get("volume"), idx))))
        return bars[-days:]

    def _load_akshare(self, symbol: Symbol, days: int) -> list[Bar]:
        """Load and normalize history through AkShare."""
        if symbol.market != "cn":
            return []
        import akshare as ak

        code = symbol.display[2:]
        frame = ak.stock_zh_a_hist(symbol=code, period="daily", adjust="qfq").tail(days)
        bars: list[Bar] = []
        for _, row in frame.iterrows():
            bars.append(
                Bar(
                    str(row.get("日期") or row.get("date")),
                    safe_float(row.get("开盘")),
                    safe_float(row.get("最高")),
                    safe_float(row.get("最低")),
                    safe_float(row.get("收盘")),
                    safe_float(row.get("成交量")),
                )
            )
        return [bar for bar in bars if bar.close > 0]

    def _load_alpha_vantage(self, symbol: Symbol, days: int) -> list[Bar]:
        """Load and normalize daily history through Alpha Vantage."""
        key = self.api_keys.get("alpha_vantage_key", "").strip()
        if not key:
            raise RuntimeError("未配置 Alpha Vantage Key")
        query = urllib.parse.urlencode({"function": "TIME_SERIES_DAILY_ADJUSTED", "symbol": symbol.provider_code, "outputsize": "full", "apikey": key})
        with urllib.request.urlopen(f"https://www.alphavantage.co/query?{query}", timeout=self.timeout_s) as response:
            payload = json.loads(response.read().decode("utf-8"))
        series = payload.get("Time Series (Daily)") or {}
        bars = []
        for day, row in sorted(series.items())[-days:]:
            bars.append(Bar(day, safe_float(row.get("1. open")), safe_float(row.get("2. high")), safe_float(row.get("3. low")), safe_float(row.get("4. close")), safe_float(row.get("6. volume"))))
        return bars


def parse_provider_order(value: str | list[str]) -> list[str]:
    """Normalize provider configuration into a distinct ordered name list."""
    if isinstance(value, list):
        raw = value
    else:
        text = str(value or "auto").strip().lower()
        raw = [part.strip() for part in text.split(",")] if "," in text else [text]
    allowed = {"auto", "akshare", "yahoo", "alpha_vantage"}
    out = [item for item in raw if item in allowed]
    return out or ["auto"]


def safe_float(value: Any) -> float:
    """Convert provider values to float while treating missing values as zero."""
    try:
        if hasattr(value, "item"):
            value = value.item()
        return float(value or 0)
    except Exception:
        return 0.0


def value_at(values: list[Any] | None, index: int) -> Any:
    """Safely read a provider array that may be absent or shorter than timestamps."""
    return values[index] if values and index < len(values) else None


def yfinance_date_window(days: int, today: date | None = None) -> tuple[str, str]:
    """Build a calendar window instead of unsupported arbitrary period strings."""
    end_day = (today or date.today()) + timedelta(days=1)
    start_day = end_day - timedelta(days=max(days * 2, 90))
    return start_day.isoformat(), end_day.isoformat()


def compact_error(exc: Exception) -> str:
    """Return a short single-line provider error suitable for quality metadata."""
    text = str(exc).strip() or exc.__class__.__name__
    return text[:160]


def provider_advice(attempts: list[ProviderAttempt]) -> str:
    """Build an actionable report note from provider failures."""
    missing = [item.provider for item in attempts if item.status == "not_configured"]
    failed = [item.provider for item in attempts if item.status in {"failed", "empty"}]
    parts = []
    if missing:
        parts.append(f"请在设置页补充凭据：{', '.join(missing)}")
    if failed:
        parts.append(f"请检查网络、额度或服务返回：{', '.join(failed)}")
    return "；".join(parts) or "请在设置页配置并检查至少一个受支持的真实数据源。"


def synthetic_breadth(market: str, scores: list[float]) -> dict:
    """Derive a stable breadth estimate from representative asset scores."""
    avg = sum(scores) / len(scores)
    total = {"cn": 5200, "hk": 2500, "us": 5000}.get(market, 3000)
    advancers = int(total * max(0.2, min(0.8, avg / 100)))
    return {
        "advancers": advancers,
        "decliners": total - advancers,
        "limit_up": int(advancers * 0.018) if market == "cn" else None,
        "limit_down": int((total - advancers) * 0.006) if market == "cn" else None,
        "turnover_billion": round(total * (0.8 + avg / 100) / 10, 2),
        "basis": "representative_asset_estimate",
        "is_estimated": True,
    }


def synthetic_sector_rotation(market: str, scores: list[float], assets: list[dict[str, Any]]) -> dict:
    """Construct a deterministic sector-rotation view from snapshot scores."""
    base = {
        "cn": ["AI硬件", "券商", "新能源", "消费", "医药", "地产"],
        "hk": ["互联网", "生物科技", "地产", "金融", "能源", "消费"],
        "us": ["半导体", "软件", "金融", "能源", "公用事业", "小盘股"],
    }.get(market, ["科技", "金融", "能源", "防御板块"])
    avg = sum(scores) / len(scores)
    ranked = sorted(assets, key=lambda item: item.get("change_pct", 0), reverse=True)
    leaders = [item["symbol"] for item in ranked[:2]] + base[:2]
    laggards = [item["symbol"] for item in ranked[-2:]] + base[-2:]
    if avg < 45:
        leaders = base[-3:]
    return {
        "leaders": list(dict.fromkeys(leaders))[:4],
        "laggards": list(dict.fromkeys(laggards))[:4],
        "basis": "representative_assets_and_market_template",
        "is_estimated": True,
    }


def quality_to_dict(quality: DataQuality) -> dict[str, Any]:
    """Serialize data-quality dataclasses into a JSON-compatible dictionary."""
    return {
        "source": quality.source,
        "status": quality.status,
        "confidence": quality.confidence,
        "attempts": [asdict(item) for item in quality.attempts],
        "notes": quality.notes,
    }


def combine_quality(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate asset quality records into a market-level quality summary."""
    statuses = {item.get("status") for item in items}
    confidences = {item.get("confidence") for item in items}
    return {
        "status": "unavailable" if items and statuses == {"unavailable"} else "partial" if "unavailable" in statuses else "ok",
        "confidence": "low" if "low" in confidences else "high",
        "sources": list(dict.fromkeys(str(item.get("source")) for item in items)),
        "items": items,
    }
