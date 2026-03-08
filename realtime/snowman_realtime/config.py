from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_WAKE_WORD_PATH = BASE_DIR / "Snowman_en_raspberry-pi_v4_0_0.ppn"
DEFAULT_READY_CUE_PATH = BASE_DIR / "ready_cue.wav"
DEFAULT_FAILURE_CUE_PATH = BASE_DIR / "wake_chime.wav"
DEFAULT_SESSION_END_CUE_PATH = BASE_DIR / "end_cue.wav"
DEFAULT_WEB_SEARCH_WAIT_CUE_PATH = BASE_DIR / "soft_piano_loop.wav"
DEFAULT_SYSTEM_PROMPT = (
    "Your name is Snowman. You are a concise bilingual voice assistant for Raspberry Pi. "
    "Never say that you do not have a name. "
    "Tone: clear, calm, and direct. "
    "Pronunciation: clear, articulate, and steady, while keeping a natural conversational flow. "
    "Pacing: use brief, purposeful pauses after important points so the user can follow comfortably. "
    "Emotion: warm but restrained. "
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


def build_runtime_instructions(
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

    instruction_parts = [system_prompt.strip(), current_time_context]
    if location_context and location_context.strip():
        instruction_parts.append(location_context.strip())
    instruction_parts.append(LATEST_INFO_POLICY)
    if latest_turn_only:
        instruction_parts.append(LATEST_TURN_POLICY)
    return "\n\n".join(part for part in instruction_parts if part).strip()


def build_location_prompt_context(
    *,
    city: str,
    region: str,
    country_code: str,
) -> str:
    if not city or not region or not country_code:
        return ""
    return (
        f"Default local context for Snowman and the current user: {city}, {region}, {country_code}. "
        "Use this as the default location for local questions such as weather, nearby places, traffic, commute, and other ambiguous location-dependent requests. "
        "If the user explicitly names a different place, use the user-provided location instead."
    )


def build_web_search_user_location(
    *,
    city: str,
    region: str,
    country_code: str,
    timezone: str,
) -> dict[str, str] | None:
    if not city or not region or not country_code:
        return None

    location = {
        "type": "approximate",
        "city": city,
        "region": region,
        "country": country_code,
    }
    if timezone:
        location["timezone"] = timezone
    return location


def _get_bool(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
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
        load_dotenv(BASE_DIR / ".env")

        openai_api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required in realtime/.env")

        porcupine_access_key = os.getenv("PORCUPINE_ACCESS_KEY", "").strip()
        if not porcupine_access_key:
            raise RuntimeError("PORCUPINE_ACCESS_KEY is required in realtime/.env")

        return cls(
            openai_api_key=openai_api_key,
            openai_realtime_url=os.getenv(
                "OPENAI_REALTIME_URL", "wss://api.openai.com/v1/realtime"
            ).strip(),
            openai_realtime_model=os.getenv("OPENAI_REALTIME_MODEL", "gpt-realtime-mini").strip(),
            openai_voice=os.getenv("OPENAI_VOICE", "alloy").strip(),
            input_transcription_model=os.getenv(
                "INPUT_TRANSCRIPTION_MODEL", "gpt-4o-mini-transcribe"
            ).strip(),
            openai_beta_header=os.getenv("OPENAI_BETA_HEADER", "realtime=v1").strip(),
            porcupine_access_key=porcupine_access_key,
            custom_wake_keyword_path=str(
                _resolve_path(
                    os.getenv("CUSTOM_WAKE_KEYWORD_PATH", str(DEFAULT_WAKE_WORD_PATH)).strip()
                )
            ),
            wake_word_sensitivity=float(os.getenv("WAKE_WORD_SENSITIVITY", "0.5")),
            audio_device_index=int(os.getenv("AUDIO_DEVICE_INDEX", "-1")),
            input_frame_length=int(os.getenv("INPUT_FRAME_LENGTH", "512")),
            input_sample_rate=int(os.getenv("INPUT_SAMPLE_RATE", "16000")),
            realtime_sample_rate=int(os.getenv("REALTIME_SAMPLE_RATE", "24000")),
            session_idle_timeout=float(os.getenv("SESSION_IDLE_TIMEOUT", "20")),
            session_window_enabled=_get_bool("SESSION_WINDOW_ENABLED", False),
            session_followup_timeout=float(os.getenv("SESSION_FOLLOWUP_TIMEOUT", "6.0")),
            session_max_turns=int(os.getenv("SESSION_MAX_TURNS", "0")),
            interruption_enabled=_get_bool("INTERRUPTION_ENABLED", True),
            log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper(),
            system_prompt=os.getenv("SYSTEM_PROMPT", DEFAULT_SYSTEM_PROMPT).strip(),
            location_city=os.getenv("LOCATION_CITY", "").strip(),
            location_region=os.getenv("LOCATION_REGION", "").strip(),
            location_country_code=os.getenv("LOCATION_COUNTRY_CODE", "").strip(),
            location_timezone=(
                os.getenv("LOCATION_TIMEZONE", "").strip()
                or os.getenv("TZ", "").strip()
            ),
            ready_cue_path=str(
                _resolve_path(
                    os.getenv("READY_CUE_PATH", str(DEFAULT_READY_CUE_PATH)).strip()
                )
            ),
            post_reply_cue_path=_resolve_optional_path(
                os.getenv("POST_REPLY_CUE_PATH", str(DEFAULT_READY_CUE_PATH)).strip()
            ),
            post_reply_cue_delay_seconds=float(
                os.getenv("POST_REPLY_CUE_DELAY_SECONDS", "0.15")
            ),
            failure_cue_path=_resolve_optional_path(
                os.getenv("FAILURE_CUE_PATH", str(DEFAULT_FAILURE_CUE_PATH)).strip()
            ),
            session_end_cue_path=_resolve_optional_path(
                os.getenv("SESSION_END_CUE_PATH", str(DEFAULT_SESSION_END_CUE_PATH)).strip()
            ),
            web_search_wait_cue_enabled=_get_bool("WEB_SEARCH_WAIT_CUE_ENABLED", True),
            web_search_wait_cue_path=_resolve_optional_path(
                os.getenv(
                    "WEB_SEARCH_WAIT_CUE_PATH",
                    str(DEFAULT_WEB_SEARCH_WAIT_CUE_PATH),
                ).strip()
            ),
            web_search_wait_cue_delay_seconds=float(
                os.getenv("WEB_SEARCH_WAIT_CUE_DELAY_SECONDS", "0.5")
            ),
            web_search_wait_cue_gain=float(os.getenv("WEB_SEARCH_WAIT_CUE_GAIN", "0.20")),
            web_search_model=os.getenv("WEB_SEARCH_MODEL", "gpt-5.2").strip(),
            playback_device=os.getenv("PLAYBACK_DEVICE", "auto").strip(),
            output_gain=float(os.getenv("OUTPUT_GAIN", "0.5")),
            cue_output_gain=float(os.getenv("CUE_OUTPUT_GAIN", "0.22")),
            input_ns_enabled=_get_bool("INPUT_NS_ENABLED", False),
            input_agc_enabled=_get_bool("INPUT_AGC_ENABLED", False),
            input_ns_noise_floor_margin=float(
                os.getenv("INPUT_NS_NOISE_FLOOR_MARGIN", "1.8")
            ),
            input_ns_min_rms=int(os.getenv("INPUT_NS_MIN_RMS", "25")),
            input_ns_attenuation=float(os.getenv("INPUT_NS_ATTENUATION", "0.35")),
            input_agc_target_rms=int(os.getenv("INPUT_AGC_TARGET_RMS", "1100")),
            input_agc_max_gain=float(os.getenv("INPUT_AGC_MAX_GAIN", "4.0")),
            input_agc_attack=float(os.getenv("INPUT_AGC_ATTACK", "0.35")),
            input_agc_release=float(os.getenv("INPUT_AGC_RELEASE", "0.08")),
            turn_detection_type=os.getenv("TURN_DETECTION_TYPE", "none").strip(),
            turn_detection_eagerness=os.getenv("TURN_DETECTION_EAGERNESS", "low").strip(),
            turn_detection_create_response=_get_bool("TURN_DETECTION_CREATE_RESPONSE", True),
            turn_detection_interrupt_response=_get_bool(
                "TURN_DETECTION_INTERRUPT_RESPONSE", False
            ),
            recording_start_timeout=float(os.getenv("RECORDING_START_TIMEOUT", "8.0")),
            recording_max_duration=float(os.getenv("RECORDING_MAX_DURATION", "10.0")),
            recording_silence_duration=float(os.getenv("RECORDING_SILENCE_DURATION", "1.2")),
            recording_rms_threshold=int(os.getenv("RECORDING_RMS_THRESHOLD", "45")),
            recording_preroll_frames=int(os.getenv("RECORDING_PREROLL_FRAMES", "12")),
            auto_trigger_enabled=_get_bool("AUTO_TRIGGER_ENABLED", False),
            auto_trigger_interval_seconds=float(
                os.getenv("AUTO_TRIGGER_INTERVAL_SECONDS", "0.0")
            ),
            auto_trigger_max_sessions=int(os.getenv("AUTO_TRIGGER_MAX_SESSIONS", "0")),
            auto_trigger_use_synthetic_audio=_get_bool(
                "AUTO_TRIGGER_USE_SYNTHETIC_AUDIO", False
            ),
            auto_trigger_synthetic_audio_ms=int(
                os.getenv("AUTO_TRIGGER_SYNTHETIC_AUDIO_MS", "2500")
            ),
            auto_trigger_synthetic_frequency_hz=float(
                os.getenv("AUTO_TRIGGER_SYNTHETIC_FREQUENCY_HZ", "220.0")
            ),
            auto_trigger_synthetic_amplitude=int(
                os.getenv("AUTO_TRIGGER_SYNTHETIC_AMPLITUDE", "700")
            ),
            response_max_output_tokens=int(os.getenv("RESPONSE_MAX_OUTPUT_TOKENS", "800")),
            health_heartbeat_enabled=_get_bool("HEALTH_HEARTBEAT_ENABLED", True),
            health_heartbeat_interval_seconds=float(
                os.getenv("HEALTH_HEARTBEAT_INTERVAL_SECONDS", "60.0")
            ),
            realtime_connect_timeout_seconds=float(
                os.getenv("REALTIME_CONNECT_TIMEOUT_SECONDS", "20.0")
            ),
            realtime_session_created_timeout_seconds=float(
                os.getenv("REALTIME_SESSION_CREATED_TIMEOUT_SECONDS", "3.0")
            ),
            realtime_post_update_grace_seconds=float(
                os.getenv("REALTIME_POST_UPDATE_GRACE_SECONDS", "1.0")
            ),
            realtime_connect_retries=int(os.getenv("REALTIME_CONNECT_RETRIES", "2")),
            realtime_retry_backoff_seconds=float(
                os.getenv("REALTIME_RETRY_BACKOFF_SECONDS", "0.75")
            ),
            realtime_retry_backoff_max_seconds=float(
                os.getenv("REALTIME_RETRY_BACKOFF_MAX_SECONDS", "3.0")
            ),
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
