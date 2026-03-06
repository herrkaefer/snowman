from __future__ import annotations

import base64
import json
import logging
import threading
import time
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
        self._connection_closed_event = threading.Event()
        self._response_text_parts: dict[str, list[str]] = {}

    def connect(self) -> None:
        LOGGER.info("Connecting to Realtime: %s", self._settings.realtime_ws_url)
        self._stop_event.clear()
        self._connection_closed_event.clear()
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

        input_audio: dict[str, object] = {
            "format": {
                "type": "audio/pcm",
                "rate": self._settings.realtime_sample_rate,
            },
            "turn_detection": turn_detection,
        }
        if self._settings.input_transcription_model:
            input_audio["transcription"] = {
                "model": self._settings.input_transcription_model,
            }

        headers = [
            f"Authorization: Bearer {self._settings.openai_api_key}",
        ]
        self._socket = websocket.create_connection(
            self._settings.realtime_ws_url,
            header=headers,
            timeout=self._settings.realtime_connect_timeout_seconds,
            enable_multithread=True,
        )
        self._recv_until_session_created()
        self._send(
            {
                "type": "session.update",
                "session": {
                    "type": "realtime",
                    "model": self._settings.openai_realtime_model,
                    "output_modalities": ["audio"],
                    "instructions": self._settings.system_prompt,
                    "audio": {
                        "input": input_audio,
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
        self._observe_post_update_state(
            timeout_seconds=self._settings.realtime_post_update_grace_seconds
        )
        assert self._socket is not None
        self._socket.settimeout(None)
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
            self._send({"type": "response.cancel"})
        except Exception:
            LOGGER.debug("Failed to send response.cancel", exc_info=True)

    def clear_input_audio(self) -> None:
        self._send({"type": "input_audio_buffer.clear"})

    def commit_input_audio(self) -> None:
        LOGGER.info("Committing input audio buffer")
        self._send({"type": "input_audio_buffer.commit"})

    def create_response(self) -> None:
        LOGGER.info("Creating Realtime response")
        self._send(
            {
                "type": "response.create",
                "response": {
                    "instructions": (
                        "Do not greet, welcome, or introduce yourself. "
                        "Answer only the user's most recent utterance. "
                        "Your name is Snowman. If asked your name, identity, or who you are, answer Snowman directly. "
                        "Never say that you do not have a name. "
                        "You cannot see the user's surroundings, objects, screen, posture, or camera feed. "
                        "Do not claim to see, inspect, identify, or describe any visual detail unless the user explicitly states those details in words. "
                        "Do not say things like 'I can see', 'it looks like', or similar. "
                        "If the audio is unclear, incomplete, nonspeech, or you are not confident what the user said, briefly say that you did not catch it and ask them to repeat. "
                        "Do not guess or invent meaning from unclear audio. "
                        "Reply in one short sentence by default, and use two short sentences only when needed for clarity. "
                        "Keep the answer brief and complete. "
                        "Prefer a direct answer over explanation. "
                        "If the user is clearly ending the conversation, reply with one very short goodbye only. "
                        "Do not start with filler like 'okay', 'sure', or '当然'. "
                        "Do not list multiple examples, options, or extra background unless the user asks for them. "
                        "For translation requests, give just the translation unless the user asks for explanation. "
                        "Reply in the same language as the clearly understood user utterance; if the utterance is unclear, use English."
                    ),
                    "max_output_tokens": self._settings.response_max_output_tokens,
                },
            }
        )

    def close(self) -> None:
        self._stop_event.set()
        self._connection_closed_event.set()
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
            except websocket.WebSocketTimeoutException:
                continue
            except websocket.WebSocketConnectionClosedException:
                self._connection_closed_event.set()
                self._event_handler(SessionClosed(reason="socket_closed"))
                return
            except Exception as exc:
                self._connection_closed_event.set()
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
        response_id = self._extract_response_id(message)

        if message_type == "session.created":
            session = message.get("session") or {}
            session_id = None
            if isinstance(session, dict):
                raw_session_id = session.get("id")
                session_id = str(raw_session_id) if raw_session_id else None
            self._event_handler(SessionStarted(session_id=session_id))
            return

        if message_type == "session.updated":
            return

        if message_type in {"response.audio.delta", "response.output_audio.delta"}:
            delta = str(message.get("delta", ""))
            if delta:
                self._event_handler(
                    ResponseAudioChunk(
                        audio_bytes=base64.b64decode(delta),
                        response_id=response_id,
                    )
                )
            return

        if message_type == "response.cancelled":
            self._drop_response_text(response_id)
            self._event_handler(
                ResponseInterrupted(reason=message_type, response_id=response_id)
            )
            return

        if message_type in {"response.audio.done", "response.output_audio.done"}:
            self._event_handler(
                ResponsePlaybackDone(reason=message_type, response_id=response_id)
            )
            return

        if message_type in {
            "response.text.delta",
            "response.output_text.delta",
            "response.audio_transcript.delta",
            "response.output_audio_transcript.delta",
        }:
            delta = str(message.get("delta", ""))
            if delta:
                response_key = self._response_key(response_id)
                self._response_text_parts.setdefault(response_key, []).append(delta)
                self._event_handler(ResponseTextDelta(text=delta, response_id=response_id))
            return

        if message_type in {
            "response.done",
            "response.audio_transcript.done",
            "response.output_audio_transcript.done",
        }:
            text = self._consume_response_text(response_id)
            if text:
                self._event_handler(ResponseTextDone(text=text, response_id=response_id))
            return

        if message_type in {
            "conversation.item.input_audio_transcription.delta",
            "conversation.item.input_audio_transcription.completed",
            "input_audio_buffer.transcription.completed",
        }:
            if message_type.endswith(".delta"):
                return
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

    def _extract_response_id(self, message: dict[str, object]) -> str | None:
        raw_response_id = message.get("response_id")
        if raw_response_id:
            return str(raw_response_id)

        response = message.get("response")
        if isinstance(response, dict):
            nested_response_id = response.get("id")
            if nested_response_id:
                return str(nested_response_id)

        return None

    def _response_key(self, response_id: str | None) -> str:
        return response_id or "__default__"

    def _consume_response_text(self, response_id: str | None) -> str:
        response_key = self._response_key(response_id)
        parts = self._response_text_parts.pop(response_key, None)
        if parts:
            return "".join(parts)

        if response_id is None and len(self._response_text_parts) == 1:
            _, only_parts = self._response_text_parts.popitem()
            return "".join(only_parts)

        return ""

    def _drop_response_text(self, response_id: str | None) -> None:
        response_key = self._response_key(response_id)
        self._response_text_parts.pop(response_key, None)

    def _recv_until_session_created(self) -> None:
        message = self._recv_bootstrap_message(
            deadline=time.monotonic() + self._settings.realtime_session_created_timeout_seconds
        )
        message_type = str(message.get("type", ""))
        if message_type == "session.created":
            self._handle_message(message)
            return
        raise RuntimeError(f"Expected session.created, got {message_type or 'empty message'}")

    def _observe_post_update_state(self, timeout_seconds: float) -> None:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            try:
                message = self._recv_bootstrap_message(deadline=deadline)
            except TimeoutError:
                return

            message_type = str(message.get("type", ""))
            if message_type == "session.updated":
                return
            if message_type == "error":
                error = message.get("error") or {}
                if isinstance(error, dict):
                    error_message = str(error.get("message", "unknown realtime error"))
                else:
                    error_message = str(error)
                raise RuntimeError(error_message)
            if message_type == "session.created":
                continue
            LOGGER.debug("Ignoring bootstrap Realtime message during post-update: %s", message_type)
        LOGGER.debug("No session.updated received after session.update; continuing")

    def _recv_bootstrap_message(self, deadline: float) -> dict[str, object]:
        assert self._socket is not None
        while time.monotonic() < deadline:
            remaining = max(0.05, deadline - time.monotonic())
            self._socket.settimeout(min(0.25, remaining))
            try:
                raw_message = self._socket.recv()
            except websocket.WebSocketTimeoutException as exc:
                if time.monotonic() >= deadline:
                    raise TimeoutError("Timed out waiting for bootstrap message") from exc
                continue
            except websocket.WebSocketConnectionClosedException as exc:
                self._connection_closed_event.set()
                raise RealtimeConnectionClosed("Realtime socket closed during bootstrap") from exc
            except Exception as exc:
                self._connection_closed_event.set()
                raise RuntimeError(str(exc)) from exc

            if not raw_message:
                continue

            try:
                return json.loads(raw_message)
            except json.JSONDecodeError:
                LOGGER.debug("Skipping non-JSON bootstrap Realtime message: %r", raw_message)
                continue

        raise TimeoutError("Timed out waiting for bootstrap message")
