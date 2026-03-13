from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from realtime.snowman_realtime.config import (
    build_location_prompt_context,
    build_session_instructions,
    build_web_search_user_location,
)
from realtime.snowman_realtime.tools import ToolRegistry


class _DummyHTTPResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def __enter__(self) -> "_DummyHTTPResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


class LocationContextTests(unittest.TestCase):
    def test_runtime_instructions_include_location_context(self) -> None:
        instructions = build_session_instructions(
            "Snowman",
            "Base prompt.",
            location_context=build_location_prompt_context(
                street="",
                city="Chicago",
                region="IL",
                country_code="US",
            ),
            now=datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc),
        )

        self.assertIn(
            "You are physically installed and running at this home location on the Raspberry Pi: Chicago, IL, US.",
            instructions,
        )
        self.assertIn("Your name is Snowman.", instructions)

    def test_runtime_instructions_skip_empty_location_context(self) -> None:
        instructions = build_session_instructions(
            "Snowman",
            "Base prompt.",
            location_context="",
            now=datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc),
        )

        self.assertNotIn("Default local context for the assistant and current user:", instructions)

    def test_build_web_search_user_location_returns_none_without_required_fields(self) -> None:
        self.assertIsNone(
            build_web_search_user_location(
                city="",
                region="",
                country_code="",
                timezone="",
            )
        )

    def test_build_web_search_user_location_accepts_partial_fields(self) -> None:
        self.assertEqual(
            build_web_search_user_location(
                city="Chicago",
                region="",
                country_code="",
                timezone="",
            ),
            {
                "type": "approximate",
                "city": "Chicago",
            },
        )

    def test_build_location_prompt_context_includes_street_when_available(self) -> None:
        prompt = build_location_prompt_context(
            street="W Belmont Ave",
            city="Chicago",
            region="IL",
            country_code="US",
        )

        self.assertIn(
            "You are physically installed and running at this home location on the Raspberry Pi: W Belmont Ave, Chicago, IL, US.",
            prompt,
        )
        self.assertIn(
            "If the user asks where you are, where home is, what your address is, what the household address is, or where the user is without giving another location, answer directly with this configured home location.",
            prompt,
        )
        self.assertIn(
            "do not refuse on privacy grounds, and do not say that you are only virtual or have no physical location.",
            prompt,
        )
        self.assertIn(
            "For nearby, closest, near me, around here, or local business searches, include this street-level location in any web_search query you generate instead of relying on city alone.",
            prompt,
        )

    def test_web_search_uses_configured_location(self) -> None:
        settings = SimpleNamespace(
            openai_api_key="test-key",
            tool_config={"web_search": {"model": "gpt-5.2"}},
            location_city="Chicago",
            location_region="IL",
            location_country_code="US",
            location_timezone="America/Chicago",
        )
        registry = ToolRegistry(settings)
        captured: dict[str, object] = {}

        def fake_urlopen(req, timeout=20):
            captured["body"] = json.loads(req.data.decode("utf-8"))
            return _DummyHTTPResponse({"output_text": "ok", "output": []})

        with patch("realtime.snowman_realtime.toolbox.web_search.request.urlopen", fake_urlopen):
            result = json.loads(registry.execute("web_search", '{"query":"weather"}'))

        self.assertEqual(result["summary"], "ok")
        self.assertEqual(
            captured["body"]["tools"][0]["user_location"],
            {
                "type": "approximate",
                "city": "Chicago",
                "region": "IL",
                "country": "US",
                "timezone": "America/Chicago",
            },
        )

    def test_web_search_omits_location_when_unconfigured(self) -> None:
        settings = SimpleNamespace(
            openai_api_key="test-key",
            tool_config={"web_search": {"model": "gpt-5.2"}},
            location_city="",
            location_region="",
            location_country_code="",
            location_timezone="",
        )
        registry = ToolRegistry(settings)
        captured: dict[str, object] = {}

        def fake_urlopen(req, timeout=20):
            captured["body"] = json.loads(req.data.decode("utf-8"))
            return _DummyHTTPResponse({"output_text": "ok", "output": []})

        with patch("realtime.snowman_realtime.toolbox.web_search.request.urlopen", fake_urlopen):
            registry.execute("web_search", '{"query":"weather"}')

        self.assertEqual(captured["body"]["tools"], [{"type": "web_search"}])


if __name__ == "__main__":
    unittest.main()
