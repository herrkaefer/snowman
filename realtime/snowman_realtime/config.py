from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_WAKE_WORD_PATH = BASE_DIR / "Snowman_en_raspberry-pi_v3_0_0.ppn"
DEFAULT_SYSTEM_PROMPT = (
    "You are Snowman, a concise and friendly bilingual voice assistant for Raspberry Pi. "
    "Keep replies short, natural, and speech-friendly. Prefer English for English input and "
    "Simplified Chinese for Chinese input."
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
            custom_wake_keyword_path=os.getenv(
                "CUSTOM_WAKE_KEYWORD_PATH", str(DEFAULT_WAKE_WORD_PATH)
            ).strip(),
            audio_device_index=int(os.getenv("AUDIO_DEVICE_INDEX", "-1")),
            input_frame_length=int(os.getenv("INPUT_FRAME_LENGTH", "512")),
            input_sample_rate=int(os.getenv("INPUT_SAMPLE_RATE", "16000")),
            realtime_sample_rate=int(os.getenv("REALTIME_SAMPLE_RATE", "24000")),
            session_idle_timeout=float(os.getenv("SESSION_IDLE_TIMEOUT", "20")),
            interruption_enabled=_get_bool("INTERRUPTION_ENABLED", True),
            log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper(),
            system_prompt=os.getenv("SYSTEM_PROMPT", DEFAULT_SYSTEM_PROMPT).strip(),
        )

    @property
    def realtime_ws_url(self) -> str:
        return f"{self.openai_realtime_url}?model={self.openai_realtime_model}"


def configure_logging(level_name: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level_name, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
