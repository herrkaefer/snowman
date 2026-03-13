from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib import error, request

from .config import Settings


COMPACT_MODEL = "gpt-4o-mini"
COMPACT_TIMEOUT_SECONDS = 15


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class SessionTurnBufferSnapshot:
    session_id: str
    started_at: str
    turns: tuple[dict[str, str], ...]
    tool_names: tuple[str, ...]

    def has_user_content(self) -> bool:
        return any(
            turn.get("role") == "user" and turn.get("text", "").strip()
            for turn in self.turns
        )


@dataclass
class SessionTurnBuffer:
    source: str = "voice"
    _session_id: str | None = None
    _started_at: str | None = None
    _turns: list[dict[str, str]] = field(default_factory=list)
    _tool_names: list[str] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record_session_started(self, session_id: str | None) -> None:
        with self._lock:
            if self._started_at is None:
                self._started_at = _utc_now_iso()
            if session_id:
                self._session_id = session_id

    def append_user_text(self, text: str) -> None:
        normalized = text.strip()
        if not normalized:
            return
        with self._lock:
            self._turns.append({"role": "user", "text": normalized})

    def append_assistant_text(self, text: str) -> None:
        normalized = text.strip()
        if not normalized:
            return
        with self._lock:
            self._turns.append({"role": "assistant", "text": normalized})

    def record_tool_name(self, tool_name: str) -> None:
        normalized = tool_name.strip()
        if not normalized:
            return
        with self._lock:
            self._tool_names.append(normalized)

    def snapshot(self) -> SessionTurnBufferSnapshot:
        with self._lock:
            session_id = self._session_id or f"sess_{uuid.uuid4().hex}"
            started_at = self._started_at or _utc_now_iso()
            return SessionTurnBufferSnapshot(
                session_id=session_id,
                started_at=started_at,
                turns=tuple(dict(turn) for turn in self._turns),
                tool_names=tuple(self._tool_names),
            )


def compact_recent_conversation(
    settings: Settings,
    snapshot: SessionTurnBufferSnapshot,
) -> dict[str, object]:
    prompt = (
        "You are compacting one completed home voice assistant session into JSON. "
        "Return only a JSON object with these keys: summary, language, entities, topics. "
        "summary must be a short factual summary of what was discussed. "
        "Do not invent facts. Do not convert conversation content into profile-memory updates. "
        "Do not extract schedules or reminders beyond what was directly discussed. "
        "language must be the main language used by the user if clear, otherwise an empty string. "
        "entities must be an array of short entity names mentioned in the session. "
        "topics must be an array of short topic labels."
    )
    session_payload = {
        "session_id": snapshot.session_id,
        "started_at": snapshot.started_at,
        "source": "voice",
        "tool_names": list(snapshot.tool_names),
        "turns": list(snapshot.turns),
    }
    body = {
        "model": COMPACT_MODEL,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": (
                    "Summarize this completed session into the required JSON object.\n\n"
                    f"{json.dumps(session_payload, ensure_ascii=False)}"
                ),
            },
        ],
    }
    req = request.Request(
        url="https://api.openai.com/v1/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=COMPACT_TIMEOUT_SECONDS) as response:
            raw = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Recent conversation compact HTTP {exc.code}: {detail}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Recent conversation compact failed: {exc.reason}") from exc

    choices = raw.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("Recent conversation compact returned no choices.")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise RuntimeError("Recent conversation compact returned no message.")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("Recent conversation compact returned empty content.")
    try:
        compact = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Recent conversation compact returned invalid JSON content.") from exc
    if not isinstance(compact, dict):
        raise RuntimeError("Recent conversation compact returned a non-object JSON value.")
    return {
        "summary": str(compact.get("summary", "")).strip(),
        "language": str(compact.get("language", "")).strip(),
        "entities": _normalize_string_list(compact.get("entities")),
        "topics": _normalize_string_list(compact.get("topics")),
    }


def build_recent_session_record(
    snapshot: SessionTurnBufferSnapshot,
    compact: dict[str, object],
    *,
    ended_at: str | None = None,
) -> dict[str, object]:
    summary = str(compact.get("summary", "")).strip()
    if not summary:
        raise RuntimeError("Recent conversation compact summary cannot be empty.")
    return {
        "session_id": snapshot.session_id,
        "started_at": snapshot.started_at,
        "ended_at": ended_at or _utc_now_iso(),
        "source": "voice",
        "summary": summary,
        "language": str(compact.get("language", "")).strip(),
        "entities": _normalize_string_list(compact.get("entities")),
        "topics": _normalize_string_list(compact.get("topics")),
    }


def _normalize_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        text = item.strip()
        if text and text not in normalized:
            normalized.append(text)
    return normalized
