from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_WAKE_WORD_PATH = BASE_DIR / "Snowman_en_raspberry-pi_v4_0_0.ppn"
DEFAULT_READY_CUE_PATH = BASE_DIR / "ready_cue.wav"
DEFAULT_SYSTEM_PROMPT = (
    "You are Snowman, a concise bilingual voice assistant for Raspberry Pi. "
    "Reply in one short sentence by default, and use two short sentences only when needed for clarity. "
    "Keep spoken answers brief and complete. "
    "Prefer a direct answer over explanation unless the user explicitly asks for more detail. "
    "Do not start with filler like 'okay', 'sure', or '当然'. "
    "Do not list multiple examples, options, or extra background unless asked. "
    "For translation requests, give just the translation unless the user asks for explanation. "
    "Keep it natural and speech-friendly. Prefer English for English input and Simplified Chinese for Chinese input."
)


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
    openai_beta_header: str
    porcupine_access_key: str
    custom_wake_keyword_path: str
    audio_device_index: int
    input_frame_length: int
    input_sample_rate: int
    realtime_sample_rate: int
    session_idle_timeout: float
    interruption_enabled: bool
    log_level: str
    system_prompt: str
    ready_cue_path: str
    post_reply_cue_path: str
    playback_device: str
    output_gain: float
    turn_detection_type: str
    turn_detection_eagerness: str
    turn_detection_create_response: bool
    turn_detection_interrupt_response: bool
    recording_start_timeout: float
    recording_max_duration: float
    recording_silence_duration: float
    recording_rms_threshold: int
    recording_preroll_frames: int
    response_max_output_tokens: int

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
            openai_realtime_model=os.getenv("OPENAI_REALTIME_MODEL", "gpt-realtime").strip(),
            openai_voice=os.getenv("OPENAI_VOICE", "alloy").strip(),
            openai_beta_header=os.getenv("OPENAI_BETA_HEADER", "realtime=v1").strip(),
            porcupine_access_key=porcupine_access_key,
            custom_wake_keyword_path=str(
                _resolve_path(
                    os.getenv("CUSTOM_WAKE_KEYWORD_PATH", str(DEFAULT_WAKE_WORD_PATH)).strip()
                )
            ),
            audio_device_index=int(os.getenv("AUDIO_DEVICE_INDEX", "-1")),
            input_frame_length=int(os.getenv("INPUT_FRAME_LENGTH", "512")),
            input_sample_rate=int(os.getenv("INPUT_SAMPLE_RATE", "16000")),
            realtime_sample_rate=int(os.getenv("REALTIME_SAMPLE_RATE", "24000")),
            session_idle_timeout=float(os.getenv("SESSION_IDLE_TIMEOUT", "20")),
            interruption_enabled=_get_bool("INTERRUPTION_ENABLED", True),
            log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper(),
            system_prompt=os.getenv("SYSTEM_PROMPT", DEFAULT_SYSTEM_PROMPT).strip(),
            ready_cue_path=str(
                _resolve_path(
                    os.getenv("READY_CUE_PATH", str(DEFAULT_READY_CUE_PATH)).strip()
                )
            ),
            post_reply_cue_path=_resolve_optional_path(
                os.getenv("POST_REPLY_CUE_PATH", str(DEFAULT_READY_CUE_PATH)).strip()
            ),
            playback_device=os.getenv("PLAYBACK_DEVICE", "auto").strip(),
            output_gain=float(os.getenv("OUTPUT_GAIN", "0.5")),
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
            response_max_output_tokens=int(os.getenv("RESPONSE_MAX_OUTPUT_TOKENS", "500")),
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
    return str(_resolve_path(raw_path))


def configure_logging(level_name: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level_name, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
