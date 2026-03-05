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
    ResponseInterrupted,
    SessionClosed,
    SessionError,
    SessionStarted,
    TranscriptFinal,
    TranscriptPartial,
)


LOGGER = logging.getLogger(__name__)
EventHandler = Callable[[object], None]


class RealtimeVoiceAgent:
    def __init__(self, settings: Settings, event_handler: EventHandler) -> None:
        self._settings = settings
        self._event_handler = event_handler
        self._socket: websocket.WebSocket | None = None
        self._receiver_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def connect(self) -> None:
        headers = [
            f"Authorization: Bearer {self._settings.openai_api_key}",
            f"OpenAI-Beta: {self._settings.openai_beta_header}",
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
                            },
                            "turn_detection": {
                                "type": "server_vad",
                                "interrupt_response": self._settings.interruption_enabled,
                            },
                        },
                        "output": {
                            "format": {
                                "type": "audio/pcm",
                            },
                            "voice": self._settings.openai_voice,
                        },
                    },
                },
            }
        )
        self._receiver_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._receiver_thread.start()

    def send_audio(self, audio_bytes: bytes) -> None:
        self._send(
            {
                "type": "input_audio_buffer.append",
                "audio": base64.b64encode(audio_bytes).decode("ascii"),
            }
        )

    def interrupt(self) -> None:
        try:
            self._send({"type": "output_audio_buffer.clear"})
        except Exception:
            LOGGER.debug("Failed to send output_audio_buffer.clear", exc_info=True)

    def close(self) -> None:
        self._stop_event.set()
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
            raise RuntimeError("Realtime socket is not connected")
        self._socket.send(json.dumps(payload))

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
            return

        if message_type in {"response.text.delta", "response.output_text.delta"}:
            delta = str(message.get("delta", ""))
            if delta:
                self._event_handler(TranscriptPartial(text=delta))
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
