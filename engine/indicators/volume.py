from engine.data.market_data import Bar


def volume_indicators(bars: list[Bar]) -> dict:
    """Calculate volume ratios and price-volume confirmation signals."""
    volumes = [bar.volume for bar in bars]
    avg5 = sum(volumes[-5:]) / 5
    avg20 = sum(volumes[-20:]) / 20
    latest = volumes[-1]
    previous5 = sum(volumes[-6:-1]) / 5 if len(volumes) >= 6 else avg5
    return {
        "volume_latest": round(latest, 2),
        "volume_avg5": round(avg5, 2),
        "volume_avg20": round(avg20, 2),
        "volume_ratio_5_20": round(avg5 / avg20, 2) if avg20 else 0,
        "latest_to_avg5": round(latest / previous5, 2) if previous5 else 0,
        "latest_to_avg20": round(latest / avg20, 2) if avg20 else 0,
        "declining_3d": volumes[-1] < volumes[-2] < volumes[-3],
        "last3_to_avg20": round((sum(volumes[-3:]) / 3) / avg20, 2) if avg20 else 0,
    }
