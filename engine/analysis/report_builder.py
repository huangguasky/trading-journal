from __future__ import annotations

from engine.time_utils import today_cn


def build_stock_report(payload: dict) -> tuple[dict, str]:
    indicators = payload["indicators"]
    strategies = payload["strategies"]
    quote = payload["quote"]
    evidence = payload["evidence"]
    strategy_stack = evidence.get("strategy_stack", {})
    core_strategies = strategy_stack.get("core", strategies[:3])
    score = score_stock(core_strategies, indicators, evidence.get("data_quality", {}))
    rating = rating_for_score(score)
    action = action_for(score, indicators, evidence)
    plan = build_operation_plan(quote, indicators, score, core_strategies)
    risk_items = risk_flags(indicators, evidence.get("conflicts", []), core_strategies)
    report = {
        "type": "stock_report",
        "symbol": payload["symbol"],
        "market": payload["market"],
        "date": today_cn(),
        "score": score,
        "rating": rating,
        "action": action,
        "quote": quote,
        "evidence": evidence,
        "strategies": strategies,
        "selected_strategies": core_strategies,
        "news": payload["news"],
        "data_quality": evidence.get("data_quality", {}),
        "risk_flags": risk_items,
        "operation_plan": plan,
        "tracking": {
            "base_price": quote["price"],
            "target_price": plan["target"],
            "stop_price": plan["stop"],
            "review_after_days": 5,
            "watch_conditions": plan["watch_conditions"],
        },
    }
    return report, render_stock_markdown(report)


def build_market_report(payload: dict) -> tuple[dict, str]:
    report = {
        "market": payload["market"],
        "date": today_cn(),
        "market_regime": payload["market_regime"],
        "score": payload["score"],
        "indices": payload["indices"],
        "breadth": payload["breadth"],
        "sector_rotation": payload["sector_rotation"],
        "macro_news": payload["macro_news"],
        "risk_flags": payload["risk_flags"],
        "tomorrow_watch": payload["tomorrow_watch"],
        "strategy_bias": payload["strategy_bias"],
        "data_quality": payload.get("data_quality", {}),
        "market_context": payload.get("market_context", {}),
    }
    return report, render_market_markdown(report)


def score_stock(strategies: list[dict], indicators: dict, data_quality: dict) -> float:
    strategy_score = sum(item["score"] for item in strategies) / max(1, len(strategies))
    trend_bonus = 4 if indicators["trend"]["above_ma60"] else -5
    volume_bonus = 3 if indicators["volume"]["volume_ratio_5_20"] >= 1 else -2
    risk_penalty = 5 if indicators["levels"]["atr_pct"] > 6 else 0
    quality_penalty = 8 if any((data_quality.get(key) or {}).get("confidence") == "low" for key in ("history", "price", "news")) else 0
    return round(max(0, min(100, strategy_score + trend_bonus + volume_bonus - risk_penalty - quality_penalty)), 1)


def build_operation_plan(quote: dict, indicators: dict, score: float, strategies: list[dict]) -> dict:
    support = indicators["levels"]["support_20d"]
    resistance = indicators["levels"]["resistance_20d"]
    atr_pct = indicators["levels"]["atr_pct"]
    top_name = strategies[0]["name"] if strategies else "综合策略"
    entry = f"以「{top_name}」为主线，优先等待放量站上 {resistance}，或回踩 {support} 附近企稳后分批观察。"
    if score < 50:
        entry = f"当前不适合主动追买，除非重新站回 {resistance} 且量能修复，否则以观察和风险控制为主。"
    target = round(quote["price"] * (1 + max(0.04, atr_pct / 100 * 2)), 3)
    return {
        "entry": entry,
        "stop": support,
        "target": target,
        "position": position_hint(score, atr_pct),
        "watch_conditions": [
            f"收盘价能否站稳 20 日线 {indicators['trend']['ma20']}",
            f"成交量比值能否维持在 1.0 以上，当前为 {indicators['volume']['volume_ratio_5_20']}",
            f"若跌破 {support}，原有策略假设需要重新评估",
        ],
    }


def rating_for_score(score: float) -> str:
    if score >= 78:
        return "强势关注"
    if score >= 62:
        return "偏多观察"
    if score >= 48:
        return "中性震荡"
    return "防御回避"


def action_for(score: float, indicators: dict, evidence: dict) -> str:
    if evidence.get("conflicts") and score < 70:
        return "有机会但证据不完整，等待确认优先"
    if score >= 75 and indicators["levels"]["atr_pct"] <= 4.5:
        return "可按计划分批参与或继续持有"
    if score >= 60:
        return "等待突破或回踩确认"
    if score >= 45:
        return "轻仓观察，不追高"
    return "优先控制风险"


def position_hint(score: float, atr_pct: float) -> str:
    if score < 50:
        return "观望或极轻仓"
    if atr_pct >= 6:
        return "小仓位：波动较高"
    if atr_pct >= 4:
        return "正常偏轻"
    return "正常仓位"


def risk_flags(indicators: dict, conflicts: list[str], strategies: list[dict]) -> list[str]:
    flags = list(conflicts)
    for strategy in strategies:
        flags.extend(strategy.get("risks", [])[:2])
    if indicators["momentum"]["rsi14"] > 75:
        flags.append("RSI 进入偏热区，短线不宜情绪化追高。")
    if indicators["levels"]["atr_pct"] > 5:
        flags.append("ATR 波动偏高，应降低仓位或拉长观察周期。")
    if not indicators["trend"]["above_ma60"]:
        flags.append("价格仍在 60 日均线下方，中期趋势尚未确认。")
    return list(dict.fromkeys(flags))[:8]


def render_stock_markdown(report: dict) -> str:
    plan = report["operation_plan"]
    strategies = "\n".join(format_strategy_line(item) for item in report["selected_strategies"])
    support_strategies = "\n".join(format_strategy_line(item) for item in report["strategies"][len(report["selected_strategies"]):len(report["selected_strategies"]) + 4])
    confirmations = "\n".join(f"- {item}" for item in report["evidence"].get("confirmations", []))
    risks = "\n".join(f"- {item}" for item in report["risk_flags"]) or "- 暂无明显风险信号。"
    news = "\n".join(f"- {item['title']}（{item.get('source', 'unknown')}）" for item in report["news"]) or "- 暂无相关新闻。"
    quality = render_quality(report.get("data_quality", {}))
    watch = "\n".join(f"- {item}" for item in plan["watch_conditions"])
    return f"""# {report['symbol']} 个股分析报告

生成日期：{report['date']}
综合评分：{report['score']}/100
评级：{report['rating']}
操作建议：{report['action']}

## 1. 决策摘要
当前价格为 {report['quote']['price']} {report['quote']['currency']}，涨跌幅 {report['quote']['change_pct']}%。建议仓位为「{plan['position']}」，止损参考 {plan['stop']}，目标观察 {plan['target']}。

## 2. 核心证据
{confirmations}

## 3. 策略融合
{strategies}

辅助观察：
{support_strategies or "- 暂无额外辅助策略。"}

## 4. 资讯与风险
{news}

风险提示：
{risks}

## 5. 操作计划
- 入场：{plan['entry']}
- 止损：{plan['stop']}
- 目标：{plan['target']}
- 仓位：{plan['position']}

后续追踪：
{watch}

## 6. 数据质量
{quality}
"""


def render_market_markdown(report: dict) -> str:
    indices = "\n".join(f"- {item['symbol']}: {item['price']}（{item['change_pct']}%）" for item in report["indices"])
    leaders = "、".join(report["sector_rotation"]["leaders"])
    laggards = "、".join(report["sector_rotation"]["laggards"])
    risks = "\n".join(f"- {item}" for item in report["risk_flags"]) or "- 暂无明显风险信号。"
    watch = "\n".join(f"- {item}" for item in report["tomorrow_watch"])
    news = "\n".join(f"- {item['title']}（{item.get('source', 'unknown')}）" for item in report["macro_news"])
    context = report.get("market_context", {})
    quality = render_quality({"market": report.get("data_quality", {})})
    return f"""# {market_label(report['market'])}市场复盘

生成日期：{report['date']}
市场状态：{market_regime_label(report['market_regime'])}
市场评分：{report['score']}/100
策略倾向：{strategy_bias_label(report['strategy_bias'])}

## 1. 市场结论
当前市场宽度为上涨 {report['breadth'].get('advancers')} 家、下跌 {report['breadth'].get('decliners')} 家。总体判断为「{market_regime_label(report['market_regime'])}」，更适合采用「{strategy_bias_label(report['strategy_bias'])}」框架。

## 2. 主要指数
{indices}

## 3. 市场宽度与情绪
- 涨停家数：{report['breadth'].get('limit_up')}
- 跌停家数：{report['breadth'].get('limit_down')}
- 成交额：{report['breadth'].get('turnover_billion')} 亿（估算）
- 情绪描述：{context.get('sentiment', '中性')}

## 4. 板块轮动
- 领先方向：{leaders}
- 落后方向：{laggards}

## 5. 宏观与事件
{news}

## 6. 风险提示
{risks}

## 7. 明日关注
{watch}

## 8. 数据质量
{quality}
"""


def format_strategy_line(strategy: dict) -> str:
    evidence = "；".join(strategy.get("evidence", [])[:2]) or "暂无明确证据"
    return f"- {strategy.get('name')}：{strategy.get('score')}/100（{stance_label(strategy.get('stance', ''))}），{evidence}"


def render_quality(data_quality: dict) -> str:
    if not data_quality:
        return "- 未记录数据质量。"
    lines: list[str] = []
    for name, block in data_quality.items():
        if not isinstance(block, dict):
            continue
        source = block.get("source") or ",".join(block.get("sources", [])) or "unknown"
        lines.append(f"- {quality_label(name)}：{block.get('status', 'unknown')}，来源 {source}，置信度 {block.get('confidence', 'unknown')}")
        for note in block.get("notes", [])[:2]:
            lines.append(f"  - {note}")
    return "\n".join(lines) or "- 未记录数据质量。"


def quality_label(value: str) -> str:
    return {"history": "K线", "price": "行情", "news": "资讯", "market": "市场快照"}.get(value, value)


def stance_label(value: str) -> str:
    return {"positive": "偏多", "neutral": "中性", "negative": "偏空"}.get(value, value)


def market_label(value: str) -> str:
    return {"cn": "A股", "hk": "港股", "us": "美股"}.get(value, value.upper())


def market_regime_label(value: str) -> str:
    return {"risk_on": "风险偏好升温", "neutral": "震荡均衡", "risk_off": "防御优先", "volatile": "高波动震荡"}.get(value, value)


def strategy_bias_label(value: str) -> str:
    return {"trend": "趋势跟随", "defensive": "防御优先", "wait": "等待确认", "event": "事件驱动"}.get(value, value)
