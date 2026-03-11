from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib import error, request

from .config import Settings, build_web_search_user_location
from .memory import MemoryStore, MemoryValidationError


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)


def build_tool_definitions(*, memory_enabled: bool) -> list[ToolDefinition]:
    definitions = [
        ToolDefinition(
            name="local_time",
            description=(
                "Get the exact current local time on the Raspberry Pi. "
                "Use this only when the provided session timestamp may be stale or the user explicitly wants the precise current time."
            ),
            parameters={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        ),
        ToolDefinition(
            name="web_search",
            description=(
                "Search the web for current or changing information. "
                "Required for recent facts and time-sensitive questions such as current officeholders, news, weather, prices, laws, schedules, standings, or anything asked as current, latest, today, now, or recent."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The web search query to look up.",
                    }
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        ),
    ]
    if memory_enabled:
        definitions.extend(
            [
                ToolDefinition(
                    name="profile_memory_get",
                    description=(
                        "Load the full profile memory document containing stable facts about people, preferences, and household context."
                    ),
                    parameters={
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False,
                    },
                ),
                ToolDefinition(
                    name="profile_memory_update",
                    description=(
                        "Replace the full profile memory document with updated Markdown. "
                        "Use this after reading the current profile memory when you need to add, correct, or remove stable profile facts."
                    ),
                    parameters={
                        "type": "object",
                        "properties": {
                            "updated_markdown": {
                                "type": "string",
                                "description": "The complete updated profile memory Markdown document.",
                            }
                        },
                        "required": ["updated_markdown"],
                        "additionalProperties": False,
                    },
                ),
            ]
        )
    return definitions


class ToolRegistry:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        memory_enabled = bool(getattr(settings, "memory_enabled", False))
        self._definitions = build_tool_definitions(memory_enabled=memory_enabled)
        self._memory_store = (
            MemoryStore.from_path(str(getattr(settings, "memory_dir", "")))
            if memory_enabled
            else None
        )
        if self._memory_store is not None:
            self._memory_store.ensure_initialized()

    @property
    def tools(self) -> list[ToolDefinition]:
        return list(self._definitions)

    def realtime_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            }
            for tool in self._definitions
        ]

    def execute(self, name: str, arguments_json: str) -> str:
        try:
            arguments = json.loads(arguments_json) if arguments_json else {}
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Invalid tool arguments for {name}: {exc}") from exc

        if name == "local_time":
            return json.dumps(self._local_time(), ensure_ascii=False)
        if name == "web_search":
            query = str(arguments.get("query", "")).strip()
            if not query:
                raise RuntimeError("web_search requires a non-empty query")
            return json.dumps(self._web_search(query), ensure_ascii=False)
        if name == "profile_memory_get":
            return json.dumps(self._profile_memory_get(), ensure_ascii=False)
        if name == "profile_memory_update":
            updated_markdown = str(arguments.get("updated_markdown", ""))
            if not updated_markdown.strip():
                raise RuntimeError("profile_memory_update requires updated_markdown")
            return json.dumps(
                self._profile_memory_update(updated_markdown),
                ensure_ascii=False,
            )
        raise RuntimeError(f"Unknown tool: {name}")

    def _local_time(self) -> dict[str, Any]:
        now = datetime.now().astimezone()
        return {
            "local_time": now.strftime("%Y-%m-%d %H:%M:%S"),
            "timezone": now.tzname() or "local",
            "iso8601": now.isoformat(),
        }

    def _web_search(self, query: str) -> dict[str, Any]:
        LOGGER.info("Running OpenAI web_search tool for query: %s", query)
        user_location = build_web_search_user_location(
            city=self._settings.location_city,
            region=self._settings.location_region,
            country_code=self._settings.location_country_code,
            timezone=self._settings.location_timezone,
        )
        tool_config: dict[str, Any] = {"type": "web_search"}
        if user_location is not None:
            tool_config["user_location"] = user_location

        body = {
            "model": self._settings.web_search_model,
            "input": (
                "Search the web and answer briefly in the same language as the query. "
                "Focus on current factual information. Include at most three short sources.\n\n"
                f"Query: {query}"
            ),
            "tools": [tool_config],
        }
        req = request.Request(
            url="https://api.openai.com/v1/responses",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._settings.openai_api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=20) as response:
                raw = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"OpenAI web_search HTTP {exc.code}: {detail}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"OpenAI web_search failed: {exc.reason}") from exc

        summary = self._extract_response_text(raw)
        sources = self._extract_sources(raw)
        return {
            "query": query,
            "summary": summary,
            "sources": sources[:3],
        }

    def _profile_memory_get(self) -> dict[str, Any]:
        if self._memory_store is None:
            raise RuntimeError("profile memory is not enabled")
        return {
            "profile_markdown": self._memory_store.read_profile(),
        }

    def _profile_memory_update(self, updated_markdown: str) -> dict[str, Any]:
        if self._memory_store is None:
            raise RuntimeError("profile memory is not enabled")
        try:
            saved = self._memory_store.update_profile(updated_markdown)
        except MemoryValidationError as exc:
            raise RuntimeError(str(exc)) from exc
        return {
            "status": "updated",
            "profile_markdown": saved,
        }

    def _extract_response_text(self, payload: dict[str, Any]) -> str:
        output_text = payload.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text.strip()

        output = payload.get("output")
        if not isinstance(output, list):
            return ""

        text_parts: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            if item.get("type") != "message":
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for content_item in content:
                if not isinstance(content_item, dict):
                    continue
                if content_item.get("type") in {"output_text", "text"}:
                    text_value = content_item.get("text")
                    if isinstance(text_value, str):
                        text_parts.append(text_value)
        return "".join(text_parts).strip()

    def _extract_sources(self, payload: dict[str, Any]) -> list[dict[str, str]]:
        output = payload.get("output")
        if not isinstance(output, list):
            return []

        sources: list[dict[str, str]] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for content_item in content:
                if not isinstance(content_item, dict):
                    continue
                annotations = content_item.get("annotations")
                if not isinstance(annotations, list):
                    continue
                for annotation in annotations:
                    if not isinstance(annotation, dict):
                        continue
                    url = annotation.get("url")
                    if not isinstance(url, str) or not url:
                        continue
                    title = annotation.get("title")
                    source = {
                        "url": url,
                        "title": title if isinstance(title, str) and title else url,
                    }
                    if source not in sources:
                        sources.append(source)
        return sources
