from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class Tool:
    name: str
    description: str
    schema: dict[str, Any]
    handler: Callable[[dict[str, Any]], Any]
    timeout_s: float = 8


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class AgentResult:
    content: str
    card: dict[str, Any] | None
    tool_trace: list[dict[str, Any]]
    status: str = "ok"

