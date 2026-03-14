from __future__ import annotations

import json
import logging
from typing import Any
from urllib import error, parse, request


LOGGER = logging.getLogger(__name__)
DEFAULT_HA_TIMEOUT_SECONDS = 12
AREA_LOOKUP_TEMPLATE = "{{ area_name(%r) or '' }}"


def home_assistant_url(settings: Any) -> str:
    tool_config = getattr(settings, "tool_config", {})
    home_assistant_config = {}
    if isinstance(tool_config, dict):
        for tool_name in (
            "home_assistant_call_service",
            "home_assistant_get_state",
            "home_assistant_search_entities",
            "home_assistant",
        ):
            candidate = tool_config.get(tool_name, {})
            if isinstance(candidate, dict) and candidate:
                home_assistant_config = candidate
                break
    ha_url = (
        str(home_assistant_config.get("ha_url", "")).strip()
        if isinstance(home_assistant_config, dict)
        else ""
    )
    if not ha_url:
        raise RuntimeError("Home Assistant URL is not configured.")
    return ha_url.rstrip("/")


def home_assistant_token(settings: Any) -> str:
    token = str(getattr(settings, "ha_access_token", "")).strip()
    if not token:
        raise RuntimeError("Home Assistant access token is not configured.")
    return token


def home_assistant_request_json(
    settings: Any,
    *,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    timeout: float = DEFAULT_HA_TIMEOUT_SECONDS,
) -> Any:
    response_text = _home_assistant_request(
        settings,
        method=method,
        path=path,
        body=body,
        timeout=timeout,
    )
    try:
        return json.loads(response_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Home Assistant returned invalid JSON for {method.upper()} {path}"
        ) from exc


def home_assistant_request_text(
    settings: Any,
    *,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    timeout: float = DEFAULT_HA_TIMEOUT_SECONDS,
) -> str:
    return _home_assistant_request(
        settings,
        method=method,
        path=path,
        body=body,
        timeout=timeout,
    )


def fetch_states(settings: Any) -> list[dict[str, Any]]:
    payload = home_assistant_request_json(settings, method="GET", path="/api/states")
    if not isinstance(payload, list):
        raise RuntimeError("Home Assistant states response must be a list.")
    return [item for item in payload if isinstance(item, dict)]


def fetch_state(settings: Any, entity_id: str) -> dict[str, Any]:
    payload = home_assistant_request_json(
        settings,
        method="GET",
        path=f"/api/states/{parse.quote(entity_id, safe='')}",
    )
    if not isinstance(payload, dict):
        raise RuntimeError("Home Assistant state response must be an object.")
    return payload


def render_template(settings: Any, template: str) -> str:
    return home_assistant_request_text(
        settings,
        method="POST",
        path="/api/template",
        body={"template": template},
    ).strip()


def lookup_area_name(settings: Any, entity_id: str) -> str:
    try:
        return render_template(settings, AREA_LOOKUP_TEMPLATE % entity_id)
    except RuntimeError as exc:
        LOGGER.debug("Unable to resolve Home Assistant area for %s: %s", entity_id, exc)
        return ""


def normalize_state_payload(
    payload: dict[str, Any],
    *,
    area_name: str = "",
) -> dict[str, Any]:
    entity_id = str(payload.get("entity_id", "")).strip()
    attributes = payload.get("attributes", {})
    friendly_name = ""
    if isinstance(attributes, dict):
        friendly_name = str(attributes.get("friendly_name", "")).strip()
    return {
        "entity_id": entity_id,
        "friendly_name": friendly_name or entity_id,
        "state": str(payload.get("state", "")).strip(),
        "area_name": area_name.strip(),
    }


def _home_assistant_request(
    settings: Any,
    *,
    method: str,
    path: str,
    body: dict[str, Any] | None,
    timeout: float,
) -> str:
    raw_body = json.dumps(body).encode("utf-8") if body is not None else None
    req = request.Request(
        url=home_assistant_url(settings) + path,
        data=raw_body,
        headers={
            "Authorization": f"Bearer {home_assistant_token(settings)}",
            "Content-Type": "application/json",
        },
        method=method.upper(),
    )
    try:
        with request.urlopen(req, timeout=timeout) as response:
            return response.read().decode("utf-8")
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore").strip()
        if detail:
            detail = f": {_truncate(detail, max_chars=240)}"
        raise RuntimeError(
            f"Home Assistant {method.upper()} {path} failed with HTTP {exc.code}{detail}"
        ) from exc
    except error.URLError as exc:
        raise RuntimeError(
            f"Home Assistant {method.upper()} {path} failed: {exc.reason}"
        ) from exc


def _truncate(value: str, *, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 3] + "..."
