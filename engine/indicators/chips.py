from engine.data.market_data import Bar


def chip_indicators(bars: list[Bar]) -> dict:
    """Estimate holding-cost concentration and profit ratios from price history."""
    close = bars[-1].close
    closes = [bar.close for bar in bars[-120:]]
    profitable = sum(1 for value in closes if value <= close)
    concentration = (max(closes) - min(closes)) / close if close else 0
    return {
        "profit_position_pct": round(profitable / len(closes) * 100, 2),
        "cost_concentration": round(concentration * 100, 2),
        "note": "Sampled from recent closes; replace with real chip distribution when a provider supports it.",
    }
