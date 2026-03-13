from __future__ import annotations

import unittest

from realtime.scripts.check_legacy_config_match import compare_store_to_legacy_env


class CheckLegacyConfigMatchTests(unittest.TestCase):
    def test_compare_store_to_legacy_env_reports_matches(self) -> None:
        results = compare_store_to_legacy_env(
            config_payload={
                "provider": "openai",
                "openai_realtime_model": "gpt-realtime",
                "openai_voice": "marin",
                "wake_word_sensitivity": 0.6,
                "output_gain": 0.35,
                "cue_output_gain": 0.78,
                "custom_wake_keyword_path": "/home/snowman/data/wake_words/Snowman_en_raspberry-pi_v4_0_0.ppn",
                "location_city": "Chicago",
                "location_region": "IL",
                "location_country_code": "US",
                "location_timezone": "America/Chicago",
                "advanced": {
                    "input_ns_enabled": True,
                },
            },
            secrets_payload={
                "openai_api_key": "sk-test-1234567890",
                "porcupine_access_key": "abcd" * 10,
            },
            legacy_env={
                "OPENAI_API_KEY": "sk-test-1234567890",
                "PORCUPINE_ACCESS_KEY": "abcd" * 10,
                "OPENAI_VOICE": "marin",
                "CUSTOM_WAKE_KEYWORD_PATH": "Snowman_en_raspberry-pi_v4_0_0.ppn",
                "LOCATION_CITY": "Chicago",
                "LOCATION_REGION": "IL",
                "LOCATION_COUNTRY_CODE": "US",
                "LOCATION_TIMEZONE": "America/Chicago",
                "OPENAI_REALTIME_MODEL": "gpt-realtime",
                "WAKE_WORD_SENSITIVITY": "0.6",
                "OUTPUT_GAIN": "0.35",
                "CUE_OUTPUT_GAIN": "0.78",
                "INPUT_NS_ENABLED": "true",
                "SESSION_WINDOW_ENABLED": "true",
            },
        )

        self.assertTrue(results)
        self.assertTrue(all(result.matches for result in results))
        wake_word_result = next(
            result for result in results if result.env_key == "CUSTOM_WAKE_KEYWORD_PATH"
        )
        self.assertEqual(wake_word_result.note, "Matched by wake word filename.")

    def test_compare_store_to_legacy_env_reports_mismatch(self) -> None:
        results = compare_store_to_legacy_env(
            config_payload={
                "provider": "openai",
                "openai_realtime_model": "gpt-realtime",
                "openai_voice": "alloy",
                "wake_word_sensitivity": 0.5,
                "output_gain": 0.5,
                "cue_output_gain": 0.22,
                "advanced": {},
            },
            secrets_payload={},
            legacy_env={"WAKE_WORD_SENSITIVITY": "0.6"},
        )

        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].matches)
        self.assertEqual(results[0].current_key, "wake_word_sensitivity")


if __name__ == "__main__":
    unittest.main()
