from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.data.normalize import Symbol
from engine.time_utils import now_cn_text


@dataclass
class EnrichmentBundle:
    """Optional external data paired with a common quality contract."""

    data: dict[str, Any]
    quality: dict[str, Any]


class EnrichmentData:
    """Load optional realtime and fundamental data without blocking core analysis."""

    def __init__(self, timeout_s: float = 8):
        self.timeout_s = timeout_s

    def realtime_quote(self, symbol: Symbol) -> EnrichmentBundle:
        """Return a realtime quote when yfinance supports the symbol."""
        try:
            import yfinance as yf

            ticker = yf.Ticker(symbol.provider_code)
            fast = ticker.fast_info
            price = safe_number(fast.get("last_price"))
            previous = safe_number(fast.get("previous_close"))
            if not price:
                raise RuntimeError("实时价格为空")
            data = {
                "symbol": symbol.display,
                "name": symbol.display,
                "price": price,
                "previous_close": previous,
                "change_pct": round((price / previous - 1) * 100, 2) if previous else None,
                "open": safe_number(fast.get("open")),
                "high": safe_number(fast.get("day_high")),
                "low": safe_number(fast.get("day_low")),
                "volume": safe_number(fast.get("last_volume")),
                "market_cap": safe_number(fast.get("market_cap")),
                "as_of": now_cn_text(),
                "is_partial_bar": True,
                "is_stale": False,
            }
            return EnrichmentBundle(data, quality("yfinance", "ok", "medium", "实时行情已取得"))
        except Exception as exc:
            return EnrichmentBundle({}, quality("yfinance", "unavailable", "low", compact_error(exc)))

    def fundamentals(self, symbol: Symbol) -> EnrichmentBundle:
        """Return a compact cross-market fundamental snapshot through yfinance."""
        try:
            import yfinance as yf

            info = yf.Ticker(symbol.provider_code).info or {}
            data = {
                "valuation": compact({
                    "pe_ttm": info.get("trailingPE"),
                    "pe_forward": info.get("forwardPE"),
                    "pb": info.get("priceToBook"),
                    "ps": info.get("priceToSalesTrailing12Months"),
                    "market_cap": info.get("marketCap"),
                }),
                "growth": compact({
                    "revenue_yoy": info.get("revenueGrowth"),
                    "profit_yoy": info.get("earningsGrowth"),
                }),
                "quality": compact({
                    "roe": info.get("returnOnEquity"),
                    "gross_margin": info.get("grossMargins"),
                    "operating_margin": info.get("operatingMargins"),
                    "operating_cashflow": info.get("operatingCashflow"),
                }),
                "earnings": compact({"next_earnings_timestamp": info.get("earningsTimestamp")}),
                "industry": compact({"sector": info.get("sector"), "industry": info.get("industry")}),
                "company": compact({"name": info.get("longName") or info.get("shortName")}),
                "as_of": now_cn_text(),
            }
            coverage = sum(bool(data.get(key)) for key in ("valuation", "growth", "quality", "earnings", "industry"))
            if not coverage:
                raise RuntimeError("基本面字段为空")
            confidence = "medium" if coverage >= 3 else "low"
            return EnrichmentBundle(data, quality("yfinance", "ok" if coverage >= 3 else "partial", confidence, f"覆盖 {coverage}/5 个基本面分组"))
        except Exception as exc:
            return EnrichmentBundle({}, quality("yfinance", "unavailable", "low", compact_error(exc)))

    def chip_distribution(self, symbol: Symbol) -> EnrichmentBundle:
        """Load real A-share chip distribution when AkShare exposes it."""
        if symbol.market != "cn":
            return EnrichmentBundle({}, quality("akshare-cyq", "not_supported", "low", "当前市场暂无真实筹码接口"))
        try:
            import akshare as ak
            frame = ak.stock_cyq_em(symbol=symbol.display[2:], adjust="qfq")
            if frame is None or frame.empty:
                raise RuntimeError("筹码分布为空")
            row = frame.iloc[-1]
            data = compact({
                "date": str(row.get("日期") or "")[:10],
                "profit_position_pct": safe_number(row.get("获利比例")),
                "avg_cost": safe_number(row.get("平均成本")),
                "concentration_90": safe_number(row.get("90成本-集中度")),
                "concentration_70": safe_number(row.get("70成本-集中度")),
                "source_type": "real_distribution",
            })
            if len(data) <= 2:
                raise RuntimeError("筹码关键字段为空")
            return EnrichmentBundle(data, quality("akshare-cyq", "ok", "medium", "真实筹码分布已取得"))
        except Exception as exc:
            return EnrichmentBundle({}, quality("akshare-cyq", "unavailable", "low", compact_error(exc)))


def quality(source: str, status: str, confidence: str, message: str) -> dict[str, Any]:
    """Build the shared quality shape used by enrichment providers."""
    return {
        "source": source,
        "status": status,
        "confidence": confidence,
        "as_of": now_cn_text(),
        "attempts": [{"provider": source, "status": status, "message": message}],
        "notes": [] if status == "ok" else [message],
    }


def compact(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value not in (None, "", [])}


def safe_number(value: Any) -> float | None:
    try:
        number = float(value)
        return round(number, 4)
    except (TypeError, ValueError):
        return None


def compact_error(exc: Exception) -> str:
    return str(exc).replace("\n", " ")[:160] or type(exc).__name__
