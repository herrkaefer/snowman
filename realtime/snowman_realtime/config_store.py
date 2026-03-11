from __future__ import annotations

import json
import os
import shlex
from dataclasses import dataclass
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = APP_DIR.parent / "data"
CONFIG_FILENAME = "config.json"
SECRETS_FILENAME = "secrets.json"
SUPPORTED_PROVIDER = "openai"
LEGACY_BASIC_ENV_TO_CONFIG_KEY = {
    "OPENAI_VOICE": "openai_voice",
    "SYSTEM_PROMPT": "system_prompt",
    "CUSTOM_WAKE_KEYWORD_PATH": "custom_wake_keyword_path",
    "LOCATION_CITY": "location_city",
    "LOCATION_REGION": "location_region",
    "LOCATION_COUNTRY_CODE": "location_country_code",
    "LOCATION_TIMEZONE": "location_timezone",
}
LEGACY_SECRET_ENV_TO_CONFIG_KEY = {
    "OPENAI_API_KEY": "openai_api_key",
    "PORCUPINE_ACCESS_KEY": "porcupine_access_key",
    "ADMIN_PASSWORD": "admin_password",
}

REQUIRED_FIELD_ERRORS = {
    "provider": "AI provider is required.",
    "openai_api_key": "OpenAI API key is required.",
    "porcupine_access_key": "Porcupine access key is required.",
    "openai_voice": "Voice is required.",
    "system_prompt": "Prompt is required.",
}

DEFAULT_ADVANCED_CONFIG: dict[str, object] = {
    "openai_realtime_url": "wss://api.openai.com/v1/realtime",
    "openai_realtime_model": "gpt-realtime",
    "input_transcription_model": "gpt-4o-mini-transcribe",
    "openai_beta_header": "realtime=v1",
    "wake_word_sensitivity": 0.5,
    "audio_device_index": -1,
    "input_frame_length": 512,
    "input_sample_rate": 16000,
    "realtime_sample_rate": 24000,
    "session_idle_timeout": 20.0,
    "session_followup_timeout": 6.0,
    "session_max_turns": 0,
    "interruption_enabled": True,
    "log_level": "INFO",
    "ready_cue_path": "audio/ready_cue.wav",
    "post_reply_cue_path": "audio/ready_cue.wav",
    "post_reply_cue_delay_seconds": 0.15,
    "failure_cue_path": "audio/wake_chime.wav",
    "session_end_cue_path": "audio/end_cue.wav",
    "web_search_wait_cue_enabled": True,
    "web_search_wait_cue_path": "audio/soft_piano_loop.wav",
    "web_search_wait_cue_delay_seconds": 0.5,
    "web_search_wait_cue_gain": 0.20,
    "web_search_model": "gpt-5.2",
    "playback_device": "auto",
    "output_gain": 0.5,
    "cue_output_gain": 0.22,
    "input_ns_enabled": False,
    "input_agc_enabled": False,
    "input_ns_noise_floor_margin": 1.8,
    "input_ns_min_rms": 25,
    "input_ns_attenuation": 0.35,
    "input_agc_target_rms": 1100,
    "input_agc_max_gain": 4.0,
    "input_agc_attack": 0.35,
    "input_agc_release": 0.08,
    "turn_detection_type": "none",
    "turn_detection_eagerness": "low",
    "turn_detection_create_response": True,
    "turn_detection_interrupt_response": False,
    "recording_start_timeout": 8.0,
    "recording_max_duration": 10.0,
    "recording_silence_duration": 1.2,
    "recording_rms_threshold": 45,
    "recording_preroll_frames": 12,
    "auto_trigger_enabled": False,
    "auto_trigger_interval_seconds": 0.0,
    "auto_trigger_max_sessions": 0,
    "auto_trigger_use_synthetic_audio": False,
    "auto_trigger_synthetic_audio_ms": 2500,
    "auto_trigger_synthetic_frequency_hz": 220.0,
    "auto_trigger_synthetic_amplitude": 700,
    "response_max_output_tokens": 800,
    "health_heartbeat_enabled": True,
    "health_heartbeat_interval_seconds": 60.0,
    "realtime_connect_timeout_seconds": 20.0,
    "realtime_session_created_timeout_seconds": 3.0,
    "realtime_post_update_grace_seconds": 1.0,
    "realtime_connect_retries": 2,
    "realtime_retry_backoff_seconds": 0.75,
    "realtime_retry_backoff_max_seconds": 3.0,
}


@dataclass(frozen=True)
class ConfigPaths:
    data_dir: Path
    config_path: Path
    secrets_path: Path


def resolve_config_paths() -> ConfigPaths:
    raw_data_dir = os.getenv("SNOWMAN_DATA_DIR", "").strip()
    data_dir = Path(raw_data_dir).expanduser() if raw_data_dir else DEFAULT_DATA_DIR
    return ConfigPaths(
        data_dir=data_dir,
        config_path=data_dir / CONFIG_FILENAME,
        secrets_path=data_dir / SECRETS_FILENAME,
    )


def load_secrets_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise RuntimeError(f"Secrets file must contain a JSON object: {path}")
    return {
        key: str(value).strip()
        for key, value in payload.items()
        if isinstance(key, str) and value is not None
    }


def load_config_file(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise RuntimeError(f"Config file must contain a JSON object: {path}")
    return payload


def default_config_values(*, default_system_prompt: str) -> dict[str, object]:
    return {
        "provider": SUPPORTED_PROVIDER,
        "openai_voice": "alloy",
        "system_prompt": default_system_prompt,
        "custom_wake_keyword_path": "",
        "location_city": "",
        "location_region": "",
        "location_country_code": "",
        "location_timezone": "",
        "openai_api_key": "",
        "porcupine_access_key": "",
        "admin_password": "",
        "advanced": dict(DEFAULT_ADVANCED_CONFIG),
    }


def default_public_config(*, default_system_prompt: str) -> dict[str, object]:
    defaults = default_config_values(default_system_prompt=default_system_prompt)
    return {
        "provider": defaults["provider"],
        "openai_voice": defaults["openai_voice"],
        "system_prompt": defaults["system_prompt"],
        "custom_wake_keyword_path": defaults["custom_wake_keyword_path"],
        "location_city": defaults["location_city"],
        "location_region": defaults["location_region"],
        "location_country_code": defaults["location_country_code"],
        "location_timezone": defaults["location_timezone"],
        "advanced": dict(DEFAULT_ADVANCED_CONFIG),
    }


def load_config_values(*, default_system_prompt: str) -> dict[str, object]:
    defaults = default_config_values(default_system_prompt=default_system_prompt)
    paths = resolve_config_paths()
    config_payload = load_config_file(paths.config_path)
    secret_payload = load_secrets_file(paths.secrets_path)
    return materialize_config_values(
        config_payload=config_payload,
        secret_payload=secret_payload,
        default_system_prompt=default_system_prompt,
    )


def materialize_config_values(
    *,
    config_payload: dict[str, object],
    secret_payload: dict[str, str],
    default_system_prompt: str,
) -> dict[str, object]:
    defaults = default_config_values(default_system_prompt=default_system_prompt)
    advanced_payload = config_payload.get("advanced", {})
    if not isinstance(advanced_payload, dict):
        advanced_payload = {}
    advanced = dict(DEFAULT_ADVANCED_CONFIG)
    for key, value in advanced_payload.items():
        if key in DEFAULT_ADVANCED_CONFIG:
            advanced[key] = value

    return {
        "provider": str(config_payload.get("provider", defaults["provider"])).strip(),
        "openai_voice": str(config_payload.get("openai_voice", defaults["openai_voice"])).strip(),
        "system_prompt": str(config_payload.get("system_prompt", defaults["system_prompt"])).strip(),
        "custom_wake_keyword_path": str(
            config_payload.get("custom_wake_keyword_path", defaults["custom_wake_keyword_path"])
        ).strip(),
        "location_city": str(config_payload.get("location_city", defaults["location_city"])).strip(),
        "location_region": str(config_payload.get("location_region", defaults["location_region"])).strip(),
        "location_country_code": str(
            config_payload.get("location_country_code", defaults["location_country_code"])
        ).strip(),
        "location_timezone": str(
            config_payload.get("location_timezone", defaults["location_timezone"])
        ).strip(),
        "openai_api_key": secret_payload.get("openai_api_key", "").strip(),
        "porcupine_access_key": secret_payload.get("porcupine_access_key", "").strip(),
        "admin_password": secret_payload.get("admin_password", "").strip(),
        "advanced": advanced,
    }


def merge_config_values(current: dict[str, object], updates: dict[str, object]) -> dict[str, object]:
    merged = dict(current)
    current_advanced = current.get("advanced", {})
    merged["advanced"] = dict(current_advanced) if isinstance(current_advanced, dict) else {}

    for key, value in updates.items():
        if key in {"openai_api_key", "porcupine_access_key", "admin_password"}:
            if isinstance(value, str):
                stripped = value.strip()
                if stripped:
                    merged[key] = stripped
            continue
        if key == "advanced":
            if not isinstance(value, dict):
                continue
            for adv_key, adv_value in value.items():
                if adv_key in DEFAULT_ADVANCED_CONFIG:
                    merged["advanced"][adv_key] = adv_value
            continue
        if isinstance(value, str):
            merged[key] = value.strip()
        else:
            merged[key] = value
    return merged


def validate_config_values(payload: dict[str, object]) -> list[str]:
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

    if not isinstance(payload.get("advanced", {}), dict):
        errors.append("Advanced config must be an object.")
    return errors


def missing_required_fields(payload: dict[str, object]) -> list[str]:
    missing: list[str] = []
    provider = str(payload.get("provider", "")).strip().lower()
    if not provider or provider != SUPPORTED_PROVIDER:
        missing.append("provider")

    for key in ("openai_api_key", "porcupine_access_key", "openai_voice", "system_prompt"):
        value = payload.get(key, "")
        if not isinstance(value, str) or not value.strip():
            missing.append(key)
    return missing


def config_values_for_api(payload: dict[str, object]) -> dict[str, object]:
    advanced = payload.get("advanced", {})
    openai_api_key = str(payload["openai_api_key"]).strip()
    porcupine_access_key = str(payload["porcupine_access_key"]).strip()
    return {
        "provider": payload["provider"],
        "openai_voice": payload["openai_voice"],
        "system_prompt": payload["system_prompt"],
        "custom_wake_keyword_path": payload["custom_wake_keyword_path"],
        "location_city": payload["location_city"],
        "location_region": payload["location_region"],
        "location_country_code": payload["location_country_code"],
        "location_timezone": payload["location_timezone"],
        "openai_api_key": "",
        "porcupine_access_key": "",
        "custom_wake_keyword_name": Path(str(payload["custom_wake_keyword_path"]).strip()).name,
        "custom_wake_keyword_configured": bool(str(payload["custom_wake_keyword_path"]).strip()),
        "openai_api_key_configured": bool(openai_api_key),
        "porcupine_access_key_configured": bool(porcupine_access_key),
        "openai_api_key_masked": _mask_secret(openai_api_key),
        "porcupine_access_key_masked": _mask_secret(porcupine_access_key),
        "advanced": advanced if isinstance(advanced, dict) else dict(DEFAULT_ADVANCED_CONFIG),
    }


def write_config_files(paths: ConfigPaths, payload: dict[str, object]) -> None:
    paths.data_dir.mkdir(parents=True, exist_ok=True)
    config_payload = {
        "provider": str(payload["provider"]).strip().lower(),
        "openai_voice": str(payload["openai_voice"]).strip(),
        "system_prompt": str(payload["system_prompt"]).strip(),
        "custom_wake_keyword_path": str(payload.get("custom_wake_keyword_path", "")).strip(),
        "location_city": str(payload.get("location_city", "")).strip(),
        "location_region": str(payload.get("location_region", "")).strip(),
        "location_country_code": str(payload.get("location_country_code", "")).strip(),
        "location_timezone": str(payload.get("location_timezone", "")).strip(),
        "advanced": _normalized_advanced_config(payload.get("advanced", {})),
    }
    config_tmp = paths.config_path.with_suffix(".json.tmp")
    with config_tmp.open("w", encoding="utf-8") as handle:
        json.dump(config_payload, handle, indent=2, ensure_ascii=True)
        handle.write("\n")
    config_tmp.replace(paths.config_path)

    secrets_payload = {
        "openai_api_key": str(payload["openai_api_key"]).strip(),
        "porcupine_access_key": str(payload["porcupine_access_key"]).strip(),
    }
    admin_password = str(payload.get("admin_password", "")).strip()
    if admin_password:
        secrets_payload["admin_password"] = admin_password
    secrets_tmp = paths.secrets_path.with_suffix(".json.tmp")
    with secrets_tmp.open("w", encoding="utf-8") as handle:
        json.dump(secrets_payload, handle, indent=2, ensure_ascii=True)
        handle.write("\n")
    secrets_tmp.replace(paths.secrets_path)


def load_legacy_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    payload: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        try:
            parsed = shlex.split(raw_value)
        except ValueError:
            continue
        payload[key] = parsed[0] if parsed else raw_value.strip('"')
    return payload


def config_updates_from_legacy_env(env_values: dict[str, str]) -> dict[str, object]:
    updates: dict[str, object] = {}
    for env_key, config_key in LEGACY_BASIC_ENV_TO_CONFIG_KEY.items():
        value = env_values.get(env_key, "").strip()
        if value:
            updates[config_key] = value

    advanced: dict[str, object] = {}
    for config_key, default_value in DEFAULT_ADVANCED_CONFIG.items():
        env_key = config_key.upper()
        raw_value = env_values.get(env_key, "").strip()
        if raw_value:
            advanced[config_key] = _coerce_legacy_value(raw_value, default_value)
    if advanced:
        updates["advanced"] = advanced
    return updates


def secret_updates_from_legacy_env(env_values: dict[str, str]) -> dict[str, str]:
    updates: dict[str, str] = {}
    for env_key, config_key in LEGACY_SECRET_ENV_TO_CONFIG_KEY.items():
        value = env_values.get(env_key, "").strip()
        if value:
            updates[config_key] = value
    return updates


def _normalized_advanced_config(value: object) -> dict[str, object]:
    normalized = dict(DEFAULT_ADVANCED_CONFIG)
    if isinstance(value, dict):
        for key, item in value.items():
            if key in DEFAULT_ADVANCED_CONFIG:
                normalized[key] = item
    return normalized


def _mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def _coerce_legacy_value(raw_value: str, default_value: object) -> object:
    if isinstance(default_value, bool):
        return raw_value.strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(default_value, int):
        return int(raw_value)
    if isinstance(default_value, float):
        return float(raw_value)
    return raw_value
