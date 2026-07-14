from engine.data.market_data import Bar


def sma(values: list[float], window: int) -> float:
    """Calculate a simple moving average over the available trailing window."""
    sample = values[-window:]
    return sum(sample) / len(sample)


def trend_indicators(bars: list[Bar]) -> dict:
    """Calculate moving averages and classify the prevailing price trend."""
    closes = [bar.close for bar in bars]
    ma5 = sma(closes, min(5, len(closes)))
    ma10 = sma(closes, min(10, len(closes)))
    ma20 = sma(closes, min(20, len(closes)))
    ma60 = sma(closes, min(60, len(closes)))
    ma120 = sma(closes, min(120, len(closes)))
    close = closes[-1]
    ma5_cross = crossed_above(closes, 5, 10, 3)
    ma10_cross = crossed_above(closes, 10, 20, 3)
    return {
        "close": round(close, 3),
        "ma5": round(ma5, 3),
        "ma10": round(ma10, 3),
        "ma20": round(ma20, 3),
        "ma60": round(ma60, 3),
        "ma120": round(ma120, 3),
        "above_ma5": close >= ma5,
        "above_ma10": close >= ma10,
        "above_ma20": close >= ma20,
        "above_ma60": close >= ma60,
        "above_ma120": close >= ma120,
        "bullish_alignment": ma5 >= ma10 >= ma20,
        "distance_to_ma5_pct": round(abs(close / ma5 - 1) * 100, 2) if ma5 else 0,
        "distance_to_ma10_pct": round(abs(close / ma10 - 1) * 100, 2) if ma10 else 0,
        "distance_to_ma20_pct": round(abs(close / ma20 - 1) * 100, 2) if ma20 else 0,
        "near_pullback_ma5_or_ma10": abs(close / ma5 - 1) * 100 <= 1 or abs(close / ma10 - 1) * 100 <= 2,
        "ma5_cross_above_ma10_3d": ma5_cross,
        "ma10_cross_above_ma20_3d": ma10_cross,
        "golden_cross_3d": ma5_cross or ma10_cross,
        "ma20_slope_pct": round((ma20 / sma(closes[:-5], min(20, len(closes[:-5]))) - 1) * 100, 2) if len(closes) > 25 else 0,
    }


def crossed_above(values: list[float], fast_window: int, slow_window: int, lookback: int) -> bool:
    """Return whether a fast SMA crossed above a slow SMA recently."""
    start = max(slow_window, len(values) - lookback)
    for end in range(start, len(values)):
        previous = values[:end]
        current = values[: end + 1]
        if sma(previous, fast_window) <= sma(previous, slow_window) and sma(current, fast_window) > sma(current, slow_window):
            return True
    return False
