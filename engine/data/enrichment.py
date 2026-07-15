from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
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
        """Return a realtime quote from Yahoo's cookie-free chart metadata."""
        try:
            meta = self._yahoo_chart_meta(symbol)
            price = safe_number(meta.get("regularMarketPrice"))
            previous = safe_number(meta.get("chartPreviousClose") or meta.get("previousClose"))
            if not price:
                raise RuntimeError("实时价格为空")
            stamp = meta.get("regularMarketTime")
            data = {
                "symbol": symbol.display,
                "name": meta.get("longName") or meta.get("shortName") or symbol.display,
                "price": price,
                "previous_close": previous,
                "change_pct": round((price / previous - 1) * 100, 2) if previous else None,
                "high": safe_number(meta.get("regularMarketDayHigh")),
                "low": safe_number(meta.get("regularMarketDayLow")),
                "volume": safe_number(meta.get("regularMarketVolume")),
                "fifty_two_week_high": safe_number(meta.get("fiftyTwoWeekHigh")),
                "fifty_two_week_low": safe_number(meta.get("fiftyTwoWeekLow")),
                "as_of": datetime.fromtimestamp(stamp, timezone.utc).astimezone().isoformat() if stamp else now_cn_text(),
                "is_partial_bar": True,
                "is_stale": False,
            }
            return EnrichmentBundle(data, quality("yahoo-chart", "ok", "high", "实时行情已取得"))
        except Exception as exc:
            return EnrichmentBundle({}, quality("yahoo-chart", "unavailable", "low", compact_error(exc)))

    def fundamentals(self, symbol: Symbol) -> EnrichmentBundle:
        """Return a compact cross-market fundamental snapshot through yfinance."""
        if symbol.market == "hk":
            return self._hk_fundamentals(symbol)
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

    def _hk_fundamentals(self, symbol: Symbol) -> EnrichmentBundle:
        """Load Hong Kong fundamentals through AkShare's dedicated F10 APIs."""
        try:
            import akshare as ak

            code = symbol.provider_code.split(".")[0].zfill(5)
            latest = ak.stock_hk_financial_indicator_em(symbol=code)
            annual = ak.stock_financial_hk_analysis_indicator_em(symbol=code, indicator="年度")
            profile = ak.stock_hk_company_profile_em(symbol=code)
            if latest is None or latest.empty:
                raise RuntimeError("港股核心财务指标为空")
            row = latest.iloc[0]
            annual_row = annual.iloc[0] if annual is not None and not annual.empty else {}
            profile_row = profile.iloc[0] if profile is not None and not profile.empty else {}
            data = {
                "valuation": compact({
                    "pe_ttm": safe_number(row.get("市盈率")),
                    "pb": safe_number(row.get("市净率")),
                    "market_cap": safe_number(row.get("港股市值(港元)")),
                    "dividend_yield": percent_ratio(row.get("股息率TTM(%)")),
                }),
                "growth": compact({
                    "revenue_yoy": percent_ratio(annual_row.get("OPERATE_INCOME_YOY")),
                    "profit_yoy": percent_ratio(annual_row.get("HOLDER_PROFIT_YOY")),
                }),
                "quality": compact({
                    "roe": percent_ratio(row.get("股东权益回报率(%)")),
                    "net_margin": percent_ratio(row.get("销售净利率(%)")),
                    "roa": percent_ratio(row.get("总资产回报率(%)")),
                    "operating_cashflow_per_share": safe_number(row.get("每股经营现金流(元)")),
                }),
                "industry": compact({"sector": profile_row.get("所属行业")}),
                "company": compact({"name": profile_row.get("公司名称") or annual_row.get("SECURITY_NAME_ABBR")}),
                "as_of": str(annual_row.get("REPORT_DATE") or now_cn_text())[:10],
            }
            coverage = sum(bool(data.get(key)) for key in ("valuation", "growth", "quality", "industry", "company"))
            return EnrichmentBundle(data, quality("akshare-hk-f10", "ok" if coverage >= 3 else "partial", "high" if coverage >= 4 else "medium", f"覆盖 {coverage}/5 个基本面分组"))
        except Exception as exc:
            return EnrichmentBundle({}, quality("akshare-hk-f10", "unavailable", "low", compact_error(exc)))

    def _yahoo_chart_meta(self, symbol: Symbol) -> dict[str, Any]:
        ticker = urllib.parse.quote(symbol.provider_code, safe="")
        request = urllib.request.Request(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=5d&interval=1d",
            headers={"User-Agent": "Mozilla/5.0 (TradingJournal/0.2)"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
            payload = json.loads(response.read().decode("utf-8"))
        results = ((payload.get("chart") or {}).get("result") or [])
        return (results[0].get("meta") or {}) if results else {}

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


def percent_ratio(value: Any) -> float | None:
    """Convert provider percentage points to the ratio convention used by reports."""
    number = safe_number(value)
    return round(number / 100, 6) if number is not None else None


def compact_error(exc: Exception) -> str:
    return str(exc).replace("\n", " ")[:160] or type(exc).__name__
