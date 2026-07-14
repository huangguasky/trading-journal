from engine.strategies.base import StrategyDefinition
from engine.strategies.registry import StrategyRegistry, evaluate_strategy


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
        "one_yang_three_yin",
    }.issubset(keys)


def test_builtin_strategies_have_scoring_rules():
    for strategy in StrategyRegistry().all():
        assert strategy.rules, strategy.key
        assert any(rule.get("weight", 0) > 0 for rule in strategy.rules), strategy.key


def test_failed_required_rule_keeps_strategy_negative():
    strategy = StrategyDefinition(
        key="strict_pattern",
        name="严格形态",
        description="",
        tags=[],
        risk_bias="balanced",
        rules=[
            {"metric": "patterns.matched", "op": "truthy", "weight": 10, "required": True},
            {"metric": "trend.strong", "op": "truthy", "weight": 50},
        ],
    )

    result = evaluate_strategy(strategy, {"patterns": {"matched": False}, "trend": {"strong": True}}, [])

    assert result.score == 49
    assert result.stance == "negative"


def test_missing_required_metric_also_keeps_strategy_negative():
    strategy = StrategyDefinition(
        key="missing_metric",
        name="缺失指标",
        description="",
        tags=[],
        risk_bias="balanced",
        rules=[
            {"metric": "patterns.missing", "op": "truthy", "weight": 10, "required": True},
            {"metric": "trend.strong", "op": "truthy", "weight": 50},
        ],
    )

    result = evaluate_strategy(strategy, {"trend": {"strong": True}}, [])

    assert result.score == 49
    assert result.stance == "negative"
