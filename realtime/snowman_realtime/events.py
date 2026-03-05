from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WakeDetected:
    keyword: str


@dataclass(frozen=True)
class SessionStarted:
    session_id: str | None


@dataclass(frozen=True)
class TranscriptPartial:
    text: str


@dataclass(frozen=True)
class TranscriptFinal:
    text: str


@dataclass(frozen=True)
class ResponseAudioChunk:
    audio_bytes: bytes


@dataclass(frozen=True)
class ResponseTextDelta:
    text: str


@dataclass(frozen=True)
class ResponseTextDone:
    text: str


@dataclass(frozen=True)
class ResponseInterrupted:
    reason: str


@dataclass(frozen=True)
class ResponsePlaybackDone:
    reason: str


@dataclass(frozen=True)
class SessionError:
    message: str


@dataclass(frozen=True)
class SessionClosed:
    reason: str
