from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from realtime.snowman_realtime.config import DEFAULT_SYSTEM_PROMPT, Settings
from realtime.snowman_realtime.managed_config import (
    ManagedConfigPaths,
    load_editable_config,
    merge_editable_config,
    missing_required_fields,
    validate_editable_config,
    write_managed_config,
)


class ManagedConfigTests(unittest.TestCase):
    def test_load_editable_config_prefers_managed_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            data_dir.joinpath("config.json").write_text(
                json.dumps(
                    {
                        "provider": "openai",
                        "openai_voice": "shimmer",
                        "system_prompt": "Managed prompt",
                        "location_city": "Chicago",
                        "session_window_enabled": True,
                    }
                ),
                encoding="utf-8",
            )
            data_dir.joinpath("secrets.env").write_text(
                'OPENAI_API_KEY="managed-openai"\nPORCUPINE_ACCESS_KEY="managed-porcupine"\n',
                encoding="utf-8",
            )
            env_values = {
                "OPENAI_VOICE": "alloy",
                "SYSTEM_PROMPT": "Env prompt",
                "OPENAI_API_KEY": "env-openai",
                "PORCUPINE_ACCESS_KEY": "env-porcupine",
            }

            with patch.dict(os.environ, {"SNOWMAN_DATA_DIR": temp_dir}, clear=False):
                editable = load_editable_config(
                    default_system_prompt=DEFAULT_SYSTEM_PROMPT,
                    env_values=env_values,
                )

        self.assertEqual(editable["openai_voice"], "shimmer")
        self.assertEqual(editable["system_prompt"], "Managed prompt")
        self.assertEqual(editable["openai_api_key"], "managed-openai")
        self.assertEqual(editable["porcupine_access_key"], "managed-porcupine")
        self.assertEqual(editable["location_city"], "Chicago")
        self.assertTrue(editable["session_window_enabled"])

    def test_merge_blank_secret_preserves_current_secret(self) -> None:
        merged = merge_editable_config(
            {
                "provider": "openai",
                "openai_voice": "alloy",
                "system_prompt": "Prompt",
                "location_city": "",
                "location_region": "",
                "location_country_code": "",
                "location_timezone": "",
                "session_window_enabled": False,
                "openai_api_key": "existing-openai",
                "porcupine_access_key": "existing-porcupine",
                "admin_password": "existing-admin",
            },
            {
                "openai_api_key": "   ",
                "porcupine_access_key": "",
                "system_prompt": "Updated prompt",
            },
        )

        self.assertEqual(merged["openai_api_key"], "existing-openai")
        self.assertEqual(merged["porcupine_access_key"], "existing-porcupine")
        self.assertEqual(merged["system_prompt"], "Updated prompt")

    def test_validation_reports_missing_required_fields(self) -> None:
        errors = validate_editable_config(
            {
                "provider": "",
                "openai_api_key": "",
                "porcupine_access_key": "",
                "openai_voice": "",
                "system_prompt": "",
            }
        )

        self.assertGreaterEqual(len(errors), 5)
        self.assertIn("provider", missing_required_fields({"provider": "gemini"}))

    def test_write_managed_config_persists_json_and_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = ManagedConfigPaths(
                data_dir=Path(temp_dir),
                config_path=Path(temp_dir) / "config.json",
                secrets_path=Path(temp_dir) / "secrets.env",
            )
            write_managed_config(
                paths,
                {
                    "provider": "openai",
                    "openai_voice": "shimmer",
                    "system_prompt": "Prompt",
                    "location_city": "Chicago",
                    "location_region": "IL",
                    "location_country_code": "US",
                    "location_timezone": "America/Chicago",
                    "session_window_enabled": True,
                    "openai_api_key": "test-openai",
                    "porcupine_access_key": "test-porcupine",
                    "admin_password": "admin-pass",
                },
            )

            config_payload = json.loads(paths.config_path.read_text(encoding="utf-8"))
            secrets_payload = paths.secrets_path.read_text(encoding="utf-8")

        self.assertEqual(config_payload["openai_voice"], "shimmer")
        self.assertTrue(config_payload["session_window_enabled"])
        self.assertIn('OPENAI_API_KEY="test-openai"', secrets_payload)
        self.assertIn('ADMIN_PASSWORD="admin-pass"', secrets_payload)


class SettingsManagedConfigTests(unittest.TestCase):
    def test_settings_load_uses_managed_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            data_dir.joinpath("config.json").write_text(
                json.dumps(
                    {
                        "provider": "openai",
                        "openai_voice": "shimmer",
                        "system_prompt": "Managed prompt",
                        "session_window_enabled": True,
                    }
                ),
                encoding="utf-8",
            )
            data_dir.joinpath("secrets.env").write_text(
                'OPENAI_API_KEY="managed-openai"\nPORCUPINE_ACCESS_KEY="managed-porcupine"\n',
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"SNOWMAN_DATA_DIR": temp_dir}, clear=False):
                with patch("realtime.snowman_realtime.config.dotenv_values", return_value={}):
                    settings = Settings.load()

        self.assertEqual(settings.provider, "openai")
        self.assertEqual(settings.openai_voice, "shimmer")
        self.assertEqual(settings.system_prompt, "Managed prompt")
        self.assertTrue(settings.session_window_enabled)
        self.assertEqual(settings.openai_api_key, "managed-openai")
        self.assertEqual(settings.porcupine_access_key, "managed-porcupine")


if __name__ == "__main__":
    unittest.main()
