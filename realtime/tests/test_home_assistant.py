from __future__ import annotations

import json
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from unittest.mock import patch

from realtime.snowman_realtime.config import build_session_instructions
from realtime.snowman_realtime.config_store import ConfigPaths
from realtime.snowman_realtime.config_ui import (
    _run_internal_tool,
    _tool_payload_for_api,
)
from realtime.snowman_realtime.toolbox._ha_helpers import home_assistant_request_json
from realtime.snowman_realtime.toolbox._home_assistant_connect_and_sync import (
    load_registry_snapshot,
    registry_snapshot_status,
    verify_and_sync_registry_snapshot,
)
from realtime.snowman_realtime.tools import ToolRegistry, build_tool_definitions


class _FakeHTTPResponse:
    def __init__(self, payload: str) -> None:
        self._payload = payload.encode("utf-8")

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> "_FakeHTTPResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class _FakeWebSocket:
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self._responses = [json.dumps(item) for item in responses]
        self.sent_messages: list[dict[str, object]] = []
        self.closed = False

    def recv(self) -> str:
        if not self._responses:
            raise AssertionError("No more websocket responses queued")
        return self._responses.pop(0)

    def send(self, message: str) -> None:
        self.sent_messages.append(json.loads(message))

    def close(self) -> None:
        self.closed = True


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        memory_enabled=False,
        tool_config={
            "home_assistant_connect_and_sync": {
                "ha_url": "http://ha.local:8123",
            }
        },
        ha_access_token="ha-test-token",
    )


class HomeAssistantToolTests(unittest.TestCase):
    def test_build_tool_definitions_include_home_assistant_tools(self) -> None:
        names = [definition.name for definition in build_tool_definitions(memory_enabled=False)]

        self.assertIn("home_assistant_call_service", names)
        self.assertIn("home_assistant_get_state", names)
        self.assertIn("home_assistant_search_entities", names)
        self.assertNotIn("home_assistant_connect_and_sync", names)

    def test_session_instructions_route_home_assistant_requests(self) -> None:
        instructions = build_session_instructions("Snowman", "Base prompt.")

        self.assertIn("home_assistant_search_entities", instructions)
        self.assertIn("home_assistant_get_state", instructions)
        self.assertIn("home_assistant_call_service", instructions)

    def test_tool_payload_includes_home_assistant_secret_field(self) -> None:
        payload = _tool_payload_for_api(
            {
                "tool_config": {
                    "home_assistant_connect_and_sync": {
                        "ha_url": "http://ha.local:8123",
                    }
                },
                "ha_access_token": "ha-test-token",
                "advanced": {
                    "memory_enabled": False,
                },
            }
        )

        home_assistant = next(item for item in payload if item["name"] == "home_assistant_connect_and_sync")
        self.assertEqual(
            home_assistant["config_values"]["ha_url"],
            "http://ha.local:8123",
        )
        self.assertEqual(home_assistant["secret_fields"][0]["key"], "ha_access_token")
        self.assertTrue(home_assistant["secret_fields"][0]["configured"])
        self.assertTrue(home_assistant["internal"])

    def test_tool_registry_hides_home_assistant_tools_without_token(self) -> None:
        settings = _settings()
        settings.ha_access_token = ""

        registry = ToolRegistry(settings)
        names = [tool.name for tool in registry.tools]

        self.assertNotIn("home_assistant_call_service", names)
        self.assertNotIn("home_assistant_get_state", names)
        self.assertNotIn("home_assistant_search_entities", names)

    def test_tool_registry_hides_home_assistant_tools_without_url(self) -> None:
        settings = _settings()
        settings.tool_config["home_assistant_connect_and_sync"]["ha_url"] = ""

        registry = ToolRegistry(settings)
        names = [tool.name for tool in registry.tools]

        self.assertNotIn("home_assistant_call_service", names)
        self.assertNotIn("home_assistant_get_state", names)
        self.assertNotIn("home_assistant_search_entities", names)

    def test_home_assistant_search_entities_matches_area_name(self) -> None:
        registry = ToolRegistry(_settings())
        with patch(
            "realtime.snowman_realtime.toolbox.home_assistant_search_entities.fetch_states",
            return_value=[
                {
                    "entity_id": "light.ceiling_1",
                    "state": "on",
                    "attributes": {"friendly_name": "Ceiling 1"},
                },
                {
                    "entity_id": "light.floor_lamp",
                    "state": "off",
                    "attributes": {"friendly_name": "Floor Lamp"},
                },
                {
                    "entity_id": "switch.office_fan",
                    "state": "off",
                    "attributes": {"friendly_name": "Office Fan"},
                },
            ],
        ), patch(
            "realtime.snowman_realtime.toolbox.home_assistant_search_entities.lookup_area_name",
            side_effect=lambda _settings, entity_id: "Living Room" if entity_id.startswith("light.") else "",
        ):
            result = json.loads(
                registry.execute(
                    "home_assistant_search_entities",
                    json.dumps({"domain_filter": "light", "query": "living room", "limit": 5}),
                )
            )

        self.assertEqual(result["count"], 2)
        self.assertEqual(
            {item["entity_id"] for item in result["entities"]},
            {"light.ceiling_1", "light.floor_lamp"},
        )
        self.assertTrue(all(item["area_name"] == "Living Room" for item in result["entities"]))

    def test_home_assistant_search_entities_expands_chinese_aliases(self) -> None:
        registry = ToolRegistry(_settings())
        with patch(
            "realtime.snowman_realtime.toolbox.home_assistant_search_entities.fetch_states",
            return_value=[
                {
                    "entity_id": "light.living_room_ceiling_light",
                    "state": "on",
                    "attributes": {"friendly_name": "Living Room Ceiling Light"},
                },
                {
                    "entity_id": "light.kitchen_light",
                    "state": "off",
                    "attributes": {"friendly_name": "Kitchen Light"},
                },
            ],
        ), patch(
            "realtime.snowman_realtime.toolbox.home_assistant_search_entities.lookup_area_name",
            return_value="",
        ):
            result = json.loads(
                registry.execute(
                    "home_assistant_search_entities",
                    json.dumps({"domain_filter": "light", "query": "客厅的灯", "limit": 5}, ensure_ascii=False),
                )
            )

        self.assertGreaterEqual(result["count"], 1)
        self.assertEqual(result["entities"][0]["entity_id"], "light.living_room_ceiling_light")

    def test_home_assistant_search_entities_prefers_structured_area_and_name(self) -> None:
        registry = ToolRegistry(_settings())
        with patch(
            "realtime.snowman_realtime.toolbox.home_assistant_search_entities.fetch_states",
            return_value=[
                {
                    "entity_id": "light.foyer_light",
                    "state": "off",
                    "attributes": {"friendly_name": "Foyer Light"},
                },
                {
                    "entity_id": "light.sideboard_lamp",
                    "state": "off",
                    "attributes": {"friendly_name": "Sideboard Lamp"},
                },
            ],
        ), patch(
            "realtime.snowman_realtime.toolbox.home_assistant_search_entities.lookup_area_name",
            side_effect=lambda _settings, entity_id: "Foyer" if entity_id == "light.foyer_light" else "Dining Room",
        ):
            result = json.loads(
                registry.execute(
                    "home_assistant_search_entities",
                    json.dumps({"domain_filter": "light", "area": "门厅", "name": "灯", "limit": 5}, ensure_ascii=False),
                )
            )

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["entities"][0]["entity_id"], "light.foyer_light")

    def test_home_assistant_search_entities_uses_registry_snapshot_area_mapping(self) -> None:
        registry = ToolRegistry(_settings())
        snapshot = {
            "ha_url": "http://ha.local:8123",
            "areas": [{"area_id": "area_dining", "name": "Dining Area"}],
            "devices": [{"id": "device_sideboard", "area_id": "area_dining"}],
            "entities": [
                {
                    "entity_id": "light.sideboard_lamp",
                    "device_id": "device_sideboard",
                    "area_id": None,
                    "disabled_by": None,
                    "hidden_by": None,
                    "name": "Sideboard Lamp",
                },
                {
                    "entity_id": "light.kitchen_light",
                    "device_id": "",
                    "area_id": "",
                    "disabled_by": None,
                    "hidden_by": None,
                    "name": "Kitchen Light",
                },
            ],
        }
        with patch(
            "realtime.snowman_realtime.toolbox.home_assistant_search_entities.load_registry_snapshot",
            return_value=snapshot,
        ), patch(
            "realtime.snowman_realtime.toolbox.home_assistant_search_entities.fetch_states",
            return_value=[
                {
                    "entity_id": "light.sideboard_lamp",
                    "state": "off",
                    "attributes": {"friendly_name": "Sideboard Lamp"},
                },
                {
                    "entity_id": "light.kitchen_light",
                    "state": "off",
                    "attributes": {"friendly_name": "Kitchen Light"},
                },
            ],
        ), patch(
            "realtime.snowman_realtime.toolbox.home_assistant_search_entities.lookup_area_name",
            side_effect=AssertionError("lookup_area_name should not be used when registry snapshot exists"),
        ):
            result = json.loads(
                registry.execute(
                    "home_assistant_search_entities",
                    json.dumps({"domain_filter": "light", "area": "餐厅", "name": "灯", "limit": 5}, ensure_ascii=False),
                )
            )

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["entities"][0]["entity_id"], "light.sideboard_lamp")
        self.assertEqual(result["entities"][0]["area_name"], "Dining Area")

    def test_home_assistant_get_state_returns_compact_state_dict(self) -> None:
        registry = ToolRegistry(_settings())
        with patch(
            "realtime.snowman_realtime.toolbox.home_assistant_get_state.fetch_state",
            side_effect=[
                {
                    "entity_id": "climate.downstairs",
                    "state": "cool",
                    "attributes": {"friendly_name": "Downstairs Thermostat", "temperature": 72},
                }
            ],
        ), patch(
            "realtime.snowman_realtime.toolbox.home_assistant_get_state.lookup_area_name",
            return_value="Living Room",
        ):
            result = json.loads(
                registry.execute(
                    "home_assistant_get_state",
                    json.dumps({"entity_id": "climate.downstairs"}),
                )
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["states"]["climate.downstairs"]["state"], "cool")
        self.assertEqual(
            result["states"]["climate.downstairs"]["friendly_name"],
            "Downstairs Thermostat",
        )
        self.assertEqual(result["states"]["climate.downstairs"]["area_name"], "Living Room")
        self.assertEqual(result["states"]["climate.downstairs"]["attributes"]["temperature"], 72)

    def test_home_assistant_get_state_supports_multiple_entities(self) -> None:
        registry = ToolRegistry(_settings())
        with patch(
            "realtime.snowman_realtime.toolbox.home_assistant_get_state.fetch_state",
            side_effect=[
                {
                    "entity_id": "light.dining_light",
                    "state": "off",
                    "attributes": {"friendly_name": "Dining Light"},
                },
                {
                    "entity_id": "light.sideboard_lamp",
                    "state": "on",
                    "attributes": {"friendly_name": "Sideboard Lamp"},
                },
            ],
        ), patch(
            "realtime.snowman_realtime.toolbox.home_assistant_get_state.lookup_area_name",
            side_effect=["Dining Area", "Dining Area"],
        ):
            result = json.loads(
                registry.execute(
                    "home_assistant_get_state",
                    json.dumps({"entity_id": ["light.dining_light", "light.sideboard_lamp"]}),
                )
            )

        self.assertEqual(result["count"], 2)
        self.assertEqual(result["states"]["light.dining_light"]["state"], "off")
        self.assertEqual(result["states"]["light.sideboard_lamp"]["state"], "on")
        self.assertEqual(result["missing_entity_ids"], [])

    def test_home_assistant_call_service_flattens_targets_for_rest_api(self) -> None:
        registry = ToolRegistry(_settings())
        with patch(
            "realtime.snowman_realtime.toolbox.home_assistant_call_service.home_assistant_request_json",
            return_value=[
                {
                    "entity_id": "light.ceiling_1",
                    "state": "off",
                    "attributes": {"friendly_name": "Ceiling 1"},
                },
                {
                    "entity_id": "light.floor_lamp",
                    "state": "off",
                    "attributes": {"friendly_name": "Floor Lamp"},
                },
            ],
        ) as request_json:
            result = json.loads(
                registry.execute(
                    "home_assistant_call_service",
                    json.dumps(
                        {
                            "domain": "light",
                            "service": "turn_off",
                            "entity_id": ["light.ceiling_1", "light.floor_lamp"],
                            "service_data": {"transition": 2},
                        }
                    ),
                )
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["changed_entity_ids"], ["light.ceiling_1", "light.floor_lamp"])
        self.assertTrue(result["results"]["light.ceiling_1"]["changed"])
        self.assertEqual(
            request_json.call_args.kwargs["body"],
            {
                "entity_id": ["light.ceiling_1", "light.floor_lamp"],
                "transition": 2,
            },
        )

    def test_home_assistant_call_service_requires_non_empty_target(self) -> None:
        registry = ToolRegistry(_settings())

        with self.assertRaisesRegex(
            RuntimeError,
            "requires entity_id or area_id",
        ):
            registry.execute(
                "home_assistant_call_service",
                json.dumps(
                    {
                        "domain": "light",
                        "service": "turn_off",
                    }
                ),
            )

    def test_home_assistant_get_state_rejects_invalid_entity_id_type(self) -> None:
        registry = ToolRegistry(_settings())

        with self.assertRaisesRegex(
            RuntimeError,
            "entity_id must be a string or list of strings",
        ):
            registry.execute(
                "home_assistant_get_state",
                json.dumps({"entity_id": 123}),
            )


class HomeAssistantHelperTests(unittest.TestCase):
    def test_home_assistant_request_json_maps_http_error(self) -> None:
        settings = _settings()
        http_error = HTTPError(
            url="http://ha.local:8123/api/states",
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=BytesIO(b'{"message":"unauthorized"}'),
        )
        with patch(
            "realtime.snowman_realtime.toolbox._ha_helpers.request.urlopen",
            side_effect=http_error,
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                r"Home Assistant GET /api/states failed with HTTP 401",
            ):
                home_assistant_request_json(settings, method="GET", path="/api/states")

    def test_home_assistant_request_json_parses_success_payload(self) -> None:
        settings = _settings()
        with patch(
            "realtime.snowman_realtime.toolbox._ha_helpers.request.urlopen",
            return_value=_FakeHTTPResponse('{"ok": true}'),
        ):
            payload = home_assistant_request_json(settings, method="GET", path="/api/states")

        self.assertEqual(payload, {"ok": True})

    def test_verify_and_sync_registry_snapshot_writes_snapshot(self) -> None:
        settings = _settings()
        fake_socket = _FakeWebSocket(
            [
                {"type": "auth_required"},
                {"type": "auth_ok"},
                {"id": 1, "type": "result", "success": True, "result": {"location_name": "Home"}},
                {"id": 2, "type": "result", "success": True, "result": [{"area_id": "area_1", "name": "Living Room"}]},
                {"id": 3, "type": "result", "success": True, "result": [{"id": "device_1", "area_id": "area_1"}]},
                {
                    "id": 4,
                    "type": "result",
                    "success": True,
                    "result": [{"entity_id": "light.living_room_ceiling", "device_id": "device_1"}],
                },
            ]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            with patch(
                "realtime.snowman_realtime.toolbox._home_assistant_connect_and_sync.resolve_config_paths",
                return_value=ConfigPaths(
                    data_dir=temp_path,
                    config_path=temp_path / "config.json",
                    secrets_path=temp_path / "secrets.json",
                    identity_path=temp_path / "identity.md",
                ),
            ), patch(
                "realtime.snowman_realtime.toolbox._home_assistant_connect_and_sync.websocket.create_connection",
                return_value=fake_socket,
            ):
                snapshot = verify_and_sync_registry_snapshot(settings)
                saved = load_registry_snapshot(settings)
                status = registry_snapshot_status(settings)

        self.assertEqual(snapshot["areas"][0]["name"], "Living Room")
        self.assertIsNotNone(saved)
        assert saved is not None
        self.assertEqual(saved["entities"][0]["entity_id"], "light.living_room_ceiling")
        self.assertTrue(status["exists"])
        self.assertEqual(status["counts"]["entities"], 1)
        self.assertTrue(fake_socket.closed)
        self.assertEqual(fake_socket.sent_messages[0]["type"], "auth")
        self.assertEqual(fake_socket.sent_messages[1]["type"], "get_config")

    def test_run_internal_tool_returns_registry_status(self) -> None:
        config_payload = {
            "tool_config": {
                "home_assistant_connect_and_sync": {
                    "ha_url": "http://ha.local:8123",
                }
            },
            "ha_access_token": "saved-token",
        }
        with patch(
            "realtime.snowman_realtime.config_ui.execute_tool_by_name",
            return_value={
                "ok": True,
                "message": "Home Assistant verified.",
                "registry_cache": {
                    "exists": True,
                    "fetched_at": "2026-03-13T12:00:00Z",
                    "counts": {"areas": 1, "devices": 1, "entities": 1},
                },
            },
        ), patch(
            "realtime.snowman_realtime.config_ui._settings_namespace_for_config",
            return_value=_settings(),
        ):
            payload = _run_internal_tool(config_payload, "home_assistant_connect_and_sync")

        self.assertIn("Home Assistant verified.", payload["message"])
        self.assertTrue(payload["registry_cache"]["exists"])


if __name__ == "__main__":
    unittest.main()
