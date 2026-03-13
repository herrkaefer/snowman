from __future__ import annotations

from typing import Any

from ..memory import MemoryValidationError, default_profile_markdown
from ..tools import ToolAvailability, ToolContext, ToolDefinition, ToolSpec


def _is_enabled(availability: ToolAvailability) -> bool:
    return availability.memory_enabled


def _execute(context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    if context.memory_store is None:
        raise RuntimeError("profile memory is not enabled")

    updated_markdown = str(arguments.get("updated_markdown", ""))
    if not updated_markdown.strip():
        raise RuntimeError("profile_memory_update requires updated_markdown")

    current_profile = context.memory_store.read_profile()
    if (
        current_profile.strip()
        and current_profile.strip() != default_profile_markdown().strip()
        and not context.session_state.profile_loaded
    ):
        raise RuntimeError(
            "profile_memory_update requires profile_memory_get first in the current session so existing profile content is preserved."
        )
    try:
        saved = context.memory_store.update_profile(updated_markdown)
    except MemoryValidationError as exc:
        raise RuntimeError(str(exc)) from exc
    return {
        "status": "updated",
        "profile_markdown": saved,
    }


TOOL = ToolSpec(
    definition=ToolDefinition(
        name="profile_memory_update",
        description=(
            "Replace the full profile memory document with updated Markdown. "
            "You must call profile_memory_get first in the current session, preserve unrelated existing facts, and make only the minimal necessary edit. "
            "Do not overwrite the whole document with a single new fact."
        ),
        parameters={
            "type": "object",
            "properties": {
                "updated_markdown": {
                    "type": "string",
                    "description": "The complete updated profile memory Markdown document.",
                }
            },
            "required": ["updated_markdown"],
            "additionalProperties": False,
        },
    ),
    execute=_execute,
    is_enabled=_is_enabled,
)
