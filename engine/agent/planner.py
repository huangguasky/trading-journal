from __future__ import annotations

import re
from typing import Any

from engine.data.normalize import normalize_symbol


STOCK_TOPIC_PATTERN = re.compile(
    r"股票|个股|大盘|指数|市场|行情|股价|走势|趋势|技术面|基本面|估值|财报|公告|新闻|"
    r"买入|卖出|持仓|仓位|止损|止盈|风险|策略|突破|支撑|压力|复盘|跟踪|追踪|"
    r"上涨|下跌|涨停|跌停|追涨|抄底|"
    r"stock|market|price|quote|trend|risk|buy|sell|hold|portfolio|breakout|support|resistance|"
    r"rsi|macd|ma\d*|etf",
    re.IGNORECASE,
)

FOLLOW_UP_PATTERN = re.compile(
    r"它|这个|这只|该股|刚才|上面|那|继续|再看|还有|呢|风险|止损|目标|仓位|能买吗|能卖吗|"
    r"it|this|that|more|continue|risk|target|stop",
    re.IGNORECASE,
)


def parse_intent(message: str, context_symbols: list[str] | None = None) -> dict:
    """Infer requested analysis intent, symbols, and market from free-form text."""
    text = message.strip()
    symbols = extract_symbols(text)
    if not symbols and context_symbols and FOLLOW_UP_PATTERN.search(text):
        symbols = context_symbols[:2]
    lower = text.lower()
    if any(word in lower for word in ["market", "大盘", "指数", "复盘"]):
        return {"intent": "market", "symbols": symbols, "market": detect_market(lower), "allowed_tools": ["get_market_context", "search_news"]}
    if any(word in lower for word in ["昨天", "last report", "变化", "tracking", "追踪", "报告"]):
        return {"intent": "report_followup", "symbols": symbols, "allowed_tools": ["get_last_report", "get_signal_tracking", "get_quote", "get_indicators"]}
    if any(word in lower for word in ["突破", "breakout", "策略", "strategy", "追", "持仓", "买", "卖"]):
        return {"intent": "stock_decision", "symbols": symbols, "allowed_tools": ["get_quote", "get_indicators", "search_news", "get_last_report", "get_signal_tracking", "run_stock_report"]}
    return {"intent": "general_stock", "symbols": symbols, "allowed_tools": ["get_quote", "get_indicators", "search_news", "get_last_report"]}


def is_stock_question(message: str, history: list[dict[str, Any]] | None = None) -> bool:
    """Reject clearly unrelated prompts before any analysis tool is called."""
    text = message.strip()
    if not text:
        return False
    if extract_symbols(text) or STOCK_TOPIC_PATTERN.search(text):
        return True
    return bool(history and FOLLOW_UP_PATTERN.search(text) and conversation_symbols(history))


def conversation_symbols(history: list[dict[str, Any]] | None) -> list[str]:
    """Find the most recently discussed symbols in a bounded chat history."""
    for item in reversed(history or []):
        symbols = extract_symbols(str(item.get("content", "")))
        if symbols:
            return symbols
    return []


def extract_symbols(text: str) -> list[str]:
    """Extract and normalize distinct stock symbols mentioned in text."""
    pattern = r"\bHK\d{1,5}\b|\b\d{1,5}\.HK\b|\b\d{6}\b|\b[A-Z]{1,5}(?:\.[A-Z]{1,3})?\b"
    raw = re.findall(pattern, text.upper())
    ignored = {"A", "HK", "US", "CN", "ETF", "RSI", "MACD", "MA"}
    out = []
    for item in raw:
        if item not in ignored:
            try:
                out.append(normalize_symbol(item).display)
            except ValueError:
                continue
    return list(dict.fromkeys(out))


def detect_market(text: str) -> str:
    """Detect a CN, HK, or US market hint, defaulting to CN."""
    if "港" in text or "hk" in text:
        return "hk"
    if "美" in text or "us" in text or "nasdaq" in text:
        return "us"
    return "cn"
