from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentProfile:
    """Execution policy for one ask-stock complexity level."""

    key: str
    name: str
    description: str
    agents: tuple[str, ...]
    tools: tuple[str, ...]
    max_steps: int


AGENT_PROFILES = {
    "quick": AgentProfile(
        key="quick",
        name="快速",
        description="适合行情确认和简单技术问题，响应最快。",
        agents=("行情", "技术", "回答"),
        tools=("get_quote", "get_indicators", "get_market_context"),
        max_steps=3,
    ),
    "standard": AgentProfile(
        key="standard",
        name="标准",
        description="兼顾技术、基本面、资讯和风险，适合日常问股。",
        agents=("行情", "技术", "基本面", "资讯", "风险", "决策"),
        tools=("get_quote", "get_indicators", "get_fundamentals", "search_news", "get_last_report", "get_market_context"),
        max_steps=5,
    ),
    "deep": AgentProfile(
        key="deep",
        name="深度",
        description="在标准分析上加入历史走势、策略和信号追踪，适合交易计划与复盘。",
        agents=("行情", "技术", "基本面", "资讯", "策略", "风险", "追踪", "决策"),
        tools=(
            "get_quote",
            "get_history",
            "get_indicators",
            "get_fundamentals",
            "search_news",
            "get_last_report",
            "get_signal_tracking",
            "get_market_context",
        ),
        max_steps=7,
    ),
}


def get_agent_profile(value: str | None) -> AgentProfile:
    """Return a supported profile, defaulting invalid values to standard."""
    return AGENT_PROFILES.get(str(value or "").strip().lower(), AGENT_PROFILES["standard"])


def serialize_agent_profiles() -> list[dict]:
    """Expose stable profile metadata to the settings UI."""
    return [
        {
            "key": profile.key,
            "name": profile.name,
            "description": profile.description,
            "agents": list(profile.agents),
            "max_steps": profile.max_steps,
        }
        for profile in AGENT_PROFILES.values()
    ]
