from engine.data.market_data import Bar
from engine.indicators import compute_indicators


def test_indicators_expose_strategy_ready_ma_volume_and_range_signals():
    bars = [Bar(f"d{index}", 10, 10.1, 9.9, 10, 100) for index in range(25)]
    bars.extend(
        [
            Bar("d25", 10, 10.35, 10, 10.3, 300),
            Bar("d26", 10.25, 10.3, 10.05, 10.2, 180),
            Bar("d27", 10.18, 10.25, 10.04, 10.12, 150),
            Bar("d28", 10.1, 10.2, 10.02, 10.08, 120),
            Bar("d29", 10.1, 10.5, 10.05, 10.4, 400),
        ]
    )

    indicators = compute_indicators(bars)

    assert indicators["patterns"]["one_yang_three_yin"] is True
    assert indicators["patterns"]["bullish_candle"] is True
    assert indicators["levels"]["breakout_above_prior_20d"] is True
    assert indicators["volume"]["latest_to_avg5"] > 1
    assert "ma5_cross_above_ma10_3d" in indicators["trend"]
    assert "golden_cross_3d" in indicators["trend"]
    assert "near_pullback_ma5_or_ma10" in indicators["trend"]
    assert indicators["trend"]["distance_to_ma5_pct"] >= 0
    assert "box_confirmed_60d" in indicators["levels"]


def test_one_yang_three_yin_rejects_non_contracting_middle_volume():
    bars = [Bar(f"d{index}", 10, 10.1, 9.9, 10, 100) for index in range(25)]
    bars.extend(
        [
            Bar("d25", 10, 10.35, 10, 10.3, 300),
            Bar("d26", 10.25, 10.3, 10.05, 10.2, 120),
            Bar("d27", 10.18, 10.25, 10.04, 10.12, 150),
            Bar("d28", 10.1, 10.2, 10.02, 10.08, 180),
            Bar("d29", 10.1, 10.5, 10.05, 10.4, 400),
        ]
    )

    assert compute_indicators(bars)["patterns"]["one_yang_three_yin"] is False
