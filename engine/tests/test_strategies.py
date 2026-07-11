from engine.strategies.registry import StrategyRegistry


def test_builtin_strategy_library_is_practical():
    strategies = StrategyRegistry().all()
    keys = {item.key for item in strategies}

    assert len(strategies) >= 15
    assert {
        "trend_following",
        "pullback_entry",
        "breakout_volume",
        "event_catalyst",
        "quality_growth",
        "risk_first",
        "bottom_accumulation",
        "range_rotation",
        "ma_reversal",
        "market_leader",
        "sentiment_repair",
        "expectation_reset",
        "theme_heat",
        "candle_squeeze",
        "swing_structure",
        "chip_repair",
    }.issubset(keys)


def test_builtin_strategies_have_scoring_rules():
    for strategy in StrategyRegistry().all():
        assert strategy.rules, strategy.key
        assert any(rule.get("weight", 0) > 0 for rule in strategy.rules), strategy.key
