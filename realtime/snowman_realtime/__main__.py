from snowman_realtime.assistant import SnowmanRealtimeAssistant
from snowman_realtime.config import Settings, configure_logging


def main() -> None:
    settings = Settings.load()
    configure_logging(settings.log_level)
    SnowmanRealtimeAssistant(settings).run()


if __name__ == "__main__":
    main()
