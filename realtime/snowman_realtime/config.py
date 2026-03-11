from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .config_store import load_config_values


BASE_DIR = Path(__file__).resolve().parents[1]
AUDIO_DIR = BASE_DIR / "audio"
DEFAULT_WAKE_WORD_PATH = BASE_DIR / "Snowman_en_raspberry-pi_v4_0_0.ppn"
DEFAULT_READY_CUE_PATH = AUDIO_DIR / "ready_cue.wav"
DEFAULT_FAILURE_CUE_PATH = AUDIO_DIR / "wake_chime.wav"
DEFAULT_SESSION_END_CUE_PATH = AUDIO_DIR / "end_cue.wav"
DEFAULT_WEB_SEARCH_WAIT_CUE_PATH = AUDIO_DIR / "soft_piano_loop.wav"
DEFAULT_SYSTEM_PROMPT = (
    "You are a concise bilingual voice assistant running on a Raspberry Pi at the user's home. "
    "Voice style: friendly, clear, cheerful, warm, and supportive. "
    "Speak naturally with clear articulation, a steady conversational flow, and brief purposeful pauses after important points. "
    "You cannot see the user's surroundings, objects, screen, posture, or camera feed. "
    "Do not claim to see, inspect, identify, or describe any visual detail unless the user explicitly states those details in words. "
    "Do not say things like 'I can see', 'it looks like', or similar. "
    "If the audio is unclear, incomplete, nonspeech, or you are not confident what the user said, briefly say that you did not catch it and ask them to repeat. "
    "Do not guess or invent meaning from unclear audio. "
    "Reply in one short sentence by default, and use two short sentences only when needed for clarity. "
    "Keep spoken answers brief and complete. "
    "Answer the question directly. "
    "Prefer a direct answer over explanation unless the user explicitly asks for more detail. "
    "If the user is clearly ending the conversation, reply with one very short goodbye only. "
    "Use available tools for current local time, recent news, weather, prices, and other current information instead of guessing. "
    "Do not start with filler like 'okay', 'sure', '当然', or '好的'. "
    "Do not add pleasantries, thanks, return questions, or offers to help unless the user asks for them. "
    "Do not list multiple examples, options, or extra background unless asked. "
    "For translation requests, give just the translation unless the user asks for explanation. "
    "Keep it natural and speech-friendly. "
    "Reply in the same language as the clearly understood user utterance; if the utterance is unclear, use English."
)
LATEST_INFO_POLICY = (
    "For any question that could plausibly depend on current or changing information, you must call web_search before answering and must not answer from memory. "
    "This includes politics and officeholders, current leaders, recent events, news, weather, prices, exchange rates, laws, regulations, product availability, schedules, sports results, and anything phrased as current, latest, today, now, or recent. "
    "If web_search fails or is unavailable, briefly say that you cannot verify the latest information right now."
)
LATEST_TURN_POLICY = (
    "Do not greet, welcome, or introduce yourself. "
    "Answer only the user's most recent utterance."
)


class ConfigError(RuntimeError):
    """Raised when Snowman cannot start because required config is missing or invalid."""


def build_runtime_instructions(
    agent_name: str,
    system_prompt: str,
    *,
    latest_turn_only: bool = False,
    location_context: str | None = None,
    now: datetime | None = None,
) -> str:
    current_time = (now or datetime.now().astimezone()).replace(microsecond=0)
    utc_offset = current_time.strftime("%z")
    if len(utc_offset) == 5:
        utc_offset = f"{utc_offset[:3]}:{utc_offset[3:]}"
    current_time_context = (
        "Current local date and time on the Raspberry Pi: "
        f"{current_time.strftime('%A, %Y-%m-%d %H:%M:%S')} "
        f"{current_time.tzname() or 'local'} (UTC{utc_offset}). "
        "You may answer ordinary current date or time questions directly from this timestamp. "
        "Use local_time only if you need to re-check the exact current local time because the conversation has been open for a while or the user explicitly wants the precise current time."
    )

    instruction_parts = [_build_agent_identity_prompt(agent_name), _strip_legacy_name_line(system_prompt), current_time_context]
    if location_context and location_context.strip():
        instruction_parts.append(location_context.strip())
    instruction_parts.append(LATEST_INFO_POLICY)
    if latest_turn_only:
        instruction_parts.append(LATEST_TURN_POLICY)
    return "\n\n".join(part for part in instruction_parts if part).strip()


def build_location_prompt_context(
    *,
    street: str,
    city: str,
    region: str,
    country_code: str,
) -> str:
    parts = [part.strip() for part in (street, city, region, country_code) if part and part.strip()]
    if not parts:
        return ""
    return (
        f"Your current default location, and the user's default location unless they specify otherwise, is {', '.join(parts)}. "
        "If the user explicitly gives a different location, use the user-provided location instead."
    )


def build_web_search_user_location(
    *,
    city: str,
    region: str,
    country_code: str,
    timezone: str,
) -> dict[str, str] | None:
    city = city.strip()
    region = region.strip()
    country_code = country_code.strip()
    timezone = timezone.strip()
    if not any((city, region, country_code, timezone)):
        return None

    location: dict[str, str] = {
        "type": "approximate",
    }
    if city:
        location["city"] = city
    if region:
        location["region"] = region
    if country_code:
        location["country"] = country_code
    if timezone:
        location["timezone"] = timezone
    return location


@dataclass(frozen=True)
class Settings:
    agent_name: str
    provider: str
    openai_api_key: str
    openai_realtime_url: str
    openai_realtime_model: str
    openai_voice: str
    input_transcription_model: str
    openai_beta_header: str
    porcupine_access_key: str
    custom_wake_keyword_path: str
    wake_word_sensitivity: float
    audio_device_index: int
    input_frame_length: int
    input_sample_rate: int
    realtime_sample_rate: int
    session_idle_timeout: float
    session_window_enabled: bool
    session_followup_timeout: float
    session_max_turns: int
    interruption_enabled: bool
    log_level: str
    system_prompt: str
    location_street: str
    location_city: str
    location_region: str
    location_country_code: str
    location_timezone: str
    ready_cue_path: str
    post_reply_cue_path: str
    post_reply_cue_delay_seconds: float
    failure_cue_path: str
    session_end_cue_path: str
    web_search_wait_cue_enabled: bool
    web_search_wait_cue_path: str
    web_search_wait_cue_delay_seconds: float
    web_search_wait_cue_gain: float
    web_search_model: str
    playback_device: str
    output_gain: float
    cue_output_gain: float
    input_ns_enabled: bool
    input_agc_enabled: bool
    input_ns_noise_floor_margin: float
    input_ns_min_rms: int
    input_ns_attenuation: float
    input_agc_target_rms: int
    input_agc_max_gain: float
    input_agc_attack: float
    input_agc_release: float
    turn_detection_type: str
    turn_detection_eagerness: str
    turn_detection_create_response: bool
    turn_detection_interrupt_response: bool
    recording_start_timeout: float
    recording_max_duration: float
    recording_silence_duration: float
    recording_rms_threshold: int
    recording_preroll_frames: int
    auto_trigger_enabled: bool
    auto_trigger_interval_seconds: float
    auto_trigger_max_sessions: int
    auto_trigger_use_synthetic_audio: bool
    auto_trigger_synthetic_audio_ms: int
    auto_trigger_synthetic_frequency_hz: float
    auto_trigger_synthetic_amplitude: int
    response_max_output_tokens: int
    health_heartbeat_enabled: bool
    health_heartbeat_interval_seconds: float
    realtime_connect_timeout_seconds: float
    realtime_session_created_timeout_seconds: float
    realtime_post_update_grace_seconds: float
    realtime_connect_retries: int
    realtime_retry_backoff_seconds: float
    realtime_retry_backoff_max_seconds: float

    @classmethod
    def load(cls) -> "Settings":
        config_values = load_config_values(default_system_prompt=DEFAULT_SYSTEM_PROMPT)
        advanced = config_values["advanced"]
        assert isinstance(advanced, dict)

        provider = str(config_values["provider"]).strip().lower()
        if provider != "openai":
            raise ConfigError(
                f"Unsupported provider {provider!r}; only 'openai' is implemented"
            )

        openai_api_key = str(config_values["openai_api_key"]).strip()
        if not openai_api_key:
            raise ConfigError("OPENAI_API_KEY is required in config.json and secrets.json")

        porcupine_access_key = str(config_values["porcupine_access_key"]).strip()
        if not porcupine_access_key:
            raise ConfigError("PORCUPINE_ACCESS_KEY is required in config.json and secrets.json")

        return cls(
            agent_name=str(config_values["agent_name"]).strip() or "Snowman",
            provider=provider,
            openai_api_key=openai_api_key,
            openai_realtime_url=_get_str(advanced, "openai_realtime_url", "wss://api.openai.com/v1/realtime"),
            openai_realtime_model=str(config_values["openai_realtime_model"]).strip(),
            openai_voice=str(config_values["openai_voice"]).strip(),
            input_transcription_model=_get_str(advanced, "input_transcription_model", "gpt-4o-mini-transcribe"),
            openai_beta_header=_get_str(advanced, "openai_beta_header", "realtime=v1"),
            porcupine_access_key=porcupine_access_key,
            custom_wake_keyword_path=str(
                _resolve_path(
                    str(config_values["custom_wake_keyword_path"]).strip()
                    or str(DEFAULT_WAKE_WORD_PATH)
                )
            ),
            wake_word_sensitivity=float(config_values["wake_word_sensitivity"]),
            audio_device_index=_get_int(advanced, "audio_device_index", -1),
            input_frame_length=_get_int(advanced, "input_frame_length", 512),
            input_sample_rate=_get_int(advanced, "input_sample_rate", 16000),
            realtime_sample_rate=_get_int(advanced, "realtime_sample_rate", 24000),
            session_idle_timeout=_get_float(advanced, "session_idle_timeout", 20.0),
            session_window_enabled=True,
            session_followup_timeout=_get_float(advanced, "session_followup_timeout", 6.0),
            session_max_turns=_get_int(advanced, "session_max_turns", 0),
            interruption_enabled=_get_bool(advanced, "interruption_enabled", True),
            log_level=_get_str(advanced, "log_level", "INFO").upper(),
            system_prompt=str(config_values["system_prompt"]).strip(),
            location_street=str(config_values["location_street"]).strip(),
            location_city=str(config_values["location_city"]).strip(),
            location_region=str(config_values["location_region"]).strip(),
            location_country_code=str(config_values["location_country_code"]).strip(),
            location_timezone=str(config_values["location_timezone"]).strip(),
            ready_cue_path=str(
                _resolve_path(
                    _get_str(advanced, "ready_cue_path", str(DEFAULT_READY_CUE_PATH))
                )
            ),
            post_reply_cue_path=_resolve_optional_path(
                _get_str(advanced, "post_reply_cue_path", str(DEFAULT_READY_CUE_PATH))
            ),
            post_reply_cue_delay_seconds=_get_float(advanced, "post_reply_cue_delay_seconds", 0.15),
            failure_cue_path=_resolve_optional_path(
                _get_str(advanced, "failure_cue_path", str(DEFAULT_FAILURE_CUE_PATH))
            ),
            session_end_cue_path=_resolve_optional_path(
                _get_str(advanced, "session_end_cue_path", str(DEFAULT_SESSION_END_CUE_PATH))
            ),
            web_search_wait_cue_enabled=_get_bool(advanced, "web_search_wait_cue_enabled", True),
            web_search_wait_cue_path=_resolve_optional_path(
                _get_str(advanced, "web_search_wait_cue_path", str(DEFAULT_WEB_SEARCH_WAIT_CUE_PATH))
            ),
            web_search_wait_cue_delay_seconds=_get_float(advanced, "web_search_wait_cue_delay_seconds", 0.5),
            web_search_wait_cue_gain=_get_float(advanced, "web_search_wait_cue_gain", 0.20),
            web_search_model=_get_str(advanced, "web_search_model", "gpt-5.2"),
            playback_device=_get_str(advanced, "playback_device", "auto"),
            output_gain=float(config_values["output_gain"]),
            cue_output_gain=float(config_values["cue_output_gain"]),
            input_ns_enabled=_get_bool(advanced, "input_ns_enabled", False),
            input_agc_enabled=_get_bool(advanced, "input_agc_enabled", False),
            input_ns_noise_floor_margin=_get_float(advanced, "input_ns_noise_floor_margin", 1.8),
            input_ns_min_rms=_get_int(advanced, "input_ns_min_rms", 25),
            input_ns_attenuation=_get_float(advanced, "input_ns_attenuation", 0.35),
            input_agc_target_rms=_get_int(advanced, "input_agc_target_rms", 1100),
            input_agc_max_gain=_get_float(advanced, "input_agc_max_gain", 4.0),
            input_agc_attack=_get_float(advanced, "input_agc_attack", 0.35),
            input_agc_release=_get_float(advanced, "input_agc_release", 0.08),
            turn_detection_type=_get_str(advanced, "turn_detection_type", "none"),
            turn_detection_eagerness=_get_str(advanced, "turn_detection_eagerness", "low"),
            turn_detection_create_response=_get_bool(advanced, "turn_detection_create_response", True),
            turn_detection_interrupt_response=_get_bool(advanced, "turn_detection_interrupt_response", False),
            recording_start_timeout=_get_float(advanced, "recording_start_timeout", 8.0),
            recording_max_duration=_get_float(advanced, "recording_max_duration", 10.0),
            recording_silence_duration=_get_float(advanced, "recording_silence_duration", 1.2),
            recording_rms_threshold=_get_int(advanced, "recording_rms_threshold", 45),
            recording_preroll_frames=_get_int(advanced, "recording_preroll_frames", 12),
            auto_trigger_enabled=_get_bool(advanced, "auto_trigger_enabled", False),
            auto_trigger_interval_seconds=_get_float(advanced, "auto_trigger_interval_seconds", 0.0),
            auto_trigger_max_sessions=_get_int(advanced, "auto_trigger_max_sessions", 0),
            auto_trigger_use_synthetic_audio=_get_bool(advanced, "auto_trigger_use_synthetic_audio", False),
            auto_trigger_synthetic_audio_ms=_get_int(advanced, "auto_trigger_synthetic_audio_ms", 2500),
            auto_trigger_synthetic_frequency_hz=_get_float(advanced, "auto_trigger_synthetic_frequency_hz", 220.0),
            auto_trigger_synthetic_amplitude=_get_int(advanced, "auto_trigger_synthetic_amplitude", 700),
            response_max_output_tokens=_get_int(advanced, "response_max_output_tokens", 800),
            health_heartbeat_enabled=_get_bool(advanced, "health_heartbeat_enabled", True),
            health_heartbeat_interval_seconds=_get_float(advanced, "health_heartbeat_interval_seconds", 60.0),
            realtime_connect_timeout_seconds=_get_float(advanced, "realtime_connect_timeout_seconds", 20.0),
            realtime_session_created_timeout_seconds=_get_float(advanced, "realtime_session_created_timeout_seconds", 3.0),
            realtime_post_update_grace_seconds=_get_float(advanced, "realtime_post_update_grace_seconds", 1.0),
            realtime_connect_retries=_get_int(advanced, "realtime_connect_retries", 2),
            realtime_retry_backoff_seconds=_get_float(advanced, "realtime_retry_backoff_seconds", 0.75),
            realtime_retry_backoff_max_seconds=_get_float(advanced, "realtime_retry_backoff_max_seconds", 3.0),
        )

    @property
    def realtime_ws_url(self) -> str:
        return f"{self.openai_realtime_url}?model={self.openai_realtime_model}"


def _resolve_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        resolved = path
    else:
        resolved = (BASE_DIR / path).resolve()

    if resolved.exists():
        return resolved

    latest_matching = sorted(BASE_DIR.glob("Snowman_en_raspberry-pi_v*_*.ppn"))
    if latest_matching:
        return latest_matching[-1].resolve()

    return resolved


def _resolve_optional_path(raw_path: str) -> str:
    if not raw_path:
        return ""
    path = Path(raw_path)
    if path.is_absolute():
        return str(path)
    return str((BASE_DIR / path).resolve())


def configure_logging(level_name: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level_name, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _build_agent_identity_prompt(agent_name: str) -> str:
    name = agent_name.strip() or "Snowman"
    return f"Your name is {name}."


def _strip_legacy_name_line(system_prompt: str) -> str:
    prompt = system_prompt.strip()
    if not prompt.startswith("Your name is "):
        return prompt
    sentence_end = prompt.find(".")
    if sentence_end != -1:
        return prompt[sentence_end + 1 :].strip()
    return prompt


def _get_str(values: dict[str, object], name: str, default: str) -> str:
    value = values.get(name, default)
    return str(value).strip()


def _get_bool(values: dict[str, object], name: str, default: bool) -> bool:
    value = values.get(name, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def _get_int(values: dict[str, object], name: str, default: int) -> int:
    value = values.get(name, default)
    return int(value)


def _get_float(values: dict[str, object], name: str, default: float) -> float:
    value = values.get(name, default)
    return float(value)
