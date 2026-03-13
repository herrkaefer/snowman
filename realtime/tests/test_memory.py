from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from realtime.snowman_realtime.config import build_session_instructions
from realtime.snowman_realtime.config_ui import (
    _memory_payload_for_api,
    _restore_profile_baseline,
    _save_profile_baseline,
    _tool_payload_for_api,
)
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
            saved = MemoryStore(Path(temp_dir)).update_profile(
                "## Family\n- Daughter: Xiaomi\n"
            )
            self.assertEqual(saved, "## Family\n- Daughter: Xiaomi\n")

    def test_memory_store_rejects_only_empty_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(Path(temp_dir))
            with self.assertRaises(MemoryValidationError):
                store.update_profile("   \n\n")

    def test_memory_store_can_save_and_restore_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(Path(temp_dir))
            original = "## Family\n- Mira\n"
            changed = "## Family\n- Mira\n- Maelia\n"
            store.update_profile(original)
            store.save_current_as_baseline()
            store.update_profile(changed)

            restored = store.restore_baseline()
            self.assertEqual(restored, original)
            self.assertTrue(store.baseline_exists())
            self.assertEqual(store.read_profile(), original)

class MemoryToolTests(unittest.TestCase):
    def test_build_tool_definitions_includes_profile_tools_when_enabled(self) -> None:
        definitions = build_tool_definitions(memory_enabled=True)
        names = [definition.name for definition in definitions]
        self.assertIn("profile_memory_get", names)
        self.assertIn("profile_memory_update", names)
        profile_get = next(definition for definition in definitions if definition.name == "profile_memory_get")
        self.assertIn("before asking a clarification question", profile_get.description)
        web_search = next(definition for definition in definitions if definition.name == "web_search")
        self.assertIn("external proper nouns", web_search.description)

    def test_tool_registry_profile_get_and_update(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = SimpleNamespace(
                memory_enabled=True,
                memory_dir=temp_dir,
                tool_config={"web_search": {"model": "gpt-5.2"}},
                openai_api_key="unused",
                location_city="",
                location_region="",
                location_country_code="",
                location_timezone="",
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

    def test_tool_registry_requires_get_before_update_when_profile_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = SimpleNamespace(
                memory_enabled=True,
                memory_dir=temp_dir,
                tool_config={"web_search": {"model": "gpt-5.2"}},
                openai_api_key="unused",
                location_city="",
                location_region="",
                location_country_code="",
                location_timezone="",
            )
            registry = ToolRegistry(settings)
            initial = (
                "# Profile Memory\n\n"
                "## Family\n"
                "- Mira: daughter, 11 years old\n"
            )
            registry.execute(
                "profile_memory_update",
                json.dumps({"updated_markdown": initial}),
            )
            registry.reset_session_state()

            with self.assertRaises(RuntimeError):
                registry.execute(
                    "profile_memory_update",
                    json.dumps({"updated_markdown": initial + "- Maelia: daughter, 3 years old\n"}),
                )

            registry.execute("profile_memory_get", "{}")
            result = json.loads(
                registry.execute(
                    "profile_memory_update",
                    json.dumps(
                        {
                            "updated_markdown": initial + "- Maelia: daughter, 3 years old\n"
                        }
                    ),
                )
            )
            self.assertEqual(result["status"], "updated")


class MemoryPromptTests(unittest.TestCase):
    def test_session_instructions_include_memory_index_context(self) -> None:
        instructions = build_session_instructions(
            "Snowman",
            "Base prompt.",
            memory_index_context="# Memory Index\n\n## profile\nretrieval_tools: profile_memory_get",
        )

        self.assertIn("# Memory Index", instructions)
        self.assertIn("profile_memory_get", instructions)
        self.assertIn("who is X, what is X, tell me about X", instructions)
        self.assertIn("ask one brief clarification question", instructions)


class MemoryConfigUITests(unittest.TestCase):
    def test_tool_payload_includes_web_search_config_fields(self) -> None:
        payload = _tool_payload_for_api(
            {
                "tool_config": {
                    "web_search": {
                        "model": "gpt-4.1",
                    }
                },
                "advanced": {
                    "memory_enabled": True,
                },
            }
        )

        web_search = next(item for item in payload if item["name"] == "web_search")
        self.assertEqual(web_search["config_values"]["model"], "gpt-4.1")
        self.assertEqual(web_search["config_fields"][0]["key"], "model")

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
            self.assertIn("ask one brief clarification question", payload["memory_index_markdown"])
            self.assertEqual(payload["recent_conversation_compact_model"], "gpt-4o-mini")
            self.assertIn("gpt-5.2", payload["recent_conversation_compact_model_options"])
            self.assertIn("gpt-4.1", payload["recent_conversation_compact_model_options"])
            self.assertFalse(payload["baseline_exists"])

    def test_memory_baseline_api_helpers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = {
                "advanced": {
                    "memory_enabled": True,
                    "memory_dir": temp_dir,
                }
            }
            store = MemoryStore(Path(temp_dir))
            store.update_profile("## Family\n- Mira\n")

            saved = _save_profile_baseline(config)
            self.assertTrue(saved["baseline_exists"])

            store.update_profile("## Family\n- Mira\n- Maelia\n")
            restored = _restore_profile_baseline(config)
            self.assertEqual(restored["profile_markdown"], "## Family\n- Mira\n")

    def test_tool_payload_for_api_respects_memory_toggle(self) -> None:
        disabled_tools = _tool_payload_for_api({"advanced": {"memory_enabled": False}})
        enabled_tools = _tool_payload_for_api({"advanced": {"memory_enabled": True}})

        disabled_names = [item["name"] for item in disabled_tools]
        enabled_names = [item["name"] for item in enabled_tools]

        self.assertNotIn("profile_memory_get", disabled_names)
        self.assertIn("profile_memory_get", enabled_names)


if __name__ == "__main__":
    unittest.main()
