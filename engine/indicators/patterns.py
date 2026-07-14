from engine.data.market_data import Bar


def pattern_indicators(bars: list[Bar]) -> dict:
    """Detect deterministic candle patterns used by strategy rules."""
    last = bars[-1]
    candle_range = max(last.high - last.low, 1e-9)
    lower_shadow = min(last.open, last.close) - last.low
    return {
        "bullish_candle": last.close > last.open,
        "lower_shadow_ratio": round(lower_shadow / candle_range, 3),
        "one_yang_three_yin": one_yang_three_yin(bars),
    }


def one_yang_three_yin(bars: list[Bar]) -> bool:
    """Detect a large bullish candle, three contracting candles, then breakout."""
    if len(bars) < 6:
        return False
    first, *middle, last = bars[-5:]
    first_body_pct = (first.close / first.open - 1) * 100 if first.open else 0
    inside_first = all(
        item.low >= first.open
        and first.open <= item.close <= first.close
        and abs(item.close / item.open - 1) * 100 <= 2
        for item in middle
        if item.open
    )
    shrinking_volume = middle[0].volume > middle[1].volume > middle[2].volume
    return bool(
        first_body_pct >= 2
        and len(middle) == 3
        and inside_first
        and shrinking_volume
        and last.close > last.open
        and last.close > first.close
    )
