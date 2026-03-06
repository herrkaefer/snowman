from __future__ import annotations

import base64
import json
import logging
import threading
from collections.abc import Callable

import websocket

from .config import Settings
from .events import (
    ResponseAudioChunk,
    ResponsePlaybackDone,
    ResponseTextDelta,
    ResponseTextDone,
    ResponseInterrupted,
    SessionClosed,
    SessionError,
    SessionStarted,
    TranscriptFinal,
    TranscriptPartial,
)


LOGGER = logging.getLogger(__name__)
EventHandler = Callable[[object], None]


class RealtimeConnectionClosed(RuntimeError):
    """Raised when the Realtime socket is no longer writable."""


class RealtimeVoiceAgent:
    def __init__(self, settings: Settings, event_handler: EventHandler) -> None:
        self._settings = settings
        self._event_handler = event_handler
        self._socket: websocket.WebSocket | None = None
        self._receiver_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._response_text_parts: list[str] = []

    def connect(self) -> None:
        LOGGER.info("Connecting to Realtime: %s", self._settings.realtime_ws_url)
        turn_detection: dict[str, object] | None
        if self._settings.turn_detection_type.lower() in {"", "none", "off", "manual"}:
            turn_detection = None
        else:
            turn_detection = {
                "type": self._settings.turn_detection_type,
                "eagerness": self._settings.turn_detection_eagerness,
                "create_response": self._settings.turn_detection_create_response,
                "interrupt_response": self._settings.turn_detection_interrupt_response,
            }

        headers = [
            f"Authorization: Bearer {self._settings.openai_api_key}",
        ]
        self._socket = websocket.create_connection(
            self._settings.realtime_ws_url,
            header=headers,
            timeout=15,
            enable_multithread=True,
        )
        self._send(
            {
                "type": "session.update",
                "session": {
                    "type": "realtime",
                    "instructions": self._settings.system_prompt,
                    "audio": {
                        "input": {
                            "format": {
                                "type": "audio/pcm",
                                "rate": self._settings.realtime_sample_rate,
                            },
                            "turn_detection": turn_detection,
                        },
                        "output": {
                            "format": {
                                "type": "audio/pcm",
                                "rate": self._settings.realtime_sample_rate,
                            },
                            "voice": self._settings.openai_voice,
                        },
                    },
                },
            }
        )
        self._receiver_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._receiver_thread.start()
        LOGGER.info("Realtime socket connected")

    def send_audio(self, audio_bytes: bytes) -> None:
        try:
            self._send(
                {
                    "type": "input_audio_buffer.append",
                    "audio": base64.b64encode(audio_bytes).decode("ascii"),
                }
            )
        except (OSError, websocket.WebSocketConnectionClosedException) as exc:
            raise RealtimeConnectionClosed("Realtime socket is closed") from exc

    def interrupt(self) -> None:
        try:
            self._send({"type": "output_audio_buffer.clear"})
        except Exception:
            LOGGER.debug("Failed to send output_audio_buffer.clear", exc_info=True)

    def clear_input_audio(self) -> None:
        self._send({"type": "input_audio_buffer.clear"})

    def commit_input_audio(self) -> None:
        LOGGER.info("Committing input audio buffer")
        self._send({"type": "input_audio_buffer.commit"})

    def create_response(self) -> None:
        self._response_text_parts = []
        LOGGER.info("Creating Realtime response")
        self._send(
            {
                "type": "response.create",
                "response": {
                    "instructions": (
                        "Do not greet, welcome, or introduce yourself. "
                        "Answer only the user's most recent utterance. "
                        "Reply in one short sentence by default, and use two short sentences only when needed for clarity. "
                        "Keep the answer brief and complete. "
                        "Prefer a direct answer over explanation. "
                        "Do not start with filler like 'okay', 'sure', or '当然'. "
                        "Do not list multiple examples, options, or extra background unless the user asks for them. "
                        "For translation requests, give just the translation unless the user asks for explanation."
                    ),
                    "max_output_tokens": self._settings.response_max_output_tokens,
                },
            }
        )

    def close(self) -> None:
        self._stop_event.set()
        LOGGER.info("Closing Realtime client")
        if self._socket is not None:
            try:
                self._socket.close()
            except Exception:
                LOGGER.debug("Socket close failed", exc_info=True)
            self._socket = None
        if self._receiver_thread is not None:
            self._receiver_thread.join(timeout=1.0)
            self._receiver_thread = None

    def _send(self, payload: dict[str, object]) -> None:
        if self._socket is None:
            raise RealtimeConnectionClosed("Realtime socket is not connected")
        try:
            self._socket.send(json.dumps(payload))
        except (OSError, websocket.WebSocketConnectionClosedException) as exc:
            raise RealtimeConnectionClosed("Realtime socket is closed") from exc

    def _recv_loop(self) -> None:
        assert self._socket is not None
        while not self._stop_event.is_set():
            try:
                raw_message = self._socket.recv()
            except websocket.WebSocketConnectionClosedException:
                self._event_handler(SessionClosed(reason="socket_closed"))
                return
            except Exception as exc:
                self._event_handler(SessionError(message=str(exc)))
                return

            if not raw_message:
                continue

            try:
                message = json.loads(raw_message)
            except json.JSONDecodeError:
                LOGGER.debug("Skipping non-JSON Realtime message: %r", raw_message)
                continue

            self._handle_message(message)

    def _handle_message(self, message: dict[str, object]) -> None:
        message_type = str(message.get("type", ""))

        if message_type in {"session.created", "session.updated"}:
            session = message.get("session") or {}
            session_id = None
            if isinstance(session, dict):
                raw_session_id = session.get("id")
                session_id = str(raw_session_id) if raw_session_id else None
            self._event_handler(SessionStarted(session_id=session_id))
            return

        if message_type in {"response.audio.delta", "response.output_audio.delta"}:
            delta = str(message.get("delta", ""))
            if delta:
                self._event_handler(
                    ResponseAudioChunk(audio_bytes=base64.b64decode(delta))
                )
            return

        if message_type == "response.cancelled":
            self._event_handler(ResponseInterrupted(reason=message_type))
            return

        if message_type in {"response.audio.done", "response.output_audio.done"}:
            self._event_handler(ResponsePlaybackDone(reason=message_type))
            return

        if message_type in {
            "response.text.delta",
            "response.output_text.delta",
            "response.audio_transcript.delta",
            "response.output_audio_transcript.delta",
        }:
            delta = str(message.get("delta", ""))
            if delta:
                self._response_text_parts.append(delta)
                self._event_handler(ResponseTextDelta(text=delta))
            return

        if message_type in {
            "response.done",
            "response.audio_transcript.done",
            "response.output_audio_transcript.done",
        }:
            if self._response_text_parts:
                self._event_handler(ResponseTextDone(text="".join(self._response_text_parts)))
            return

        if message_type in {
            "conversation.item.input_audio_transcription.completed",
            "input_audio_buffer.transcription.completed",
        }:
            transcript = str(message.get("transcript", ""))
            if transcript:
                self._event_handler(TranscriptFinal(text=transcript))
            return

        if message_type == "input_audio_buffer.speech_started":
            self._event_handler(ResponseInterrupted(reason="speech_started"))
            return

        if message_type == "error":
            error = message.get("error") or {}
            if isinstance(error, dict):
                error_message = str(error.get("message", "unknown realtime error"))
            else:
                error_message = str(error)
            self._event_handler(SessionError(message=error_message))
