from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values


APP_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = APP_DIR.parent / "data"
CONFIG_FILENAME = "config.json"
SECRETS_FILENAME = "secrets.env"

SUPPORTED_PROVIDER = "openai"

REQUIRED_FIELD_ERRORS = {
    "provider": "AI provider is required.",
    "openai_api_key": "OpenAI API key is required.",
    "porcupine_access_key": "Porcupine access key is required.",
    "openai_voice": "Voice is required.",
    "system_prompt": "Prompt is required.",
}


@dataclass(frozen=True)
class ManagedConfigPaths:
    data_dir: Path
    config_path: Path
    secrets_path: Path


def resolve_managed_config_paths() -> ManagedConfigPaths:
    raw_data_dir = os.getenv("SNOWMAN_DATA_DIR", "").strip()
    data_dir = Path(raw_data_dir).expanduser() if raw_data_dir else DEFAULT_DATA_DIR
    return ManagedConfigPaths(
        data_dir=data_dir,
        config_path=data_dir / CONFIG_FILENAME,
        secrets_path=data_dir / SECRETS_FILENAME,
    )


def load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    return {
        key: value
        for key, value in dotenv_values(path).items()
        if key and value is not None
    }


def load_json_file(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise RuntimeError(f"Managed config file must contain a JSON object: {path}")
    return payload


def default_editable_config(*, default_system_prompt: str) -> dict[str, object]:
    return {
        "provider": SUPPORTED_PROVIDER,
        "openai_voice": "alloy",
        "system_prompt": default_system_prompt,
        "location_city": "",
        "location_region": "",
        "location_country_code": "",
        "location_timezone": "",
        "session_window_enabled": False,
        "openai_api_key": "",
        "porcupine_access_key": "",
        "admin_password": "",
    }


def load_editable_config(
    *,
    default_system_prompt: str,
    env_values: dict[str, str],
) -> dict[str, object]:
    defaults = default_editable_config(default_system_prompt=default_system_prompt)
    paths = resolve_managed_config_paths()
    config_payload = load_json_file(paths.config_path)
    secret_payload = load_env_file(paths.secrets_path)

    provider = (
        str(config_payload.get("provider", "")).strip()
        or env_values.get("VOICE_BACKEND", "").strip()
        or str(defaults["provider"])
    )
    editable = {
        "provider": provider,
        "openai_voice": (
            str(config_payload.get("openai_voice", "")).strip()
            or env_values.get("OPENAI_VOICE", "").strip()
            or str(defaults["openai_voice"])
        ),
        "system_prompt": (
            str(config_payload.get("system_prompt", "")).strip()
            or env_values.get("SYSTEM_PROMPT", "").strip()
            or str(defaults["system_prompt"])
        ),
        "location_city": (
            str(config_payload.get("location_city", "")).strip()
            or env_values.get("LOCATION_CITY", "").strip()
        ),
        "location_region": (
            str(config_payload.get("location_region", "")).strip()
            or env_values.get("LOCATION_REGION", "").strip()
        ),
        "location_country_code": (
            str(config_payload.get("location_country_code", "")).strip()
            or env_values.get("LOCATION_COUNTRY_CODE", "").strip()
        ),
        "location_timezone": (
            str(config_payload.get("location_timezone", "")).strip()
            or env_values.get("LOCATION_TIMEZONE", "").strip()
            or env_values.get("TZ", "").strip()
        ),
        "session_window_enabled": _coerce_bool(
            config_payload.get(
                "session_window_enabled",
                env_values.get("SESSION_WINDOW_ENABLED", defaults["session_window_enabled"]),
            )
        ),
        "openai_api_key": secret_payload.get(
            "OPENAI_API_KEY",
            env_values.get("OPENAI_API_KEY", ""),
        ).strip(),
        "porcupine_access_key": secret_payload.get(
            "PORCUPINE_ACCESS_KEY",
            env_values.get("PORCUPINE_ACCESS_KEY", ""),
        ).strip(),
        "admin_password": secret_payload.get(
            "ADMIN_PASSWORD",
            env_values.get("ADMIN_PASSWORD", ""),
        ).strip(),
    }
    return editable


def merge_editable_config(
    current: dict[str, object],
    updates: dict[str, object],
) -> dict[str, object]:
    merged = dict(current)
    for key, value in updates.items():
        if key in {"openai_api_key", "porcupine_access_key", "admin_password"}:
            if isinstance(value, str):
                stripped = value.strip()
                if stripped:
                    merged[key] = stripped
            continue
        if key == "session_window_enabled":
            merged[key] = _coerce_bool(value)
            continue
        if isinstance(value, str):
            merged[key] = value.strip()
        else:
            merged[key] = value
    return merged


def validate_editable_config(payload: dict[str, object]) -> list[str]:
    errors: list[str] = []
    provider = str(payload.get("provider", "")).strip().lower()
    if not provider:
        errors.append(REQUIRED_FIELD_ERRORS["provider"])
    elif provider != SUPPORTED_PROVIDER:
        errors.append(f"Unsupported provider: {provider}. Only openai is currently available.")

    for key in ("openai_api_key", "porcupine_access_key", "openai_voice", "system_prompt"):
        value = payload.get(key, "")
        if not isinstance(value, str) or not value.strip():
            errors.append(REQUIRED_FIELD_ERRORS[key])

    return errors


def missing_required_fields(payload: dict[str, object]) -> list[str]:
    missing: list[str] = []
    provider = str(payload.get("provider", "")).strip().lower()
    if not provider:
        missing.append("provider")
    elif provider != SUPPORTED_PROVIDER:
        missing.append("provider")

    for key in ("openai_api_key", "porcupine_access_key", "openai_voice", "system_prompt"):
        value = payload.get(key, "")
        if not isinstance(value, str) or not value.strip():
            missing.append(key)

    return missing


def build_runtime_status(payload: dict[str, object]) -> str:
    return "not_configured" if missing_required_fields(payload) else "configured"


def editable_config_for_api(payload: dict[str, object]) -> dict[str, object]:
    return {
        "provider": payload["provider"],
        "openai_voice": payload["openai_voice"],
        "system_prompt": payload["system_prompt"],
        "location_city": payload["location_city"],
        "location_region": payload["location_region"],
        "location_country_code": payload["location_country_code"],
        "location_timezone": payload["location_timezone"],
        "session_window_enabled": payload["session_window_enabled"],
        "openai_api_key": "",
        "porcupine_access_key": "",
        "openai_api_key_configured": bool(str(payload["openai_api_key"]).strip()),
        "porcupine_access_key_configured": bool(str(payload["porcupine_access_key"]).strip()),
    }


def write_managed_config(paths: ManagedConfigPaths, payload: dict[str, object]) -> None:
    paths.data_dir.mkdir(parents=True, exist_ok=True)
    config_payload = {
        "provider": str(payload["provider"]).strip().lower(),
        "openai_voice": str(payload["openai_voice"]).strip(),
        "system_prompt": str(payload["system_prompt"]).strip(),
        "location_city": str(payload.get("location_city", "")).strip(),
        "location_region": str(payload.get("location_region", "")).strip(),
        "location_country_code": str(payload.get("location_country_code", "")).strip(),
        "location_timezone": str(payload.get("location_timezone", "")).strip(),
        "session_window_enabled": _coerce_bool(payload.get("session_window_enabled", False)),
    }
    config_tmp = paths.config_path.with_suffix(".json.tmp")
    with config_tmp.open("w", encoding="utf-8") as handle:
        json.dump(config_payload, handle, indent=2, ensure_ascii=True)
        handle.write("\n")
    config_tmp.replace(paths.config_path)

    secret_lines = [
        f'OPENAI_API_KEY="{_escape_env_value(str(payload["openai_api_key"]).strip())}"',
        f'PORCUPINE_ACCESS_KEY="{_escape_env_value(str(payload["porcupine_access_key"]).strip())}"',
    ]
    admin_password = str(payload.get("admin_password", "")).strip()
    if admin_password:
        secret_lines.append(f'ADMIN_PASSWORD="{_escape_env_value(admin_password)}"')
    secrets_tmp = paths.secrets_path.with_suffix(".env.tmp")
    with secrets_tmp.open("w", encoding="utf-8") as handle:
        handle.write("\n".join(secret_lines))
        handle.write("\n")
    secrets_tmp.replace(paths.secrets_path)


def _escape_env_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _coerce_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(value, (int, float)):
        return bool(value)
    return False
