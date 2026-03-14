from __future__ import annotations

import logging
from typing import Any

from ._ha_helpers import (
    fetch_state,
    home_assistant_request_json,
    lookup_area_name,
    normalize_state_payload,
)
from ..tools import ToolConfigField, ToolContext, ToolDefinition, ToolSpec


LOGGER = logging.getLogger(__name__)


def _execute(context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    action = str(arguments.get("action", "")).strip()
    LOGGER.info(
        "home_assistant input: action=%r keys=%s",
        action,
        sorted(arguments.keys()),
    )
    if action == "get_state":
        return _get_state(context, arguments)
    if action == "call_service":
        return _call_service(context, arguments)
    raise RuntimeError(
        "home_assistant action must be exactly 'get_state' or 'call_service'"
    )


def _get_state(context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    entity_id = str(arguments.get("entity_id", "")).strip()
    if not entity_id:
        raise RuntimeError("home_assistant get_state requires entity_id")

    LOGGER.info("home_assistant get_state input: entity_id=%r", entity_id)
    payload = fetch_state(context.settings, entity_id)
    result = normalize_state_payload(
        payload,
        area_name=lookup_area_name(context.settings, entity_id),
    )
    attributes = payload.get("attributes", {})
    result["attributes"] = attributes if isinstance(attributes, dict) else {}
    LOGGER.info(
        "home_assistant get_state output: entity_id=%s state=%s area_name=%r",
        result["entity_id"],
        result["state"],
        result["area_name"],
    )
    return {
        "action": "get_state",
        "ok": True,
        **result,
    }


def _call_service(context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    domain = str(arguments.get("domain", "")).strip()
    service = str(arguments.get("service", "")).strip()
    if not domain:
        raise RuntimeError("home_assistant call_service requires domain")
    if not service:
        raise RuntimeError("home_assistant call_service requires service")

    target = _normalize_target(arguments.get("target"))
    if not target:
        raise RuntimeError(
            "home_assistant call_service requires target.entity_id or target.area_id"
        )
    service_data = arguments.get("service_data")
    if service_data is None:
        service_data = {}
    if not isinstance(service_data, dict):
        raise RuntimeError("home_assistant service_data must be an object")

    request_body: dict[str, Any] = {}
    if target:
        request_body.update(target)
    if service_data:
        request_body.update(service_data)

    LOGGER.info(
        "home_assistant call_service input: domain=%r service=%r target=%s service_data_keys=%s",
        domain,
        service,
        _target_log_summary(target),
        sorted(service_data.keys()),
    )
    payload = home_assistant_request_json(
        context.settings,
        method="POST",
        path=f"/api/services/{domain}/{service}",
        body=request_body,
    )
    changed_entities = _extract_changed_entities(payload)
    LOGGER.info(
        "home_assistant call_service output: domain=%s service=%s changed_entities=%s count=%d",
        domain,
        service,
        changed_entities,
        len(changed_entities),
    )
    return {
        "action": "call_service",
        "ok": True,
        "domain": domain,
        "service": service,
        "target": target,
        "service_data": service_data,
        "changed_entities": changed_entities,
        "result_count": len(changed_entities),
    }


def _normalize_target(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise RuntimeError("home_assistant target must be an object")

    normalized: dict[str, Any] = {}
    for key in ("entity_id", "area_id"):
        if key not in value:
            continue
        normalized_value = _normalize_target_value(value[key], label=key)
        if normalized_value:
            normalized[key] = normalized_value
    return normalized


def _normalize_target_value(value: Any, *, label: str) -> str | list[str]:
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            raise RuntimeError(f"home_assistant target {label} cannot be empty")
        return normalized
    if isinstance(value, list):
        normalized_items = [str(item).strip() for item in value if str(item).strip()]
        if not normalized_items:
            raise RuntimeError(f"home_assistant target {label} list cannot be empty")
        return normalized_items
    raise RuntimeError(
        f"home_assistant target {label} must be a string or list of strings"
    )


def _target_log_summary(target: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key, value in target.items():
        if isinstance(value, list):
            summary[key] = {"count": len(value), "items": value[:5]}
        else:
            summary[key] = value
    return summary


def _extract_changed_entities(payload: Any) -> list[str]:
    if not isinstance(payload, list):
        return []
    changed_entities: list[str] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        entity_id = str(item.get("entity_id", "")).strip()
        if entity_id and entity_id not in changed_entities:
            changed_entities.append(entity_id)
    return changed_entities


TOOL = ToolSpec(
    definition=ToolDefinition(
        name="home_assistant",
        description=(
            "Control Home Assistant devices or query their current state. "
            "Use action='get_state' when the entity_id is already known. "
            "Use action='call_service' only after discovering likely entities with home_assistant_entities, and include a non-empty target.entity_id or target.area_id."
        ),
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["get_state", "call_service"],
                    "description": "Whether to fetch one entity state or call a Home Assistant service.",
                },
                "entity_id": {
                    "type": "string",
                    "description": "Required for get_state. The exact Home Assistant entity_id to inspect.",
                },
                "domain": {
                    "type": "string",
                    "description": "Required for call_service. Service domain such as light, switch, scene, climate, or media_player.",
                },
                "service": {
                    "type": "string",
                    "description": "Required for call_service. Service name such as turn_on, turn_off, set_temperature, or play_media.",
                },
                "target": {
                    "type": "object",
                    "description": "Optional Home Assistant target object. Supports entity_id or area_id as a string or list of strings.",
                },
                "service_data": {
                    "type": "object",
                    "description": "Optional service data object forwarded to Home Assistant.",
                },
            },
            "required": ["action"],
            "additionalProperties": False,
        },
    ),
    execute=_execute,
    config_fields=(
        ToolConfigField(
            key="ha_url",
            label="HA URL",
            field_type="text",
            description="Base Home Assistant URL, for example http://homeassistant.local:8123.",
            default="",
        ),
    ),
)
