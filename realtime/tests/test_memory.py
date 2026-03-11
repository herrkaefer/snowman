from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from realtime.snowman_realtime.config import build_runtime_instructions
from realtime.snowman_realtime.config_ui import _memory_payload_for_api, _tool_payload_for_api
from realtime.snowman_realtime.memory import (
    MemoryStore,
    MemoryValidationError,
    default_profile_markdown,
    render_memory_index_markdown,
)
from realtime.snowman_realtime.tools import ToolRegistry, build_tool_definitions


class MemoryStoreTests(unittest.TestCase):
    def test_memory_store_initializes_default_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(Path(temp_dir))
            store.ensure_initialized()

            self.assertTrue(store.paths.profile_path.exists())
            self.assertTrue(store.paths.index_path.exists())
            self.assertEqual(store.read_profile(), default_profile_markdown())
            self.assertEqual(store.read_memory_index(), render_memory_index_markdown())
            self.assertIn("- description:", store.read_memory_index())

    def test_memory_store_updates_profile_markdown(self) -> None:
        updated = (
            "# Profile Memory\n\n"
            "## People\n"
            "- Daughter: Xiaomi\n\n"
            "## Preferences\n"
            "- Prefers concise answers.\n\n"
            "## Household\n"
            "- Raspberry Pi assistant in the home.\n\n"
            "## Notes\n"
            "- Speaks Chinese during planning.\n"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(Path(temp_dir))
            saved = store.update_profile(updated)

            self.assertEqual(saved, updated.strip() + "\n")
            self.assertEqual(store.read_profile(), updated.strip() + "\n")

    def test_memory_store_rejects_missing_sections(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(MemoryValidationError):
                MemoryStore(Path(temp_dir)).update_profile(
                    "# Profile Memory\n\n## People\n- Daughter: Xiaomi\n"
                )

    def test_memory_store_rejects_unexpected_large_shrink(self) -> None:
        original = (
            "# Profile Memory\n\n"
            "## People\n"
            "- Daughter: Xiaomi\n"
            "- Son: Leo\n\n"
            "## Preferences\n"
            "- Likes short answers.\n"
            "- Prefers Mandarin.\n\n"
            "## Household\n"
            "- Lives in Chicago.\n"
            "- Uses a Raspberry Pi voice assistant.\n\n"
            "## Notes\n"
            "- Stable note one.\n"
            "- Stable note two.\n"
        )
        tiny = (
            "# Profile Memory\n\n"
            "## People\n"
            "- \n\n"
            "## Preferences\n"
            "- \n\n"
            "## Household\n"
            "- \n\n"
            "## Notes\n"
            "- \n"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(Path(temp_dir))
            store.update_profile(original)
            with self.assertRaises(MemoryValidationError):
                store.update_profile(tiny)


class MemoryToolTests(unittest.TestCase):
    def test_build_tool_definitions_includes_profile_tools_when_enabled(self) -> None:
        names = [definition.name for definition in build_tool_definitions(memory_enabled=True)]
        self.assertIn("profile_memory_get", names)
        self.assertIn("profile_memory_update", names)

    def test_tool_registry_profile_get_and_update(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = SimpleNamespace(
                memory_enabled=True,
                memory_dir=temp_dir,
                openai_api_key="unused",
                location_city="",
                location_region="",
                location_country_code="",
                location_timezone="",
                web_search_model="gpt-5.2",
            )
            registry = ToolRegistry(settings)
            initial = json.loads(registry.execute("profile_memory_get", "{}"))
            self.assertIn("# Profile Memory", initial["profile_markdown"])

            updated = (
                "# Profile Memory\n\n"
                "## People\n"
                "- Daughter: Xiaomi\n\n"
                "## Preferences\n"
                "- Likes direct answers.\n\n"
                "## Household\n"
                "- Home assistant runs on Raspberry Pi.\n\n"
                "## Notes\n"
                "- Planning discussions often happen in Chinese.\n"
            )
            result = json.loads(
                registry.execute(
                    "profile_memory_update",
                    json.dumps({"updated_markdown": updated}),
                )
            )

            self.assertEqual(result["status"], "updated")
            self.assertEqual(result["profile_markdown"], updated.strip() + "\n")


class MemoryPromptTests(unittest.TestCase):
    def test_runtime_instructions_include_memory_index_context(self) -> None:
        instructions = build_runtime_instructions(
            "Snowman",
            "Base prompt.",
            memory_index_context="# Memory Index\n\n## profile\nretrieval_tools: profile_memory_get",
        )

        self.assertIn("# Memory Index", instructions)
        self.assertIn("profile_memory_get", instructions)


class MemoryConfigUITests(unittest.TestCase):
    def test_memory_payload_for_api_includes_profile_and_index(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            payload = _memory_payload_for_api(
                {
                    "advanced": {
                        "memory_enabled": True,
                        "memory_dir": temp_dir,
                    }
                }
            )

            self.assertTrue(payload["memory_enabled"])
            self.assertEqual(payload["memory_dir"], temp_dir)
            self.assertIn("# Profile Memory", payload["profile_markdown"])
            self.assertIn("# Memory Index", payload["memory_index_markdown"])
            self.assertIn("- description:", payload["memory_index_markdown"])

    def test_tool_payload_for_api_respects_memory_toggle(self) -> None:
        disabled_tools = _tool_payload_for_api({"advanced": {"memory_enabled": False}})
        enabled_tools = _tool_payload_for_api({"advanced": {"memory_enabled": True}})

        disabled_names = [item["name"] for item in disabled_tools]
        enabled_names = [item["name"] for item in enabled_tools]

        self.assertNotIn("profile_memory_get", disabled_names)
        self.assertIn("profile_memory_get", enabled_names)


if __name__ == "__main__":
    unittest.main()
