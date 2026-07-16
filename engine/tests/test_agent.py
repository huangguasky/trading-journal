from engine.agent.loop import answer_matches_quote, bounded_tool_calls, clean_llm_answer, plan_tool_calls, run_agent_loop
from engine.agent.planner import ambiguous_bare_symbol, conversation_symbols, extract_symbols, is_stock_question, parse_intent
from engine.agent.profiles import get_agent_profile
from engine.agent.tools import ToolRegistry
from engine.config import get_settings
from engine.storage.db import Database


def test_agent_runs_stock_decision_tools(tmp_path):
    settings = get_settings()
    registry = ToolRegistry(Database(tmp_path / "test.db"), tool_timeout_s=4)
    result = run_agent_loop("600519 can I chase with breakout strategy?", registry, settings, max_steps=3)
    assert result.status in {"ok", "degraded"}
    assert result.tool_trace
    assert result.card is not None
    assert result.card["symbols"] == ["SH600519"]


def test_extract_hk_symbols_is_case_insensitive_and_deduplicated():
    assert extract_symbols("看看 HK700、hk00700 和 700.hk") == ["HK0700"]


def test_explicit_codes_work_when_directly_followed_by_chinese_text():
    assert extract_symbols("HK0917适合做T吗") == ["HK0917"]
    assert extract_symbols("600519能买吗") == ["SH600519"]
    assert extract_symbols("AAPL走势如何") == ["AAPL"]


def test_hk_share_class_suffix_is_not_parsed_as_us_ticker():
    assert extract_symbols("阿里巴巴-SW (09988.HK) 现在适合追涨吗？") == ["HK9988"]
    assert extract_symbols("小米集团-W（01810.HK）走势如何？") == ["HK1810"]


def test_known_company_name_resolves_without_requiring_a_code():
    assert extract_symbols("腾讯控股现在适合追涨吗？") == ["HK0700"]
    assert extract_symbols("阿里巴巴现在能买吗？") == ["HK9988"]


def test_multiple_symbols_follow_the_users_mention_order():
    assert extract_symbols("AAPL、腾讯和阿里巴巴哪个更强？") == ["AAPL", "HK0700", "HK9988"]


def test_more_than_two_symbols_requires_narrowing_before_tools_run():
    registry = RecordingRegistry()
    result = run_agent_loop("比较 AAPL、腾讯和阿里巴巴", registry, get_settings(), complexity="standard")
    assert result.status == "needs_clarification"
    assert result.card["intent"] == "too_many_symbols"
    assert "一次最多比较 2 只股票" in result.content
    assert registry.calls == []


def test_extracts_leading_bare_hk_symbol_for_chat_question():
    assert extract_symbols("1810 现在适合追涨吗？") == ["HK1810"]


def test_company_name_resolves_without_treating_price_as_symbol():
    assert extract_symbols("小米涨到 2026 元还能追吗？") == ["HK1810"]


def test_does_not_treat_arbitrary_number_inside_question_as_symbol():
    assert extract_symbols("股价涨到 2026 元还能追吗？") == []


def test_does_not_treat_leading_year_or_price_as_symbol():
    assert extract_symbols("2026年腾讯业绩怎么样？") == ["HK0700"]
    assert extract_symbols("482元的腾讯还能买吗？") == ["HK0700"]


def test_english_words_are_not_parsed_as_us_tickers():
    assert extract_symbols("AAPL can I buy after this breakout?") == ["AAPL"]
    assert extract_symbols("aapl能买吗？") == ["AAPL"]


def test_bare_hk_question_asks_for_clarification_without_running_tools():
    registry = RecordingRegistry()
    result = run_agent_loop("1810 现在适合追涨吗？", registry, get_settings(), complexity="quick")
    assert result.status == "needs_clarification"
    assert "小米集团-W（01810.HK）" in result.content
    assert registry.calls == []


def test_bare_700_asks_to_confirm_tencent_without_inventing_a_quote():
    registry = RecordingRegistry()
    result = run_agent_loop("700 现在适合追涨吗？", registry, get_settings(), complexity="quick")
    assert result.status == "degraded"
    assert result.card["symbols"] == ["HK0700"]
    assert registry.calls == ["get_quote", "get_indicators"]


def test_bare_700_with_chinese_followup_particle_resolves_tencent():
    assert extract_symbols("700呢") == ["HK0700"]


def test_bare_hk_day_trade_question_is_clarified_not_rejected():
    registry = RecordingRegistry()
    result = run_agent_loop("917今天适合卖了等明天买回来这样做T吗", registry, get_settings(), complexity="quick")
    assert result.status == "needs_clarification"
    assert "裸代码 `917`" in result.content
    assert result.card["intent"] == "symbol_clarification"
    assert registry.calls == []


def test_day_trade_t_is_not_parsed_as_us_ticker():
    assert extract_symbols("00917.HK 今天适合做T吗") == ["HK0917"]


def test_explicit_hk_hint_skips_clarification_and_runs_tools():
    registry = RecordingRegistry()
    result = run_agent_loop("1810 港股小米现在适合追涨吗？", registry, get_settings(), complexity="quick")
    assert result.status == "degraded"
    assert result.card["symbols"] == ["HK1810"]
    assert registry.calls == ["get_quote", "get_indicators"]


def test_hk_share_class_question_uses_tools_only_for_hk_symbol():
    registry = RecordingRegistry()
    result = run_agent_loop("阿里巴巴-SW (09988.HK) 现在适合追涨吗？", registry, get_settings(), complexity="quick")
    assert result.card["symbols"] == ["HK9988"]
    assert registry.calls == ["get_quote", "get_indicators"]


def test_confirmation_continues_original_question_with_confirmed_symbol():
    registry = RecordingRegistry()
    history = [
        {"role": "user", "content": "1810 现在适合追涨吗？"},
        {"role": "assistant", "content": "先确认一下标的：裸代码 `1810` 不能唯一说明市场。你指的是港股 **小米集团-W（01810.HK）** 吗？"},
    ]
    result = run_agent_loop("是小米", registry, get_settings(), complexity="quick", history=history)
    assert result.status == "degraded"
    assert result.card["symbols"] == ["HK1810"]
    assert registry.calls == ["get_quote", "get_indicators"]


def test_unresolved_clarification_stays_in_clarification_state():
    registry = RecordingRegistry()
    history = [
        {"role": "user", "content": "917今天适合做T吗"},
        {"role": "assistant", "content": "请确认标的。", "card": {"intent": "symbol_clarification", "pending_code": "917", "symbols": []}},
    ]
    result = run_agent_loop("不是，我问A股", registry, get_settings(), complexity="quick", history=history)
    assert result.status == "needs_clarification"
    assert "6 位 A 股代码" in result.content
    assert registry.calls == []


def test_explicit_different_company_overrides_pending_clarification():
    registry = RecordingRegistry()
    history = [
        {"role": "user", "content": "1810 现在适合追涨吗？"},
        {"role": "assistant", "content": "请确认标的。", "card": {"intent": "symbol_clarification", "pending_code": "1810", "symbols": []}},
    ]
    result = run_agent_loop("不是，是腾讯", registry, get_settings(), complexity="quick", history=history)
    assert result.card["symbols"] == ["HK0700"]
    assert registry.calls == ["get_quote", "get_indicators"]


def test_tencent_confirmation_continues_with_hk0700():
    registry = RecordingRegistry()
    history = [
        {"role": "user", "content": "700 现在适合追涨吗？"},
        {"role": "assistant", "content": "先确认一下标的：裸代码 `700` 不能唯一说明市场。你指的是港股 **腾讯控股（00700.HK）** 吗？"},
    ]
    result = run_agent_loop("是腾讯", registry, get_settings(), complexity="quick", history=history)
    assert result.card["symbols"] == ["HK0700"]
    assert registry.calls == ["get_quote", "get_indicators"]


def test_missing_symbol_never_reaches_llm_or_invents_market_data():
    registry = RecordingRegistry()
    result = run_agent_loop("这只股票现在适合追涨吗？", registry, get_settings(), complexity="quick")
    assert result.status == "needs_clarification"
    assert "完整代码或公司名称" in result.content
    assert registry.calls == []


def test_explicit_stock_codes_are_not_ambiguous():
    assert ambiguous_bare_symbol("1810 现在适合追涨吗？") == "1810"
    assert ambiguous_bare_symbol("HK1810 现在适合追涨吗？") is None
    assert ambiguous_bare_symbol("1810.HK 现在适合追涨吗？") is None
    assert ambiguous_bare_symbol("600519 现在适合追涨吗？") is None


def test_unsolicited_trailing_json_is_removed_from_markdown_answer():
    content = "## 结论\n\n暂不追涨。\n\n```json\n{\"decision\": \"wait\"}\n```"
    assert clean_llm_answer(content, "现在适合追涨吗？") == "## 结论\n\n暂不追涨。"
    assert "```json" in clean_llm_answer(content, "请用 JSON 回答")


def test_answer_price_must_match_fresh_quote_evidence():
    trace = [{
        "call": {"name": "get_quote"},
        "result": {"ok": True, "result": {"symbol": "HK0700", "price": 482.0}},
    }]
    assert answer_matches_quote("腾讯现价 482 HKD。", trace)
    assert not answer_matches_quote("腾讯现价 532.0 HKD。", trace)


class RecordingRegistry:
    def __init__(self):
        self.calls = []

    def execute(self, name, arguments, allowed_tools=None):
        self.calls.append(name)
        return {"ok": False, "tool": name, "error": "test"}


class PartialRegistry(RecordingRegistry):
    def execute(self, name, arguments, allowed_tools=None):
        self.calls.append(name)
        if name == "search_news":
            return {"ok": True, "tool": name, "result": {"items": []}}
        return {"ok": False, "tool": name, "error": "行情暂不可用"}


def test_agent_rejects_unrelated_question_before_tools_run():
    registry = RecordingRegistry()
    result = run_agent_loop("帮我写一首生日诗", registry, get_settings())
    assert result.status == "refused"
    assert registry.calls == []


def test_news_success_without_quote_is_degraded_not_model_evidence():
    registry = PartialRegistry()
    result = run_agent_loop("分析 AAPL 的新闻和走势", registry, get_settings(), complexity="standard")
    assert result.status == "degraded"
    assert "行情 调用失败" in result.content
    assert "资讯：检索到 0 条" in result.content


def test_follow_up_inherits_symbol_from_conversation():
    history = [
        {"role": "user", "content": "分析一下 600519 的走势"},
        {"role": "assistant", "content": "已经完成初步分析。"},
    ]
    plan = parse_intent("那风险和止损呢？", ["600519"])
    assert is_stock_question("那风险和止损呢？", history)
    assert plan["symbols"] == ["600519"]


def test_follow_up_ignores_symbols_in_untrusted_assistant_prose():
    history = [
        {"role": "user", "content": "分析一下 600519"},
        {"role": "assistant", "content": "错误提到了 00700.HK。"},
    ]
    assert parse_intent("那止损呢？", conversation_symbols(history))["symbols"] == ["SH600519"]


def test_follow_up_prefers_structured_result_symbols():
    history = [
        {"role": "user", "content": "上一只股票怎么样"},
        {"role": "assistant", "content": "分析完成。", "card": {"symbols": ["HK0700"]}},
    ]
    symbols = conversation_symbols(history)
    assert symbols == ["HK0700"]


def test_stock_specific_review_is_not_misclassified_as_market_review():
    plan = parse_intent("复盘一下腾讯控股")
    assert plan["intent"] == "general_stock"
    assert plan["symbols"] == ["HK0700"]


def test_two_symbol_tool_budget_keeps_evidence_symmetric():
    plan = parse_intent("比较 AAPL 和 MSFT 能不能买")
    profile = get_agent_profile("quick")
    plan["allowed_tools"] = [tool for tool in plan["allowed_tools"] if tool in profile.tools]
    calls = bounded_tool_calls(plan_tool_calls(plan, profile), profile.max_steps, 2)
    assert [(call.name, call.arguments["symbol"]) for call in calls] == [
        ("get_quote", "AAPL"),
        ("get_quote", "MSFT"),
    ]


def test_stock_decision_plan_does_not_include_unreachable_report_generation():
    assert "run_stock_report" not in parse_intent("腾讯能买吗")["allowed_tools"]


def test_fundamental_questions_request_fundamental_evidence_in_supported_profiles():
    plan = parse_intent("腾讯的估值和业绩怎么样？")
    assert "get_fundamentals" in plan["allowed_tools"]

    standard = get_agent_profile("standard")
    plan["allowed_tools"] = [tool for tool in plan["allowed_tools"] if tool in standard.tools]
    calls = plan_tool_calls(plan, standard)
    assert "get_fundamentals" in [call.name for call in calls]
    assert "get_fundamentals" not in get_agent_profile("quick").tools


def test_multi_symbol_budget_prioritizes_the_requested_evidence_type():
    plan = parse_intent("比较 AAPL 和 MSFT 的估值")
    profile = get_agent_profile("standard")
    plan["allowed_tools"] = [tool for tool in plan["allowed_tools"] if tool in profile.tools]
    calls = bounded_tool_calls(plan_tool_calls(plan, profile), profile.max_steps, 2)
    assert [(call.name, call.arguments["symbol"]) for call in calls] == [
        ("get_quote", "AAPL"),
        ("get_quote", "MSFT"),
        ("get_fundamentals", "AAPL"),
        ("get_fundamentals", "MSFT"),
    ]


def test_complexity_profiles_change_agent_team_and_tool_depth():
    quick_registry = RecordingRegistry()
    quick = run_agent_loop("分析 600519 的走势", quick_registry, get_settings(), complexity="quick")
    deep_registry = RecordingRegistry()
    deep = run_agent_loop("分析 600519 的走势", deep_registry, get_settings(), complexity="deep")

    assert quick.card["agents"] == list(get_agent_profile("quick").agents)
    assert deep.card["agents"] == list(get_agent_profile("deep").agents)
    assert "get_history" not in quick_registry.calls
    assert "get_history" in deep_registry.calls
    assert len(deep_registry.calls) > len(quick_registry.calls)


def test_quick_market_mode_does_not_schedule_news_agent():
    registry = RecordingRegistry()
    result = run_agent_loop("A股大盘今天怎么样？", registry, get_settings(), complexity="quick")
    assert result.status == "degraded"
    assert registry.calls == ["get_market_context"]


def test_malformed_history_is_ignored():
    registry = RecordingRegistry()
    result = run_agent_loop("分析 600519", registry, get_settings(), history={"role": "user"})
    assert result.status == "degraded"
