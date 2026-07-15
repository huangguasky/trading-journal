from engine.agent.loop import run_agent_loop
from engine.agent.planner import extract_symbols, is_stock_question, parse_intent
from engine.agent.profiles import get_agent_profile
from engine.agent.tools import ToolRegistry
from engine.config import get_settings
from engine.storage.db import Database


def test_agent_runs_stock_decision_tools(tmp_path):
    settings = get_settings()
    registry = ToolRegistry(Database(tmp_path / "test.db"), tool_timeout_s=4)
    result = run_agent_loop("600519 can I chase with breakout strategy?", registry, settings, max_steps=3)
    assert result.status == "ok"
    assert result.tool_trace
    assert result.card is not None


def test_extract_hk_symbols_is_case_insensitive_and_deduplicated():
    assert extract_symbols("看看 HK700、hk00700 和 700.hk") == ["HK0700"]


class RecordingRegistry:
    def __init__(self):
        self.calls = []

    def execute(self, name, arguments, allowed_tools=None):
        self.calls.append(name)
        return {"ok": False, "tool": name, "error": "test"}


def test_agent_rejects_unrelated_question_before_tools_run():
    registry = RecordingRegistry()
    result = run_agent_loop("帮我写一首生日诗", registry, get_settings())
    assert result.status == "refused"
    assert registry.calls == []


def test_follow_up_inherits_symbol_from_conversation():
    history = [
        {"role": "user", "content": "分析一下 600519 的走势"},
        {"role": "assistant", "content": "已经完成初步分析。"},
    ]
    plan = parse_intent("那风险和止损呢？", ["600519"])
    assert is_stock_question("那风险和止损呢？", history)
    assert plan["symbols"] == ["600519"]


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
    assert result.status == "ok"
    assert registry.calls == ["get_market_context"]


def test_malformed_history_is_ignored():
    registry = RecordingRegistry()
    result = run_agent_loop("分析 600519", registry, get_settings(), history={"role": "user"})
    assert result.status == "ok"
