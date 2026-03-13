from __future__ import annotations

import json
import os
import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import available_timezones

from .country_data import COUNTRY_OPTIONS


APP_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = APP_DIR.parent / "data"
CONFIG_FILENAME = "config.json"
SECRETS_FILENAME = "secrets.json"
IDENTITY_FILENAME = "identity.md"
SUPPORTED_PROVIDER = "openai"
LEGACY_BASIC_ENV_TO_CONFIG_KEY = {
    "OPENAI_REALTIME_MODEL": "openai_realtime_model",
    "OPENAI_VOICE": "openai_voice",
    "WAKE_WORD_SENSITIVITY": "wake_word_sensitivity",
    "OUTPUT_GAIN": "output_gain",
    "CUE_OUTPUT_GAIN": "cue_output_gain",
    "LOCATION_STREET": "location_street",
    "CUSTOM_WAKE_KEYWORD_PATH": "custom_wake_keyword_path",
    "LOCATION_CITY": "location_city",
    "LOCATION_REGION": "location_region",
    "LOCATION_COUNTRY_CODE": "location_country_code",
    "LOCATION_TIMEZONE": "location_timezone",
}

PROVIDER_OPTIONS = (SUPPORTED_PROVIDER,)

OPENAI_REALTIME_MODEL_OPTIONS = (
    "gpt-realtime",
    "gpt-realtime-mini",
)

OPENAI_VOICE_OPTIONS = (
    "alloy",
    "ash",
    "ballad",
    "coral",
    "echo",
    "fable",
    "marin",
    "nova",
    "onyx",
    "sage",
    "shimmer",
    "verse",
)
LEGACY_SECRET_ENV_TO_CONFIG_KEY = {
    "OPENAI_API_KEY": "openai_api_key",
    "PORCUPINE_ACCESS_KEY": "porcupine_access_key",
    "ADMIN_PASSWORD": "admin_password",
}

REQUIRED_FIELD_ERRORS = {
    "provider": "AI provider is required.",
    "openai_api_key": "API key is required.",
    "porcupine_access_key": "Porcupine access key is required.",
    "custom_wake_keyword_path": "Wake word model (.ppn) is required.",
    "openai_realtime_model": "Realtime model is required.",
    "openai_voice": "Voice is required.",
    "system_prompt": "Prompt is required.",
}

DEFAULT_ADVANCED_CONFIG: dict[str, object] = {
    "openai_realtime_url": "wss://api.openai.com/v1/realtime",
    "input_transcription_model": "gpt-4o-mini-transcribe",
    "openai_beta_header": "realtime=v1",
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
    "memory_enabled": True,
    "memory_dir": "state/memory",
}


@dataclass(frozen=True)
class ConfigPaths:
    data_dir: Path
    config_path: Path
    secrets_path: Path
    identity_path: Path


def resolve_config_paths() -> ConfigPaths:
    raw_data_dir = os.getenv("SNOWMAN_DATA_DIR", "").strip()
    data_dir = Path(raw_data_dir).expanduser() if raw_data_dir else DEFAULT_DATA_DIR
    return ConfigPaths(
        data_dir=data_dir,
        config_path=data_dir / CONFIG_FILENAME,
        secrets_path=data_dir / SECRETS_FILENAME,
        identity_path=data_dir / IDENTITY_FILENAME,
    )


def load_identity_file(path: Path) -> str:
    if not path.exists():
        return ""
    return _editable_system_prompt(path.read_text(encoding="utf-8"))


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
        "agent_name": "Snowman",
        "provider": SUPPORTED_PROVIDER,
        "openai_realtime_model": OPENAI_REALTIME_MODEL_OPTIONS[0],
        "openai_voice": "alloy",
        "system_prompt": default_system_prompt,
        "location_street": "",
        "wake_word_sensitivity": 0.5,
        "output_gain": 0.5,
        "cue_output_gain": 0.22,
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
        "agent_name": defaults["agent_name"],
        "provider": defaults["provider"],
        "openai_realtime_model": defaults["openai_realtime_model"],
        "openai_voice": defaults["openai_voice"],
        "system_prompt": defaults["system_prompt"],
        "location_street": defaults["location_street"],
        "wake_word_sensitivity": defaults["wake_word_sensitivity"],
        "output_gain": defaults["output_gain"],
        "cue_output_gain": defaults["cue_output_gain"],
        "custom_wake_keyword_path": defaults["custom_wake_keyword_path"],
        "location_city": defaults["location_city"],
        "location_region": defaults["location_region"],
        "location_country_code": defaults["location_country_code"],
        "location_timezone": defaults["location_timezone"],
        "advanced": dict(DEFAULT_ADVANCED_CONFIG),
    }


def load_config_values(*, default_system_prompt: str) -> dict[str, object]:
    paths = resolve_config_paths()
    config_payload = load_config_file(paths.config_path)
    secret_payload = load_secrets_file(paths.secrets_path)
    identity_prompt = load_identity_file(paths.identity_path)
    return materialize_config_values(
        config_payload=config_payload,
        secret_payload=secret_payload,
        default_system_prompt=default_system_prompt,
        identity_prompt=identity_prompt,
    )


def materialize_config_values(
    *,
    config_payload: dict[str, object],
    secret_payload: dict[str, str],
    default_system_prompt: str,
    identity_prompt: str = "",
) -> dict[str, object]:
    defaults = default_config_values(default_system_prompt=default_system_prompt)
    advanced_payload = config_payload.get("advanced", {})
    if not isinstance(advanced_payload, dict):
        advanced_payload = {}
    wake_word_sensitivity = config_payload.get(
        "wake_word_sensitivity",
        advanced_payload.get("wake_word_sensitivity", defaults["wake_word_sensitivity"]),
    )
    output_gain = config_payload.get(
        "output_gain",
        advanced_payload.get("output_gain", defaults["output_gain"]),
    )
    cue_output_gain = config_payload.get(
        "cue_output_gain",
        advanced_payload.get("cue_output_gain", defaults["cue_output_gain"]),
    )
    advanced = dict(DEFAULT_ADVANCED_CONFIG)
    for key, value in advanced_payload.items():
        if key in DEFAULT_ADVANCED_CONFIG:
            advanced[key] = value

    prompt_value = _editable_system_prompt(identity_prompt) or defaults["system_prompt"]

    return {
        "agent_name": str(config_payload.get("agent_name", defaults["agent_name"])).strip(),
        "provider": str(config_payload.get("provider", defaults["provider"])).strip(),
        "openai_realtime_model": str(
            config_payload.get(
                "openai_realtime_model",
                advanced_payload.get("openai_realtime_model", defaults["openai_realtime_model"]),
            )
        ).strip(),
        "openai_voice": str(config_payload.get("openai_voice", defaults["openai_voice"])).strip(),
        "system_prompt": prompt_value,
        "location_street": str(config_payload.get("location_street", defaults["location_street"])).strip(),
        "wake_word_sensitivity": _coerce_config_value(wake_word_sensitivity, defaults["wake_word_sensitivity"]),
        "output_gain": _coerce_config_value(output_gain, defaults["output_gain"]),
        "cue_output_gain": _coerce_config_value(cue_output_gain, defaults["cue_output_gain"]),
        "custom_wake_keyword_path": str(
            config_payload.get("custom_wake_keyword_path", defaults["custom_wake_keyword_path"])
        ).strip(),
        "location_city": str(config_payload.get("location_city", defaults["location_city"])).strip(),
        "location_region": str(config_payload.get("location_region", defaults["location_region"])).strip(),
        "location_country_code": _normalized_country_code(
            config_payload.get("location_country_code", defaults["location_country_code"])
        ),
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

    for key in (
        "openai_api_key",
        "porcupine_access_key",
        "custom_wake_keyword_path",
        "openai_realtime_model",
        "openai_voice",
        "system_prompt",
    ):
        value = payload.get(key, "")
        if not isinstance(value, str) or not value.strip():
            errors.append(REQUIRED_FIELD_ERRORS[key])

    agent_name = str(payload.get("agent_name", "")).strip()
    if not agent_name:
        errors.append("Voice assistant name is required.")

    model = str(payload.get("openai_realtime_model", "")).strip()
    if model and model not in OPENAI_REALTIME_MODEL_OPTIONS:
        errors.append(
            "Realtime model must be one of: "
            + ", ".join(OPENAI_REALTIME_MODEL_OPTIONS)
            + "."
        )

    voice = str(payload.get("openai_voice", "")).strip()
    if voice and voice not in OPENAI_VOICE_OPTIONS:
        errors.append(
            "Voice must be one of: "
            + ", ".join(OPENAI_VOICE_OPTIONS)
            + "."
        )

    advanced = payload.get("advanced", {})
    if isinstance(advanced, dict):
        audio_device_index = advanced.get("audio_device_index", -1)
        try:
            int(audio_device_index)
        except (TypeError, ValueError):
            errors.append("Microphone input must be a valid device selection.")

        playback_device = str(advanced.get("playback_device", "auto")).strip()
        if not playback_device:
            errors.append("Speaker output must be a valid device selection.")

    try:
        wake_word_sensitivity = float(payload.get("wake_word_sensitivity", 0.5))
    except (TypeError, ValueError):
        errors.append("Wake word sensitivity must be a number between 0.0 and 1.0.")
    else:
        if not 0.0 <= wake_word_sensitivity <= 1.0:
            errors.append("Wake word sensitivity must be between 0.0 and 1.0.")

    for gain_key, label in (("output_gain", "Output gain"), ("cue_output_gain", "Cue gain")):
        try:
            float(payload.get(gain_key, 0.0))
        except (TypeError, ValueError):
            errors.append(f"{label} must be a number.")

    if not isinstance(payload.get("advanced", {}), dict):
        errors.append("Advanced config must be an object.")
    return errors


def missing_required_fields(payload: dict[str, object]) -> list[str]:
    missing: list[str] = []
    provider = str(payload.get("provider", "")).strip().lower()
    if not provider or provider != SUPPORTED_PROVIDER:
        missing.append("provider")

    for key in (
        "openai_api_key",
        "porcupine_access_key",
        "custom_wake_keyword_path",
        "openai_realtime_model",
        "openai_voice",
        "system_prompt",
    ):
        value = payload.get(key, "")
        if not isinstance(value, str) or not value.strip():
            missing.append(key)
    if not str(payload.get("agent_name", "")).strip():
        missing.append("agent_name")
    return missing


def config_values_for_api(payload: dict[str, object]) -> dict[str, object]:
    advanced = payload.get("advanced", {})
    openai_api_key = str(payload["openai_api_key"]).strip()
    porcupine_access_key = str(payload["porcupine_access_key"]).strip()
    return {
        "agent_name": payload["agent_name"],
        "provider": payload["provider"],
        "openai_realtime_model": payload["openai_realtime_model"],
        "openai_voice": payload["openai_voice"],
        "audio_device_index": int(advanced.get("audio_device_index", -1)),
        "playback_device": str(advanced.get("playback_device", "auto")).strip() or "auto",
        "system_prompt": _editable_system_prompt(str(payload["system_prompt"])),
        "location_street": payload["location_street"],
        "wake_word_sensitivity": payload["wake_word_sensitivity"],
        "output_gain": payload["output_gain"],
        "cue_output_gain": payload["cue_output_gain"],
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
        "provider_options": list(PROVIDER_OPTIONS),
        "openai_realtime_model_options": list(OPENAI_REALTIME_MODEL_OPTIONS),
        "openai_voice_options": list(OPENAI_VOICE_OPTIONS),
        "country_options": _country_options(),
        "timezone_options": _timezone_options(),
        "advanced": advanced if isinstance(advanced, dict) else dict(DEFAULT_ADVANCED_CONFIG),
    }


def write_config_files(paths: ConfigPaths, payload: dict[str, object]) -> None:
    paths.data_dir.mkdir(parents=True, exist_ok=True)
    config_payload = {
        "agent_name": str(payload.get("agent_name", "Snowman")).strip() or "Snowman",
        "provider": str(payload["provider"]).strip().lower(),
        "openai_realtime_model": str(payload["openai_realtime_model"]).strip(),
        "openai_voice": str(payload["openai_voice"]).strip(),
        "location_street": str(payload.get("location_street", "")).strip(),
        "wake_word_sensitivity": float(payload.get("wake_word_sensitivity", 0.5)),
        "output_gain": float(payload.get("output_gain", 0.5)),
        "cue_output_gain": float(payload.get("cue_output_gain", 0.22)),
        "custom_wake_keyword_path": str(payload.get("custom_wake_keyword_path", "")).strip(),
        "location_city": str(payload.get("location_city", "")).strip(),
        "location_region": str(payload.get("location_region", "")).strip(),
        "location_country_code": _normalized_country_code(payload.get("location_country_code", "")),
        "location_timezone": str(payload.get("location_timezone", "")).strip(),
        "advanced": _normalized_advanced_config(payload.get("advanced", {})),
    }
    config_tmp = paths.config_path.with_suffix(".json.tmp")
    with config_tmp.open("w", encoding="utf-8") as handle:
        json.dump(config_payload, handle, indent=2, ensure_ascii=True)
        handle.write("\n")
    config_tmp.replace(paths.config_path)

    identity_tmp = paths.identity_path.with_suffix(".md.tmp")
    identity_tmp.write_text(
        _editable_system_prompt(str(payload["system_prompt"])) + "\n",
        encoding="utf-8",
    )
    identity_tmp.replace(paths.identity_path)

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
            if config_key in {"wake_word_sensitivity", "output_gain", "cue_output_gain"}:
                updates[config_key] = float(value)
            else:
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


def _coerce_config_value(value: object, default_value: object) -> object:
    if value is None:
        return default_value
    if isinstance(default_value, bool):
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(default_value, int):
        return int(value)
    if isinstance(default_value, float):
        return float(value)
    return value


def _editable_system_prompt(system_prompt: str) -> str:
    prompt = system_prompt.strip()
    if not prompt or prompt.startswith("#"):
        return prompt
    if not _looks_like_legacy_identity_prompt(prompt):
        return prompt
    return _legacy_identity_to_markdown(prompt)


def _looks_like_legacy_identity_prompt(prompt: str) -> bool:
    normalized = " ".join(prompt.split()).lower()
    required_markers = (
        "you are a concise",
        "voice style:",
        "reply in one short sentence",
        "reply in the same language",
    )
    return all(marker in normalized for marker in required_markers)


def _legacy_identity_to_markdown(prompt: str) -> str:
    sentences = _split_prompt_sentences(prompt)
    sections: list[tuple[str, list[str]]] = [
        ("Role", []),
        ("Tone", []),
        ("Perception Limits", []),
        ("Audio Handling", []),
        ("Response Style", []),
        ("Tool Use", []),
        ("Language", []),
        ("Additional Rules", []),
    ]
    section_map = {title: items for title, items in sections}

    for sentence in sentences:
        lower = sentence.lower()
        if sentence.startswith("You are "):
            section_map["Role"].append(sentence)
        elif sentence.startswith("Voice style:") or sentence.startswith("Speak naturally") or sentence.startswith("Keep it natural"):
            section_map["Tone"].append(sentence)
        elif "cannot see" in lower or sentence.startswith("Do not claim to see") or sentence.startswith("Do not say things like"):
            section_map["Perception Limits"].append(sentence)
        elif sentence.startswith("If the audio is unclear") or sentence.startswith("Do not guess or invent meaning from unclear audio"):
            section_map["Audio Handling"].append(sentence)
        elif sentence.startswith("Use available tools"):
            section_map["Tool Use"].append(sentence)
        elif sentence.startswith("Reply in the same language") or sentence.startswith("If the utterance is unclear, use English"):
            section_map["Language"].append(sentence)
        elif (
            sentence.startswith("Reply in one short sentence")
            or sentence.startswith("Keep spoken answers")
            or sentence.startswith("Answer the question directly")
            or sentence.startswith("Prefer a direct answer")
            or sentence.startswith("If the user is clearly ending")
            or sentence.startswith("Do not start with filler")
            or sentence.startswith("Do not add pleasantries")
            or sentence.startswith("Do not list multiple examples")
            or sentence.startswith("For translation requests")
        ):
            section_map["Response Style"].append(sentence)
        else:
            section_map["Additional Rules"].append(sentence)

    lines = ["# Identity"]
    for title, items in sections:
        if not items:
            continue
        lines.append("")
        lines.append(f"## {title}")
        for item in items:
            lines.append(f"- {item}")
    return "\n".join(lines).strip()


def _split_prompt_sentences(prompt: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", prompt.strip())
    parts = re.split(r"(?<=[.!?])\s+", normalized)
    return [part.strip() for part in parts if part.strip()]


def _timezone_options() -> list[str]:
    return [""] + sorted(available_timezones())


def _country_options() -> list[dict[str, str]]:
    return [{"value": "", "label": "Select a country"}] + [
        {"value": code, "label": name} for code, name in COUNTRY_OPTIONS
    ]


def _normalized_country_code(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    upper = raw.upper()
    for code, name in COUNTRY_OPTIONS:
        if raw == code or upper == code:
            return code
        if raw.casefold() == name.casefold():
            return code
    return upper
