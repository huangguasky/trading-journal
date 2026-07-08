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
    plan = parse_intent(message)
    allowed = plan["allowed_tools"]
    symbols = plan["symbols"]
    tool_trace: list[dict[str, Any]] = []
    steps = max_steps or settings.agent_max_steps

    scripted_calls = plan_tool_calls(plan)
    for index, call in enumerate(scripted_calls[:steps]):
        result = registry.execute(call.name, call.arguments, allowed)
        tool_trace.append({"step": index + 1, "call": call.__dict__, "result": result})

    llm = synthesize_with_llm(message, plan, tool_trace, settings)
    if llm:
        return AgentResult(llm, build_card(plan, tool_trace), tool_trace)
    return AgentResult(fallback_answer(message, plan, tool_trace, symbols), build_card(plan, tool_trace), tool_trace)


def plan_tool_calls(plan: dict) -> list[ToolCall]:
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
    if not trace:
        return "I need a symbol or market context first. Try `600519 can I chase?`, `HK00700 breakout strategy`, or `US market review`."
    lines = [f"Intent: {plan['intent']}. I used {len(trace)} local tool calls."]
    for item in trace:
        result = item["result"]
        if not result.get("ok"):
            lines.append(f"- {item['call']['name']} failed: {result.get('error')}")
            continue
        payload = result.get("result")
        if item["call"]["name"] == "run_stock_report":
            lines.append(f"- {payload['symbol']}: score {payload['score']}/100, action {payload['action']}, top risk: {(payload['risk_flags'] or ['none'])[0]}")
        elif item["call"]["name"] == "get_market_context":
            lines.append(f"- {payload['market'].upper()} market: {payload['market_regime']}, score {payload['score']}/100, bias {payload['strategy_bias']}")
        elif item["call"]["name"] == "get_indicators":
            lines.append(f"- Indicators: MA20 {payload['trend']['ma20']}, RSI {payload['momentum']['rsi14']}, ATR {payload['levels']['atr_pct']}%")
        elif item["call"]["name"] == "get_last_report" and payload:
            lines.append(f"- Last report: {payload['title']} score {payload['score']}")
    lines.append("Use this as a review input, not as investment advice. Verify live quotes and announcements before trading.")
    return "\n".join(lines)


def build_card(plan: dict, trace: list[dict]) -> dict:
    card = {"intent": plan["intent"], "symbols": plan.get("symbols", []), "tools": []}
    for item in trace:
        card["tools"].append({"name": item["call"]["name"], "ok": bool(item["result"].get("ok"))})
    return card

