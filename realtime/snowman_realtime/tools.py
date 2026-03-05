from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)


class ToolRegistry:
    """Placeholder registry for future function calling support."""

    def __init__(self, tools: list[ToolDefinition] | None = None) -> None:
        self._tools = tools or []

    @property
    def tools(self) -> list[ToolDefinition]:
        return list(self._tools)
