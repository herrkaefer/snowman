from __future__ import annotations

import audioop
import logging
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path

from .audio import (
    InputAudioProcessor,
    MicrophoneStream,
    PCMResampler,
    RawAplayPlayer,
    generate_sine_pcm,
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
            if self._settings.auto_trigger_enabled:
                self._run_auto_trigger_loop()
                return
            while True:
                wake_event = self._wake_detector.wait_for_wake()
                if wake_event is None:
                    continue
                LOGGER.info("Wake event: %s", wake_event.keyword)
                while self._run_session():
                    LOGGER.info("Wake-word interrupt requested a new turn")
        finally:
            self._wake_detector.close()

    def _run_auto_trigger_loop(self) -> None:
        LOGGER.info(
            "Auto trigger mode enabled: interval=%.2fs max_sessions=%d",
            self._settings.auto_trigger_interval_seconds,
            self._settings.auto_trigger_max_sessions,
        )
        session_count = 0
        while True:
            if (
                self._settings.auto_trigger_max_sessions > 0
                and session_count >= self._settings.auto_trigger_max_sessions
            ):
                LOGGER.info("Auto trigger session limit reached")
                return

            session_count += 1
            LOGGER.info("Auto trigger session %d starting", session_count)
            interrupted = self._run_session()
            if interrupted:
                LOGGER.info("Wake-word interrupt requested a new auto-triggered turn")
            if self._settings.auto_trigger_interval_seconds > 0:
                time.sleep(self._settings.auto_trigger_interval_seconds)

    def _run_session(self) -> bool:
        session_started_at = time.monotonic()
        player = RawAplayPlayer(
            sample_rate=self._settings.realtime_sample_rate,
            playback_device=resolve_playback_device(self._settings.playback_device),
            output_gain=self._settings.output_gain,
        )
        microphone = MicrophoneStream(
            device_index=resolve_input_device_index(self._settings.audio_device_index),
            frame_length=self._settings.input_frame_length,
            processor=InputAudioProcessor(
                noise_suppression_enabled=self._settings.input_ns_enabled,
                agc_enabled=self._settings.input_agc_enabled,
                noise_floor_margin=self._settings.input_ns_noise_floor_margin,
                noise_suppression_min_rms=self._settings.input_ns_min_rms,
                noise_suppression_attenuation=self._settings.input_ns_attenuation,
                agc_target_rms=self._settings.input_agc_target_rms,
                agc_max_gain=self._settings.input_agc_max_gain,
                agc_attack=self._settings.input_agc_attack,
                agc_release=self._settings.input_agc_release,
            ),
        )
        LOGGER.info(
            "Input cleanup: ns=%s agc=%s",
            self._settings.input_ns_enabled,
            self._settings.input_agc_enabled,
        )
        resampler = PCMResampler(
            source_rate=self._settings.input_sample_rate,
            target_rate=self._settings.realtime_sample_rate,
        )

        should_stop = False
        response_started = False
        response_complete = False
        last_activity = time.monotonic()
        first_response_audio_at: float | None = None
        response_done_at: float | None = None

        def handle_event(event: object) -> None:
            nonlocal should_stop, response_started, response_complete, last_activity
            nonlocal first_response_audio_at, response_done_at
            last_activity = time.monotonic()

            if isinstance(event, ResponseAudioChunk):
                LOGGER.info("Received response audio chunk: %d bytes", len(event.audio_bytes))
                response_started = True
                if first_response_audio_at is None:
                    first_response_audio_at = time.monotonic()
                player.play(event.audio_bytes)
                return

            if isinstance(event, ResponsePlaybackDone):
                LOGGER.info("Response playback done: %s", event.reason)
                response_complete = True
                response_done_at = time.monotonic()
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

        client: RealtimeVoiceAgent | None = None

        try:
            if Path(self._settings.ready_cue_path).exists():
                try:
                    player.play_wav_file(self._settings.ready_cue_path, blocking=True)
                except Exception:
                    LOGGER.exception("Failed to play ready cue")

            record_started_at = time.monotonic()
            utterance = self._capture_utterance(microphone)
            if not utterance:
                LOGGER.info("No utterance captured after trigger")
                return False
            record_finished_at = time.monotonic()
            LOGGER.info(
                "Recorded utterance: frames=%d duration=%.2fs",
                len(utterance),
                record_finished_at - record_started_at,
            )

            connect_started_at = time.monotonic()
            connect_result = self._connect_and_request_response(
                utterance=utterance,
                resampler=resampler,
                event_handler=handle_event,
            )
            if connect_result is None:
                self._play_failure_cue(player)
                return False
            client, response_requested_at = connect_result
            should_stop = False
            LOGGER.info("Realtime session started with %d placeholder tools", len(self._tool_registry.tools))
            LOGGER.info("Realtime connect duration: %.2fs", time.monotonic() - connect_started_at)

            interrupted = self._play_response_until_done_or_interrupt(
                client=client,
                player=player,
                response_state=lambda: (response_started, response_complete, should_stop, last_activity),
            )
            if first_response_audio_at is not None:
                LOGGER.info(
                    "First response audio latency: %.2fs",
                    first_response_audio_at - response_requested_at,
                )
            if response_done_at is not None and first_response_audio_at is not None:
                LOGGER.info(
                    "Response playback duration: %.2fs",
                    response_done_at - first_response_audio_at,
                )
            if response_complete:
                self._play_post_reply_cue(player)
            return interrupted
        finally:
            try:
                microphone.stop()
            except Exception:
                LOGGER.debug("Microphone stop failed", exc_info=True)
            self._wake_detector.stop()
            if client is not None:
                client.close()
            player.close()
            LOGGER.info("Realtime session finished in %.2fs", time.monotonic() - session_started_at)

    def _connect_and_request_response(
        self,
        utterance: list[bytes],
        resampler: PCMResampler,
        event_handler: Callable[[object], None],
    ) -> tuple[RealtimeVoiceAgent, float] | None:
        max_attempts = max(1, self._settings.realtime_connect_retries + 1)

        for attempt in range(1, max_attempts + 1):
            client = RealtimeVoiceAgent(self._settings, event_handler)
            try:
                client.connect()
                for chunk in utterance:
                    client.send_audio(resampler.convert(chunk))
                client.commit_input_audio()
                response_requested_at = time.monotonic()
                client.create_response()
                return client, response_requested_at
            except (Exception, RealtimeConnectionClosed) as exc:
                failure_kind = self._classify_realtime_attempt_error(exc)
                LOGGER.warning(
                    "Realtime request attempt %d/%d failed (%s): %s",
                    attempt,
                    max_attempts,
                    failure_kind,
                    exc,
                )
                client.close()
                if attempt >= max_attempts:
                    break
                backoff_seconds = min(
                    self._settings.realtime_retry_backoff_seconds * (2 ** (attempt - 1)),
                    self._settings.realtime_retry_backoff_max_seconds,
                )
                LOGGER.info(
                    "Retrying Realtime request in %.2fs",
                    backoff_seconds,
                )
                time.sleep(backoff_seconds)

        LOGGER.error("Realtime request failed after %d attempts", max_attempts)
        return None

    def _classify_realtime_attempt_error(self, exc: Exception) -> str:
        message = str(exc).lower()
        if "timed out" in message or "timeout" in message:
            return "timeout"
        if "session.update" in message:
            return "post_update"
        if "session.created" in message:
            return "session_created"
        if "socket is closed" in message or "socket closed" in message:
            return "socket_closed"
        return exc.__class__.__name__

    def _play_post_reply_cue(self, player: RawAplayPlayer) -> None:
        cue_path = self._settings.post_reply_cue_path
        if not cue_path or not Path(cue_path).exists():
            return
        try:
            player.play_wav_file(cue_path, blocking=True)
        except Exception:
            LOGGER.exception("Failed to play post-reply cue")

    def _play_failure_cue(self, player: RawAplayPlayer) -> None:
        cue_path = self._settings.failure_cue_path
        if not cue_path or not Path(cue_path).exists():
            return
        try:
            player.play_wav_file(cue_path, blocking=True)
        except Exception:
            LOGGER.exception("Failed to play failure cue")

    def _record_utterance(self, microphone: MicrophoneStream) -> list[bytes]:
        LOGGER.info("Recording one utterance after trigger")
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

    def _capture_utterance(self, microphone: MicrophoneStream) -> list[bytes]:
        if (
            self._settings.auto_trigger_enabled
            and self._settings.auto_trigger_use_synthetic_audio
        ):
            LOGGER.info(
                "Using synthetic auto-trigger utterance: duration_ms=%d freq=%.1f amplitude=%d",
                self._settings.auto_trigger_synthetic_audio_ms,
                self._settings.auto_trigger_synthetic_frequency_hz,
                self._settings.auto_trigger_synthetic_amplitude,
            )
            return self._build_synthetic_utterance()

        microphone.start()
        try:
            return self._record_utterance(microphone)
        finally:
            microphone.stop()

    def _build_synthetic_utterance(self) -> list[bytes]:
        pcm_bytes = generate_sine_pcm(
            sample_rate=self._settings.input_sample_rate,
            duration_ms=self._settings.auto_trigger_synthetic_audio_ms,
            amplitude=self._settings.auto_trigger_synthetic_amplitude,
            frequency_hz=self._settings.auto_trigger_synthetic_frequency_hz,
        )
        bytes_per_frame = self._settings.input_frame_length * 2
        utterance = [
            pcm_bytes[offset : offset + bytes_per_frame]
            for offset in range(0, len(pcm_bytes), bytes_per_frame)
        ]
        if not utterance:
            return []
        if len(utterance[-1]) < bytes_per_frame:
            utterance[-1] = utterance[-1] + (b"\x00" * (bytes_per_frame - len(utterance[-1])))
        return utterance

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
