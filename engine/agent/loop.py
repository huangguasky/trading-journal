from __future__ import annotations

import json
import os
import uuid
from typing import Any

from engine.config import Settings

from .planner import conversation_symbols, is_stock_question, parse_intent
from .profiles import AgentProfile, get_agent_profile
from .prompts import SYSTEM_PROMPT
from .schema import AgentResult, ToolCall
from .tools import ToolRegistry


def run_agent_loop(
    message: str,
    registry: ToolRegistry,
    settings: Settings,
    max_steps: int | None = None,
    complexity: str = "standard",
    history: list[dict[str, Any]] | None = None,
) -> AgentResult:
    """Plan tool calls, execute them within limits, and synthesize an agent response."""
    clean_history = normalize_history(history)
    profile = get_agent_profile(complexity)
    if not is_stock_question(message, clean_history):
        return AgentResult(
            "我只能回答股票、证券市场、持仓与投资研究相关的问题。你可以告诉我股票代码，并询问走势、风险、仓位或交易计划。",
            {"intent": "out_of_scope", "symbols": [], "tools": [], "agents": [], "complexity": profile.key},
            [],
            status="refused",
        )

    plan = parse_intent(message, conversation_symbols(clean_history))
    if profile.key == "deep" and plan["symbols"]:
        for tool_name in ("get_history", "get_signal_tracking"):
            if tool_name not in plan["allowed_tools"]:
                plan["allowed_tools"].append(tool_name)
    allowed = [name for name in plan["allowed_tools"] if name in profile.tools]
    plan["allowed_tools"] = allowed
    symbols = plan["symbols"]
    tool_trace: list[dict[str, Any]] = []
    configured_steps = max_steps or settings.agent_max_steps
    steps = min(max(1, configured_steps), profile.max_steps)

    # Tool execution stays deterministic and bounded even when an LLM is
    # configured; the model only synthesizes evidence returned by these calls.
    scripted_calls = plan_tool_calls(plan, profile)
    for index, call in enumerate(scripted_calls[:steps]):
        result = registry.execute(call.name, call.arguments, allowed)
        tool_trace.append({"step": index + 1, "call": call.__dict__, "result": result})

    llm = synthesize_with_llm(message, plan, tool_trace, settings, clean_history, profile)
    if llm:
        return AgentResult(llm, build_card(plan, tool_trace, profile), tool_trace)
    return AgentResult(fallback_answer(message, plan, tool_trace, symbols), build_card(plan, tool_trace, profile), tool_trace)


def plan_tool_calls(plan: dict, profile: AgentProfile | None = None) -> list[ToolCall]:
    """Translate a parsed intent plan into the ordered tool calls it requires."""
    calls: list[ToolCall] = []
    if plan["intent"] == "market":
        if "get_market_context" in plan["allowed_tools"]:
            calls.append(ToolCall(str(uuid.uuid4()), "get_market_context", {"market": plan.get("market", "cn")}))
        if "search_news" in plan["allowed_tools"]:
            calls.append(ToolCall(str(uuid.uuid4()), "search_news", {"market": plan.get("market", "cn")}))
        return calls
    symbols = plan.get("symbols") or []
    if not symbols:
        return calls
    for symbol in symbols[:2]:
        if "get_quote" in plan["allowed_tools"]:
            calls.append(ToolCall(str(uuid.uuid4()), "get_quote", {"symbol": symbol}))
        if "get_history" in plan["allowed_tools"]:
            calls.append(ToolCall(str(uuid.uuid4()), "get_history", {"symbol": symbol, "days": 60}))
        if "get_indicators" in plan["allowed_tools"]:
            calls.append(ToolCall(str(uuid.uuid4()), "get_indicators", {"symbol": symbol}))
        if "search_news" in plan["allowed_tools"]:
            calls.append(ToolCall(str(uuid.uuid4()), "search_news", {"symbol": symbol}))
        if "get_last_report" in plan["allowed_tools"]:
            calls.append(ToolCall(str(uuid.uuid4()), "get_last_report", {"symbol": symbol}))
        if "get_signal_tracking" in plan["allowed_tools"]:
            calls.append(ToolCall(str(uuid.uuid4()), "get_signal_tracking", {"symbol": symbol}))
    return calls


def synthesize_with_llm(
    message: str,
    plan: dict,
    tool_trace: list[dict],
    settings: Settings,
    history: list[dict[str, str]] | None = None,
    profile: AgentProfile | None = None,
) -> str | None:
    """Ask the configured LLM to summarize tool evidence, returning None on failure."""
    if not settings.llm_api_key:
        return None
    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url)
        prior_messages = [
            {"role": item["role"], "content": item["content"]}
            for item in (history or [])[-8:]
        ]
        profile = profile or get_agent_profile("standard")
        response = client.chat.completions.create(
            model=settings.llm_model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                *prior_messages,
                {"role": "user", "content": json.dumps({
                    "question": message,
                    "intent": plan,
                    "analysis_team": list(profile.agents),
                    "tool_trace": tool_trace,
                }, ensure_ascii=False)},
            ],
            temperature=0.2,
        )
        content = response.choices[0].message.content
        return content.strip() if isinstance(content, str) and content.strip() else None
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
        elif item["call"]["name"] == "get_quote":
            lines.append(f"- {payload.get('symbol', symbols[0] if symbols else '标的')}：最新价 {payload.get('price', '-')}，涨跌幅 {payload.get('change_pct', '-')}%。")
        elif item["call"]["name"] == "get_market_context":
            lines.append(f"- {market_label(payload['market'])}：状态 {market_regime_label(payload['market_regime'])}，评分 {payload['score']}/100，策略倾向 {strategy_bias_label(payload['strategy_bias'])}")
        elif item["call"]["name"] == "get_history":
            lines.append(f"- 历史走势：已检查最近 {len(payload.get('bars', []))} 根日线。")
        elif item["call"]["name"] == "get_indicators":
            lines.append(f"- 技术指标：MA20 {payload['trend']['ma20']}，RSI {payload['momentum']['rsi14']}，ATR {payload['levels']['atr_pct']}%")
        elif item["call"]["name"] == "search_news":
            lines.append(f"- 资讯：检索到 {len(payload.get('items', []))} 条可用信息，需结合发布时间判断有效性。")
        elif item["call"]["name"] == "get_last_report" and payload:
            lines.append(f"- 最近报告：{payload['title']}，评分 {payload['score']}")
        elif item["call"]["name"] == "get_signal_tracking":
            lines.append(f"- 信号追踪：当前有 {len(payload or [])} 条历史跟踪记录。")
    lines.append("以上内容适合作为复盘和交易计划输入，不构成投资建议；下单前请复核实时行情、公告与风险事件。")
    return "\n".join(lines)


def build_card(plan: dict, trace: list[dict], profile: AgentProfile | None = None) -> dict:
    """Create compact structured metadata for rendering an agent result card."""
    profile = profile or get_agent_profile("standard")
    card = {
        "intent": plan["intent"],
        "symbols": plan.get("symbols", []),
        "tools": [],
        "agents": list(profile.agents),
        "complexity": profile.key,
    }
    for item in trace:
        card["tools"].append({"name": item["call"]["name"], "ok": bool(item["result"].get("ok"))})
    return card


def normalize_history(history: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    """Keep only recent plain user/assistant messages supplied by the client."""
    normalized: list[dict[str, str]] = []
    if not isinstance(history, list):
        return normalized
    for item in history[-12:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", ""))
        content = str(item.get("content", "")).strip()
        if role in {"user", "assistant"} and content:
            normalized.append({"role": role, "content": content[:6000]})
    return normalized


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
