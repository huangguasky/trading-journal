from __future__ import annotations


def build_stock_evidence(symbol: str, quote: dict, indicators: dict, news: list[dict], strategies: list[dict]) -> dict:
    top_strategy = strategies[0] if strategies else {}
    return {
        "symbol": symbol,
        "price": quote,
        "technical": indicators,
        "news": news,
        "strategy": top_strategy,
        "conflicts": detect_conflicts(indicators, strategies),
    }


def detect_conflicts(indicators: dict, strategies: list[dict]) -> list[str]:
    conflicts: list[str] = []
    if indicators["trend"]["above_ma60"] and indicators["momentum"]["rsi14"] > 78:
        conflicts.append("Trend is positive but RSI is overheated.")
    if indicators["volume"]["volume_ratio_5_20"] < 0.75 and strategies and strategies[0]["stance"] == "positive":
        conflicts.append("Strategy score is positive, but volume confirmation is weak.")
    if indicators["levels"]["atr_pct"] > 6:
        conflicts.append("Volatility is high enough to dominate entry timing.")
    return conflicts

