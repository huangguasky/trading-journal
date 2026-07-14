from __future__ import annotations

from engine.time_utils import today_cn


def build_stock_report(payload: dict) -> tuple[dict, str]:
    """Turn a stock-analysis payload into a structured report and Markdown."""
    indicators = payload["indicators"]
    strategies = payload["strategies"]
    quote = payload["quote"]
    evidence = payload["evidence"]
    strategy_stack = evidence.get("strategy_stack", {})
    core_strategies = strategy_stack.get("core", strategies[:3])
    data_quality = evidence.get("data_quality", {})
    score = score_stock(core_strategies, indicators, data_quality)
    rating = rating_for_score(score)
    confidence = build_confidence(data_quality)
    decision_limits = build_decision_limits(data_quality, payload.get("market_context", {}))
    action = apply_decision_guardrail(action_for(score, indicators, evidence), decision_limits)
    plan = build_operation_plan(quote, indicators, score, core_strategies)
    plan = apply_plan_guardrail(plan, decision_limits)
    risk_items = risk_flags(indicators, evidence.get("conflicts", []), core_strategies)
    report = {
        "type": "stock_report",
        "symbol": payload["symbol"],
        "market": payload["market"],
        "date": today_cn(),
        "score": score,
        "rating": rating,
        "action": action,
        "confidence": confidence,
        "coverage": build_coverage(data_quality),
        "decision_limits": decision_limits,
        "quote": quote,
        "evidence": evidence,
        "strategies": strategies,
        "selected_strategies": core_strategies,
        "news": payload["news"],
        "intelligence": payload.get("intelligence", {}),
        "fundamentals": payload.get("fundamentals", {}),
        "market_context": payload.get("market_context", {}),
        "diagnostics": payload.get("diagnostics", {}),
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
    """Turn a market-analysis payload into a structured report and Markdown."""
    report = {
        "market": payload["market"],
        "date": today_cn(),
        "market_regime": payload["market_regime"],
        "score": payload["score"],
        "indices": payload["indices"],
        "breadth": payload["breadth"],
        "sector_rotation": payload["sector_rotation"],
        "macro_news": payload["macro_news"],
        "news_intelligence": payload.get("news_intelligence", {}),
        "market_dimensions": payload.get("market_dimensions", {}),
        "risk_flags": payload["risk_flags"],
        "tomorrow_watch": payload["tomorrow_watch"],
        "trading_plan": payload.get("trading_plan", {}),
        "strategy_bias": payload["strategy_bias"],
        "data_quality": payload.get("data_quality", {}),
        "market_context": payload.get("market_context", {}),
    }
    return report, render_market_markdown(report)


def score_stock(strategies: list[dict], indicators: dict, data_quality: dict) -> float:
    """Calculate a bounded stock score with strategy, trend, and quality adjustments."""
    strategy_score = sum(item["score"] for item in strategies) / max(1, len(strategies))
    trend_bonus = 4 if indicators["trend"]["above_ma60"] else -5
    volume_bonus = 3 if indicators["volume"]["volume_ratio_5_20"] >= 1 else -2
    risk_penalty = 5 if indicators["levels"]["atr_pct"] > 6 else 0
    quality_penalty = 8 if any((data_quality.get(key) or {}).get("confidence") == "low" for key in ("history", "price", "news")) else 0
    return round(max(0, min(100, strategy_score + trend_bonus + volume_bonus - risk_penalty - quality_penalty)), 1)


def build_operation_plan(quote: dict, indicators: dict, score: float, strategies: list[dict]) -> dict:
    """Derive action, position, entry, target, and stop guidance from analysis."""
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
    """Map a numeric stock score to its qualitative rating."""
    if score >= 78:
        return "强势关注"
    if score >= 62:
        return "偏多观察"
    if score >= 48:
        return "中性震荡"
    return "防御回避"


def action_for(score: float, indicators: dict, evidence: dict) -> str:
    """Choose an action while accounting for score, trend, and evidence conflicts."""
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
    """Suggest position size from conviction and ATR-based volatility."""
    if score < 50:
        return "观望或极轻仓"
    if atr_pct >= 6:
        return "小仓位：波动较高"
    if atr_pct >= 4:
        return "正常偏轻"
    return "正常仓位"


def risk_flags(indicators: dict, conflicts: list[str], strategies: list[dict]) -> list[str]:
    """Collect technical, evidence, and strategy risks for the report."""
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


def build_coverage(data_quality: dict) -> dict:
    """Summarize whether each evidence domain is available to the decision."""
    mapping = {
        "technical": "history",
        "realtime": "realtime",
        "news": "news",
        "fundamentals": "fundamentals",
    }
    return {
        name: (data_quality.get(source) or {}).get("status") in {"ok", "partial"}
        for name, source in mapping.items()
    }


def build_confidence(data_quality: dict) -> dict:
    """Keep directional score separate from evidence sufficiency."""
    history = (data_quality.get("history") or {}).get("confidence")
    available = sum(build_coverage(data_quality).values())
    if history == "low":
        return {"level": "low", "reason": "核心历史行情处于降级状态，技术结论仅供流程观察。"}
    if available >= 3:
        return {"level": "high", "reason": "行情与多个增强证据域可用。"}
    if available >= 2:
        return {"level": "medium", "reason": "核心行情可用，但部分增强证据缺失。"}
    return {"level": "low", "reason": "仅有有限证据域可用，结论需要外部复核。"}


def build_decision_limits(data_quality: dict, market_context: dict | None = None) -> list[str]:
    """Return hard decision constraints caused by missing critical inputs."""
    limits: list[str] = []
    history = data_quality.get("history") or {}
    if history.get("confidence") == "low" or history.get("status") == "unavailable":
        limits.append("真实行情缺失或置信度过低，禁止输出主动买入建议。")
    if (data_quality.get("realtime") or {}).get("status") not in {"ok", "partial"}:
        limits.append("缺少实时行情，入场价、止损价和目标价须在交易前重新核对。")
    if (data_quality.get("news") or {}).get("status") not in {"ok", "partial"}:
        limits.append("缺少可靠资讯，事件催化和风险判断不完整。")
    if (data_quality.get("fundamentals") or {}).get("status") not in {"ok", "partial"}:
        limits.append("缺少基本面数据，质量成长与估值结论不可用。")
    if (data_quality.get("chips") or {}).get("status") == "estimated":
        limits.append("筹码指标是历史收盘价估算值，不可当作真实筹码分布。")
    if (market_context or {}).get("market_regime") == "risk_off":
        limits.append("大盘处于防御状态，仓位上限应下调并提高入场确认要求。")
    return limits


def apply_decision_guardrail(action: str, limits: list[str]) -> str:
    """Prevent strong actions when the core market data is not trustworthy."""
    if any("禁止输出主动买入" in item for item in limits):
        return "数据不足，仅作观察；获取真实行情后重新分析"
    if any("大盘处于防御状态" in item for item in limits) and action.startswith("可按计划"):
        return "大盘偏防御，降低仓位并等待更强确认"
    return action


def apply_plan_guardrail(plan: dict, limits: list[str]) -> dict:
    """Remove executable price guidance when its underlying quote is untrusted."""
    if not any("禁止输出主动买入" in item for item in limits):
        return plan
    guarded = dict(plan)
    guarded.update({
        "entry": "先取得真实行情并重新运行分析，本次不提供可执行入场价。",
        "stop": None,
        "target": None,
        "position": "观望",
        "indicative": False,
    })
    return guarded


def render_stock_markdown(report: dict) -> str:
    """Render a structured stock report as user-facing Markdown."""
    plan = report["operation_plan"]
    strategies = "\n".join(format_strategy_line(item) for item in report["selected_strategies"])
    support_strategies = "\n".join(format_strategy_line(item) for item in report["strategies"][len(report["selected_strategies"]):len(report["selected_strategies"]) + 4])
    confirmations = "\n".join(f"- {item}" for item in report["evidence"].get("confirmations", []))
    risks = "\n".join(f"- {item}" for item in report["risk_flags"]) or "- 暂无明显风险信号。"
    news = "\n".join(f"- {item['title']}（{item.get('source', 'unknown')}）" for item in report["news"]) or "- 暂无相关新闻。"
    quality = render_quality(report.get("data_quality", {}))
    watch = "\n".join(f"- {item}" for item in plan["watch_conditions"])
    confidence = report.get("confidence", {})
    coverage = "、".join(name for name, available in report.get("coverage", {}).items() if available) or "无"
    limits = "\n".join(f"- {item}" for item in report.get("decision_limits", [])) or "- 暂无额外决策限制。"
    fundamentals = render_fundamentals(report.get("fundamentals", {}))
    intelligence = render_intelligence(report.get("intelligence", {}))
    market_context = render_market_context(report.get("market_context", {}))
    return f"""# {report['symbol']} 个股分析报告

生成日期：{report['date']}
综合评分：{report['score']}/100
评级：{report['rating']}
操作建议：{report['action']}
结论置信度：{confidence.get('level', 'unknown')}（{confidence.get('reason', '未说明')}）
证据覆盖：{coverage}
行情截止：{report['quote'].get('as_of', report['date'])}（{'盘中数据' if report['quote'].get('is_partial_bar') else '日线数据'}）

## 1. 决策摘要
当前价格为 {report['quote']['price']} {report['quote']['currency']}，涨跌幅 {report['quote']['change_pct']}%。建议仓位为「{plan['position']}」，止损参考 {plan['stop']}，目标观察 {plan['target']}。

## 2. 核心证据
{confirmations}

## 3. 策略融合
{strategies}

辅助观察：
{support_strategies or "- 暂无额外辅助策略。"}

## 4. 基本面与市场环境
{fundamentals}

{market_context}

## 5. 资讯与风险
{news}

情报分类：
{intelligence}

风险提示：
{risks}

## 6. 操作计划
- 入场：{plan['entry']}
- 止损：{plan['stop']}
- 目标：{plan['target']}
- 仓位：{plan['position']}

后续追踪：
{watch}

失效条件与决策限制：
{limits}

## 7. 数据质量
{quality}
"""


def render_fundamentals(data: dict) -> str:
    if not data:
        return "- 基本面数据不可用，本报告不作估值和成长判断。"
    lines = []
    for group in ("valuation", "growth", "quality", "earnings", "industry"):
        values = data.get(group) or {}
        if values:
            lines.append(f"- {group}: " + "，".join(f"{key}={value}" for key, value in values.items()))
    return "\n".join(lines) or "- 基本面覆盖不足。"


def render_intelligence(data: dict) -> str:
    metrics = data.get("metrics") or {}
    summary = "- 新闻 {news_count} 条，催化 {catalyst_count} 条，风险事件 {risk_event_count} 条，业绩相关 {earnings_news_count} 条。".format(
        news_count=metrics.get("news_count", 0),
        catalyst_count=metrics.get("catalyst_count", 0),
        risk_event_count=metrics.get("risk_event_count", 0),
        earnings_news_count=metrics.get("earnings_news_count", 0),
    )
    social = data.get("social_sentiment") or {}
    if social:
        summary += f"\n- 社交情绪：{social.get('score')}/100，近 7 日提及 {social.get('mentions')} 条（低权重辅助）。"
    return summary


def render_market_context(data: dict) -> str:
    if data.get("status") != "ok":
        return "- 市场环境：暂无可复用的大盘报告。"
    return f"- 市场环境：{data.get('market_regime')}，市场评分 {data.get('score')}，策略倾向 {data.get('strategy_bias')}。"


def render_market_markdown(report: dict) -> str:
    """Render a structured market report as user-facing Markdown."""
    indices = "\n".join(f"- {item['symbol']}: {item['price']}（{item['change_pct']}%）" for item in report["indices"])
    leaders = "、".join(report["sector_rotation"]["leaders"])
    laggards = "、".join(report["sector_rotation"]["laggards"])
    risks = "\n".join(f"- {item}" for item in report["risk_flags"]) or "- 暂无明显风险信号。"
    watch = "\n".join(f"- {item}" for item in report["tomorrow_watch"])
    news = "\n".join(format_market_news(item) for item in report["macro_news"]) or "- 暂无可靠市场资讯。"
    context = report.get("market_context", {})
    dimensions = report.get("market_dimensions", {})
    plan = report.get("trading_plan", {})
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
- 成交额：{report['breadth'].get('turnover_billion')} 亿（{'代表性资产估算' if report['breadth'].get('is_estimated') else '实采'}）
- 情绪描述：{context.get('sentiment', '中性')}
- 指数一致性：{dimensions.get('index_alignment', {}).get('label', '暂无数据')}
- 上涨家数占比：{dimensions.get('breadth', {}).get('advancer_ratio', '暂无数据')}%（{'估算' if dimensions.get('breadth', {}).get('is_estimated') else '实采'}）

## 4. 板块轮动
- 领先方向：{leaders}
- 落后方向：{laggards}
- 数据口径：{'代表性资产与市场模板推导' if report['sector_rotation'].get('is_estimated') else '实采排行'}

## 5. 宏观与事件
{news}

## 6. 风险提示
{risks}

## 7. 明日关注
{watch}

## 8. 明日交易框架
- 风险姿态：{plan.get('stance', '观察')}
- 建议仓位区间：{plan.get('position_range', '未评估')}
- 关注方向：{'、'.join(plan.get('focus', [])) or '暂无'}
- 回避方向：{'、'.join(plan.get('avoid', [])) or '暂无'}
- 失效条件：{plan.get('invalidation', '暂无')}

## 9. 数据质量与边界
{quality}
"""


def format_market_news(item: dict) -> str:
    """Render source, date, topic, and optional link without inventing context."""
    title = item.get("title", "未命名资讯")
    if item.get("url"):
        title = f"[{title}]({item['url']})"
    meta = " / ".join(str(value) for value in (item.get("source"), item.get("date"), item.get("topic")) if value)
    summary = str(item.get("summary") or "").strip()
    return f"- {title}" + (f"（{meta}）" if meta else "") + (f"：{summary}" if summary else "")


def format_strategy_line(strategy: dict) -> str:
    """Format one strategy result for inclusion in Markdown."""
    evidence = "；".join(strategy.get("evidence", [])[:2]) or "暂无明确证据"
    return f"- {strategy.get('name')}：{strategy.get('score')}/100（{stance_label(strategy.get('stance', ''))}），{evidence}"


def render_quality(data_quality: dict) -> str:
    """Render data provenance and fallback notes as a readable sentence."""
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
    """Translate a data-quality code into a user-facing label."""
    return {"history": "K线", "price": "行情", "news": "资讯", "market": "市场快照", "realtime": "实时行情", "fundamentals": "基本面", "chips": "筹码", "social_sentiment": "社交情绪"}.get(value, value)


def stance_label(value: str) -> str:
    """Translate a strategy stance code into a user-facing label."""
    return {"positive": "偏多", "neutral": "中性", "negative": "偏空"}.get(value, value)


def market_label(value: str) -> str:
    """Translate a market code into a user-facing label."""
    return {"cn": "A股", "hk": "港股", "us": "美股"}.get(value, value.upper())


def market_regime_label(value: str) -> str:
    """Translate a market-regime code into a user-facing label."""
    return {"risk_on": "风险偏好升温", "neutral": "震荡均衡", "risk_off": "防御优先", "volatile": "高波动震荡"}.get(value, value)


def strategy_bias_label(value: str) -> str:
    """Translate a strategy-bias code into a user-facing label."""
    return {"trend": "趋势跟随", "defensive": "防御优先", "wait": "等待确认", "event": "事件驱动"}.get(value, value)
