from __future__ import annotations

import json
import math
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Any, Callable

from .normalize import Symbol, normalize_symbol


@dataclass
class Bar:
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class Quote:
    symbol: str
    market: str
    name: str
    price: float
    change_pct: float
    currency: str
    source: str


@dataclass
class ProviderAttempt:
    provider: str
    status: str
    message: str = ""


@dataclass
class DataQuality:
    source: str
    status: str
    confidence: str
    attempts: list[ProviderAttempt]
    notes: list[str]


@dataclass
class HistoryBundle:
    bars: list[Bar]
    quality: DataQuality


class MarketData:
    def __init__(self, provider_order: str | list[str] = "auto", api_keys: dict[str, str] | None = None, timeout_s: float = 8):
        self.provider_order = parse_provider_order(provider_order)
        self.api_keys = api_keys or {}
        self.timeout_s = timeout_s
        self.last_quality: dict[str, DataQuality] = {}

    def history(self, symbol_or_code: Symbol | str, days: int = 260) -> list[Bar]:
        return self.history_bundle(symbol_or_code, days).bars

    def history_bundle(self, symbol_or_code: Symbol | str, days: int = 260) -> HistoryBundle:
        symbol = symbol_or_code if isinstance(symbol_or_code, Symbol) else normalize_symbol(symbol_or_code)
        attempts: list[ProviderAttempt] = []
        for provider in self.providers_for(symbol):
            loader = self.loader_for(provider)
            if loader is None:
                attempts.append(ProviderAttempt(provider, "skipped", "当前版本未启用该数据源"))
                continue
            try:
                bars = loader(symbol, days)
                if len(bars) >= 30:
                    quality = DataQuality(provider, "ok", "high" if provider != "sample" else "low", attempts + [ProviderAttempt(provider, "ok", f"取得 {len(bars)} 根K线")], [])
                    self.last_quality[symbol.display] = quality
                    return HistoryBundle(bars[-days:], quality)
                attempts.append(ProviderAttempt(provider, "empty", "返回数据不足 30 根K线"))
            except Exception as exc:
                attempts.append(ProviderAttempt(provider, "failed", compact_error(exc)))

        bars = sample_history(symbol, days)
        quality = DataQuality(
            "sample",
            "fallback",
            "low",
            attempts + [ProviderAttempt("sample", "ok", "使用本地离线样本补足流程")],
            ["行情源不可用，技术结论只能用于流程演示和结构观察，不宜直接作为交易依据。"],
        )
        self.last_quality[symbol.display] = quality
        return HistoryBundle(bars, quality)

    def quote(self, symbol_or_code: Symbol | str) -> Quote:
        symbol = symbol_or_code if isinstance(symbol_or_code, Symbol) else normalize_symbol(symbol_or_code)
        bundle = self.history_bundle(symbol, 260)
        bars = bundle.bars
        last = bars[-1]
        prev = bars[-2]
        currency = {"cn": "CNY", "hk": "HKD", "us": "USD"}[symbol.market]
        return Quote(symbol.display, symbol.market, symbol.display, round(last.close, 3), round((last.close / prev.close - 1) * 100, 2), currency, bundle.quality.source)

    def quote_with_quality(self, symbol_or_code: Symbol | str) -> tuple[Quote, DataQuality]:
        symbol = symbol_or_code if isinstance(symbol_or_code, Symbol) else normalize_symbol(symbol_or_code)
        bundle = self.history_bundle(symbol, 260)
        bars = bundle.bars
        last = bars[-1]
        prev = bars[-2]
        currency = {"cn": "CNY", "hk": "HKD", "us": "USD"}[symbol.market]
        quote = Quote(symbol.display, symbol.market, symbol.display, round(last.close, 3), round((last.close / prev.close - 1) * 100, 2), currency, bundle.quality.source)
        return quote, bundle.quality

    def market_snapshot(self, market: str) -> dict:
        symbols = {
            "cn": ["000001", "399001", "399006", "000300"],
            "hk": ["HK800000", "HK800700", "HK800100", "HK00700", "HK09988"],
            "us": ["SPY", "QQQ", "DIA", "VIXY", "TLT", "UUP", "AAPL", "MSFT", "NVDA"],
        }.get(market, ["SPY"])
        quotes: list[dict[str, Any]] = []
        qualities: list[dict[str, Any]] = []
        for code in symbols:
            quote, quality = self.quote_with_quality(code)
            quotes.append(asdict(quote))
            qualities.append(quality_to_dict(quality))
        index_count = {"cn": 4, "hk": 3, "us": 6}.get(market, 3)
        indices = quotes[:index_count]
        leaders_universe = quotes[index_count:] or quotes
        scores = [max(0, min(100, 50 + item["change_pct"] * 8)) for item in indices]
        breadth = synthetic_breadth(market, scores)
        sector_rotation = synthetic_sector_rotation(market, scores, leaders_universe)
        return {
            "market": market,
            "indices": indices,
            "breadth": breadth,
            "sector_rotation": sector_rotation,
            "watch_assets": leaders_universe,
            "data_quality": combine_quality(qualities),
        }

    def providers_for(self, symbol: Symbol) -> list[str]:
        selected = self.provider_order
        if selected == ["auto"]:
            selected = ["tushare", "akshare", "yfinance", "alpha_vantage", "sample"]
        if selected == ["sample"]:
            return ["sample"]
        allowed = {
            "cn": {"tushare", "akshare", "yfinance", "sample"},
            "hk": {"yfinance", "alpha_vantage", "sample"},
            "us": {"yfinance", "alpha_vantage", "sample"},
        }[symbol.market]
        return [item for item in selected if item in allowed] or ["sample"]

    def loader_for(self, provider: str) -> Callable[[Symbol, int], list[Bar]] | None:
        return {
            "akshare": self._load_akshare,
            "yfinance": self._load_yfinance,
            "tushare": self._load_tushare,
            "alpha_vantage": self._load_alpha_vantage,
            "sample": sample_history,
        }.get(provider)

    def _load_yfinance(self, symbol: Symbol, days: int) -> list[Bar]:
        import yfinance as yf

        frame = yf.download(symbol.provider_code, period=f"{max(days, 30)}d", progress=False, auto_adjust=False, threads=False)
        if frame is None or frame.empty:
            return []
        bars: list[Bar] = []
        for idx, row in frame.reset_index().iterrows():
            day = str(row.get("Date") or row.get("Datetime") or idx)[:10]
            close = safe_float(row.get("Close", 0))
            if close <= 0:
                continue
            bars.append(Bar(day, safe_float(row.get("Open", close)), safe_float(row.get("High", close)), safe_float(row.get("Low", close)), close, safe_float(row.get("Volume", 0))))
        return bars

    def _load_akshare(self, symbol: Symbol, days: int) -> list[Bar]:
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

    def _load_tushare(self, symbol: Symbol, days: int) -> list[Bar]:
        token = self.api_keys.get("tushare_token", "").strip()
        if not token:
            raise RuntimeError("未配置 Tushare Token")
        if symbol.market != "cn":
            return []
        import tushare as ts

        pro = ts.pro_api(token)
        code = symbol.provider_code.replace(".SS", ".SH")
        end = date.today().strftime("%Y%m%d")
        start = (date.today() - timedelta(days=max(days * 2, 80))).strftime("%Y%m%d")
        frame = pro.daily(ts_code=code, start_date=start, end_date=end)
        if frame is None or frame.empty:
            return []
        frame = frame.sort_values("trade_date").tail(days)
        return [
            Bar(str(row["trade_date"]), safe_float(row["open"]), safe_float(row["high"]), safe_float(row["low"]), safe_float(row["close"]), safe_float(row.get("vol", 0)))
            for _, row in frame.iterrows()
        ]

    def _load_alpha_vantage(self, symbol: Symbol, days: int) -> list[Bar]:
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
    if isinstance(value, list):
        raw = value
    else:
        text = str(value or "auto").strip().lower()
        raw = [part.strip() for part in text.split(",")] if "," in text else [text]
    allowed = {"auto", "tushare", "akshare", "yfinance", "alpha_vantage", "sample"}
    out = [item for item in raw if item in allowed]
    return out or ["auto"]


def safe_float(value: Any) -> float:
    try:
        if hasattr(value, "item"):
            value = value.item()
        return float(value or 0)
    except Exception:
        return 0.0


def compact_error(exc: Exception) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    return text[:160]


def sample_history(symbol: Symbol, days: int = 260) -> list[Bar]:
    seed = sum(ord(ch) for ch in symbol.display)
    base = 12 + seed % 220
    today = date.today()
    out: list[Bar] = []
    for index in range(days):
        wave = math.sin(index / 8 + seed) * 0.025 + math.cos(index / 21) * 0.015
        drift = ((seed % 15) - 5) * index / days * 0.003
        close = max(1, base * (1 + wave + drift + index * 0.0006))
        high = close * (1.012 + abs(math.sin(index)) * 0.012)
        low = close * (0.988 - abs(math.cos(index)) * 0.01)
        open_ = (high + low) / 2
        out.append(Bar(f"sample-{today - timedelta(days=days-index)}", round(open_, 3), round(high, 3), round(low, 3), round(close, 3), 1_000_000 + seed * 100 + index * 8000))
    return out


def synthetic_breadth(market: str, scores: list[float]) -> dict:
    avg = sum(scores) / len(scores)
    total = {"cn": 5200, "hk": 2500, "us": 5000}.get(market, 3000)
    advancers = int(total * max(0.2, min(0.8, avg / 100)))
    return {
        "advancers": advancers,
        "decliners": total - advancers,
        "limit_up": int(advancers * 0.018) if market == "cn" else None,
        "limit_down": int((total - advancers) * 0.006) if market == "cn" else None,
        "turnover_billion": round(total * (0.8 + avg / 100) / 10, 2),
    }


def synthetic_sector_rotation(market: str, scores: list[float], assets: list[dict[str, Any]]) -> dict:
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
    return {"leaders": list(dict.fromkeys(leaders))[:4], "laggards": list(dict.fromkeys(laggards))[:4]}


def quality_to_dict(quality: DataQuality) -> dict[str, Any]:
    return {
        "source": quality.source,
        "status": quality.status,
        "confidence": quality.confidence,
        "attempts": [asdict(item) for item in quality.attempts],
        "notes": quality.notes,
    }


def combine_quality(items: list[dict[str, Any]]) -> dict[str, Any]:
    statuses = {item.get("status") for item in items}
    confidences = {item.get("confidence") for item in items}
    return {
        "status": "fallback" if "fallback" in statuses else "ok",
        "confidence": "low" if "low" in confidences else "high",
        "sources": list(dict.fromkeys(str(item.get("source")) for item in items)),
        "items": items,
    }
