from __future__ import annotations

from datetime import date


def build_stock_report(payload: dict) -> tuple[dict, str]:
    indicators = payload["indicators"]
    strategies = payload["strategies"]
    quote = payload["quote"]
    score = round(sum(item["score"] for item in strategies[:3]) / max(1, min(3, len(strategies))), 1)
    rating = rating_for_score(score)
    action = action_for(score, indicators)
    plan = {
        "entry": f"Prefer confirmation above {indicators['levels']['resistance_20d']} or controlled pullback near {indicators['levels']['support_20d']}.",
        "stop": indicators["levels"]["support_20d"],
        "target": round(quote["price"] * (1 + max(0.04, indicators["levels"]["atr_pct"] / 100 * 2)), 3),
        "position": position_hint(indicators["levels"]["atr_pct"]),
    }
    report = {
        "type": "stock_report",
        "symbol": payload["symbol"],
        "market": payload["market"],
        "date": str(date.today()),
        "score": score,
        "rating": rating,
        "action": action,
        "quote": quote,
        "evidence": payload["evidence"],
        "strategies": strategies,
        "news": payload["news"],
        "risk_flags": risk_flags(indicators, payload["evidence"].get("conflicts", [])),
        "operation_plan": plan,
        "tracking": {
            "base_price": quote["price"],
            "target_price": plan["target"],
            "stop_price": plan["stop"],
            "review_after_days": 5,
        },
    }
    return report, render_stock_markdown(report)


def build_market_report(payload: dict) -> tuple[dict, str]:
    report = {
        "market": payload["market"],
        "date": str(date.today()),
        "market_regime": payload["market_regime"],
        "score": payload["score"],
        "indices": payload["indices"],
        "breadth": payload["breadth"],
        "sector_rotation": payload["sector_rotation"],
        "macro_news": payload["macro_news"],
        "risk_flags": payload["risk_flags"],
        "tomorrow_watch": payload["tomorrow_watch"],
        "strategy_bias": payload["strategy_bias"],
    }
    return report, render_market_markdown(report)


def rating_for_score(score: float) -> str:
    if score >= 78:
        return "strong_watch"
    if score >= 62:
        return "constructive"
    if score >= 48:
        return "neutral"
    return "defensive"


def action_for(score: float, indicators: dict) -> str:
    if score >= 75 and indicators["levels"]["atr_pct"] <= 4.5:
        return "planned_buy_or_hold"
    if score >= 60:
        return "wait_for_confirmation"
    if score >= 45:
        return "observe_only"
    return "reduce_risk"


def position_hint(atr_pct: float) -> str:
    if atr_pct >= 6:
        return "small only: volatility is high"
    if atr_pct >= 4:
        return "normal-minus"
    return "normal"


def risk_flags(indicators: dict, conflicts: list[str]) -> list[str]:
    flags = list(conflicts)
    if indicators["momentum"]["rsi14"] > 75:
        flags.append("RSI overheat: avoid emotional chasing.")
    if indicators["levels"]["atr_pct"] > 5:
        flags.append("ATR is high: reduce position size or widen review window.")
    if not indicators["trend"]["above_ma60"]:
        flags.append("Below MA60: medium-term trend has not confirmed.")
    return list(dict.fromkeys(flags))


def render_stock_markdown(report: dict) -> str:
    strategy_lines = "\n".join(f"- {s['name']}: {s['score']}/100 ({s['stance']}) - {'; '.join(s['evidence'][:2])}" for s in report["strategies"][:4])
    risks = "\n".join(f"- {item}" for item in report["risk_flags"]) or "- No major risk flag."
    news = "\n".join(f"- {item['title']}" for item in report["news"]) or "- No news."
    plan = report["operation_plan"]
    return f"""# {report['symbol']} Stock Report

Date: {report['date']}
Score: {report['score']}/100
Rating: {report['rating']}
Action: {report['action']}

## Decision Summary
Price is {report['quote']['price']} {report['quote']['currency']}. The preferred plan is `{plan['position']}` with stop near {plan['stop']} and target near {plan['target']}.

## Strategy Hits
{strategy_lines}

## News / Risk
{news}

## Risk Flags
{risks}

## Operation Plan
- Entry: {plan['entry']}
- Stop: {plan['stop']}
- Target: {plan['target']}
- Position: {plan['position']}
"""


def render_market_markdown(report: dict) -> str:
    indices = "\n".join(f"- {item['symbol']}: {item['price']} ({item['change_pct']}%)" for item in report["indices"])
    leaders = ", ".join(report["sector_rotation"]["leaders"])
    laggards = ", ".join(report["sector_rotation"]["laggards"])
    risks = "\n".join(f"- {item}" for item in report["risk_flags"]) or "- No major risk flag."
    watch = "\n".join(f"- {item}" for item in report["tomorrow_watch"])
    return f"""# {report['market'].upper()} Market Review

Date: {report['date']}
Regime: {report['market_regime']}
Score: {report['score']}/100
Strategy Bias: {report['strategy_bias']}

## Indices
{indices}

## Breadth
- Advancers: {report['breadth'].get('advancers')}
- Decliners: {report['breadth'].get('decliners')}
- Turnover: {report['breadth'].get('turnover_billion')} billion

## Sector Rotation
- Leaders: {leaders}
- Laggards: {laggards}

## Risks
{risks}

## Tomorrow Watch
{watch}
"""

