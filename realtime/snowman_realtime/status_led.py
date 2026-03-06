from __future__ import annotations

import logging
import sys
from pathlib import Path


LOGGER = logging.getLogger(__name__)
VOICEHAT_BUTTON_LED_PIN = 25


def _import_pwm_led():
    try:
        from gpiozero import PWMLED  # type: ignore

        return PWMLED
    except ImportError:
        dist_packages = Path("/usr/lib/python3/dist-packages")
        if dist_packages.exists():
            sys.path.append(str(dist_packages))
            from gpiozero import PWMLED  # type: ignore

            return PWMLED
        raise


class SessionStatusLed:
    def __init__(self) -> None:
        self._led = None
        try:
            pwm_led = _import_pwm_led()
            self._led = pwm_led(VOICEHAT_BUTTON_LED_PIN)
            LOGGER.info("Session status LED enabled on pin %d", VOICEHAT_BUTTON_LED_PIN)
        except Exception as exc:
            LOGGER.info("Session status LED unavailable: %s", exc)

    def user_can_speak(self) -> None:
        if self._led is None:
            return
        self._led.value = 1.0

    def processing(self) -> None:
        if self._led is None:
            return
        self._led.pulse(fade_in_time=0.45, fade_out_time=0.45, n=None, background=True)

    def off(self) -> None:
        if self._led is None:
            return
        self._led.off()

    def close(self) -> None:
        if self._led is None:
            return
        try:
            self._led.off()
            self._led.close()
        except Exception:
            LOGGER.debug("Failed to close session status LED", exc_info=True)
        self._led = None
