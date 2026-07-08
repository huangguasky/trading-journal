from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class StrategyDefinition:
    key: str
    name: str
    description: str
    tags: list[str]
    risk_bias: str
    rules: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class StrategyResult:
    key: str
    name: str
    score: float
    stance: str
    evidence: list[str]
    risks: list[str]


def score_to_stance(score: float) -> str:
    if score >= 70:
        return "positive"
    if score >= 50:
        return "neutral"
    return "negative"

