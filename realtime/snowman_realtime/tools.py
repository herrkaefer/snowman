from __future__ import annotations

import importlib
import json
import pkgutil
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Callable

from . import toolbox
from .memory import MemoryStore


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolSessionState:
    profile_loaded: bool = False


@dataclass(frozen=True)
class ToolAvailability:
    memory_enabled: bool = False


@dataclass
class ToolContext:
    settings: Any
    session_state: ToolSessionState
    memory_store: Any | None = None


def _always_enabled(_: ToolAvailability) -> bool:
    return True


@dataclass(frozen=True)
class ToolSpec:
    definition: ToolDefinition
    execute: Callable[[ToolContext, dict[str, Any]], dict[str, Any]]
    config_fields: tuple["ToolConfigField", ...] = ()
    is_enabled: Callable[[ToolAvailability], bool] = _always_enabled


@dataclass(frozen=True)
class ToolConfigField:
    key: str
    label: str
    field_type: str
    description: str
    default: Any
    options: tuple[dict[str, str], ...] = ()


@lru_cache(maxsize=1)
def discover_tool_specs() -> tuple[ToolSpec, ...]:
    discovered: dict[str, ToolSpec] = {}
    for module_info in pkgutil.iter_modules(toolbox.__path__):
        if module_info.ispkg or module_info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{toolbox.__name__}.{module_info.name}")
        spec = getattr(module, "TOOL", None)
        if not isinstance(spec, ToolSpec):
            raise RuntimeError(f"Tool module {module.__name__} must define TOOL as ToolSpec")
        tool_name = spec.definition.name
        if tool_name in discovered:
            raise RuntimeError(f"Duplicate tool name discovered: {tool_name}")
        discovered[tool_name] = spec
    return tuple(discovered[name] for name in sorted(discovered))


def build_tool_definitions(*, memory_enabled: bool) -> list[ToolDefinition]:
    availability = ToolAvailability(memory_enabled=memory_enabled)
    return [
        spec.definition
        for spec in discover_tool_specs()
        if spec.is_enabled(availability)
    ]


def build_tool_ui_payload(
    *,
    memory_enabled: bool,
    tool_config: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    availability = ToolAvailability(memory_enabled=memory_enabled)
    current_tool_config = tool_config if isinstance(tool_config, dict) else {}
    items: list[dict[str, Any]] = []
    for spec in discover_tool_specs():
        if not spec.is_enabled(availability):
            continue
        spec_values = current_tool_config.get(spec.definition.name, {})
        if not isinstance(spec_values, dict):
            spec_values = {}
        fields = []
        values: dict[str, Any] = {}
        for field in spec.config_fields:
            fields.append(
                {
                    "key": field.key,
                    "label": field.label,
                    "type": field.field_type,
                    "description": field.description,
                    "default": field.default,
                    "options": [dict(option) for option in field.options],
                }
            )
            values[field.key] = spec_values.get(field.key, field.default)
        items.append(
            {
                "name": spec.definition.name,
                "description": spec.definition.description,
                "config_fields": fields,
                "config_values": values,
            }
        )
    return items


def build_default_tool_config() -> dict[str, dict[str, Any]]:
    defaults: dict[str, dict[str, Any]] = {}
    for spec in discover_tool_specs():
        if not spec.config_fields:
            continue
        defaults[spec.definition.name] = {
            field.key: field.default for field in spec.config_fields
        }
    return defaults


def get_tool_config_field(tool_name: str, field_key: str) -> ToolConfigField | None:
    for spec in discover_tool_specs():
        if spec.definition.name != tool_name:
            continue
        for field in spec.config_fields:
            if field.key == field_key:
                return field
        return None
    return None


class ToolRegistry:
    def __init__(self, settings: Any) -> None:
        self._settings = settings
        self._availability = ToolAvailability(
            memory_enabled=bool(getattr(settings, "memory_enabled", False))
        )
        self._specs_by_name = {
            spec.definition.name: spec
            for spec in discover_tool_specs()
            if spec.is_enabled(self._availability)
        }
        self._definitions = [
            spec.definition for name, spec in sorted(self._specs_by_name.items())
        ]
        self._session_state = ToolSessionState()
        self._memory_store = (
            MemoryStore.from_path(str(getattr(settings, "memory_dir", "")))
            if self._availability.memory_enabled
            else None
        )
        if self._memory_store is not None:
            self._memory_store.ensure_initialized()

    def reset_session_state(self) -> None:
        self._session_state = ToolSessionState()

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

        spec = self._specs_by_name.get(name)
        if spec is None:
            raise RuntimeError(f"Unknown tool: {name}")

        result = spec.execute(
            ToolContext(
                settings=self._settings,
                session_state=self._session_state,
                memory_store=self._memory_store,
            ),
            arguments,
        )
        return json.dumps(result, ensure_ascii=False)
