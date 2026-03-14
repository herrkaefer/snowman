from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import parse

import websocket

from ..config_store import resolve_config_paths
from ._ha_helpers import home_assistant_url, home_assistant_token


LOGGER = logging.getLogger(__name__)
DEFAULT_HA_WEBSOCKET_TIMEOUT_SECONDS = 15
SNAPSHOT_DIRNAME = "home_assistant"
SNAPSHOT_FILENAME = "registry_snapshot.json"


def verify_and_sync_registry_snapshot(settings: Any) -> dict[str, Any]:
    snapshot = fetch_registry_snapshot(settings)
    write_registry_snapshot(snapshot)
    return snapshot


def fetch_registry_snapshot(settings: Any) -> dict[str, Any]:
    websocket_url = _home_assistant_websocket_url(settings)
    call_id = 1
    socket: websocket.WebSocket | None = None
    try:
        socket = websocket.create_connection(
            websocket_url,
            timeout=DEFAULT_HA_WEBSOCKET_TIMEOUT_SECONDS,
            enable_multithread=False,
        )
        _authenticate_socket(socket, settings)
        config = _send_command(socket, call_id, "get_config")
        call_id += 1
        areas = _send_command(socket, call_id, "config/area_registry/list")
        call_id += 1
        devices = _send_command(socket, call_id, "config/device_registry/list")
        call_id += 1
        entities = _send_command(socket, call_id, "config/entity_registry/list")
    finally:
        if socket is not None:
            try:
                socket.close()
            except Exception:
                LOGGER.debug("Failed to close Home Assistant registry websocket", exc_info=True)

    return {
        "fetched_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "ha_url": home_assistant_url(settings),
        "config": config if isinstance(config, dict) else {},
        "areas": _ensure_object_list(areas),
        "devices": _ensure_object_list(devices),
        "entities": _ensure_object_list(entities),
    }


def write_registry_snapshot(snapshot: dict[str, Any]) -> Path:
    path = registry_snapshot_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".json.tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(snapshot, handle, indent=2, ensure_ascii=True)
    tmp_path.replace(path)
    return path


def load_registry_snapshot(settings: Any | None = None) -> dict[str, Any] | None:
    path = registry_snapshot_path()
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        LOGGER.warning("Ignoring invalid Home Assistant registry snapshot at %s", path)
        return None
    if not isinstance(payload, dict):
        return None
    if settings is not None:
        try:
            current_url = home_assistant_url(settings)
        except RuntimeError:
            current_url = ""
        snapshot_url = str(payload.get("ha_url", "")).strip().rstrip("/")
        if current_url and snapshot_url and snapshot_url != current_url.rstrip("/"):
            return None
    return payload


def registry_snapshot_status(settings: Any | None = None) -> dict[str, Any]:
    path = registry_snapshot_path()
    payload = load_registry_snapshot()
    counts = {
        "areas": len(_ensure_object_list(payload.get("areas"))) if isinstance(payload, dict) else 0,
        "devices": len(_ensure_object_list(payload.get("devices"))) if isinstance(payload, dict) else 0,
        "entities": len(_ensure_object_list(payload.get("entities"))) if isinstance(payload, dict) else 0,
    }
    configured_url = ""
    snapshot_url = ""
    matches_current_url = False
    if settings is not None:
        try:
            configured_url = home_assistant_url(settings)
        except RuntimeError:
            configured_url = ""
    if isinstance(payload, dict):
        snapshot_url = str(payload.get("ha_url", "")).strip()
    if configured_url and snapshot_url:
        matches_current_url = configured_url.rstrip("/") == snapshot_url.rstrip("/")
    return {
        "path": str(path),
        "exists": bool(isinstance(payload, dict)),
        "fetched_at": str(payload.get("fetched_at", "")).strip() if isinstance(payload, dict) else "",
        "counts": counts,
        "ha_url": snapshot_url,
        "configured_ha_url": configured_url,
        "matches_current_url": matches_current_url if configured_url else False,
    }


def registry_snapshot_path() -> Path:
    return resolve_config_paths().data_dir / SNAPSHOT_DIRNAME / SNAPSHOT_FILENAME


def _home_assistant_websocket_url(settings: Any) -> str:
    parsed = parse.urlparse(home_assistant_url(settings))
    scheme = "wss" if parsed.scheme == "https" else "ws"
    base_path = parsed.path.rstrip("/")
    return parse.urlunparse(
        (
            scheme,
            parsed.netloc,
            f"{base_path}/api/websocket",
            "",
            "",
            "",
        )
    )


def _authenticate_socket(socket: websocket.WebSocket, settings: Any) -> None:
    opening = _receive_json(socket)
    if opening.get("type") != "auth_required":
        raise RuntimeError("Home Assistant websocket did not request authentication.")
    socket.send(
        json.dumps(
            {
                "type": "auth",
                "access_token": home_assistant_token(settings),
            }
        )
    )
    auth_response = _receive_json(socket)
    response_type = str(auth_response.get("type", "")).strip()
    if response_type == "auth_ok":
        return
    message = str(auth_response.get("message", "")).strip()
    if response_type == "auth_invalid":
        raise RuntimeError(
            f"Home Assistant websocket authentication failed{': ' + message if message else '.'}"
        )
    raise RuntimeError("Home Assistant websocket authentication failed.")


def _send_command(socket: websocket.WebSocket, call_id: int, command_type: str) -> Any:
    socket.send(json.dumps({"id": call_id, "type": command_type}))
    while True:
        payload = _receive_json(socket)
        if int(payload.get("id", -1)) != call_id:
            continue
        if payload.get("type") != "result":
            continue
        if payload.get("success") is True:
            return payload.get("result")
        error_payload = payload.get("error", {})
        if isinstance(error_payload, dict):
            code = str(error_payload.get("code", "")).strip()
            message = str(error_payload.get("message", "")).strip()
        else:
            code = ""
            message = str(error_payload).strip()
        suffix = f" ({code})" if code else ""
        detail = f": {message}" if message else ""
        raise RuntimeError(
            f"Home Assistant websocket command {command_type} failed{suffix}{detail}"
        )


def _receive_json(socket: websocket.WebSocket) -> dict[str, Any]:
    try:
        raw_message = socket.recv()
    except websocket.WebSocketTimeoutException as exc:
        raise RuntimeError("Home Assistant websocket request timed out.") from exc
    except websocket.WebSocketConnectionClosedException as exc:
        raise RuntimeError("Home Assistant websocket connection closed unexpectedly.") from exc
    if not isinstance(raw_message, str):
        raise RuntimeError("Home Assistant websocket returned a non-text frame.")
    try:
        payload = json.loads(raw_message)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Home Assistant websocket returned invalid JSON.") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Home Assistant websocket returned a non-object payload.")
    return payload


def _ensure_object_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]
