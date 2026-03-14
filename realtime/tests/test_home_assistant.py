from __future__ import annotations

import json
import unittest
from io import BytesIO
from types import SimpleNamespace
from urllib.error import HTTPError
from unittest.mock import patch

from realtime.snowman_realtime.config import build_session_instructions
from realtime.snowman_realtime.config_ui import _tool_payload_for_api
from realtime.snowman_realtime.toolbox._ha_helpers import home_assistant_request_json
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


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        memory_enabled=False,
        tool_config={
            "home_assistant": {
                "ha_url": "http://ha.local:8123",
            }
        },
        ha_access_token="ha-test-token",
    )


class HomeAssistantToolTests(unittest.TestCase):
    def test_build_tool_definitions_include_home_assistant_tools(self) -> None:
        names = [definition.name for definition in build_tool_definitions(memory_enabled=False)]

        self.assertIn("home_assistant", names)
        self.assertIn("home_assistant_entities", names)

    def test_session_instructions_route_home_assistant_requests(self) -> None:
        instructions = build_session_instructions("Snowman", "Base prompt.")

        self.assertIn("home_assistant_entities", instructions)
        self.assertIn("home_assistant", instructions)

    def test_tool_payload_includes_home_assistant_secret_field(self) -> None:
        payload = _tool_payload_for_api(
            {
                "tool_config": {
                    "home_assistant": {
                        "ha_url": "http://ha.local:8123",
                    }
                },
                "ha_access_token": "ha-test-token",
                "advanced": {
                    "memory_enabled": False,
                },
            }
        )

        home_assistant = next(item for item in payload if item["name"] == "home_assistant")
        self.assertEqual(
            home_assistant["config_values"]["ha_url"],
            "http://ha.local:8123",
        )
        self.assertEqual(home_assistant["secret_fields"][0]["key"], "ha_access_token")
        self.assertTrue(home_assistant["secret_fields"][0]["configured"])

    def test_home_assistant_entities_matches_area_name(self) -> None:
        registry = ToolRegistry(_settings())
        with patch(
            "realtime.snowman_realtime.toolbox.home_assistant_entities.fetch_states",
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
            "realtime.snowman_realtime.toolbox.home_assistant_entities.lookup_area_name",
            side_effect=lambda _settings, entity_id: "Living Room" if entity_id.startswith("light.") else "",
        ):
            result = json.loads(
                registry.execute(
                    "home_assistant_entities",
                    json.dumps({"domain_filter": "light", "query": "living room", "limit": 5}),
                )
            )

        self.assertEqual(result["count"], 2)
        self.assertEqual(
            {item["entity_id"] for item in result["entities"]},
            {"light.ceiling_1", "light.floor_lamp"},
        )
        self.assertTrue(all(item["area_name"] == "Living Room" for item in result["entities"]))

    def test_home_assistant_entities_expands_chinese_aliases(self) -> None:
        registry = ToolRegistry(_settings())
        with patch(
            "realtime.snowman_realtime.toolbox.home_assistant_entities.fetch_states",
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
            "realtime.snowman_realtime.toolbox.home_assistant_entities.lookup_area_name",
            return_value="",
        ):
            result = json.loads(
                registry.execute(
                    "home_assistant_entities",
                    json.dumps({"domain_filter": "light", "query": "客厅的灯", "limit": 5}, ensure_ascii=False),
                )
            )

        self.assertGreaterEqual(result["count"], 1)
        self.assertEqual(result["entities"][0]["entity_id"], "light.living_room_ceiling_light")

    def test_home_assistant_entities_prefers_structured_area_and_name(self) -> None:
        registry = ToolRegistry(_settings())
        with patch(
            "realtime.snowman_realtime.toolbox.home_assistant_entities.fetch_states",
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
            "realtime.snowman_realtime.toolbox.home_assistant_entities.lookup_area_name",
            side_effect=lambda _settings, entity_id: "Foyer" if entity_id == "light.foyer_light" else "Dining Room",
        ):
            result = json.loads(
                registry.execute(
                    "home_assistant_entities",
                    json.dumps({"domain_filter": "light", "area": "门厅", "name": "灯", "limit": 5}, ensure_ascii=False),
                )
            )

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["entities"][0]["entity_id"], "light.foyer_light")

    def test_home_assistant_get_state_returns_compact_state(self) -> None:
        registry = ToolRegistry(_settings())
        with patch(
            "realtime.snowman_realtime.toolbox.home_assistant.fetch_state",
            return_value={
                "entity_id": "climate.downstairs",
                "state": "cool",
                "attributes": {"friendly_name": "Downstairs Thermostat", "temperature": 72},
            },
        ), patch(
            "realtime.snowman_realtime.toolbox.home_assistant.lookup_area_name",
            return_value="Living Room",
        ):
            result = json.loads(
                registry.execute(
                    "home_assistant",
                    json.dumps({"action": "get_state", "entity_id": "climate.downstairs"}),
                )
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["state"], "cool")
        self.assertEqual(result["friendly_name"], "Downstairs Thermostat")
        self.assertEqual(result["area_name"], "Living Room")
        self.assertEqual(result["attributes"]["temperature"], 72)

    def test_home_assistant_call_service_flattens_target_for_rest_api(self) -> None:
        registry = ToolRegistry(_settings())
        with patch(
            "realtime.snowman_realtime.toolbox.home_assistant.home_assistant_request_json",
            return_value=[
                {"entity_id": "light.ceiling_1"},
                {"entity_id": "light.floor_lamp"},
            ],
        ) as request_json:
            result = json.loads(
                registry.execute(
                    "home_assistant",
                    json.dumps(
                        {
                            "action": "call_service",
                            "domain": "light",
                            "service": "turn_off",
                            "target": {"entity_id": ["light.ceiling_1", "light.floor_lamp"]},
                            "service_data": {"transition": 2},
                        }
                    ),
                )
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["changed_entities"], ["light.ceiling_1", "light.floor_lamp"])
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
            "requires target.entity_id or target.area_id",
        ):
            registry.execute(
                "home_assistant",
                json.dumps(
                    {
                        "action": "call_service",
                        "domain": "light",
                        "service": "turn_off",
                    }
                ),
            )

    def test_home_assistant_rejects_invalid_action_value(self) -> None:
        registry = ToolRegistry(_settings())

        with self.assertRaisesRegex(
            RuntimeError,
            "action must be exactly 'get_state' or 'call_service'",
        ):
            registry.execute(
                "home_assistant",
                json.dumps({"action": "turn_off"}),
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


if __name__ == "__main__":
    unittest.main()
