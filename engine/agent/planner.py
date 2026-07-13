from __future__ import annotations

import re

from engine.data.normalize import normalize_symbol


def parse_intent(message: str) -> dict:
    """Infer requested analysis intent, symbols, and market from free-form text."""
    text = message.strip()
    symbols = extract_symbols(text)
    lower = text.lower()
    if any(word in lower for word in ["market", "大盘", "指数", "复盘"]):
        return {"intent": "market", "symbols": symbols, "market": detect_market(lower), "allowed_tools": ["get_market_context", "search_news"]}
    if any(word in lower for word in ["昨天", "last report", "变化", "tracking", "追踪", "报告"]):
        return {"intent": "report_followup", "symbols": symbols, "allowed_tools": ["get_last_report", "get_signal_tracking", "get_quote", "get_indicators"]}
    if any(word in lower for word in ["突破", "breakout", "策略", "strategy", "追", "持仓", "买", "卖"]):
        return {"intent": "stock_decision", "symbols": symbols, "allowed_tools": ["get_quote", "get_indicators", "search_news", "get_last_report", "get_signal_tracking", "run_stock_report"]}
    return {"intent": "general_stock", "symbols": symbols, "allowed_tools": ["get_quote", "get_indicators", "search_news", "get_last_report"]}


def extract_symbols(text: str) -> list[str]:
    """Extract and normalize distinct stock symbols mentioned in text."""
    pattern = r"\bHK\d{1,5}\b|\b\d{6}\b|\b[A-Z]{1,5}(?:\.[A-Z]{1,3})?\b"
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
