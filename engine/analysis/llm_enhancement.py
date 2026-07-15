from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from engine.config import Settings


Completion = Callable[[str, dict[str, Any]], str]


class NaturalLanguageEnhancer:
    """Optionally enrich rule results with bounded, structured LLM analysis."""

    def __init__(self, settings: Settings, enabled: bool = True, completion: Completion | None = None):
        self.settings = settings
        self.enabled = enabled
        self.completion = completion

    def enhance_stock(self, context: dict[str, Any]) -> dict[str, Any]:
        """Analyze unstructured stock evidence without replacing numeric rules."""
        return self._enhance("stock", trim_stock_context(context), STOCK_SCHEMA)

    def enhance_market(self, context: dict[str, Any]) -> dict[str, Any]:
        """Analyze unstructured market evidence without replacing market scoring."""
        return self._enhance("market", trim_market_context(context), MARKET_SCHEMA)

    def _enhance(self, kind: str, context: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
        if not self.enabled:
            return enhancement_result("disabled", "规则分析", "LLM 自然语言增强已关闭。")
        if not self.settings.llm_api_key and self.completion is None:
            return enhancement_result("not_configured", "规则分析", "未配置 LLM，已使用规则结果。")
        if not has_unstructured_evidence(context):
            return enhancement_result("skipped", "规则分析", "没有可供自然语言分析的有效文本证据。")
        try:
            raw = self.completion(kind, context) if self.completion else self._openai_completion(kind, context, schema)
            payload = normalize_payload(parse_json_object(raw), schema)
            return {
                "status": "enhanced",
                "mode": "rules_plus_llm",
                "provider": "configured_llm",
                "model": self.settings.llm_model,
                "analysis": payload,
                "notes": ["LLM 只增强非结构化证据解释，不改变行情、指标和基础评分。"],
            }
        except Exception as exc:
            return enhancement_result("fallback", "规则分析", f"LLM 增强失败，已回退规则结果：{str(exc)[:160]}")

    def _openai_completion(self, kind: str, context: dict[str, Any], schema: dict[str, Any]) -> str:
        from openai import OpenAI

        client = OpenAI(
            api_key=self.settings.llm_api_key,
            base_url=self.settings.llm_base_url,
            timeout=self.settings.tool_timeout_s,
            max_retries=0,
        )
        response = client.chat.completions.create(
            model=self.settings.llm_model,
            messages=[
                {"role": "system", "content": ENHANCEMENT_PROMPT},
                {"role": "user", "content": json.dumps({"analysis_type": kind, "required_schema": schema, "evidence": context}, ensure_ascii=False)},
            ],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content
        if not isinstance(content, str) or not content.strip():
            raise ValueError("empty LLM response")
        return content


ENHANCEMENT_PROMPT = """You analyze stock-market evidence supplied by the application.
Return one JSON object matching required_schema exactly. Use only supplied evidence.
Focus on tasks that need language understanding: event direction, expectation gaps,
time horizon, source limitations, social sentiment reliability, cross-evidence conflicts,
and concise risk/catalyst/watch summaries. Do not recalculate technical indicators,
market scores, prices, targets, or position sizes. Do not give buy/sell instructions.
Every conclusion must be traceable to the supplied text. Use Chinese output strings.
When evidence is insufficient, use neutral/unknown and explain the limitation."""


STOCK_SCHEMA = {
    "summary": "string",
    "news_direction": "positive|neutral|negative|mixed|unknown",
    "impact_horizon": "intraday|short_term|medium_term|long_term|unknown",
    "social_reliability": "low|medium|high|unknown",
    "catalysts": ["string"],
    "risks": ["string"],
    "conflicts": ["string"],
    "confirmations": ["string"],
    "watch_conditions": ["string"],
}

MARKET_SCHEMA = {
    "summary": "string",
    "news_direction": "positive|neutral|negative|mixed|unknown",
    "impact_horizon": "intraday|short_term|medium_term|long_term|unknown",
    "macro_drivers": ["string"],
    "sector_catalysts": ["string"],
    "risks": ["string"],
    "conflicts": ["string"],
    "watch_conditions": ["string"],
}


def trim_stock_context(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol": context.get("symbol"),
        "news": trim_articles(context.get("news", [])),
        "rule_intelligence": context.get("rule_intelligence", {}),
        "social_sentiment": context.get("social_sentiment", {}),
        "fundamentals": context.get("fundamentals", {}),
        "market_context": context.get("market_context", {}),
        "technical_summary": context.get("technical_summary", {}),
        "strategies": trim_strategies(context.get("strategies", [])),
    }


def trim_market_context(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "market": context.get("market"),
        "news": trim_articles(context.get("news", [])),
        "rule_intelligence": context.get("rule_intelligence", {}),
        "market_context": context.get("market_context", {}),
        "dimensions": context.get("dimensions", {}),
        "regime": context.get("regime"),
        "score": context.get("score"),
        "sector_rotation": context.get("sector_rotation", {}),
    }


def trim_articles(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {key: str(item.get(key, ""))[:600] for key in ("title", "summary", "source", "date", "topic") if item.get(key)}
        for item in items[:12]
    ]


def trim_strategies(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"name": item.get("name"), "stance": item.get("stance"), "score": item.get("score"), "evidence": item.get("evidence", [])[:2]}
        for item in items[:4]
    ]


def has_unstructured_evidence(context: dict[str, Any]) -> bool:
    return bool(context.get("news") or context.get("social_sentiment") or context.get("fundamentals"))


def parse_json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("LLM response is not a JSON object")
    return value


def normalize_payload(payload: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, expected in schema.items():
        value = payload.get(key)
        if isinstance(expected, list):
            normalized[key] = [str(item).strip()[:300] for item in value[:8] if str(item).strip()] if isinstance(value, list) else []
        elif "|" in expected:
            allowed = expected.split("|")
            candidate = str(value or "unknown").strip()
            normalized[key] = candidate if candidate in allowed else "unknown"
        else:
            normalized[key] = str(value).strip()[:1200] if value is not None else "unknown"
    return normalized


def enhancement_result(status: str, mode: str, note: str) -> dict[str, Any]:
    return {"status": status, "mode": mode, "provider": "none", "analysis": {}, "notes": [note]}
