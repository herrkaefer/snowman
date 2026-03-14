from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from realtime.snowman_realtime.config import DEFAULT_SYSTEM_PROMPT, Settings
from realtime.snowman_realtime.config_store import (
    ConfigPaths,
    config_updates_from_legacy_env,
    config_values_for_api,
    default_public_config,
    load_config_values,
    merge_config_values,
    missing_required_fields,
    validate_config_values,
    write_config_files,
)
from realtime.snowman_realtime.tools import build_default_tool_config
from realtime.scripts.migrate_legacy_config import merge_config


class ConfigStoreTests(unittest.TestCase):
    def test_load_config_values_reads_config_and_secrets_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            data_dir.joinpath("config.json").write_text(
                json.dumps(
                    {
                        "agent_name": "Juniper",
                        "provider": "openai",
                        "openai_realtime_model": "gpt-realtime-mini",
                        "openai_voice": "shimmer",
                        "location_street": "W Belmont Ave",
                        "location_country_code": "United States",
                        "wake_word_sensitivity": 0.65,
                        "output_gain": 0.4,
                        "cue_output_gain": 0.7,
                        "custom_wake_keyword_path": "/tmp/custom.ppn",
                        "location_city": "Chicago",
                    }
                ),
                encoding="utf-8",
            )
            data_dir.joinpath("identity.md").write_text("Saved prompt\n", encoding="utf-8")
            data_dir.joinpath("secrets.json").write_text(
                json.dumps(
                    {
                        "openai_api_key": "saved-openai",
                        "porcupine_access_key": "saved-porcupine",
                        "ha_access_token": "saved-ha",
                    }
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"SNOWMAN_DATA_DIR": temp_dir}, clear=False):
                config_values = load_config_values(
                    default_system_prompt=DEFAULT_SYSTEM_PROMPT,
                )

        self.assertEqual(config_values["agent_name"], "Juniper")
        self.assertEqual(config_values["openai_realtime_model"], "gpt-realtime-mini")
        self.assertEqual(config_values["openai_voice"], "shimmer")
        self.assertEqual(config_values["system_prompt"], "Saved prompt")
        self.assertEqual(config_values["location_street"], "W Belmont Ave")
        self.assertEqual(config_values["location_country_code"], "US")
        self.assertEqual(config_values["wake_word_sensitivity"], 0.65)
        self.assertEqual(config_values["output_gain"], 0.4)
        self.assertEqual(config_values["cue_output_gain"], 0.7)
        self.assertEqual(config_values["custom_wake_keyword_path"], "/tmp/custom.ppn")
        self.assertEqual(config_values["openai_api_key"], "saved-openai")
        self.assertEqual(config_values["porcupine_access_key"], "saved-porcupine")
        self.assertEqual(config_values["ha_access_token"], "saved-ha")
        self.assertEqual(config_values["location_city"], "Chicago")
        self.assertEqual(config_values["tool_config"], build_default_tool_config())
        self.assertEqual(config_values["advanced"]["recent_conversation_compact_model"], "gpt-4o-mini")

    def test_load_config_values_reads_identity_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            data_dir.joinpath("config.json").write_text(
                json.dumps(
                    {
                        "agent_name": "Juniper",
                        "provider": "openai",
                        "openai_realtime_model": "gpt-realtime-mini",
                        "openai_voice": "shimmer",
                    }
                ),
                encoding="utf-8",
            )
            data_dir.joinpath("identity.md").write_text(
                "# Identity\n\n## Role\n- Identity file prompt\n",
                encoding="utf-8",
            )
            data_dir.joinpath("secrets.json").write_text(
                json.dumps(
                    {
                        "openai_api_key": "saved-openai",
                        "porcupine_access_key": "saved-porcupine",
                    }
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"SNOWMAN_DATA_DIR": temp_dir}, clear=False):
                config_values = load_config_values(
                    default_system_prompt=DEFAULT_SYSTEM_PROMPT,
                )

        self.assertEqual(config_values["system_prompt"], "# Identity\n\n## Role\n- Identity file prompt")

    def test_load_config_values_formats_legacy_identity_prompt(self) -> None:
        legacy_prompt = (
            "You are a concise bilingual voice assistant running on a Raspberry Pi at the user's home. "
            "Voice style: friendly, clear, cheerful, warm, and supportive. "
            "Reply in one short sentence by default, and use two short sentences only when needed for clarity. "
            "Reply in the same language as the clearly understood user utterance; if the utterance is unclear, use English."
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            data_dir.joinpath("identity.md").write_text(legacy_prompt, encoding="utf-8")
            data_dir.joinpath("config.json").write_text(
                json.dumps(
                    {
                        "agent_name": "Juniper",
                        "provider": "openai",
                        "openai_realtime_model": "gpt-realtime-mini",
                        "openai_voice": "shimmer",
                    }
                ),
                encoding="utf-8",
            )
            data_dir.joinpath("secrets.json").write_text(
                json.dumps(
                    {
                        "openai_api_key": "saved-openai",
                        "porcupine_access_key": "saved-porcupine",
                    }
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"SNOWMAN_DATA_DIR": temp_dir}, clear=False):
                config_values = load_config_values(
                    default_system_prompt=DEFAULT_SYSTEM_PROMPT,
                )

        self.assertIn("# Identity", config_values["system_prompt"])
        self.assertIn("## Role", config_values["system_prompt"])
        self.assertIn("## Tone", config_values["system_prompt"])
        self.assertIn("## Response Style", config_values["system_prompt"])
        self.assertIn("## Language", config_values["system_prompt"])

    def test_merge_blank_secret_preserves_current_secret(self) -> None:
        merged = merge_config_values(
            {
                "provider": "openai",
                "agent_name": "Snowman",
                "openai_realtime_model": "gpt-realtime",
                "openai_voice": "alloy",
                "system_prompt": "Prompt",
                "location_street": "",
                "wake_word_sensitivity": 0.5,
                "output_gain": 0.5,
                "cue_output_gain": 0.22,
                "custom_wake_keyword_path": "",
                "location_city": "",
                "location_region": "",
                "location_country_code": "",
                "location_timezone": "",
                "openai_api_key": "existing-openai",
                "porcupine_access_key": "existing-porcupine",
                "admin_password": "existing-admin",
                "ha_access_token": "existing-ha",
                "advanced": {},
            },
            {
                "openai_api_key": "   ",
                "porcupine_access_key": "",
                "ha_access_token": " ",
                "agent_name": "Juniper",
                "openai_realtime_model": "gpt-realtime-mini",
                "system_prompt": "Updated prompt",
                "location_street": "W Belmont Ave",
                "wake_word_sensitivity": 0.7,
                "output_gain": 0.45,
                "cue_output_gain": 0.8,
            },
        )

        self.assertEqual(merged["agent_name"], "Juniper")
        self.assertEqual(merged["openai_realtime_model"], "gpt-realtime-mini")
        self.assertEqual(merged["openai_api_key"], "existing-openai")
        self.assertEqual(merged["porcupine_access_key"], "existing-porcupine")
        self.assertEqual(merged["ha_access_token"], "existing-ha")
        self.assertEqual(merged["system_prompt"], "Updated prompt")
        self.assertEqual(merged["location_street"], "W Belmont Ave")
        self.assertEqual(merged["wake_word_sensitivity"], 0.7)
        self.assertEqual(merged["output_gain"], 0.45)
        self.assertEqual(merged["cue_output_gain"], 0.8)

    def test_load_config_values_uses_defaults_when_files_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {"SNOWMAN_DATA_DIR": temp_dir}, clear=False):
                config_values = load_config_values(
                    default_system_prompt=DEFAULT_SYSTEM_PROMPT,
                )

        self.assertEqual(config_values["openai_api_key"], "")
        self.assertEqual(config_values["porcupine_access_key"], "")
        self.assertEqual(config_values["agent_name"], "Snowman")
        self.assertEqual(config_values["openai_realtime_model"], "gpt-realtime")
        self.assertEqual(config_values["system_prompt"], DEFAULT_SYSTEM_PROMPT)
        self.assertEqual(config_values["wake_word_sensitivity"], 0.5)
        self.assertEqual(config_values["output_gain"], 0.5)
        self.assertEqual(config_values["cue_output_gain"], 0.22)
        self.assertEqual(config_values["openai_voice"], "alloy")
        self.assertEqual(config_values["tool_config"], build_default_tool_config())

    def test_load_config_values_migrates_legacy_web_search_model_to_tool_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            data_dir.joinpath("config.json").write_text(
                json.dumps(
                    {
                        "agent_name": "Snowman",
                        "provider": "openai",
                        "openai_realtime_model": "gpt-realtime",
                        "openai_voice": "alloy",
                        "advanced": {
                            "web_search_model": "gpt-4.1",
                        },
                    }
                ),
                encoding="utf-8",
            )
            data_dir.joinpath("secrets.json").write_text(
                json.dumps(
                    {
                        "openai_api_key": "saved-openai",
                        "porcupine_access_key": "saved-porcupine",
                    }
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"SNOWMAN_DATA_DIR": temp_dir}, clear=False):
                config_values = load_config_values(default_system_prompt=DEFAULT_SYSTEM_PROMPT)

        self.assertEqual(config_values["tool_config"]["web_search"]["model"], "gpt-4.1")

    def test_validation_reports_missing_required_fields(self) -> None:
        errors = validate_config_values(
            {
                "provider": "",
                "agent_name": "",
                "openai_realtime_model": "bad-model",
                "openai_api_key": "",
                "porcupine_access_key": "",
                "openai_voice": "",
                "system_prompt": "",
                "wake_word_sensitivity": 2,
                "output_gain": "bad",
                "cue_output_gain": "bad",
                "tool_config": {
                    "home_assistant": {
                        "ha_url": "ftp://invalid",
                    }
                },
                "advanced": {},
            }
        )

        self.assertGreaterEqual(len(errors), 5)
        self.assertIn("Voice assistant name is required.", errors)
        self.assertIn("Realtime model must be one of: gpt-realtime, gpt-realtime-mini.", errors)
        self.assertIn("Wake word sensitivity must be between 0.0 and 1.0.", errors)
        self.assertIn("Output gain must be a number.", errors)
        self.assertIn("Cue gain must be a number.", errors)
        self.assertIn("Home Assistant URL must be a valid http:// or https:// URL.", errors)
        self.assertIn("provider", missing_required_fields({"provider": "gemini"}))

    def test_write_config_files_persists_json_and_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = ConfigPaths(
                data_dir=Path(temp_dir),
                config_path=Path(temp_dir) / "config.json",
                secrets_path=Path(temp_dir) / "secrets.json",
                identity_path=Path(temp_dir) / "identity.md",
            )
            write_config_files(
                paths,
                {
                    "agent_name": "Juniper",
                    "provider": "openai",
                    "openai_realtime_model": "gpt-realtime-mini",
                    "openai_voice": "shimmer",
                    "system_prompt": "Prompt",
                    "location_street": "W Belmont Ave",
                    "wake_word_sensitivity": 0.6,
                    "output_gain": 0.35,
                    "cue_output_gain": 0.78,
                    "custom_wake_keyword_path": "/tmp/custom.ppn",
                    "location_city": "Chicago",
                    "location_region": "IL",
                    "location_country_code": "US",
                    "location_timezone": "America/Chicago",
                    "openai_api_key": "test-openai",
                    "porcupine_access_key": "test-porcupine",
                    "admin_password": "admin-pass",
                    "ha_access_token": "test-ha-token",
                    "tool_config": {
                        "home_assistant": {
                            "ha_url": "http://homeassistant.local:8123",
                        },
                        "web_search": {
                            "model": "gpt-4.1",
                        }
                    },
                    "advanced": {},
                },
            )

            config_payload = json.loads(paths.config_path.read_text(encoding="utf-8"))
            secrets_payload = json.loads(paths.secrets_path.read_text(encoding="utf-8"))
            identity_markdown = paths.identity_path.read_text(encoding="utf-8")

        self.assertEqual(config_payload["agent_name"], "Juniper")
        self.assertEqual(config_payload["openai_realtime_model"], "gpt-realtime-mini")
        self.assertEqual(config_payload["openai_voice"], "shimmer")
        self.assertNotIn("system_prompt", config_payload)
        self.assertEqual(config_payload["location_street"], "W Belmont Ave")
        self.assertEqual(config_payload["wake_word_sensitivity"], 0.6)
        self.assertEqual(config_payload["output_gain"], 0.35)
        self.assertEqual(config_payload["cue_output_gain"], 0.78)
        self.assertEqual(config_payload["custom_wake_keyword_path"], "/tmp/custom.ppn")
        self.assertEqual(
            config_payload["tool_config"]["home_assistant"]["ha_url"],
            "http://homeassistant.local:8123",
        )
        self.assertEqual(config_payload["tool_config"]["web_search"]["model"], "gpt-4.1")
        self.assertEqual(identity_markdown, "Prompt\n")
        self.assertEqual(secrets_payload["openai_api_key"], "test-openai")
        self.assertEqual(secrets_payload["admin_password"], "admin-pass")
        self.assertEqual(secrets_payload["ha_access_token"], "test-ha-token")
        self.assertNotIn("ha_access_token", config_payload)

    def test_config_values_for_api_exposes_audio_device_settings(self) -> None:
        payload = config_values_for_api(
            {
                "agent_name": "Juniper",
                "provider": "openai",
                "openai_realtime_model": "gpt-realtime",
                "openai_voice": "marin",
                "system_prompt": "Prompt",
                "location_street": "",
                "wake_word_sensitivity": 0.6,
                "output_gain": 0.35,
                "cue_output_gain": 0.78,
                "custom_wake_keyword_path": "",
                "location_city": "Chicago",
                "location_region": "IL",
                "location_country_code": "US",
                "location_timezone": "America/Chicago",
                "openai_api_key": "test-openai",
                "porcupine_access_key": "test-porcupine",
                "ha_access_token": "test-ha-token",
                "admin_password": "",
                "tool_config": {
                    "home_assistant": {
                        "ha_url": "http://homeassistant.local:8123",
                    },
                    "web_search": {
                        "model": "gpt-4.1",
                    }
                },
                "advanced": {
                    "audio_device_index": 4,
                    "playback_device": "plughw:2,0",
                },
            }
        )

        self.assertEqual(payload["audio_device_index"], 4)
        self.assertEqual(payload["playback_device"], "plughw:2,0")
        self.assertEqual(payload["ha_access_token"], "")
        self.assertTrue(payload["ha_access_token_configured"])
        self.assertEqual(payload["ha_access_token_masked"], "test...oken")
        self.assertEqual(
            payload["tool_config"]["home_assistant"]["ha_url"],
            "http://homeassistant.local:8123",
        )
        self.assertEqual(payload["tool_config"]["web_search"]["model"], "gpt-4.1")

    def test_config_updates_from_legacy_env_parses_advanced_values(self) -> None:
        updates = config_updates_from_legacy_env(
            {
                "OPENAI_VOICE": "nova",
                "OPENAI_REALTIME_MODEL": "gpt-realtime",
                "WAKE_WORD_SENSITIVITY": "0.75",
                "OUTPUT_GAIN": "0.4",
                "CUE_OUTPUT_GAIN": "0.9",
                "INPUT_NS_ENABLED": "true",
                "RESPONSE_MAX_OUTPUT_TOKENS": "1024",
            }
        )

        self.assertEqual(updates["wake_word_sensitivity"], 0.75)
        self.assertEqual(updates["output_gain"], 0.4)
        self.assertEqual(updates["cue_output_gain"], 0.9)
        self.assertEqual(updates["openai_realtime_model"], "gpt-realtime")
        self.assertEqual(updates["openai_voice"], "nova")
        self.assertTrue(updates["advanced"]["input_ns_enabled"])
        self.assertEqual(updates["advanced"]["response_max_output_tokens"], 1024)

    def test_default_public_config_uses_current_advanced_defaults(self) -> None:
        payload = default_public_config(default_system_prompt=DEFAULT_SYSTEM_PROMPT)
        self.assertEqual(payload["agent_name"], "Snowman")
        self.assertEqual(payload["openai_realtime_model"], "gpt-realtime")
        self.assertEqual(payload["wake_word_sensitivity"], 0.5)
        self.assertEqual(payload["output_gain"], 0.5)
        self.assertEqual(payload["cue_output_gain"], 0.22)
        self.assertEqual(payload["tool_config"], build_default_tool_config())
        self.assertTrue(payload["advanced"]["memory_enabled"])

    def test_legacy_advanced_overrides_default_values_during_migration(self) -> None:
        defaults = default_public_config(default_system_prompt=DEFAULT_SYSTEM_PROMPT)
        merged = merge_config(
            defaults,
            {
                "wake_word_sensitivity": 0.6,
                "output_gain": 0.35,
                "cue_output_gain": 0.78,
            },
        )

        self.assertEqual(merged["wake_word_sensitivity"], 0.6)
        self.assertEqual(merged["output_gain"], 0.35)
        self.assertEqual(merged["cue_output_gain"], 0.78)


class SettingsConfigTests(unittest.TestCase):
    def test_settings_load_uses_config_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            custom_ppn_path = data_dir / "custom.ppn"
            custom_ppn_path.write_bytes(b"test")
            data_dir.joinpath("config.json").write_text(
                json.dumps(
                    {
                        "agent_name": "Juniper",
                        "provider": "openai",
                        "openai_realtime_model": "gpt-realtime-mini",
                        "openai_voice": "shimmer",
                        "location_street": "W Belmont Ave",
                        "wake_word_sensitivity": 0.6,
                        "output_gain": 0.35,
                        "cue_output_gain": 0.78,
                        "custom_wake_keyword_path": str(custom_ppn_path),
                    }
                ),
                encoding="utf-8",
            )
            data_dir.joinpath("identity.md").write_text("Saved prompt\n", encoding="utf-8")
            data_dir.joinpath("secrets.json").write_text(
                json.dumps(
                    {
                        "openai_api_key": "saved-openai",
                        "porcupine_access_key": "saved-porcupine",
                        "ha_access_token": "saved-ha",
                    }
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"SNOWMAN_DATA_DIR": temp_dir}, clear=False):
                settings = Settings.load()

        self.assertEqual(settings.agent_name, "Juniper")
        self.assertEqual(settings.provider, "openai")
        self.assertEqual(settings.openai_realtime_model, "gpt-realtime-mini")
        self.assertEqual(settings.openai_voice, "shimmer")
        self.assertEqual(settings.system_prompt, "Saved prompt")
        self.assertEqual(settings.location_street, "W Belmont Ave")
        self.assertTrue(settings.session_window_enabled)
        self.assertEqual(settings.custom_wake_keyword_path, str(custom_ppn_path))
        self.assertEqual(settings.wake_word_sensitivity, 0.6)
        self.assertEqual(settings.output_gain, 0.35)
        self.assertEqual(settings.cue_output_gain, 0.78)
        self.assertEqual(settings.openai_api_key, "saved-openai")
        self.assertEqual(settings.ha_access_token, "saved-ha")
        self.assertEqual(settings.porcupine_access_key, "saved-porcupine")


if __name__ == "__main__":
    unittest.main()
