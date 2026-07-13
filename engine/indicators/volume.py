from engine.data.market_data import Bar


def volume_indicators(bars: list[Bar]) -> dict:
    """Calculate volume ratios and price-volume confirmation signals."""
    volumes = [bar.volume for bar in bars]
    avg5 = sum(volumes[-5:]) / 5
    avg20 = sum(volumes[-20:]) / 20
    return {
        "volume_latest": round(volumes[-1], 2),
        "volume_avg5": round(avg5, 2),
        "volume_avg20": round(avg20, 2),
        "volume_ratio_5_20": round(avg5 / avg20, 2) if avg20 else 0,
    }
