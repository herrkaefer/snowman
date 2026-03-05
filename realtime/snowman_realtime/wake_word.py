from __future__ import annotations

import logging
import time

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
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self._recorder.start()
        self._started = True
        LOGGER.info("Listening for wake word using device: %s", self._recorder.selected_device)

    def stop(self) -> None:
        if not self._started:
            return
        self._recorder.stop()
        self._started = False

    def wait_for_wake(self, timeout: float | None = None) -> WakeDetected | None:
        self.start()
        deadline = None if timeout is None else time.monotonic() + timeout
        try:
            while True:
                pcm = self._recorder.read()
                keyword_index = self._porcupine.process(pcm)
                if keyword_index >= 0:
                    LOGGER.info("Wake word detected")
                    return WakeDetected(keyword="snowman")
                if deadline is not None and time.monotonic() >= deadline:
                    return None
        finally:
            self.stop()

    def poll_for_wake(self, timeout: float) -> WakeDetected | None:
        self.start()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            pcm = self._recorder.read()
            keyword_index = self._porcupine.process(pcm)
            if keyword_index >= 0:
                LOGGER.info("Wake word detected")
                return WakeDetected(keyword="snowman")
        return None

    def close(self) -> None:
        self.stop()
        self._porcupine.delete()
        self._recorder.delete()
