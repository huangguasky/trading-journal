from engine.data.market_data import Bar


def ema(values: list[float], span: int) -> list[float]:
    """Calculate an exponential moving-average series."""
    alpha = 2 / (span + 1)
    out = [values[0]]
    for value in values[1:]:
        out.append(alpha * value + (1 - alpha) * out[-1])
    return out


def rsi(values: list[float], window: int = 14) -> float:
    """Calculate the latest relative strength index value."""
    gains: list[float] = []
    losses: list[float] = []
    for left, right in zip(values[-window - 1 : -1], values[-window:]):
        delta = right - left
        gains.append(max(delta, 0))
        losses.append(abs(min(delta, 0)))
    avg_gain = sum(gains) / len(gains)
    avg_loss = sum(losses) / len(losses)
    if avg_loss == 0:
        return 100
    return 100 - 100 / (1 + avg_gain / avg_loss)


def momentum_indicators(bars: list[Bar]) -> dict:
    """Calculate RSI, MACD, and recent return momentum indicators."""
    closes = [bar.close for bar in bars]
    fast = ema(closes, 12)
    slow = ema(closes, 26)
    macd_line = [a - b for a, b in zip(fast[-len(slow) :], slow)]
    signal = ema(macd_line, 9)
    return {
        "rsi14": round(rsi(closes), 2),
        "rsi6": round(rsi(closes, 6), 2),
        "rsi12": round(rsi(closes, 12), 2),
        "rsi24": round(rsi(closes, 24), 2),
        "macd": round(macd_line[-1], 4),
        "macd_signal": round(signal[-1], 4),
        "macd_hist": round(macd_line[-1] - signal[-1], 4),
        "return_20d_pct": round((closes[-1] / closes[-20] - 1) * 100, 2),
        "decline_from_20d_high_pct": round((closes[-1] / max(closes[-20:]) - 1) * 100, 2),
    }
