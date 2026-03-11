import logging

from .assistant import SnowmanRealtimeAssistant
from .config import ConfigError, Settings, configure_logging


CONFIG_EXIT_CODE = 78


def main() -> int:
    try:
        settings = Settings.load()
    except ConfigError as exc:
        configure_logging("INFO")
        logging.getLogger(__name__).error("Snowman realtime is not configured: %s", exc)
        return CONFIG_EXIT_CODE

    configure_logging(settings.log_level)
    SnowmanRealtimeAssistant(settings).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
