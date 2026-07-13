from __future__ import annotations

import json
import os
import uuid
from typing import Any

from engine.config import Settings

from .planner import parse_intent
from .prompts import SYSTEM_PROMPT
from .schema import AgentResult, ToolCall
from .tools import ToolRegistry


def run_agent_loop(message: str, registry: ToolRegistry, settings: Settings, max_steps: int | None = None) -> AgentResult:
    """Plan tool calls, execute them within limits, and synthesize an agent response."""
    plan = parse_intent(message)
    allowed = plan["allowed_tools"]
    symbols = plan["symbols"]
    tool_trace: list[dict[str, Any]] = []
    steps = max_steps or settings.agent_max_steps

    # Tool execution stays deterministic and bounded even when an LLM is
    # configured; the model only synthesizes evidence returned by these calls.
    scripted_calls = plan_tool_calls(plan)
    for index, call in enumerate(scripted_calls[:steps]):
        result = registry.execute(call.name, call.arguments, allowed)
        tool_trace.append({"step": index + 1, "call": call.__dict__, "result": result})

    llm = synthesize_with_llm(message, plan, tool_trace, settings)
    if llm:
        return AgentResult(llm, build_card(plan, tool_trace), tool_trace)
    return AgentResult(fallback_answer(message, plan, tool_trace, symbols), build_card(plan, tool_trace), tool_trace)


def plan_tool_calls(plan: dict) -> list[ToolCall]:
    """Translate a parsed intent plan into the ordered tool calls it requires."""
    calls: list[ToolCall] = []
    if plan["intent"] == "market":
        calls.append(ToolCall(str(uuid.uuid4()), "get_market_context", {"market": plan.get("market", "cn")}))
        calls.append(ToolCall(str(uuid.uuid4()), "search_news", {"market": plan.get("market", "cn")}))
        return calls
    symbols = plan.get("symbols") or []
    if not symbols:
        return calls
    for symbol in symbols[:2]:
        if "run_stock_report" in plan["allowed_tools"]:
            calls.append(ToolCall(str(uuid.uuid4()), "run_stock_report", {"symbol": symbol}))
        else:
            calls.append(ToolCall(str(uuid.uuid4()), "get_quote", {"symbol": symbol}))
            calls.append(ToolCall(str(uuid.uuid4()), "get_indicators", {"symbol": symbol}))
        if "get_last_report" in plan["allowed_tools"]:
            calls.append(ToolCall(str(uuid.uuid4()), "get_last_report", {"symbol": symbol}))
        if "get_signal_tracking" in plan["allowed_tools"]:
            calls.append(ToolCall(str(uuid.uuid4()), "get_signal_tracking", {"symbol": symbol}))
    return calls


def synthesize_with_llm(message: str, plan: dict, tool_trace: list[dict], settings: Settings) -> str | None:
    """Ask the configured LLM to summarize tool evidence, returning None on failure."""
    if not settings.llm_api_key:
        return None
    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url)
        response = client.chat.completions.create(
            model=settings.llm_model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps({"question": message, "intent": plan, "tool_trace": tool_trace}, ensure_ascii=False)},
            ],
            temperature=0.2,
        )
        return response.choices[0].message.content
    except Exception:
        return None


def fallback_answer(message: str, plan: dict, trace: list[dict], symbols: list[str]) -> str:
    """Build a deterministic answer when no LLM response is available."""
    if not trace:
        return "我需要先知道你要问的股票或市场。可以试试：`600519 能追吗`、`HK00700 用突破策略看一下`、`美股市场复盘`。"
    lines = [f"识别意图：{intent_label(plan['intent'])}。本次调用了 {len(trace)} 个本地工具。"]
    for item in trace:
        result = item["result"]
        if not result.get("ok"):
            lines.append(f"- {tool_label(item['call']['name'])} 调用失败：{result.get('error')}")
            continue
        payload = result.get("result")
        if item["call"]["name"] == "run_stock_report":
            lines.append(f"- {payload['symbol']}：评分 {payload['score']}/100，建议“{payload['action']}”，首要风险：{(payload['risk_flags'] or ['暂无'])[0]}")
        elif item["call"]["name"] == "get_market_context":
            lines.append(f"- {market_label(payload['market'])}：状态 {market_regime_label(payload['market_regime'])}，评分 {payload['score']}/100，策略倾向 {strategy_bias_label(payload['strategy_bias'])}")
        elif item["call"]["name"] == "get_indicators":
            lines.append(f"- 技术指标：MA20 {payload['trend']['ma20']}，RSI {payload['momentum']['rsi14']}，ATR {payload['levels']['atr_pct']}%")
        elif item["call"]["name"] == "get_last_report" and payload:
            lines.append(f"- 最近报告：{payload['title']}，评分 {payload['score']}")
    lines.append("以上内容适合作为复盘和交易计划输入，不构成投资建议；下单前请复核实时行情、公告与风险事件。")
    return "\n".join(lines)


def build_card(plan: dict, trace: list[dict]) -> dict:
    """Create compact structured metadata for rendering an agent result card."""
    card = {"intent": plan["intent"], "symbols": plan.get("symbols", []), "tools": []}
    for item in trace:
        card["tools"].append({"name": item["call"]["name"], "ok": bool(item["result"].get("ok"))})
    return card


def intent_label(value: str) -> str:
    """Translate an internal intent identifier into a user-facing label."""
    return {"market": "市场复盘", "report_followup": "报告追问", "stock_decision": "个股决策", "general_stock": "个股查询"}.get(value, value)


def tool_label(value: str) -> str:
    """Translate an internal tool identifier into a user-facing label."""
    return {
        "get_quote": "行情",
        "get_history": "K线",
        "get_indicators": "技术指标",
        "search_news": "资讯检索",
        "get_last_report": "历史报告",
        "get_signal_tracking": "信号追踪",
        "get_market_context": "市场上下文",
        "run_stock_report": "个股流水线",
    }.get(value, value)


def market_label(value: str) -> str:
    """Translate a market code into a user-facing label."""
    return {"cn": "A股", "hk": "港股", "us": "美股"}.get(value, value.upper())


def market_regime_label(value: str) -> str:
    """Translate a market-regime code into a user-facing label."""
    return {"risk_on": "风险偏好升温", "neutral": "震荡均衡", "risk_off": "防守优先", "volatile": "高波动震荡"}.get(value, value)


def strategy_bias_label(value: str) -> str:
    """Translate a strategy-bias code into a user-facing label."""
    return {"trend": "趋势跟随", "defensive": "防守优先", "wait": "等待确认", "event": "事件驱动"}.get(value, value)
