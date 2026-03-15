from __future__ import annotations

import logging
from typing import Any

from ._ha_helpers import (
    has_home_assistant_runtime_config,
    home_assistant_request_json,
    normalize_state_payload,
)
from ..tools import ToolAvailability, ToolContext, ToolDefinition, ToolSpec


LOGGER = logging.getLogger(__name__)


def _runtime_enabled(settings: Any, _: ToolAvailability) -> bool:
    return has_home_assistant_runtime_config(settings)


def _execute(context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    domain = str(arguments.get("domain", "")).strip()
    service = str(arguments.get("service", "")).strip()
    if not domain:
        raise RuntimeError("home_assistant_call_service requires domain")
    if not service:
        raise RuntimeError("home_assistant_call_service requires service")

    normalized_entity_ids = _normalize_optional_ids(
        arguments.get("entity_id"),
        label="entity_id",
    )
    normalized_area_ids = _normalize_optional_ids(
        arguments.get("area_id"),
        label="area_id",
    )
    if not normalized_entity_ids and not normalized_area_ids:
        raise RuntimeError(
            "home_assistant_call_service requires entity_id or area_id"
        )
    service_data = arguments.get("service_data")
    if service_data is None:
        service_data = {}
    if not isinstance(service_data, dict):
        raise RuntimeError("home_assistant_call_service service_data must be an object")

    request_body = dict(service_data)
    if normalized_entity_ids:
        request_body["entity_id"] = (
            normalized_entity_ids[0]
            if len(normalized_entity_ids) == 1
            else normalized_entity_ids
        )
    if normalized_area_ids:
        request_body["area_id"] = (
            normalized_area_ids[0]
            if len(normalized_area_ids) == 1
            else normalized_area_ids
        )

    LOGGER.info(
        "home_assistant_call_service input: domain=%r service=%r entity_ids=%s area_ids=%s service_data_keys=%s",
        domain,
        service,
        normalized_entity_ids,
        normalized_area_ids,
        sorted(service_data.keys()),
    )
    payload = home_assistant_request_json(
        context.settings,
        method="POST",
        path=f"/api/services/{domain}/{service}",
        body=request_body,
    )
    result_items = _extract_result_items(payload)
    changed_entity_ids = list(result_items.keys())
    results = _build_results(
        domain=domain,
        service=service,
        requested_entity_ids=normalized_entity_ids,
        result_items=result_items,
    )
    LOGGER.info(
        "home_assistant_call_service output: domain=%s service=%s changed_entity_ids=%s result_count=%d",
        domain,
        service,
        changed_entity_ids,
        len(results),
    )
    return {
        "ok": True,
        "domain": domain,
        "service": service,
        "requested_entity_ids": normalized_entity_ids,
        "requested_area_ids": normalized_area_ids,
        "service_data": service_data,
        "changed_entity_ids": changed_entity_ids,
        "result_count": len(results),
        "results": results,
    }


def _normalize_optional_ids(value: Any, *, label: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            raise RuntimeError(f"home_assistant_call_service {label} cannot be empty")
        return [normalized]
    if isinstance(value, list):
        normalized_items = [str(item).strip() for item in value if str(item).strip()]
        if not normalized_items:
            raise RuntimeError(f"home_assistant_call_service {label} list cannot be empty")
        return normalized_items
    raise RuntimeError(
        f"home_assistant_call_service {label} must be a string or list of strings"
    )


def _extract_result_items(payload: Any) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    if not isinstance(payload, list):
        return results
    for item in payload:
        if not isinstance(item, dict):
            continue
        entity_id = str(item.get("entity_id", "")).strip()
        if not entity_id:
            continue
        results[entity_id] = item
    return results


def _build_results(
    *,
    domain: str,
    service: str,
    requested_entity_ids: list[str],
    result_items: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    ordered_entity_ids = list(dict.fromkeys(requested_entity_ids + list(result_items.keys())))
    for entity_id in ordered_entity_ids:
        item = result_items.get(entity_id)
        if item is None:
            results[entity_id] = {
                "changed": False,
                "domain": domain,
                "service": service,
            }
            continue
        normalized = normalize_state_payload(item)
        attributes = item.get("attributes", {})
        entry: dict[str, Any] = {
            "changed": True,
            "domain": domain,
            "service": service,
            "state": normalized["state"],
            "friendly_name": normalized["friendly_name"],
        }
        if isinstance(attributes, dict) and attributes:
            entry["attributes"] = attributes
        results[entity_id] = entry
    return results


TOOL = ToolSpec(
    definition=ToolDefinition(
        name="home_assistant_call_service",
        description=(
            "Call a Home Assistant service using the same shape as the Home Assistant /api/services/<domain>/<service> API. "
            "Use this only after you already know the target entity_id or area_id. "
            "Pass domain and service, plus entity_id or area_id as a string or list of strings. "
            "Put any extra Home Assistant service fields in service_data."
        ),
        parameters={
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": "Required Home Assistant domain such as light, switch, scene, climate, or media_player.",
                },
                "service": {
                    "type": "string",
                    "description": "Required Home Assistant service name such as turn_on, turn_off, set_temperature, or play_media.",
                },
                "entity_id": {
                    "oneOf": [
                        {"type": "string"},
                        {"type": "array", "items": {"type": "string"}},
                    ],
                    "description": "Optional Home Assistant entity_id or list of entity_ids to target.",
                },
                "area_id": {
                    "oneOf": [
                        {"type": "string"},
                        {"type": "array", "items": {"type": "string"}},
                    ],
                    "description": "Optional Home Assistant area_id or list of area_ids to target.",
                },
                "service_data": {
                    "type": "object",
                    "description": "Optional extra Home Assistant service fields, such as brightness_pct, transition, temperature, media_content_id, or media_content_type.",
                },
            },
            "required": ["domain", "service"],
            "additionalProperties": False,
        },
    ),
    execute=_execute,
    is_runtime_enabled=_runtime_enabled,
)
