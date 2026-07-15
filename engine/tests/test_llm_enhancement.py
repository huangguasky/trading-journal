import json
from dataclasses import replace

from engine.analysis.llm_enhancement import NaturalLanguageEnhancer
from engine.analysis.market_pipeline import apply_market_language_analysis
from engine.analysis.stock_pipeline import apply_stock_language_evidence
from engine.config import get_settings


def test_enhancer_uses_rule_fallback_without_configuration():
    enhancer = NaturalLanguageEnhancer(get_settings())

    result = enhancer.enhance_stock({"news": [{"title": "利润增长但低于预期"}]})

    assert result["status"] == "not_configured"
    assert result["mode"] == "规则分析"
    assert result["analysis"] == {}


def test_enhancer_returns_validated_structured_analysis():
    settings = replace(get_settings(), llm_api_key="test-key")

    def complete(kind, context):
        assert kind == "stock"
        assert context["news"][0]["title"] == "利润增长但低于预期"
        return json.dumps({
            "summary": "利润增长，但预期差偏负面。",
            "news_direction": "negative",
            "impact_horizon": "short_term",
            "social_reliability": "low",
            "catalysts": [],
            "risks": ["盈利低于预期"],
            "conflicts": ["增长标题与低于预期的实际影响相反"],
            "confirmations": [],
            "watch_conditions": ["关注下一期盈利指引"],
            "ignored_extra_field": "must not leak",
        }, ensure_ascii=False)

    result = NaturalLanguageEnhancer(settings, completion=complete).enhance_stock({
        "news": [{"title": "利润增长但低于预期", "summary": "利润同比增长 5%，低于市场预期 12%。"}],
    })

    assert result["status"] == "enhanced"
    assert result["analysis"]["news_direction"] == "negative"
    assert result["analysis"]["risks"] == ["盈利低于预期"]
    assert "ignored_extra_field" not in result["analysis"]


def test_invalid_llm_output_falls_back_to_rules():
    settings = replace(get_settings(), llm_api_key="test-key")
    enhancer = NaturalLanguageEnhancer(settings, completion=lambda kind, context: "not-json")

    result = enhancer.enhance_market({"news": [{"title": "央行释放流动性"}]})

    assert result["status"] == "fallback"
    assert result["analysis"] == {}


def test_unknown_enum_value_is_safely_normalized():
    settings = replace(get_settings(), llm_api_key="test-key")
    payload = {
        "summary": "测试",
        "news_direction": "extremely_bullish",
        "impact_horizon": "forever",
        "social_reliability": "certain",
        "catalysts": [], "risks": [], "conflicts": [], "confirmations": [], "watch_conditions": [],
    }
    enhancer = NaturalLanguageEnhancer(settings, completion=lambda kind, context: json.dumps(payload))

    result = enhancer.enhance_stock({"news": [{"title": "测试新闻"}]})

    assert result["analysis"]["news_direction"] == "unknown"
    assert result["analysis"]["impact_horizon"] == "unknown"
    assert result["analysis"]["social_reliability"] == "unknown"


def test_semantic_evidence_never_changes_numeric_inputs():
    enhancement = {
        "status": "enhanced",
        "analysis": {
            "risks": ["事件风险"],
            "conflicts": ["新闻与价格走势冲突"],
            "confirmations": ["公告确认事件发生"],
            "watch_conditions": ["观察事件后续进展"],
        },
    }
    evidence = {"conflicts": ["规则冲突"], "confirmations": ["规则确认"], "technical": {"score": 80}}
    risks = ["规则风险"]
    watch = ["规则观察项"]

    apply_stock_language_evidence(evidence, enhancement)
    apply_market_language_analysis(risks, watch, enhancement)

    assert evidence["technical"]["score"] == 80
    assert evidence["conflicts"] == ["规则冲突", "新闻与价格走势冲突"]
    assert risks == ["规则风险", "事件风险", "新闻与价格走势冲突"]
    assert watch == ["规则观察项", "观察事件后续进展"]
