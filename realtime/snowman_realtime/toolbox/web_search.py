from __future__ import annotations

import json
import logging
from typing import Any
from urllib import error, request

from ..config import build_web_search_user_location
from ..tools import ToolContext, ToolDefinition, ToolSpec


LOGGER = logging.getLogger(__name__)


def _execute(context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    query = str(arguments.get("query", "")).strip()
    if not query:
        raise RuntimeError("web_search requires a non-empty query")

    settings = context.settings
    LOGGER.info("Running OpenAI web_search tool for query: %s", query)
    user_location = build_web_search_user_location(
        city=settings.location_city,
        region=settings.location_region,
        country_code=settings.location_country_code,
        timezone=settings.location_timezone,
    )
    tool_config: dict[str, Any] = {"type": "web_search"}
    if user_location is not None:
        tool_config["user_location"] = user_location

    body = {
        "model": settings.web_search_model,
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
            "Authorization": f"Bearer {settings.openai_api_key}",
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

    summary = _extract_response_text(raw)
    sources = _extract_sources(raw)
    return {
        "query": query,
        "summary": summary,
        "sources": sources[:3],
    }


def _extract_response_text(payload: dict[str, Any]) -> str:
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


def _extract_sources(payload: dict[str, Any]) -> list[dict[str, str]]:
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


TOOL = ToolSpec(
    definition=ToolDefinition(
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
    execute=_execute,
)
