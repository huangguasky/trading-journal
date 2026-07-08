from engine.data.market_data import Bar


def levels_indicators(bars: list[Bar]) -> dict:
    close = bars[-1].close
    lows = [bar.low for bar in bars]
    highs = [bar.high for bar in bars]
    support = min(lows[-20:])
    resistance = max(highs[-20:])
    atr_values = []
    closes = [bar.close for bar in bars]
    for index in range(1, len(bars)):
        atr_values.append(max(bars[index].high - bars[index].low, abs(bars[index].high - closes[index - 1]), abs(bars[index].low - closes[index - 1])))
    atr = sum(atr_values[-14:]) / min(14, len(atr_values))
    return {
        "support_20d": round(support, 3),
        "resistance_20d": round(resistance, 3),
        "distance_to_support_pct": round((close - support) / close * 100, 2),
        "distance_to_resistance_pct": round((resistance - close) / close * 100, 2),
        "atr14": round(atr, 3),
        "atr_pct": round(atr / close * 100, 2),
        "high_52w": round(max(highs[-250:]), 3),
        "low_52w": round(min(lows[-250:]), 3),
    }

