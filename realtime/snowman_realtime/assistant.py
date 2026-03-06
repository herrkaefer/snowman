from __future__ import annotations

import audioop
import json
import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
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
    ResponseInterrupted,
    ResponsePlaybackDone,
    ResponseTextDelta,
    ResponseTextDone,
    SessionClosed,
    SessionError,
    SessionStarted,
    ToolCallRequested,
    TranscriptFinal,
)
from .realtime_client import RealtimeConnectionClosed, RealtimeVoiceAgent
from .status_led import SessionStatusLed
from .tools import ToolRegistry
from .wake_word import WakeWordDetector


LOGGER = logging.getLogger(__name__)
END_PHRASES = {
    "goodbye",
    "bye",
    "bye bye",
    "byebye",
    "see you",
    "see ya",
    "talk to you later",
    "stop listening",
    "end conversation",
    "that's all",
    "thats all",
    "all done",
    "thanks",
    "thank you",
    "thankyou",
    "再见",
    "再見",
    "谢谢",
    "謝謝",
    "多谢",
    "多謝",
    "谢了",
    "謝了",
    "拜拜",
    "掰掰",
    "先这样",
    "就这样吧",
    "结束对话",
    "結束對話",
}

NORMALIZED_END_PHRASES = {
    "goodbye",
    "bye",
    "byebye",
    "seeyou",
    "seeya",
    "talktoyoulater",
    "stoplistening",
    "endconversation",
    "thatsall",
    "alldone",
    "thanks",
    "thankyou",
    "再见",
    "再見",
    "谢谢",
    "謝謝",
    "多谢",
    "多謝",
    "谢了",
    "謝了",
    "拜拜",
    "掰掰",
    "先这样",
    "就这样吧",
    "结束对话",
    "結束對話",
}


class SessionWindowState(str, Enum):
    IDLE = "idle"
    READY = "ready"
    RECORDING_TURN = "recording_turn"
    WAITING_FOR_REPLY = "waiting_for_reply"
    PLAYING_REPLY = "playing_reply"
    SESSION_TIMEOUT = "session_timeout"
    SESSION_END = "session_end"


class PlaybackResult(str, Enum):
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    STOPPED = "stopped"
    SESSION_TIMEOUT = "session_timeout"


@dataclass
class TurnRuntimeState:
    reply_expected: bool = False
    response_started: bool = False
    response_complete: bool = False
    should_stop: bool = False
    session_end_requested: bool = False
    last_activity: float = 0.0
    first_response_audio_at: float | None = None
    response_done_at: float | None = None
    active_response_id: str | None = None
    ignored_response_ids: set[str] = field(default_factory=set)


class ToolWaitLoop:
    def __init__(
        self,
        *,
        path: str,
        delay_seconds: float,
        gain: float,
        sample_rate: int,
        playback_device: str | None,
    ) -> None:
        self._path = path
        self._delay_seconds = max(0.0, delay_seconds)
        self._gain = gain
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._player = RawAplayPlayer(
            sample_rate=sample_rate,
            playback_device=playback_device,
            output_gain=1.0,
        )

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._player.interrupt()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        self._player.close()

    def _run(self) -> None:
        if self._stop_event.wait(self._delay_seconds):
            return
        LOGGER.info("Starting web_search wait cue loop")
        while not self._stop_event.is_set():
            try:
                self._player.play_wav_file(
                    self._path,
                    blocking=True,
                    gain=self._gain,
                )
            except Exception:
                if not self._stop_event.is_set():
                    LOGGER.exception("Failed to play web_search wait cue")
                return
        LOGGER.info("Stopped web_search wait cue loop")


class SnowmanRealtimeAssistant:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._wake_detector = WakeWordDetector(settings)
        self._status_led = SessionStatusLed()
        self._tool_registry = ToolRegistry(settings)
        self._health_state = "starting"
        self._health_state_lock = threading.Lock()
        self._health_stop_event = threading.Event()
        self._health_thread: threading.Thread | None = None

    def run(self) -> None:
        LOGGER.info("Snowman Realtime ready")
        self._start_health_heartbeat()
        try:
            if self._settings.auto_trigger_enabled:
                self._set_health_state("auto_trigger_idle")
                self._run_auto_trigger_loop()
                return
            while True:
                self._set_health_state("idle_waiting_for_wake")
                wake_event = self._wake_detector.wait_for_wake()
                if wake_event is None:
                    continue
                LOGGER.info("Wake event: %s", wake_event.keyword)
                while self._run_session():
                    LOGGER.info("Wake-word interrupt requested a new turn")
        finally:
            self._stop_health_heartbeat()
            self._status_led.close()
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
        if self._settings.session_window_enabled:
            self._run_session_window()
            return False
        return self._run_single_turn_session()

    def _build_session_io(
        self,
    ) -> tuple[RawAplayPlayer, MicrophoneStream, PCMResampler]:
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
        return player, microphone, resampler

    def _set_session_state(
        self,
        current_state: SessionWindowState,
        next_state: SessionWindowState,
        *,
        reason: str | None = None,
    ) -> SessionWindowState:
        if current_state == next_state:
            return current_state
        if reason:
            LOGGER.info("Session state: %s -> %s (%s)", current_state.value, next_state.value, reason)
        else:
            LOGGER.info("Session state: %s -> %s", current_state.value, next_state.value)
        self._apply_session_led_state(next_state)
        self._set_health_state(next_state.value)
        return next_state

    def _set_health_state(self, state: str) -> None:
        with self._health_state_lock:
            self._health_state = state

    def _start_health_heartbeat(self) -> None:
        if not self._settings.health_heartbeat_enabled:
            return
        self._health_thread = threading.Thread(target=self._health_heartbeat_loop, daemon=True)
        self._health_thread.start()

    def _stop_health_heartbeat(self) -> None:
        self._health_stop_event.set()
        if self._health_thread is not None:
            self._health_thread.join(timeout=1.0)

    def _health_heartbeat_loop(self) -> None:
        interval = max(5.0, self._settings.health_heartbeat_interval_seconds)
        while not self._health_stop_event.wait(interval):
            with self._health_state_lock:
                state = self._health_state
            LOGGER.info("Health heartbeat: state=%s", state)

    def _apply_session_led_state(self, state: SessionWindowState) -> None:
        if state in {SessionWindowState.READY, SessionWindowState.RECORDING_TURN}:
            self._status_led.user_can_speak()
            return
        if state in {SessionWindowState.WAITING_FOR_REPLY, SessionWindowState.PLAYING_REPLY}:
            self._status_led.processing()
            return
        self._status_led.off()

    def _create_tool_wait_loop(self, tool_name: str) -> ToolWaitLoop | None:
        if tool_name != "web_search":
            return None
        if not self._settings.web_search_wait_cue_enabled:
            return None
        cue_path = self._settings.web_search_wait_cue_path
        if not cue_path or not Path(cue_path).exists():
            return None
        return ToolWaitLoop(
            path=cue_path,
            delay_seconds=self._settings.web_search_wait_cue_delay_seconds,
            gain=self._settings.web_search_wait_cue_gain,
            sample_rate=self._settings.realtime_sample_rate,
            playback_device=resolve_playback_device(self._settings.playback_device),
        )

    def _handle_tool_call(
        self,
        *,
        client: RealtimeVoiceAgent | None,
        event: ToolCallRequested,
        on_client_missing: Callable[[], None],
    ) -> None:
        if client is None:
            LOGGER.error("Tool call arrived before Realtime client was ready")
            on_client_missing()
            return

        wait_loop = self._create_tool_wait_loop(event.name)
        if wait_loop is not None:
            wait_loop.start()

        tool_output: str
        try:
            tool_output = self._tool_registry.execute(
                event.name,
                event.arguments_json,
            )
            LOGGER.info("Tool completed: %s", event.name)
        except Exception as exc:
            LOGGER.exception("Tool execution failed: %s", event.name)
            tool_output = json.dumps({"error": str(exc)}, ensure_ascii=False)
        finally:
            if wait_loop is not None:
                wait_loop.stop()

        client.submit_tool_output(
            call_id=event.call_id,
            output_json=tool_output,
        )
        client.create_response()

    def _is_end_transcript(self, transcript: str) -> bool:
        normalized = "".join(ch for ch in transcript.strip().lower() if ch.isalnum())
        if not normalized:
            return False
        return any(phrase in normalized for phrase in NORMALIZED_END_PHRASES)

    def _run_session_window(self) -> None:
        session_started_at = time.monotonic()
        session_state = SessionWindowState.IDLE
        player, microphone, resampler = self._build_session_io()
        client: RealtimeVoiceAgent | None = None
        turn_state: TurnRuntimeState | None = None
        turn_index = 0
        play_session_end_cue = False
        interrupted_response_ids: set[str] = set()

        def handle_event(event: object) -> None:
            nonlocal session_state, turn_state
            state = turn_state
            if state is not None:
                state.last_activity = time.monotonic()

            if isinstance(event, ResponseAudioChunk):
                if state is None:
                    return
                if not state.reply_expected:
                    LOGGER.debug("Ignoring response audio before reply is expected")
                    return
                if event.response_id and event.response_id in interrupted_response_ids:
                    LOGGER.debug(
                        "Ignoring audio chunk from interrupted response: %s",
                        event.response_id,
                    )
                    return
                if event.response_id:
                    if state.active_response_id is None:
                        state.active_response_id = event.response_id
                    elif state.active_response_id != event.response_id:
                        LOGGER.debug(
                            "Ignoring audio chunk from unexpected response: active=%s got=%s",
                            state.active_response_id,
                            event.response_id,
                        )
                        return
                LOGGER.info("Received response audio chunk: %d bytes", len(event.audio_bytes))
                if not state.response_started:
                    session_state = self._set_session_state(
                        session_state,
                        SessionWindowState.PLAYING_REPLY,
                    )
                    state.response_started = True
                if state.first_response_audio_at is None:
                    state.first_response_audio_at = time.monotonic()
                player.play(event.audio_bytes)
                return

            if isinstance(event, ResponsePlaybackDone):
                if state is None:
                    return
                if not state.reply_expected:
                    return
                if event.response_id and event.response_id in interrupted_response_ids:
                    LOGGER.debug(
                        "Ignoring playback done from interrupted response: %s",
                        event.response_id,
                    )
                    return
                if (
                    event.response_id
                    and state.active_response_id is not None
                    and event.response_id != state.active_response_id
                ):
                    LOGGER.debug(
                        "Ignoring playback done from unexpected response: active=%s got=%s",
                        state.active_response_id,
                        event.response_id,
                    )
                    return
                LOGGER.info("Response playback done: %s", event.reason)
                state.response_complete = True
                state.response_done_at = time.monotonic()
                return

            if isinstance(event, ResponseInterrupted):
                if state is None or not state.reply_expected:
                    return
                if event.response_id and event.response_id in interrupted_response_ids:
                    return
                if (
                    event.response_id
                    and state.active_response_id is not None
                    and event.response_id != state.active_response_id
                ):
                    return
                LOGGER.info("Response interrupted: %s", event.reason)
                return

            if isinstance(event, ResponseTextDelta):
                if state is None or not state.reply_expected:
                    return
                if event.response_id and event.response_id in interrupted_response_ids:
                    return
                if (
                    event.response_id
                    and state.active_response_id is not None
                    and event.response_id != state.active_response_id
                ):
                    return
                LOGGER.info("Response text delta: %s", event.text)
                return

            if isinstance(event, ResponseTextDone):
                if state is None or not state.reply_expected:
                    return
                if event.response_id and event.response_id in interrupted_response_ids:
                    return
                if (
                    event.response_id
                    and state.active_response_id is not None
                    and event.response_id != state.active_response_id
                ):
                    return
                LOGGER.info("Response text final: %s", event.text)
                return

            if isinstance(event, SessionStarted):
                LOGGER.info("Realtime session established: %s", event.session_id)
                return

            if isinstance(event, ToolCallRequested):
                self._handle_tool_call(
                    client=client,
                    event=event,
                    on_client_missing=lambda: setattr(state, "should_stop", True)
                    if state is not None
                    else None,
                )
                return

            if isinstance(event, TranscriptFinal):
                transcript = event.text.strip()
                LOGGER.info("Final transcript: %s", transcript)
                if self._is_end_transcript(transcript) and state is not None:
                    state.session_end_requested = True
                return

            if isinstance(event, SessionError):
                LOGGER.error("Realtime session error: %s", event.message)
                if state is not None:
                    state.should_stop = True
                return

            if isinstance(event, SessionClosed):
                LOGGER.info("Realtime session closed: %s", event.reason)
                if state is not None:
                    state.should_stop = True

        try:
            while True:
                if self._settings.session_max_turns > 0 and turn_index >= self._settings.session_max_turns:
                    session_state = self._set_session_state(
                        session_state,
                        SessionWindowState.SESSION_END,
                        reason="max_turns_reached",
                    )
                    return
                session_state = self._set_session_state(session_state, SessionWindowState.READY)
                if turn_index == 0 and Path(self._settings.ready_cue_path).exists():
                    try:
                        player.play_wav_file(
                            self._settings.ready_cue_path,
                            blocking=True,
                            gain=self._settings.cue_output_gain,
                        )
                    except Exception:
                        LOGGER.exception("Failed to play ready cue")

                turn_index += 1
                turn_state = TurnRuntimeState(last_activity=time.monotonic())
                session_state = self._set_session_state(
                    session_state,
                    SessionWindowState.RECORDING_TURN,
                    reason=f"turn={turn_index}",
                )
                record_started_at = time.monotonic()
                utterance = self._capture_utterance(
                    microphone,
                    start_timeout=(
                        self._settings.recording_start_timeout
                        if turn_index == 1
                        else self._settings.session_followup_timeout
                    ),
                )
                if not utterance:
                    timeout_reason = (
                        "initial_turn_timeout" if turn_index == 1 else "followup_timeout"
                    )
                    LOGGER.info("No utterance captured: %s", timeout_reason)
                    if turn_index > 1:
                        play_session_end_cue = True
                    session_state = self._set_session_state(
                        session_state,
                        SessionWindowState.SESSION_TIMEOUT,
                        reason=timeout_reason,
                    )
                    return
                record_finished_at = time.monotonic()
                LOGGER.info(
                    "Recorded utterance: turn=%d frames=%d duration=%.2fs",
                    turn_index,
                    len(utterance),
                    record_finished_at - record_started_at,
                )

                if client is None:
                    connect_started_at = time.monotonic()
                    client = self._connect_client(event_handler=handle_event)
                    if client is None:
                        self._play_failure_cue(player)
                        session_state = self._set_session_state(
                            session_state,
                            SessionWindowState.SESSION_END,
                            reason="connect_failed",
                        )
                        return
                    LOGGER.info(
                        "Realtime session started with %d tools",
                        len(self._tool_registry.tools),
                    )
                    LOGGER.info(
                        "Realtime connect duration: %.2fs",
                        time.monotonic() - connect_started_at,
                    )

                try:
                    response_requested_at = self._submit_turn_audio(
                        client=client,
                        utterance=utterance,
                        resampler=resampler,
                    )
                    turn_state.reply_expected = True
                except Exception as exc:
                    LOGGER.warning("Realtime turn submission failed: %s", exc)
                    self._play_failure_cue(player)
                    session_state = self._set_session_state(
                        session_state,
                        SessionWindowState.SESSION_END,
                        reason="submit_failed",
                    )
                    return

                session_state = self._set_session_state(
                    session_state,
                    SessionWindowState.WAITING_FOR_REPLY,
                    reason=f"turn={turn_index}",
                )
                playback_result = self._play_response_until_done_or_interrupt(
                    client=client,
                    player=player,
                    response_state=lambda: (
                        False if turn_state is None else turn_state.response_started,
                        False if turn_state is None else turn_state.response_complete,
                        False if turn_state is None else turn_state.should_stop,
                        time.monotonic() if turn_state is None else turn_state.last_activity,
                    ),
                    on_interrupt=(
                        None
                        if turn_state is None
                        else lambda: self._mark_interrupted_response(
                            turn_state,
                            interrupted_response_ids,
                        )
                    ),
                )

                if turn_state.first_response_audio_at is not None:
                    LOGGER.info(
                        "First response audio latency: %.2fs",
                        turn_state.first_response_audio_at - response_requested_at,
                    )
                if (
                    turn_state.response_done_at is not None
                    and turn_state.first_response_audio_at is not None
                ):
                    LOGGER.info(
                        "Response playback duration: %.2fs",
                        turn_state.response_done_at - turn_state.first_response_audio_at,
                    )

                if playback_result == PlaybackResult.INTERRUPTED:
                    LOGGER.info("Continuing session window after wake-word interrupt")
                    continue
                if playback_result == PlaybackResult.SESSION_TIMEOUT:
                    play_session_end_cue = True
                    session_state = self._set_session_state(
                        session_state,
                        SessionWindowState.SESSION_TIMEOUT,
                        reason="waiting_for_reply_timeout",
                    )
                    return
                if playback_result == PlaybackResult.STOPPED or turn_state.should_stop:
                    session_state = self._set_session_state(
                        session_state,
                        SessionWindowState.SESSION_END,
                        reason="session_closed",
                    )
                    return
                if turn_state.session_end_requested:
                    play_session_end_cue = True
                    session_state = self._set_session_state(
                        session_state,
                        SessionWindowState.SESSION_END,
                        reason="end_phrase",
                    )
                    return
                if playback_result == PlaybackResult.COMPLETED:
                    self._play_post_reply_cue(player)
        finally:
            try:
                microphone.stop()
            except Exception:
                LOGGER.debug("Microphone stop failed", exc_info=True)
            self._wake_detector.stop()
            if play_session_end_cue:
                self._play_session_end_cue(player)
            if client is not None:
                client.close()
            player.close()
            if session_state != SessionWindowState.SESSION_END:
                self._set_session_state(session_state, SessionWindowState.SESSION_END)
            LOGGER.info("Realtime session finished in %.2fs", time.monotonic() - session_started_at)

    def _run_single_turn_session(self) -> bool:
        session_started_at = time.monotonic()
        player, microphone, resampler = self._build_session_io()
        self._status_led.user_can_speak()

        should_stop = False
        response_started = False
        response_complete = False
        last_activity = time.monotonic()
        first_response_audio_at: float | None = None
        response_done_at: float | None = None

        def _set_should_stop() -> None:
            nonlocal should_stop
            should_stop = True

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

            if isinstance(event, ToolCallRequested):
                self._handle_tool_call(
                    client=client,
                    event=event,
                    on_client_missing=lambda: _set_should_stop(),
                )
                return

            if isinstance(event, TranscriptFinal):
                transcript = event.text.strip()
                LOGGER.info("Final transcript: %s", transcript)
                if self._is_end_transcript(transcript):
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
                    player.play_wav_file(
                        self._settings.ready_cue_path,
                        blocking=True,
                        gain=self._settings.cue_output_gain,
                    )
                except Exception:
                    LOGGER.exception("Failed to play ready cue")

            record_started_at = time.monotonic()
            utterance = self._capture_utterance(
                microphone,
                start_timeout=self._settings.recording_start_timeout,
            )
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
            LOGGER.info("Realtime session started with %d tools", len(self._tool_registry.tools))
            LOGGER.info("Realtime connect duration: %.2fs", time.monotonic() - connect_started_at)

            self._status_led.processing()
            playback_result = self._play_response_until_done_or_interrupt(
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
            return playback_result == PlaybackResult.INTERRUPTED
        finally:
            self._status_led.off()
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
        client = self._connect_client(event_handler=event_handler)
        if client is None:
            return None
        try:
            response_requested_at = self._submit_turn_audio(
                client=client,
                utterance=utterance,
                resampler=resampler,
            )
            return client, response_requested_at
        except Exception as exc:
            LOGGER.warning("Realtime turn submission failed: %s", exc)
            client.close()
            return None

    def _connect_client(
        self,
        event_handler: Callable[[object], None],
    ) -> RealtimeVoiceAgent | None:
        max_attempts = max(1, self._settings.realtime_connect_retries + 1)

        for attempt in range(1, max_attempts + 1):
            client = RealtimeVoiceAgent(
                self._settings,
                event_handler,
                tools=self._tool_registry.tools,
            )
            try:
                client.connect()
                return client
            except Exception as exc:
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
                LOGGER.info("Retrying Realtime request in %.2fs", backoff_seconds)
                time.sleep(backoff_seconds)

        LOGGER.error("Realtime request failed after %d attempts", max_attempts)
        return None

    def _submit_turn_audio(
        self,
        *,
        client: RealtimeVoiceAgent,
        utterance: list[bytes],
        resampler: PCMResampler,
    ) -> float:
        try:
            for chunk in utterance:
                client.send_audio(resampler.convert(chunk))
            client.commit_input_audio()
            response_requested_at = time.monotonic()
            client.create_response()
            return response_requested_at
        except (Exception, RealtimeConnectionClosed):
            raise

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
            player.play_wav_file(
                cue_path,
                blocking=True,
                gain=self._settings.cue_output_gain,
            )
        except Exception:
            LOGGER.exception("Failed to play post-reply cue")

    def _play_failure_cue(self, player: RawAplayPlayer) -> None:
        cue_path = self._settings.failure_cue_path
        if not cue_path or not Path(cue_path).exists():
            return
        try:
            player.play_wav_file(
                cue_path,
                blocking=True,
                gain=self._settings.cue_output_gain,
            )
        except Exception:
            LOGGER.exception("Failed to play failure cue")

    def _play_session_end_cue(self, player: RawAplayPlayer) -> None:
        cue_path = self._settings.session_end_cue_path
        if not cue_path or not Path(cue_path).exists():
            return
        try:
            player.play_wav_file(
                cue_path,
                blocking=True,
                gain=self._settings.cue_output_gain,
            )
        except Exception:
            LOGGER.exception("Failed to play session end cue")

    def _record_utterance(
        self,
        microphone: MicrophoneStream,
        *,
        start_timeout: float,
    ) -> list[bytes]:
        LOGGER.info("Recording one utterance after trigger")
        frames: list[bytes] = []
        preroll_frames: deque[bytes] = deque(maxlen=self._settings.recording_preroll_frames)
        speech_started = False
        start_deadline = time.monotonic() + start_timeout
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

    def _capture_utterance(
        self,
        microphone: MicrophoneStream,
        *,
        start_timeout: float,
    ) -> list[bytes]:
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
            return self._record_utterance(microphone, start_timeout=start_timeout)
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
        on_interrupt: Callable[[], None] | None = None,
    ) -> PlaybackResult:
        LOGGER.info("Waiting for response playback; say the wake word again to interrupt")
        self._wake_detector.start()
        wake_poll_count = 0

        try:
            while True:
                response_started, response_complete, should_stop, last_activity = response_state()

                if should_stop:
                    return PlaybackResult.STOPPED

                if response_complete:
                    player.drain()
                    return PlaybackResult.COMPLETED

                wake_event = self._wake_detector.poll_for_wake(timeout=0.15)
                wake_poll_count += 1
                if wake_event is not None:
                    LOGGER.info("Wake word interrupt detected during response playback")
                    if on_interrupt is not None:
                        on_interrupt()
                    client.interrupt()
                    player.interrupt()
                    return PlaybackResult.INTERRUPTED
                if wake_poll_count % 20 == 0:
                    LOGGER.info(
                        "Wake-word interrupt still polling during playback: polls=%d",
                        wake_poll_count,
                    )

                if time.monotonic() - last_activity > self._settings.session_idle_timeout:
                    LOGGER.info("Session idle timeout reached while waiting for response")
                    return PlaybackResult.SESSION_TIMEOUT
        finally:
            self._wake_detector.stop()

    def _mark_interrupted_response(
        self,
        turn_state: TurnRuntimeState,
        interrupted_response_ids: set[str],
    ) -> None:
        if not turn_state.active_response_id:
            LOGGER.info("Interrupt requested before response ID was observed")
            return
        interrupted_response_ids.add(turn_state.active_response_id)
        turn_state.ignored_response_ids.add(turn_state.active_response_id)
        LOGGER.info(
            "Ignoring interrupted response for future events: %s",
            turn_state.active_response_id,
        )
