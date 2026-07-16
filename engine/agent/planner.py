from __future__ import annotations

import re
from typing import Any

from engine.data.normalize import normalize_symbol


STOCK_TOPIC_PATTERN = re.compile(
    r"股票|个股|大盘|指数|市场|行情|股价|走势|趋势|技术面|基本面|估值|财报|公告|新闻|"
    r"买入|卖出|持仓|仓位|止损|止盈|风险|策略|突破|支撑|压力|复盘|跟踪|追踪|"
    r"上涨|下跌|涨停|跌停|追涨|抄底|做\s*T|T\+0|日内交易|"
    r"stock|market|price|quote|trend|risk|buy|sell|hold|portfolio|breakout|support|resistance|"
    r"rsi|macd|ma\d*|etf",
    re.IGNORECASE,
)

FOLLOW_UP_PATTERN = re.compile(
    r"它|这个|这只|该股|刚才|上面|那|继续|再看|还有|呢|风险|止损|目标|仓位|能买吗|能卖吗|"
    r"it|this|that|more|continue|risk|target|stop",
    re.IGNORECASE,
)

BARE_NUMERIC_SYMBOL_PATTERN = re.compile(r"^\s*(\d{1,5})(?!\d)")
EXPLICIT_HK_HINT_PATTERN = re.compile(r"港股|港交所|小米|\bHK\b|\.HK\b", re.IGNORECASE)

COMPANY_SYMBOL_ALIASES = {
    "腾讯控股": "HK0700",
    "腾讯": "HK0700",
    "阿里巴巴": "HK9988",
    "小米集团": "HK1810",
    "小米": "HK1810",
}


def parse_intent(message: str, context_symbols: list[str] | None = None) -> dict:
    """Infer requested analysis intent, symbols, and market from free-form text."""
    text = message.strip()
    symbols = extract_symbols(text)
    if not symbols and context_symbols and FOLLOW_UP_PATTERN.search(text):
        symbols = context_symbols[:2]
    lower = text.lower()
    wants_fundamentals = any(word in lower for word in ["基本面", "估值", "财报", "业绩", "市盈率", "市净率", "pe", "pb", "fundamental", "earnings", "valuation"])
    wants_news = any(word in lower for word in ["新闻", "公告", "消息", "news"])
    if not symbols and any(word in lower for word in ["market", "大盘", "指数", "复盘"]):
        return {"intent": "market", "focus": "market", "symbols": symbols, "market": detect_market(lower), "allowed_tools": ["get_market_context", "search_news"]}
    if any(word in lower for word in ["last report", "上次报告", "历史报告", "tracking", "追踪", "报告"]):
        tools = ["get_last_report", "get_signal_tracking", "get_quote", "get_indicators"]
        if wants_fundamentals:
            tools.append("get_fundamentals")
        return {"intent": "report_followup", "focus": "report", "symbols": symbols, "allowed_tools": tools}
    if any(word in lower for word in ["突破", "breakout", "策略", "strategy", "追", "持仓", "仓位", "止损", "止盈", "风险", "买", "卖", "做t", "t+0", "日内"]):
        tools = ["get_quote", "get_indicators", "search_news", "get_last_report", "get_signal_tracking"]
        if wants_fundamentals:
            tools.append("get_fundamentals")
        return {"intent": "stock_decision", "focus": "fundamentals" if wants_fundamentals else "news" if wants_news else "technical", "symbols": symbols, "allowed_tools": tools}
    tools = ["get_quote", "get_indicators", "search_news", "get_last_report"]
    if wants_fundamentals:
        tools.append("get_fundamentals")
    return {"intent": "general_stock", "focus": "fundamentals" if wants_fundamentals else "news" if wants_news else "technical", "symbols": symbols, "allowed_tools": tools}


def is_stock_question(message: str, history: list[dict[str, Any]] | None = None) -> bool:
    """Reject clearly unrelated prompts before any analysis tool is called."""
    text = message.strip()
    if not text:
        return False
    if extract_symbols(text) or STOCK_TOPIC_PATTERN.search(text):
        return True
    return bool(history and FOLLOW_UP_PATTERN.search(text) and conversation_symbols(history))


def conversation_symbols(history: list[dict[str, Any]] | None) -> list[str]:
    """Find trusted symbols from result metadata or the latest user message."""
    for item in reversed(history or []):
        card = item.get("card") if isinstance(item, dict) else None
        card_symbols = card.get("symbols") if isinstance(card, dict) else None
        if isinstance(card_symbols, list) and card_symbols:
            symbols = []
            for symbol in card_symbols:
                if not isinstance(symbol, str):
                    continue
                try:
                    symbols.append(normalize_symbol(symbol).display)
                except ValueError:
                    continue
            if symbols:
                return symbols[:2]
        if item.get("role") != "user":
            continue
        symbols = extract_symbols(str(item.get("content", "")))
        if symbols:
            return symbols[:2]
    return []


def extract_symbols(text: str) -> list[str]:
    """Extract and normalize distinct stock symbols mentioned in text."""
    candidates: list[tuple[int, int, str]] = []
    market_pattern = r"(?<![A-Za-z0-9])HK\d{1,5}(?!\d)|(?<!\d)\d{1,5}\.HK(?![A-Za-z0-9])|(?<!\d)\d{6}(?!\d)"
    for match in re.finditer(market_pattern, text, re.IGNORECASE):
        candidates.append((match.start(), 1, match.group(0).upper()))
    for match in re.finditer(r"(?<![A-Za-z0-9])[A-Z]{1,5}(?:\.[A-Z]{1,3})?(?![A-Za-z0-9])", text):
        candidates.append((match.start(), 2, match.group(0)))
    leading_lowercase = re.match(r"^\s*([a-z]{1,5}(?:\.[a-z]{1,3})?)(?=[\u3400-\u9fff，。！？])", text)
    if leading_lowercase:
        candidates.append((leading_lowercase.start(1), 2, leading_lowercase.group(1).upper()))
    for company_name, symbol in COMPANY_SYMBOL_ALIASES.items():
        start = text.find(company_name)
        if start >= 0:
            candidates.append((start, 0, symbol))
    leading_hk = leading_bare_code(text)
    if leading_hk:
        candidates.append((leading_hk.start(1), 1, leading_hk.group(1)))

    candidates.sort(key=lambda item: (item[0], item[1]))
    raw = [item[2] for item in candidates]
    if re.search(r"做\s*T|T\+0", text, re.IGNORECASE):
        raw = [item for item in raw if item != "T"]
    explicit_hk = bool(re.search(r"(?<![A-Za-z0-9])HK\d{1,5}(?!\d)|(?<!\d)\d{1,5}\.HK(?![A-Za-z0-9])", text, re.IGNORECASE))
    # Hong Kong share-class suffixes such as 阿里巴巴-SW and 小米集团-W are
    # company labels, not standalone US tickers.
    if explicit_hk and re.search(r"[-－](?:SW|W|S|SS)\b", text, re.IGNORECASE):
        raw = [item for item in raw if item not in {"SW", "W", "S", "SS"}]
    ignored = {
        "A", "I", "AM", "IS", "ARE", "BE", "DO", "DID", "THE", "TO", "OR", "AND", "VS",
        "CAN", "COULD", "BUY", "SELL", "HOLD", "AFTER", "THIS", "THAT", "WITH", "FOR", "FROM",
        "HK", "US", "CN", "ETF", "RSI", "MACD", "MA",
    }
    out = []
    for item in raw:
        if item not in ignored:
            try:
                out.append(normalize_symbol(item).display)
            except ValueError:
                continue
    return list(dict.fromkeys(out))


def ambiguous_bare_symbol(text: str) -> str | None:
    """Return an unqualified short numeric code that needs market confirmation."""
    match = leading_bare_code(text)
    if not match or match.group(1) == "700" or EXPLICIT_HK_HINT_PATTERN.search(text):
        return None
    return match.group(1)


def leading_bare_code(text: str) -> re.Match[str] | None:
    """Recognize a leading short code while excluding obvious dates, prices, and percentages."""
    match = BARE_NUMERIC_SYMBOL_PATTERN.match(text)
    if not match:
        return None
    suffix = text[match.end():].lstrip()
    if re.match(r"^(?:年|年度|财年|季度|季|月|日|号|点|元|块|%|％)", suffix):
        return None
    return match


def detect_market(text: str) -> str:
    """Detect a CN, HK, or US market hint, defaulting to CN."""
    if "港" in text or "hk" in text:
        return "hk"
    if "美" in text or "us" in text or "nasdaq" in text:
        return "us"
    return "cn"
