from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib import error, request

from .config import Settings


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)


class ToolRegistry:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._definitions = [
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
        body = {
            "model": "gpt-4.1-mini",
            "input": (
                "Search the web and answer briefly in the same language as the query. "
                "Focus on current factual information. Include at most three short sources.\n\n"
                f"Query: {query}"
            ),
            "tools": [
                {
                    "type": "web_search",
                    "user_location": {
                        "type": "approximate",
                        "country": "US",
                        "timezone": "America/Chicago",
                    },
                }
            ],
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
