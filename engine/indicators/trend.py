from engine.data.market_data import Bar


def sma(values: list[float], window: int) -> float:
    sample = values[-window:]
    return sum(sample) / len(sample)


def trend_indicators(bars: list[Bar]) -> dict:
    closes = [bar.close for bar in bars]
    ma20 = sma(closes, min(20, len(closes)))
    ma60 = sma(closes, min(60, len(closes)))
    ma120 = sma(closes, min(120, len(closes)))
    close = closes[-1]
    return {
        "close": round(close, 3),
        "ma20": round(ma20, 3),
        "ma60": round(ma60, 3),
        "ma120": round(ma120, 3),
        "above_ma20": close >= ma20,
        "above_ma60": close >= ma60,
        "above_ma120": close >= ma120,
        "ma20_slope_pct": round((ma20 / sma(closes[:-5], min(20, len(closes[:-5]))) - 1) * 100, 2) if len(closes) > 25 else 0,
    }
