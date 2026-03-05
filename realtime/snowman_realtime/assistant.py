from __future__ import annotations

import logging
import time
from pathlib import Path

from .audio import (
    MicrophoneStream,
    PCMResampler,
    RawAplayPlayer,
    resolve_input_device_index,
    resolve_playback_device,
)
from .config import Settings
from .events import (
    ResponseAudioChunk,
    ResponseInterrupted,
    ResponsePlaybackDone,
    SessionClosed,
    SessionError,
    SessionStarted,
    TranscriptFinal,
)
from .realtime_client import RealtimeConnectionClosed, RealtimeVoiceAgent
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
        player = RawAplayPlayer(
            sample_rate=self._settings.realtime_sample_rate,
            playback_device=resolve_playback_device(self._settings.playback_device),
        )
        microphone = MicrophoneStream(
            device_index=resolve_input_device_index(self._settings.audio_device_index),
            frame_length=self._settings.input_frame_length,
        )
        resampler = PCMResampler(
            source_rate=self._settings.input_sample_rate,
            target_rate=self._settings.realtime_sample_rate,
        )

        should_stop = False
        playback_active = False
        playback_done_pending = False
        last_activity = time.monotonic()

        def handle_event(event: object) -> None:
            nonlocal should_stop, playback_active, playback_done_pending, last_activity
            last_activity = time.monotonic()

            if isinstance(event, ResponseAudioChunk):
                LOGGER.info("Received response audio chunk: %d bytes", len(event.audio_bytes))
                playback_active = True
                player.play(event.audio_bytes)
                return

            if isinstance(event, ResponsePlaybackDone):
                LOGGER.info("Response playback done: %s", event.reason)
                playback_done_pending = True
                return

            if isinstance(event, ResponseInterrupted):
                LOGGER.info("Response interrupted: %s", event.reason)
                player.interrupt()
                playback_active = False
                playback_done_pending = False
                return

            if isinstance(event, SessionStarted):
                LOGGER.info("Realtime session established: %s", event.session_id)
                return

            if isinstance(event, TranscriptFinal):
                transcript = event.text.strip()
                LOGGER.info("Final transcript: %s", transcript)
                lowered = transcript.lower()
                if lowered in END_PHRASES:
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
            LOGGER.info("Realtime session started with %d placeholder tools", len(self._tool_registry.tools))

            if Path(self._settings.wake_chime_path).exists():
                try:
                    player.play_wav_file(self._settings.wake_chime_path, blocking=True)
                except Exception:
                    LOGGER.exception("Failed to play wake chime")

            microphone.start()
            LOGGER.info(
                "Continuous conversation mode enabled with %s (%s)",
                self._settings.turn_detection_type,
                self._settings.turn_detection_eagerness,
            )

            while not should_stop:
                pcm_16k = microphone.read_frame_bytes()

                if playback_done_pending:
                    player.drain()
                    playback_active = False
                    playback_done_pending = False
                    continue

                if playback_active:
                    continue

                try:
                    client.send_audio(resampler.convert(pcm_16k))
                except RealtimeConnectionClosed:
                    LOGGER.info("Realtime connection closed during audio upload")
                    break

                if time.monotonic() - last_activity > self._settings.session_idle_timeout:
                    LOGGER.info("Session idle timeout reached")
                    break
        finally:
            try:
                microphone.stop()
            except Exception:
                LOGGER.debug("Microphone stop failed", exc_info=True)
            client.close()
            player.close()
            LOGGER.info("Realtime session finished")
