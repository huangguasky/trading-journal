from __future__ import annotations

import json
import os
import re
import uuid
from typing import Any

from engine.config import Settings

from .planner import ambiguous_bare_symbol, conversation_symbols, extract_symbols, is_stock_question, parse_intent
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
    pending_code = pending_clarification_code(clean_history)
    resolved_message = resolve_clarification(message, clean_history)
    if pending_code and resolved_message is None:
        if re.search(r"^(?:算了|取消|不用了|不问了)[。.!！?？]?$", message.strip()):
            return AgentResult("好的，已取消这次标的确认。", {"intent": "clarification_cancelled", "symbols": [], "tools": [], "agents": [], "complexity": profile.key}, [], status="ok")
        return AgentResult(
            f"还无法确认裸代码 `{pending_code}` 对应的标的。请提供完整代码，例如港股 `{pending_code.zfill(5)}.HK`，或提供 6 位 A 股代码。",
            {"intent": "symbol_clarification", "pending_code": pending_code, "symbols": [], "tools": [], "agents": [], "complexity": profile.key},
            [],
            status="needs_clarification",
        )
    if resolved_message is None:
        code = ambiguous_bare_symbol(message)
        if code:
            return clarification_result(code, profile)
    effective_message = resolved_message or message
    if not is_stock_question(effective_message, clean_history):
        return AgentResult(
            "我只能回答股票、证券市场、持仓与投资研究相关的问题。你可以告诉我股票代码，并询问走势、风险、仓位或交易计划。",
            {"intent": "out_of_scope", "symbols": [], "tools": [], "agents": [], "complexity": profile.key},
            [],
            status="refused",
        )

    plan = parse_intent(effective_message, conversation_symbols(clean_history))
    if plan["intent"] != "market" and not plan["symbols"]:
        return AgentResult(
            "我还不能确定你问的是哪只股票。请提供完整代码或公司名称，例如 `HK0700`、`00700.HK` 或“腾讯控股”。",
            {"intent": "symbol_required", "symbols": [], "tools": [], "agents": [], "complexity": profile.key},
            [],
            status="needs_clarification",
        )
    if len(plan["symbols"]) > 2:
        choices = "、".join(f"`{symbol}`" for symbol in plan["symbols"])
        return AgentResult(
            f"一次最多比较 2 只股票，当前识别到 {choices}。请保留其中两只后再问，确保每只都有完整且对称的证据。",
            {"intent": "too_many_symbols", "symbols": plan["symbols"], "tools": [], "agents": [], "complexity": profile.key},
            [],
            status="needs_clarification",
        )
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
    scripted_calls = bounded_tool_calls(plan_tool_calls(plan, profile), steps, len(symbols))
    for index, call in enumerate(scripted_calls):
        result = registry.execute(call.name, call.arguments, allowed)
        tool_trace.append({"step": index + 1, "call": call.__dict__, "result": result})

    required_tool = "get_market_context" if plan["intent"] == "market" else "get_quote"
    has_required_evidence = any(
        item["call"]["name"] == required_tool and item["result"].get("ok")
        for item in tool_trace
    )
    llm = synthesize_with_llm(effective_message, plan, tool_trace, settings, clean_history, profile) if has_required_evidence else None
    if llm and answer_matches_quote(llm, tool_trace):
        return AgentResult(llm, build_card(plan, tool_trace, profile), tool_trace)
    status = "degraded" if tool_trace and not has_required_evidence else "ok"
    return AgentResult(fallback_answer(effective_message, plan, tool_trace, symbols), build_card(plan, tool_trace, profile), tool_trace, status=status)


def clarification_result(code: str, profile: AgentProfile) -> AgentResult:
    """Ask once before interpreting an unqualified short numeric code as Hong Kong stock."""
    if code == "1810":
        question = "你指的是港股 **小米集团-W（01810.HK）** 吗？"
        reply_hint = "回复“是”“小米”或“港股”即可继续；如果不是，请提供完整股票代码。"
    elif code == "700":
        question = "你指的是港股 **腾讯控股（00700.HK）** 吗？"
        reply_hint = "回复“是”“腾讯”或“港股”即可继续；如果不是，请提供完整股票代码。"
    else:
        question = "你指的是港股代码吗？"
        reply_hint = "回复“港股”即可继续；如果不是，请提供带市场信息的完整股票代码。"
    content = f"先确认一下标的：裸代码 `{code}` 不能唯一说明市场。{question}\n\n{reply_hint}A 股代码通常为 6 位。"
    card = {"intent": "symbol_clarification", "pending_code": code, "symbols": [], "tools": [], "agents": [], "complexity": profile.key}
    return AgentResult(content, card, [], status="needs_clarification")


def resolve_clarification(message: str, history: list[dict[str, Any]]) -> str | None:
    """Resolve a user's short confirmation against the immediately preceding ambiguity prompt."""
    code = pending_clarification_code(history)
    if not code:
        return None
    selected = extract_symbols(message)
    if not selected and re.search(r"^(?:是|对|没错|港股|是港股|就是港股)[。.!！?？]?$", message.strip(), re.IGNORECASE):
        selected = [f"HK{code.zfill(4)}"]
    if not selected:
        return None
    original = next((item["content"] for item in reversed(history[:-1]) if item["role"] == "user"), "")
    if not original:
        return message
    return re.sub(r"^\s*\d{1,5}", selected[0], original, count=1)


def pending_clarification_code(history: list[dict[str, Any]]) -> str:
    """Read the pending code from structured metadata, with compatibility for older chat history."""
    if len(history) < 2 or history[-1].get("role") != "assistant":
        return ""
    card = history[-1].get("card")
    pending_code = card.get("pending_code") if isinstance(card, dict) and card.get("intent") == "symbol_clarification" else None
    code_match = re.search(r"裸代码 `?(\d{1,5})`?", str(history[-1].get("content", "")))
    return str(pending_code or (code_match.group(1) if code_match else ""))


def bounded_tool_calls(calls: list[ToolCall], steps: int, symbol_count: int) -> list[ToolCall]:
    """Keep tool coverage symmetric for comparisons instead of truncating the second symbol."""
    if symbol_count <= 1:
        return calls[:steps]
    selected: list[ToolCall] = []
    index = 0
    while index < len(calls):
        name = calls[index].name
        group: list[ToolCall] = []
        while index < len(calls) and calls[index].name == name:
            group.append(calls[index])
            index += 1
        if len(selected) + len(group) <= steps:
            selected.extend(group)
    return selected


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
    focus_priorities = {
        "fundamentals": ("get_quote", "get_fundamentals", "get_indicators", "search_news", "get_last_report", "get_history", "get_signal_tracking"),
        "news": ("get_quote", "search_news", "get_indicators", "get_last_report", "get_history", "get_signal_tracking", "get_fundamentals"),
        "report": ("get_quote", "get_last_report", "get_signal_tracking", "get_indicators", "get_history", "search_news", "get_fundamentals"),
        "technical": ("get_quote", "get_indicators", "get_history", "search_news", "get_last_report", "get_signal_tracking", "get_fundamentals"),
    }
    prioritized_tools = focus_priorities.get(plan.get("focus"), focus_priorities["technical"])
    for tool_name in prioritized_tools:
        if tool_name not in plan["allowed_tools"]:
            continue
        for symbol in symbols[:2]:
            arguments = {"symbol": symbol}
            if tool_name == "get_history":
                arguments["days"] = 60
            calls.append(ToolCall(str(uuid.uuid4()), tool_name, arguments))
    return calls


def synthesize_with_llm(
    message: str,
    plan: dict,
    tool_trace: list[dict],
    settings: Settings,
    history: list[dict[str, Any]] | None = None,
    profile: AgentProfile | None = None,
) -> str | None:
    """Ask the configured LLM to summarize tool evidence, returning None on failure."""
    if not settings.llm_api_key:
        return None
    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url)
        prior_messages = [
            {"role": "user", "content": item["content"]}
            for item in (history or [])[-8:]
            if item["role"] == "user"
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
        return clean_llm_answer(content, message) if isinstance(content, str) and content.strip() else None
    except Exception:
        return None


def clean_llm_answer(content: str, question: str = "") -> str:
    """Remove unsolicited trailing machine metadata from a Markdown answer."""
    answer = content.strip()
    if re.search(r"\bjson\b|结构化数据|机器格式", question, re.IGNORECASE):
        return answer
    answer = re.sub(r"\n*```(?:json|xml|yaml)\s+[\s\S]*?```\s*$", "", answer, flags=re.IGNORECASE).strip()
    marker = answer.rfind("\n{")
    if marker >= 0:
        candidate = answer[marker + 1:].strip()
        try:
            if isinstance(json.loads(candidate), dict):
                answer = answer[:marker].rstrip()
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
    return answer


def answer_matches_quote(answer: str, trace: list[dict]) -> bool:
    """Reject a synthesized answer when its displayed current price differs from fresh tool evidence."""
    quotes = [
        item["result"].get("result", {})
        for item in trace
        if item.get("call", {}).get("name") == "get_quote" and item.get("result", {}).get("ok")
    ]
    for quote in quotes:
        price = quote.get("price")
        if not isinstance(price, (int, float)):
            continue
        exact = f"{price:g}"
        if not re.search(rf"(?<!\d){re.escape(exact)}(?:\.0+)?(?!\d)", answer):
            return False
    return True


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
        if item["call"]["name"] == "get_quote":
            delayed = "（公开行情可能延迟）" if payload.get("is_delayed") else ""
            lines.append(f"- {payload.get('symbol', symbols[0] if symbols else '标的')}：最新可用价 {payload.get('price', '-')}，涨跌幅 {payload.get('change_pct', '-')}%，数据时间 {payload.get('as_of') or '-'}{delayed}。")
        elif item["call"]["name"] == "get_market_context":
            lines.append(f"- {market_label(payload['market'])}：状态 {market_regime_label(payload['market_regime'])}，评分 {payload['score']}/100，策略倾向 {strategy_bias_label(payload['strategy_bias'])}")
        elif item["call"]["name"] == "get_history":
            lines.append(f"- 历史走势：已检查最近 {len(payload.get('bars', []))} 根日线。")
        elif item["call"]["name"] == "get_indicators":
            lines.append(f"- 技术指标：MA20 {payload['trend']['ma20']}，RSI {payload['momentum']['rsi14']}，ATR {payload['levels']['atr_pct']}%")
        elif item["call"]["name"] == "get_fundamentals":
            coverage = [key for key in ("valuation", "growth", "quality", "earnings", "industry") if payload.get(key)]
            lines.append(f"- 基本面：取得 {len(coverage)} 个数据分组（{'、'.join(coverage) or '暂无有效字段'}）。")
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


def normalize_history(history: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Keep only recent plain user/assistant messages supplied by the client."""
    normalized: list[dict[str, Any]] = []
    if not isinstance(history, list):
        return normalized
    for item in history[-12:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", ""))
        content = str(item.get("content", "")).strip()
        if role in {"user", "assistant"} and content:
            normalized_item: dict[str, Any] = {"role": role, "content": content[:6000]}
            card = item.get("card")
            if isinstance(card, dict):
                normalized_item["card"] = {
                    "intent": str(card.get("intent", ""))[:64],
                    "pending_code": str(card.get("pending_code", ""))[:8],
                    "symbols": [str(symbol)[:32] for symbol in card.get("symbols", [])[:2]] if isinstance(card.get("symbols"), list) else [],
                }
            normalized.append(normalized_item)
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
        "get_fundamentals": "基本面",
        "search_news": "资讯检索",
        "get_last_report": "历史报告",
        "get_signal_tracking": "信号追踪",
        "get_market_context": "市场上下文",
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
