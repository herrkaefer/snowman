from __future__ import annotations

import logging
from typing import Any

from ._ha_helpers import fetch_states, lookup_area_name, normalize_state_payload
from ..tools import ToolContext, ToolDefinition, ToolSpec


LOGGER = logging.getLogger(__name__)
DEFAULT_ENTITY_LIMIT = 20
MAX_ENTITY_LIMIT = 100
AREA_ENRICHMENT_LIMIT = 60
AREA_ALIASES = {
    "客厅": ("living room",),
    "起居室": ("living room",),
    "卧室": ("bedroom",),
    "主卧": ("primary bedroom", "master bedroom"),
    "厨房": ("kitchen",),
    "餐厅": ("dining area",),
    "书房": ("office", "study"),
    "卫生间": ("bathroom",),
    "浴室": ("bathroom",),
    "洗手间": ("bathroom",),
    "门厅": ("foyer", "entryway"),
    "玄关": ("foyer", "entryway"),
    "车库": ("garage",),
    "地下室": ("basement",),
    "楼下": ("downstairs",),
    "楼上": ("upstairs",),
}
NAME_ALIASES = {
    "灯": ("light", "lights", "lamp"),
    "空调": ("climate", "thermostat", "air conditioner"),
}


def _execute(context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    domain_filter = str(arguments.get("domain_filter", "")).strip().lower()
    area = str(arguments.get("area", "")).strip()
    name = str(arguments.get("name", "")).strip()
    query = str(arguments.get("query", "")).strip()
    raw_limit = arguments.get("limit", DEFAULT_ENTITY_LIMIT)
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("home_assistant_entities limit must be an integer") from exc
    if limit < 1 or limit > MAX_ENTITY_LIMIT:
        raise RuntimeError(
            f"home_assistant_entities limit must be between 1 and {MAX_ENTITY_LIMIT}"
        )

    LOGGER.info(
        "home_assistant_entities input: domain_filter=%r area=%r name=%r query=%r limit=%d",
        domain_filter,
        area,
        name,
        query,
        limit,
    )
    entities = search_home_assistant_entities(
        context.settings,
        domain_filter=domain_filter,
        area=area,
        name=name,
        query=query,
        limit=limit,
    )
    LOGGER.info(
        "home_assistant_entities output: count=%d entity_ids=%s",
        len(entities),
        [entity["entity_id"] for entity in entities],
    )
    return {
        "count": len(entities),
        "applied_filters": {
            "domain_filter": domain_filter,
            "area": area,
            "name": name,
            "query": query,
            "limit": limit,
        },
        "entities": entities,
    }


def search_home_assistant_entities(
    settings: Any,
    *,
    domain_filter: str = "",
    area: str = "",
    name: str = "",
    query: str = "",
    limit: int = DEFAULT_ENTITY_LIMIT,
) -> list[dict[str, Any]]:
    states = fetch_states(settings)
    candidates = _normalize_entities(states, domain_filter=domain_filter)
    area_terms = _expanded_terms(area, AREA_ALIASES)
    name_terms = _expanded_terms(name, NAME_ALIASES)
    query_terms = _expanded_terms(query, {**AREA_ALIASES, **NAME_ALIASES})

    if area_terms or (not area_terms and not name_terms and _looks_like_area_query(query_terms)):
        candidates = _enrich_area_names_if_needed(settings, candidates)

    if area_terms:
        area_matches = [
            entity for entity in candidates if _matches_any_term(entity, area_terms, include_area=True)
        ]
        if area_matches:
            candidates = area_matches

    if name_terms:
        name_matches = [
            entity for entity in candidates if _matches_any_term(entity, name_terms, include_area=False)
        ]
        if name_matches:
            candidates = name_matches

    if not area_terms and not name_terms and not query_terms:
        return candidates[:limit]

    scored_matches = []
    for entity in candidates:
        score = _entity_match_score(
            entity,
            area_terms=area_terms,
            name_terms=name_terms,
            query_terms=query_terms,
        )
        if score <= 0:
            continue
        scored_matches.append((score, entity))
    scored_matches.sort(
        key=lambda item: (
            item[0],
            item[1].get("friendly_name", ""),
            item[1].get("entity_id", ""),
        ),
        reverse=True,
    )
    return [entity for _, entity in scored_matches[:limit]]


def _normalize_entities(
    states: list[dict[str, Any]],
    *,
    domain_filter: str,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for payload in states:
        entity_id = str(payload.get("entity_id", "")).strip()
        if not entity_id:
            continue
        if domain_filter and not entity_id.startswith(domain_filter + "."):
            continue
        normalized.append(normalize_state_payload(payload))
    normalized.sort(key=lambda entity: (entity["friendly_name"], entity["entity_id"]))
    return normalized


def _enrich_area_names_if_needed(settings: Any, entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    area_lookups = 0
    for entity in entities:
        current = dict(entity)
        if not current.get("area_name") and area_lookups < AREA_ENRICHMENT_LIMIT:
            area_name = lookup_area_name(settings, current["entity_id"])
            if area_name:
                current["area_name"] = area_name
            area_lookups += 1
        enriched.append(current)
    return enriched


def _entity_match_score(
    entity: dict[str, Any],
    *,
    area_terms: tuple[str, ...],
    name_terms: tuple[str, ...],
    query_terms: tuple[str, ...],
) -> int:
    friendly_name = str(entity.get("friendly_name", "")).casefold()
    entity_id = str(entity.get("entity_id", "")).casefold()
    area_name = str(entity.get("area_name", "")).casefold()
    haystack = " ".join(part for part in (friendly_name, entity_id, area_name) if part).strip()
    if not haystack:
        return 0

    score = 0
    if area_terms:
        for term in area_terms:
            if term in area_name:
                score += 24
            elif term in friendly_name:
                score += 18
            elif term in entity_id:
                score += 16
    if name_terms:
        for term in name_terms:
            if term in friendly_name:
                score += 12
            elif term in entity_id:
                score += 10
            elif term in area_name:
                score += 4
    if not area_terms and not name_terms:
        for term in query_terms:
            if term in friendly_name:
                score += 8
            elif term in area_name:
                score += 7
            elif term in entity_id:
                score += 6
    if score == 0 and query_terms and all(term in haystack for term in query_terms):
        score = 1
    if score == 0 and (area_terms or name_terms):
        fallback_terms = area_terms + name_terms + query_terms
        if fallback_terms and all(term in haystack for term in fallback_terms if len(term) > 1):
            score = 1
    return score


def _matches_any_term(
    entity: dict[str, Any],
    terms: tuple[str, ...],
    *,
    include_area: bool,
) -> bool:
    friendly_name = str(entity.get("friendly_name", "")).casefold()
    entity_id = str(entity.get("entity_id", "")).casefold()
    area_name = str(entity.get("area_name", "")).casefold()
    haystacks = [friendly_name, entity_id]
    if include_area:
        haystacks.insert(0, area_name)
    return any(term in haystack for term in terms for haystack in haystacks if haystack)


def _expanded_terms(value: str, aliases: dict[str, tuple[str, ...]]) -> tuple[str, ...]:
    normalized = value.strip()
    if not normalized:
        return ()
    lower_value = normalized.casefold()
    expanded_terms = [lower_value]
    for needle, replacements in aliases.items():
        if needle.casefold() not in lower_value:
            continue
        expanded_terms.extend(replacement.casefold() for replacement in replacements)
    seen: set[str] = set()
    deduped: list[str] = []
    for term in expanded_terms:
        clean = term.strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        deduped.append(clean)
    return tuple(deduped)


def _looks_like_area_query(query_terms: tuple[str, ...]) -> bool:
    return any(term in AREA_ALIASES or term in ("living room", "foyer", "entryway", "kitchen", "bedroom") for term in query_terms)


TOOL = ToolSpec(
    definition=ToolDefinition(
        name="home_assistant_entities",
        description=(
            "Find likely Home Assistant entities when the user names a room or device naturally, such as living room lights, thermostat, scene, or media player. "
            "Prefer structured filters: use domain_filter for the HA domain, area for the room or area, and name for the device name. "
            "Use query only as a fallback when you cannot cleanly separate the room and device name. "
            "Do not pass the whole user utterance as query when you can extract structured fields. "
            "Use this first when the exact entity_id is unknown, then use home_assistant to act on the chosen entity or entities."
        ),
        parameters={
            "type": "object",
            "properties": {
                "domain_filter": {
                    "type": "string",
                    "description": "Optional Home Assistant domain such as light, switch, scene, climate, or media_player.",
                },
                "area": {
                    "type": "string",
                    "description": "Optional room or area name, such as living room, foyer, kitchen, upstairs, or basement.",
                },
                "name": {
                    "type": "string",
                    "description": "Optional device or target name, such as reading lamp, ceiling light, thermostat, or TV.",
                },
                "query": {
                    "type": "string",
                    "description": "Optional fallback text query if area and name cannot be separated cleanly.",
                },
                "limit": {
                    "type": "integer",
                    "description": f"Maximum number of entities to return. Default {DEFAULT_ENTITY_LIMIT}, max {MAX_ENTITY_LIMIT}.",
                },
            },
            "additionalProperties": False,
        },
    ),
    execute=_execute,
)
