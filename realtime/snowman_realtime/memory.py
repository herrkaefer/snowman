from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


REQUIRED_PROFILE_SECTIONS = (
    "People",
    "Preferences",
    "Household",
    "Notes",
)


class MemoryValidationError(RuntimeError):
    """Raised when profile memory content fails structural validation."""


@dataclass(frozen=True)
class MemoryPaths:
    base_dir: Path
    profile_path: Path
    index_path: Path


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
        "- use_when: identity, family members, preferences, persistent household facts\n"
        "- avoid_when: recent chat recall, reminders, dated events\n\n"
        "## recent_conversation\n"
        "- description: Reserved for recent session recall. Not implemented yet.\n"
        "- retrieval_tools: none\n"
        "- edit_tools: none\n"
        "- use_when: reserved\n"
        "- avoid_when: stable fact lookup\n\n"
        "## schedule\n"
        "- description: Reserved for future calendar or reminder workflows. Not implemented yet.\n"
        "- retrieval_tools: none\n"
        "- edit_tools: none\n"
        "- use_when: reserved\n"
        "- avoid_when: stable fact lookup\n\n"
        "## routing_rules\n"
        "- Use `profile_memory_get` when you need stable facts about the user, family, preferences, or household.\n"
        "- Use `profile_memory_update` to create or revise stable profile facts.\n"
        "- `recent_conversation` and `schedule` are not available yet.\n"
        "- For current or changing facts, still use `web_search` instead of memory.\n"
    )


class MemoryStore:
    def __init__(self, base_dir: Path) -> None:
        self._paths = MemoryPaths(
            base_dir=base_dir,
            profile_path=base_dir / "profile.md",
            index_path=base_dir / "MEMORY.md",
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

    lines = normalized.splitlines()
    if not lines or lines[0].strip() != "# Profile Memory":
        raise MemoryValidationError("Profile memory must start with '# Profile Memory'.")

    missing_sections: list[str] = []
    duplicated_sections: list[str] = []
    for section in REQUIRED_PROFILE_SECTIONS:
        matches = re.findall(rf"^## {re.escape(section)}\s*$", normalized, flags=re.MULTILINE)
        if not matches:
            missing_sections.append(section)
        elif len(matches) > 1:
            duplicated_sections.append(section)

    if missing_sections:
        raise MemoryValidationError(
            "Profile memory is missing required sections: " + ", ".join(missing_sections) + "."
        )
    if duplicated_sections:
        raise MemoryValidationError(
            "Profile memory has duplicate sections: " + ", ".join(duplicated_sections) + "."
        )

    previous_normalized = previous_markdown.replace("\r\n", "\n").strip()
    if previous_normalized:
        old_len = len(previous_normalized)
        new_len = len(normalized)
        if old_len >= 80 and new_len < max(40, int(old_len * 0.35)):
            raise MemoryValidationError(
                "Profile memory update is unexpectedly short; refusing to replace most of the document."
            )

    return normalized + "\n"
