from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import StrategyDefinition, StrategyResult, score_to_stance


BUILTIN_DIR = Path(__file__).resolve().parent / "builtin"


class StrategyRegistry:
    def __init__(self, strategy_dir: Path = BUILTIN_DIR):
        self.strategy_dir = strategy_dir
        self._items = self._load()

    def all(self) -> list[StrategyDefinition]:
        return list(self._items.values())

    def select_for_stock(self, indicators: dict, news: list[dict]) -> list[StrategyResult]:
        results = [evaluate_strategy(item, indicators, news) for item in self.all()]
        return sorted(results, key=lambda item: item.score, reverse=True)

    def select_market_bias(self, market_snapshot: dict, news: list[dict]) -> str:
        breadth = market_snapshot.get("breadth", {})
        advancers = breadth.get("advancers", 0)
        decliners = breadth.get("decliners", 1)
        ratio = advancers / max(1, advancers + decliners)
        if ratio >= 0.58:
            return "trend"
        if ratio <= 0.42:
            return "defensive"
        if news:
            return "event"
        return "wait"

    def _load(self) -> dict[str, StrategyDefinition]:
        items: dict[str, StrategyDefinition] = {}
        for path in sorted(self.strategy_dir.glob("*.yaml")):
            payload = parse_yaml_lite(path.read_text(encoding="utf-8"))
            item = StrategyDefinition(
                key=str(payload["key"]),
                name=str(payload["name"]),
                description=str(payload.get("description", "")),
                tags=list(payload.get("tags", [])),
                risk_bias=str(payload.get("risk_bias", "balanced")),
                rules=list(payload.get("rules", [])),
            )
            items[item.key] = item
        return items


def evaluate_strategy(definition: StrategyDefinition, indicators: dict, news: list[dict]) -> StrategyResult:
    score = 45.0
    evidence: list[str] = []
    risks: list[str] = []
    ctx = flatten_indicators(indicators)
    ctx["news_count"] = len(news)
    for rule in definition.rules:
        metric = rule.get("metric")
        op = rule.get("op", ">=")
        expected = rule.get("value")
        weight = float(rule.get("weight", 0))
        actual = ctx.get(str(metric))
        if actual is None:
            continue
        matched = compare(actual, op, expected)
        if matched:
            score += weight
            evidence.append(str(rule.get("evidence", f"{metric} {op} {expected}")))
        else:
            score -= max(0, weight * 0.35)
            if rule.get("risk"):
                risks.append(str(rule["risk"]))
    bounded = round(max(0, min(100, score)), 1)
    if not evidence:
        evidence.append("暂未命中强信号，适合作为观察项。")
    if definition.risk_bias == "defensive":
        risks.append("该策略偏防守，确认信号出现前不宜扩大仓位。")
    return StrategyResult(definition.key, definition.name, bounded, score_to_stance(bounded), evidence, list(dict.fromkeys(risks))[:4])


def flatten_indicators(indicators: dict) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for group, values in indicators.items():
        if isinstance(values, dict):
            for key, value in values.items():
                out[f"{group}.{key}"] = value
    return out


def compare(actual: Any, op: str, expected: Any) -> bool:
    if op == "truthy":
        return bool(actual)
    if op == "falsy":
        return not bool(actual)
    left = float(actual)
    right = float(expected)
    if op == ">":
        return left > right
    if op == ">=":
        return left >= right
    if op == "<":
        return left < right
    if op == "<=":
        return left <= right
    if op == "==":
        return left == right
    raise ValueError(f"unsupported operator: {op}")


def parse_yaml_lite(text: str) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    current_list: list[Any] | None = None
    current_item: dict[str, Any] | None = None
    list_name = ""
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        if not raw.startswith(" ") and ":" in line:
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()
            if value == "":
                current_list = []
                payload[key] = current_list
                list_name = key
            else:
                payload[key] = parse_scalar(value)
                current_list = None
            current_item = None
            continue
        stripped = line.strip()
        if stripped.startswith("- "):
            value = stripped[2:]
            if ":" in value:
                key, val = value.split(":", 1)
                current_item = {key.strip(): parse_scalar(val.strip())}
                assert current_list is not None
                current_list.append(current_item)
            else:
                assert current_list is not None
                current_list.append(parse_scalar(value))
                current_item = None
        elif current_item is not None and ":" in stripped:
            key, val = stripped.split(":", 1)
            current_item[key.strip()] = parse_scalar(val.strip())
        elif list_name and current_list is not None:
            continue
    return payload


def parse_scalar(value: str) -> Any:
    value = value.strip().strip('"').strip("'")
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        return [parse_scalar(part.strip()) for part in inner.split(",") if part.strip()]
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value
