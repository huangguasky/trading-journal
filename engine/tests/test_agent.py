from engine.agent.loop import run_agent_loop
from engine.agent.planner import extract_symbols
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
