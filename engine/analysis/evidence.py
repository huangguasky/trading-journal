from __future__ import annotations


def build_stock_evidence(symbol: str, quote: dict, indicators: dict, news: list[dict], strategies: list[dict], data_quality: dict | None = None) -> dict:
    """Assemble the facts, confirmations, conflicts, and strategy stack for a stock."""
    selected = select_strategy_stack(strategies)
    return {
        "symbol": symbol,
        "price": quote,
        "technical": indicators,
        "news": news,
        "strategy_stack": selected,
        "data_quality": data_quality or {},
        "conflicts": detect_conflicts(indicators, strategies, data_quality or {}),
        "confirmations": build_confirmations(indicators, selected),
    }


def select_strategy_stack(strategies: list[dict]) -> dict:
    """Select the strongest primary strategy and supporting secondary strategies."""
    positive = [item for item in strategies if item.get("stance") == "positive"]
    neutral = [item for item in strategies if item.get("stance") == "neutral"]
    defensive = [item for item in strategies if item.get("stance") == "negative"]
    core = (positive or neutral or strategies)[:3]
    support = [item for item in strategies if item not in core][:4]
    return {
        "core": core,
        "support": support,
        "defensive": defensive[:3],
        "top": core[0] if core else {},
    }


def build_confirmations(indicators: dict, stack: dict) -> list[str]:
    """Describe indicator and strategy signals that reinforce the thesis."""
    confirmations: list[str] = []
    if indicators["trend"]["above_ma20"] and indicators["trend"]["above_ma60"]:
        confirmations.append("价格站上 20 日和 60 日均线，趋势结构具备延续基础。")
    if indicators["volume"]["volume_ratio_5_20"] >= 1.1:
        confirmations.append("近 5 日成交量高于 20 日均量，资金参与度有所抬升。")
    if indicators["momentum"]["macd_hist"] > 0:
        confirmations.append("MACD 柱体为正，短线动能处于修复或扩张阶段。")
    top = stack.get("top") or {}
    if top:
        confirmations.append(f"策略主线偏向「{top.get('name')}」，评分 {top.get('score')}/100。")
    return confirmations or ["当前证据偏中性，需要等待价格、量能或事件催化进一步确认。"]


def detect_conflicts(indicators: dict, strategies: list[dict], data_quality: dict) -> list[str]:
    """Identify contradictory signals and data-quality limitations."""
    conflicts: list[str] = []
    if indicators["trend"]["above_ma60"] and indicators["momentum"]["rsi14"] > 78:
        conflicts.append("趋势结构偏多，但 RSI 已进入过热区，追高性价比下降。")
    if indicators["volume"]["volume_ratio_5_20"] < 0.75 and strategies and strategies[0]["stance"] == "positive":
        conflicts.append("策略评分偏多，但量能确认不足，突破类结论需要打折。")
    if indicators["levels"]["atr_pct"] > 6:
        conflicts.append("ATR 波动率较高，入场时机容易受到短线噪声影响。")
    if data_quality.get("price", {}).get("confidence") == "low" or data_quality.get("history", {}).get("confidence") == "low":
        conflicts.append("行情数据处于降级状态，本次结论置信度需要下调。")
    return conflicts
