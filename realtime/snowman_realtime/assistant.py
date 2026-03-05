from __future__ import annotations

import logging
import time

from .audio import MicrophoneStream, PCMResampler, RawAplayPlayer
from .config import Settings
from .events import (
    ResponseAudioChunk,
    ResponseInterrupted,
    SessionClosed,
    SessionError,
    TranscriptFinal,
)
from .realtime_client import RealtimeVoiceAgent
from .tools import ToolRegistry
from .wake_word import WakeWordDetector


LOGGER = logging.getLogger(__name__)
END_PHRASES = {
    "goodbye",
    "bye",
    "stop listening",
    "end conversation",
    "再见",
    "再見",
    "结束对话",
    "結束對話",
}


class SnowmanRealtimeAssistant:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._wake_detector = WakeWordDetector(settings)
        self._tool_registry = ToolRegistry()

    def run(self) -> None:
        LOGGER.info("Snowman Realtime ready")
        try:
            while True:
                wake_event = self._wake_detector.wait_for_wake()
                LOGGER.info("Wake event: %s", wake_event.keyword)
                self._run_session()
        finally:
            self._wake_detector.close()

    def _run_session(self) -> None:
        player = RawAplayPlayer(sample_rate=self._settings.realtime_sample_rate)
        microphone = MicrophoneStream(
            device_index=self._settings.audio_device_index,
            frame_length=self._settings.input_frame_length,
        )
        resampler = PCMResampler(
            source_rate=self._settings.input_sample_rate,
            target_rate=self._settings.realtime_sample_rate,
        )

        should_stop = False
        last_activity = time.monotonic()

        def handle_event(event: object) -> None:
            nonlocal should_stop, last_activity
            last_activity = time.monotonic()

            if isinstance(event, ResponseAudioChunk):
                player.play(event.audio_bytes)
                return

            if isinstance(event, ResponseInterrupted):
                if self._settings.interruption_enabled:
                    player.interrupt()
                LOGGER.info("Response interrupted: %s", event.reason)
                return

            if isinstance(event, TranscriptFinal):
                LOGGER.info("User said: %s", event.text)
                normalized_text = event.text.strip().lower()
                if any(phrase.lower() in normalized_text for phrase in END_PHRASES):
                    should_stop = True
                return

            if isinstance(event, SessionError):
                LOGGER.error("Realtime session error: %s", event.message)
                should_stop = True
                return

            if isinstance(event, SessionClosed):
                LOGGER.info("Realtime session closed: %s", event.reason)
                should_stop = True

        client = RealtimeVoiceAgent(self._settings, handle_event)

        try:
            client.connect()
            microphone.start()
            LOGGER.info("Realtime session started with %d placeholder tools", len(self._tool_registry.tools))

            while not should_stop:
                if time.monotonic() - last_activity > self._settings.session_idle_timeout:
                    LOGGER.info("Session idle timeout reached")
                    break
                pcm_16k = microphone.read_frame_bytes()
                client.send_audio(resampler.convert(pcm_16k))
        finally:
            microphone.stop()
            client.close()
            player.close()
            LOGGER.info("Realtime session finished")
