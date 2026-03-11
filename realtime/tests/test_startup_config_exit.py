from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from realtime.snowman_realtime import __main__ as main_module
from realtime.snowman_realtime.config import ConfigError


class StartupConfigExitTests(unittest.TestCase):
    def test_main_returns_config_exit_code_when_config_missing(self) -> None:
        with patch.object(main_module.Settings, "load", side_effect=ConfigError("missing key")):
            with patch.object(main_module, "configure_logging") as configure_logging:
                exit_code = main_module.main()

        self.assertEqual(exit_code, main_module.CONFIG_EXIT_CODE)
        configure_logging.assert_called_once_with("INFO")

    def test_main_runs_assistant_when_config_is_valid(self) -> None:
        fake_settings = SimpleNamespace(log_level="DEBUG")

        with patch.object(main_module.Settings, "load", return_value=fake_settings):
            with patch.object(main_module, "configure_logging") as configure_logging:
                with patch.object(main_module, "SnowmanRealtimeAssistant") as assistant_cls:
                    assistant_cls.return_value.run.return_value = None
                    exit_code = main_module.main()

        self.assertEqual(exit_code, 0)
        configure_logging.assert_called_once_with("DEBUG")
        assistant_cls.assert_called_once_with(fake_settings)
        assistant_cls.return_value.run.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
