from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


DEFAULT_RECENT_SESSION_LIMIT = 50


class MemoryValidationError(RuntimeError):
    """Raised when profile memory content fails structural validation."""


@dataclass(frozen=True)
class MemoryPaths:
    base_dir: Path
    profile_path: Path
    index_path: Path
    baseline_path: Path
    recent_sessions_path: Path


def default_profile_markdown() -> str:
    return (
        "# Profile Memory\n\n"
        "## People\n"
        "- \n\n"
        "## Preferences\n"
        "- \n\n"
        "## Household\n"
        "- \n\n"
        "## Notes\n"
        "-\n"
    )


def render_memory_index_markdown() -> str:
    return (
        "# Memory Index\n\n"
        "## profile\n"
        "- description: Stable facts about people, preferences, and household context.\n"
        "- retrieval_tools: profile_memory_get\n"
        "- edit_tools: profile_memory_update\n"
        "- use_when: identity, family members, names of people in the household, preferences, persistent household facts\n"
        "- avoid_when: recent chat recall, reminders, dated events\n\n"
        "## recent_conversation\n"
        "- description: Automatically stored compact summaries of completed recent sessions for later conversational recall.\n"
        "- retrieval_tools: recent_conversation_search\n"
        "- edit_tools: system-managed only\n"
        "- use_when: what we discussed earlier, recent context recall across sessions\n"
        "- avoid_when: stable fact lookup, authoritative household facts\n\n"
        "## schedule\n"
        "- description: Reserved for future calendar or reminder workflows. Not implemented yet.\n"
        "- retrieval_tools: none\n"
        "- edit_tools: none\n"
        "- use_when: reserved\n"
        "- avoid_when: stable fact lookup\n\n"
        "## routing_rules\n"
        "- Use `profile_memory_get` when you need stable facts about the user, family, preferences, or household.\n"
        "- Use `recent_conversation_search` when the user asks what was discussed earlier, recently, before, yesterday, or about a topic previously discussed across recent sessions.\n"
        "- If the user asks who a named person is, what their relationship is, or mentions someone as being in the family or household, prefer `profile_memory_get` before asking a clarification question.\n"
        "- For household names such as family members, do not assume the user means a public figure when profile memory is a plausible source.\n"
        "- For short names, uncommon names, or names that may have been transcribed imperfectly from speech, ask one brief clarification question before using `web_search`.\n"
        "- Before any `profile_memory_update`, you must call `profile_memory_get` in the current session.\n"
        "- When updating profile memory, preserve unrelated existing facts and make only the minimal necessary edit.\n"
        "- `recent_conversation` is stored automatically after completed sessions and is intended for later recall tools, not direct prompt injection.\n"
        "- `schedule` is not available yet.\n"
        "- For current or changing facts, still use `web_search` instead of memory.\n"
    )


class MemoryStore:
    def __init__(self, base_dir: Path) -> None:
        self._paths = MemoryPaths(
            base_dir=base_dir,
            profile_path=base_dir / "profile.md",
            index_path=base_dir / "MEMORY.md",
            baseline_path=base_dir / "profile.baseline.md",
            recent_sessions_path=base_dir / "recent_sessions.jsonl",
        )

    @classmethod
    def from_path(cls, raw_path: str) -> "MemoryStore":
        return cls(Path(raw_path))

    @property
    def paths(self) -> MemoryPaths:
        return self._paths

    def ensure_initialized(self) -> None:
        self._paths.base_dir.mkdir(parents=True, exist_ok=True)
        if not self._paths.profile_path.exists():
            self._write_text(self._paths.profile_path, default_profile_markdown())
        self._write_text(self._paths.index_path, render_memory_index_markdown())

    def read_profile(self) -> str:
        self.ensure_initialized()
        return self._paths.profile_path.read_text(encoding="utf-8")

    def read_memory_index(self) -> str:
        self.ensure_initialized()
        return self._paths.index_path.read_text(encoding="utf-8")

    def update_profile(self, updated_markdown: str) -> str:
        self.ensure_initialized()
        current = self.read_profile()
        normalized = validate_profile_markdown(updated_markdown, previous_markdown=current)
        self._write_text(self._paths.profile_path, normalized)
        self._write_text(self._paths.index_path, render_memory_index_markdown())
        return normalized

    def baseline_exists(self) -> bool:
        self.ensure_initialized()
        return self._paths.baseline_path.exists()

    def read_baseline(self) -> str:
        self.ensure_initialized()
        if not self._paths.baseline_path.exists():
            raise RuntimeError("No profile baseline has been saved yet.")
        return self._paths.baseline_path.read_text(encoding="utf-8")

    def save_current_as_baseline(self) -> str:
        self.ensure_initialized()
        current = self.read_profile()
        self._write_text(self._paths.baseline_path, current)
        return current

    def restore_baseline(self) -> str:
        self.ensure_initialized()
        baseline = self.read_baseline()
        self._write_text(self._paths.profile_path, baseline)
        self._write_text(self._paths.index_path, render_memory_index_markdown())
        return baseline

    def read_recent_sessions(self) -> list[dict[str, object]]:
        self.ensure_initialized()
        path = self._paths.recent_sessions_path
        if not path.exists():
            return []

        records: list[dict[str, object]] = []
        with path.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict):
                    records.append(record)
        return records

    def append_recent_session(
        self,
        record: dict[str, object],
        *,
        limit: int = DEFAULT_RECENT_SESSION_LIMIT,
    ) -> None:
        self.ensure_initialized()
        records = self.read_recent_sessions()
        records.append(record)
        if limit > 0:
            records = records[-limit:]

        with self._paths.recent_sessions_path.open("w", encoding="utf-8") as handle:
            for item in records:
                line = json.dumps(item, ensure_ascii=False)
                if "\n" in line or "\r" in line:
                    raise RuntimeError("Recent session record must serialize to a single JSONL line.")
                handle.write(line + "\n")
            handle.flush()

    def delete_recent_session(self, session_id: str) -> bool:
        self.ensure_initialized()
        normalized_session_id = session_id.strip()
        if not normalized_session_id:
            raise RuntimeError("session_id is required")

        records = self.read_recent_sessions()
        filtered_records = [
            record
            for record in records
            if str(record.get("session_id", "")).strip() != normalized_session_id
        ]
        if len(filtered_records) == len(records):
            return False

        with self._paths.recent_sessions_path.open("w", encoding="utf-8") as handle:
            for item in filtered_records:
                line = json.dumps(item, ensure_ascii=False)
                if "\n" in line or "\r" in line:
                    raise RuntimeError("Recent session record must serialize to a single JSONL line.")
                handle.write(line + "\n")
            handle.flush()
        return True

    def _write_text(self, path: Path, content: str) -> None:
        normalized = content.replace("\r\n", "\n").strip() + "\n"
        path.write_text(normalized, encoding="utf-8")


def validate_profile_markdown(
    updated_markdown: str,
    *,
    previous_markdown: str = "",
) -> str:
    normalized = updated_markdown.replace("\r\n", "\n").strip()
    if not normalized:
        raise MemoryValidationError("Profile memory cannot be empty.")

    return normalized + "\n"
