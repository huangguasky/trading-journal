from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class Tool:
    """Agent-callable tool schema and local handler."""
    name: str
    description: str
    schema: dict[str, Any]
    handler: Callable[[dict[str, Any]], Any]
    timeout_s: float = 8


@dataclass
class ToolCall:
    """One planned tool invocation with its arguments."""
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class AgentResult:
    """Final agent answer, execution trace, and rendering metadata."""
    content: str
    card: dict[str, Any] | None
    tool_trace: list[dict[str, Any]]
    status: str = "ok"
