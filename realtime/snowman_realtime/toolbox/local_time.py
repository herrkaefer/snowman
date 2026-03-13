from __future__ import annotations

from datetime import datetime
from typing import Any

from ..tools import ToolContext, ToolDefinition, ToolSpec


def _execute(_: ToolContext, __: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now().astimezone()
    return {
        "local_time": now.strftime("%Y-%m-%d %H:%M:%S"),
        "timezone": now.tzname() or "local",
        "iso8601": now.isoformat(),
    }


TOOL = ToolSpec(
    definition=ToolDefinition(
        name="local_time",
        description=(
            "Get the exact current local time on the Raspberry Pi. "
            "Do not use this for ordinary time questions at the start of a session, because the injected session timestamp is usually sufficient. "
            "Use this only when the injected session timestamp may be stale because the conversation has been open for a while, or when the user explicitly asks for the exact current time right now."
        ),
        parameters={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    ),
    execute=_execute,
)
