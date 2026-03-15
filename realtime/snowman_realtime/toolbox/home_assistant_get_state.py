from __future__ import annotations

import logging
from typing import Any

from ._ha_helpers import (
    fetch_state,
    has_home_assistant_runtime_config,
    lookup_area_name,
    normalize_state_payload,
)
from ..tools import ToolAvailability, ToolContext, ToolDefinition, ToolSpec


LOGGER = logging.getLogger(__name__)


def _runtime_enabled(settings: Any, _: ToolAvailability) -> bool:
    return has_home_assistant_runtime_config(settings)


def _execute(context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    entity_ids = _normalize_entity_ids(arguments.get("entity_id"))
    if not entity_ids:
        raise RuntimeError("home_assistant_get_state requires entity_id")

    LOGGER.info("home_assistant_get_state input: entity_ids=%s", entity_ids)
    states: dict[str, dict[str, Any]] = {}
    missing_entity_ids: list[str] = []
    for entity_id in entity_ids:
        try:
            payload = fetch_state(context.settings, entity_id)
        except RuntimeError as exc:
            if "HTTP 404" in str(exc):
                missing_entity_ids.append(entity_id)
                continue
            raise
        result = normalize_state_payload(
            payload,
            area_name=lookup_area_name(context.settings, entity_id),
        )
        attributes = payload.get("attributes", {})
        entry: dict[str, Any] = {
            "state": result["state"],
            "friendly_name": result["friendly_name"],
            "area_name": result["area_name"],
        }
        if isinstance(attributes, dict):
            entry["attributes"] = attributes
        states[entity_id] = entry
    LOGGER.info(
        "home_assistant_get_state output: count=%d missing=%s",
        len(states),
        missing_entity_ids,
    )
    return {
        "ok": True,
        "count": len(states),
        "states": states,
        "missing_entity_ids": missing_entity_ids,
    }


def _normalize_entity_ids(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        normalized = value.strip()
        return [normalized] if normalized else []
    if isinstance(value, list):
        normalized_items = [str(item).strip() for item in value if str(item).strip()]
        return normalized_items
    raise RuntimeError("home_assistant_get_state entity_id must be a string or list of strings")


TOOL = ToolSpec(
    definition=ToolDefinition(
        name="home_assistant_get_state",
        description=(
            "Get the current state for one or more Home Assistant entities. "
            "Use this when the exact entity_id is already known. "
            "This tool maps to Home Assistant /api/states/<entity_id> and can call it multiple times when you provide a list of entity_ids."
        ),
        parameters={
            "type": "object",
            "properties": {
                "entity_id": {
                    "oneOf": [
                        {"type": "string"},
                        {"type": "array", "items": {"type": "string"}},
                    ],
                    "description": "Required Home Assistant entity_id or list of entity_ids to inspect.",
                },
            },
            "required": ["entity_id"],
            "additionalProperties": False,
        },
    ),
    execute=_execute,
    is_runtime_enabled=_runtime_enabled,
)
