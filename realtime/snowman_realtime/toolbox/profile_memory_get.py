from __future__ import annotations

from typing import Any

from ..tools import ToolAvailability, ToolContext, ToolDefinition, ToolSpec


def _is_enabled(availability: ToolAvailability) -> bool:
    return availability.memory_enabled


def _execute(context: ToolContext, _: dict[str, Any]) -> dict[str, Any]:
    if context.memory_store is None:
        raise RuntimeError("profile memory is not enabled")
    context.session_state.profile_loaded = True
    return {
        "profile_markdown": context.memory_store.read_profile(),
    }


TOOL = ToolSpec(
    definition=ToolDefinition(
        name="profile_memory_get",
        description=(
            "Load the full profile memory document containing stable facts about people, preferences, and household context. "
            "If the user asks who a named person is, what their relationship is, or the name may refer to someone in the household, call this before asking a clarification question or assuming they are a public figure. "
            "Call this before any profile memory update so you can preserve existing content."
        ),
        parameters={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    ),
    execute=_execute,
    is_enabled=_is_enabled,
)
