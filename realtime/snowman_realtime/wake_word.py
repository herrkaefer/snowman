from __future__ import annotations

import logging

import pvporcupine
from pvrecorder import PvRecorder

from .audio import resolve_input_device_index
from .config import Settings
from .events import WakeDetected


LOGGER = logging.getLogger(__name__)


class WakeWordDetector:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._porcupine = pvporcupine.create(
            access_key=settings.porcupine_access_key,
            keyword_paths=[settings.custom_wake_keyword_path],
        )
        device_index = resolve_input_device_index(settings.audio_device_index)
        self._recorder = PvRecorder(
            device_index=device_index,
            frame_length=self._porcupine.frame_length,
        )

    def wait_for_wake(self) -> WakeDetected:
        self._recorder.start()
        LOGGER.info("Listening for wake word using device: %s", self._recorder.selected_device)
        try:
            while True:
                pcm = self._recorder.read()
                keyword_index = self._porcupine.process(pcm)
                if keyword_index >= 0:
                    LOGGER.info("Wake word detected")
                    return WakeDetected(keyword="snowman")
        finally:
            self._recorder.stop()

    def close(self) -> None:
        self._porcupine.delete()
        self._recorder.delete()
