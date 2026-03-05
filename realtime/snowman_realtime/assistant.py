from __future__ import annotations

import audioop
import logging
import time
from collections import deque
from collections.abc import Callable

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
    ResponsePlaybackDone,
    ResponseTextDelta,
    ResponseTextDone,
    SessionClosed,
    SessionError,
    SessionStarted,
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
                if wake_event is None:
                    continue
                LOGGER.info("Wake event: %s", wake_event.keyword)
                while self._run_session():
                    LOGGER.info("Wake-word interrupt requested a new turn")
        finally:
            self._wake_detector.close()

    def _run_session(self) -> bool:
        player = RawAplayPlayer(
            sample_rate=self._settings.realtime_sample_rate,
            playback_device=resolve_playback_device(self._settings.playback_device),
            output_gain=self._settings.output_gain,
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
        response_started = False
        response_complete = False
        last_activity = time.monotonic()

        def handle_event(event: object) -> None:
            nonlocal should_stop, response_started, response_complete, last_activity
            last_activity = time.monotonic()

            if isinstance(event, ResponseAudioChunk):
                LOGGER.info("Received response audio chunk: %d bytes", len(event.audio_bytes))
                response_started = True
                player.play(event.audio_bytes)
                return

            if isinstance(event, ResponsePlaybackDone):
                LOGGER.info("Response playback done: %s", event.reason)
                response_complete = True
                return

            if isinstance(event, ResponseTextDelta):
                LOGGER.info("Response text delta: %s", event.text)
                return

            if isinstance(event, ResponseTextDone):
                LOGGER.info("Response text final: %s", event.text)
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
            microphone.start()
            utterance = self._record_utterance(microphone)
            if not utterance:
                LOGGER.info("No utterance captured after wake word")
                return False
            microphone.stop()

            client.connect()
            LOGGER.info("Realtime session started with %d placeholder tools", len(self._tool_registry.tools))

            for chunk in utterance:
                client.send_audio(resampler.convert(chunk))
            client.commit_input_audio()
            client.create_response()

            interrupted = self._play_response_until_done_or_interrupt(
                client=client,
                player=player,
                response_state=lambda: (response_started, response_complete, should_stop, last_activity),
            )
            return interrupted
        finally:
            try:
                microphone.stop()
            except Exception:
                LOGGER.debug("Microphone stop failed", exc_info=True)
            self._wake_detector.stop()
            client.close()
            player.close()
            LOGGER.info("Realtime session finished")

    def _record_utterance(self, microphone: MicrophoneStream) -> list[bytes]:
        LOGGER.info("Recording one utterance after wake word")
        frames: list[bytes] = []
        preroll_frames: deque[bytes] = deque(maxlen=self._settings.recording_preroll_frames)
        speech_started = False
        start_deadline = time.monotonic() + self._settings.recording_start_timeout
        max_deadline = time.monotonic() + self._settings.recording_max_duration
        last_voice_time = 0.0

        while time.monotonic() < max_deadline:
            pcm_16k = microphone.read_frame_bytes()
            rms = audioop.rms(pcm_16k, 2)
            LOGGER.info("Input RMS: %d", rms)

            if not speech_started:
                if rms >= self._settings.recording_rms_threshold:
                    speech_started = True
                    last_voice_time = time.monotonic()
                    frames.extend(preroll_frames)
                    frames.append(pcm_16k)
                    LOGGER.info(
                        "Speech started (rms=%d, preroll_frames=%d)",
                        rms,
                        len(preroll_frames),
                    )
                elif time.monotonic() >= start_deadline:
                    LOGGER.info("Speech start timeout reached")
                    return []
                preroll_frames.append(pcm_16k)
                continue

            frames.append(pcm_16k)
            if rms >= self._settings.recording_rms_threshold:
                last_voice_time = time.monotonic()

            if time.monotonic() - last_voice_time >= self._settings.recording_silence_duration:
                LOGGER.info("Speech ended after silence (frames=%d)", len(frames))
                return frames

        LOGGER.info("Recording max duration reached (frames=%d)", len(frames))
        return frames

    def _play_response_until_done_or_interrupt(
        self,
        client: RealtimeVoiceAgent,
        player: RawAplayPlayer,
        response_state: Callable[[], tuple[bool, bool, bool, float]],
    ) -> bool:
        LOGGER.info("Waiting for response playback; say the wake word again to interrupt")
        self._wake_detector.start()

        try:
            while True:
                response_started, response_complete, should_stop, last_activity = response_state()

                if should_stop:
                    return False

                if response_complete:
                    player.drain()
                    return False

                wake_event = self._wake_detector.poll_for_wake(timeout=0.15)
                if wake_event is not None:
                    LOGGER.info("Wake word interrupt detected during response playback")
                    client.interrupt()
                    player.interrupt()
                    return True

                if time.monotonic() - last_activity > self._settings.session_idle_timeout:
                    LOGGER.info("Session idle timeout reached while waiting for response")
                    return False
        finally:
            self._wake_detector.stop()
