from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class StrategyDefinition:
    """Declarative strategy metadata and scoring rules loaded from YAML."""
    key: str
    name: str
    description: str
    tags: list[str]
    risk_bias: str
    rules: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class StrategyResult:
    """Evaluated strategy score, stance, evidence, and risk notes."""
    key: str
    name: str
    score: float
    stance: str
    evidence: list[str]
    risks: list[str]


def score_to_stance(score: float) -> str:
    """Map a strategy score to bullish, neutral, or bearish stance."""
    if score >= 70:
        return "positive"
    if score >= 50:
        return "neutral"
    return "negative"
