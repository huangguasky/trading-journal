from engine.data.market_data import Bar


def levels_indicators(bars: list[Bar]) -> dict:
    """Calculate support, resistance, ATR, and range-position levels."""
    close = bars[-1].close
    lows = [bar.low for bar in bars]
    highs = [bar.high for bar in bars]
    support = min(lows[-20:])
    resistance = max(highs[-20:])
    prior_resistance = max(highs[-21:-1])
    range_lows = lows[-60:]
    range_highs = highs[-60:]
    support_60d = min(range_lows)
    resistance_60d = max(range_highs)
    support_touches = sum(1 for value in range_lows if value <= support_60d * 1.02)
    resistance_touches = sum(1 for value in range_highs if value >= resistance_60d * 0.98)
    box_width_pct = (resistance_60d / support_60d - 1) * 100 if support_60d else 0
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
        "breakout_above_prior_20d": close > prior_resistance,
        "support_60d": round(support_60d, 3),
        "resistance_60d": round(resistance_60d, 3),
        "support_touches_60d": support_touches,
        "resistance_touches_60d": resistance_touches,
        "box_width_pct": round(box_width_pct, 2),
        "box_confirmed_60d": support_touches >= 2 and resistance_touches >= 2 and 5 <= box_width_pct <= 25,
        "atr14": round(atr, 3),
        "atr_pct": round(atr / close * 100, 2),
        "high_52w": round(max(highs[-250:]), 3),
        "low_52w": round(min(lows[-250:]), 3),
    }
