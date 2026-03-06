#!/usr/bin/env python3

from __future__ import annotations

import argparse
import signal
import time

from gpiozero import Button, PWMLED


BUTTON_PIN = 23
LED_PIN = 25


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Test the AIY Voice HAT button and single-color button LED."
    )
    parser.add_argument(
        "--mode",
        choices=("on", "off", "blink", "pulse", "button"),
        default="blink",
        help="How to drive the button LED.",
    )
    parser.add_argument(
        "--seconds",
        type=float,
        default=8.0,
        help="How long to run for non-button modes.",
    )
    parser.add_argument(
        "--brightness",
        type=float,
        default=1.0,
        help="LED brightness from 0.0 to 1.0 for on mode.",
    )
    parser.add_argument(
        "--blink-on",
        type=float,
        default=0.4,
        help="Blink on-time in seconds.",
    )
    parser.add_argument(
        "--blink-off",
        type=float,
        default=0.4,
        help="Blink off-time in seconds.",
    )
    parser.add_argument(
        "--fade-in",
        type=float,
        default=0.8,
        help="Pulse fade-in seconds.",
    )
    parser.add_argument(
        "--fade-out",
        type=float,
        default=0.8,
        help="Pulse fade-out seconds.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    led = PWMLED(LED_PIN)
    button = Button(BUTTON_PIN, pull_up=True, bounce_time=0.08)

    stopped = False

    def handle_signal(signum, frame) -> None:  # type: ignore[unused-argument]
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    print(f"Voice HAT test using BUTTON_PIN={BUTTON_PIN}, LED_PIN={LED_PIN}")
    print("Note: this hardware exposes a single-color button LED, not an RGB LED.")

    try:
        if args.mode == "on":
            led.value = max(0.0, min(1.0, args.brightness))
            print(f"LED on at brightness={led.value:.2f} for {args.seconds:.1f}s")
            time.sleep(args.seconds)
            return

        if args.mode == "off":
            led.off()
            print(f"LED off for {args.seconds:.1f}s")
            time.sleep(args.seconds)
            return

        if args.mode == "blink":
            print(
                f"LED blinking for {args.seconds:.1f}s "
                f"(on={args.blink_on:.2f}s off={args.blink_off:.2f}s)"
            )
            led.blink(on_time=args.blink_on, off_time=args.blink_off, n=None, background=True)
            time.sleep(args.seconds)
            return

        if args.mode == "pulse":
            print(
                f"LED pulsing for {args.seconds:.1f}s "
                f"(fade_in={args.fade_in:.2f}s fade_out={args.fade_out:.2f}s)"
            )
            led.pulse(fade_in_time=args.fade_in, fade_out_time=args.fade_out, n=None, background=True)
            time.sleep(args.seconds)
            return

        print("Watching button events. Press Ctrl-C to stop.")

        def on_press() -> None:
            print("button: pressed")
            led.on()

        def on_release() -> None:
            print("button: released")
            led.off()

        button.when_pressed = on_press
        button.when_released = on_release

        while not stopped:
            time.sleep(0.1)
    finally:
        button.close()
        led.close()


if __name__ == "__main__":
    main()
