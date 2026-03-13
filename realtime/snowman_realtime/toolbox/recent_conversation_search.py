from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from ..tools import ToolAvailability, ToolContext, ToolDefinition, ToolSpec


LOGGER = logging.getLogger(__name__)
DEFAULT_RECENT_SESSION_RETRIEVAL_LIMIT = 5
MAX_RECENT_SESSION_RETRIEVAL_LIMIT = 20


def _is_enabled(availability: ToolAvailability) -> bool:
    return availability.memory_enabled


def _execute(context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    if context.memory_store is None:
        raise RuntimeError("recent conversation memory is not enabled")

    query = str(arguments.get("query", "")).strip()
    start_time = str(arguments.get("start_time", "")).strip()
    end_time = str(arguments.get("end_time", "")).strip()
    raw_limit = arguments.get("limit", DEFAULT_RECENT_SESSION_RETRIEVAL_LIMIT)
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("recent_conversation_search limit must be an integer") from exc

    LOGGER.info(
        "recent_conversation_search input: query=%r start_time=%r end_time=%r limit=%s",
        query,
        start_time,
        end_time,
        limit,
    )
    sessions = search_recent_sessions(
        context.memory_store.read_recent_sessions(),
        query=query,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
    )
    LOGGER.info(
        "recent_conversation_search output: count=%d session_ids=%s ended_at=%s summary_preview=%s",
        len(sessions),
        [str(session.get("session_id", "")) for session in sessions],
        [str(session.get("ended_at", "") or session.get("started_at", "")) for session in sessions],
        [_summary_preview(session) for session in sessions],
    )
    return {
        "count": len(sessions),
        "applied_filters": {
            "query": query,
            "start_time": start_time,
            "end_time": end_time,
            "limit": limit,
        },
        "sessions": sessions,
    }


def search_recent_sessions(
    records: list[dict[str, object]],
    *,
    query: str = "",
    start_time: str = "",
    end_time: str = "",
    limit: int = DEFAULT_RECENT_SESSION_RETRIEVAL_LIMIT,
) -> list[dict[str, object]]:
    if limit < 1 or limit > MAX_RECENT_SESSION_RETRIEVAL_LIMIT:
        raise RuntimeError(
            f"recent conversation limit must be between 1 and {MAX_RECENT_SESSION_RETRIEVAL_LIMIT}"
        )

    start_dt = _parse_filter_timestamp(start_time, field_name="start_time") if start_time.strip() else None
    end_dt = _parse_filter_timestamp(end_time, field_name="end_time") if end_time.strip() else None
    if start_dt is not None and end_dt is not None and start_dt > end_dt:
        raise RuntimeError("recent conversation start_time must be earlier than or equal to end_time")

    normalized_query = query.strip().casefold()
    query_tokens = [token for token in re.split(r"\s+", normalized_query) if token]

    matches: list[dict[str, object]] = []
    for record in sort_recent_sessions(records):
        session_dt = _recent_session_datetime(record)
        if start_dt is not None:
            if session_dt is None or session_dt < start_dt:
                continue
        if end_dt is not None:
            if session_dt is None or session_dt > end_dt:
                continue
        if query_tokens and not _recent_session_matches_query(record, normalized_query, query_tokens):
            continue
        matches.append(record)
        if len(matches) >= limit:
            break
    return matches


def sort_recent_sessions(records: list[dict[str, object]]) -> list[dict[str, object]]:
    return sorted(records, key=_recent_session_sort_key, reverse=True)


def _recent_session_matches_query(
    record: dict[str, object],
    normalized_query: str,
    query_tokens: list[str],
) -> bool:
    haystack_parts = [
        str(record.get("summary", "")),
        str(record.get("language", "")),
        str(record.get("source", "")),
        " ".join(_string_list(record.get("entities"))),
        " ".join(_string_list(record.get("topics"))),
    ]
    haystack = " ".join(part for part in haystack_parts if part).casefold()
    if not haystack:
        return False
    if normalized_query and normalized_query in haystack:
        return True
    return all(token in haystack for token in query_tokens)


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _recent_session_sort_key(record: dict[str, object]) -> tuple[datetime, str]:
    session_dt = _recent_session_datetime(record)
    if session_dt is None:
        session_dt = datetime.min.replace(tzinfo=timezone.utc)
    session_id = str(record.get("session_id", ""))
    return session_dt, session_id


def _recent_session_datetime(record: dict[str, object]) -> datetime | None:
    for field_name in ("ended_at", "started_at"):
        raw_value = str(record.get(field_name, "")).strip()
        if not raw_value:
            continue
        try:
            return _parse_iso_timestamp(raw_value)
        except RuntimeError:
            continue
    return None


def _parse_filter_timestamp(value: str, *, field_name: str) -> datetime:
    try:
        return _parse_iso_timestamp(value)
    except RuntimeError as exc:
        raise RuntimeError(f"recent conversation {field_name} must be an ISO-8601 timestamp") from exc


def _parse_iso_timestamp(value: str) -> datetime:
    normalized = value.strip()
    if not normalized:
        raise RuntimeError("timestamp is required")
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise RuntimeError("invalid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise RuntimeError("timestamp timezone is required")
    return parsed.astimezone(timezone.utc)


def _summary_preview(record: dict[str, object], *, max_chars: int = 80) -> str:
    summary = str(record.get("summary", "")).strip()
    if len(summary) <= max_chars:
        return summary
    return summary[: max_chars - 3] + "..."


TOOL = ToolSpec(
    definition=ToolDefinition(
        name="recent_conversation_search",
        description=(
            "Load recent cross-session conversation summaries when the user asks what was discussed earlier, recently, before, yesterday, or about a topic from prior recent conversations. "
            "Use this for recent recall across sessions, not for stable household facts or current external information. "
            "You may pass an ISO-8601 start_time and end_time to narrow the time window, and an optional query to filter by topic, entity, or summary text."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Optional topic or entity filter matched against stored summaries, entities, and topics.",
                },
                "start_time": {
                    "type": "string",
                    "description": "Optional inclusive ISO-8601 timestamp lower bound for recent session retrieval.",
                },
                "end_time": {
                    "type": "string",
                    "description": "Optional inclusive ISO-8601 timestamp upper bound for recent session retrieval.",
                },
                "limit": {
                    "type": "integer",
                    "description": (
                        "How many sessions to return. "
                        f"Default is {DEFAULT_RECENT_SESSION_RETRIEVAL_LIMIT}. "
                        f"Allowed range: 1 to {MAX_RECENT_SESSION_RETRIEVAL_LIMIT}."
                    ),
                },
            },
            "additionalProperties": False,
        },
    ),
    execute=_execute,
    is_enabled=_is_enabled,
)
