#!/usr/bin/env python3

from __future__ import annotations

import argparse
import audioop
import math
import statistics
import struct
import threading
import time

from snowman_realtime.audio import (
    MicrophoneStream,
    RawAplayPlayer,
    resolve_input_device_index,
    resolve_playback_device,
)
from snowman_realtime.config import Settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Play a repeatable test tone at different OUTPUT_GAIN values."
    )
    parser.add_argument(
        "--gains",
        nargs="+",
        type=float,
        default=[0.35, 0.25, 0.15],
        help="One or more output gains to test.",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=2.5,
        help="Seconds of playback per gain.",
    )
    parser.add_argument(
        "--measure-mic",
        action="store_true",
        help="Also capture microphone RMS during playback for each gain.",
    )
    parser.add_argument(
        "--pause",
        type=float,
        default=1.0,
        help="Seconds to pause between gains.",
    )
    return parser


def build_test_pcm(sample_rate: int, duration_seconds: float) -> bytes:
    frame_count = max(1, int(sample_rate * duration_seconds))
    samples: list[int] = []
    for index in range(frame_count):
        t = index / sample_rate
        freq1 = 220.0 + 120.0 * t / max(duration_seconds, 0.1)
        freq2 = 440.0 + 60.0 * t / max(duration_seconds, 0.1)
        sample = int(
            2600 * math.sin(2.0 * math.pi * freq1 * t)
            + 1800 * math.sin(2.0 * math.pi * freq2 * t)
        )
        samples.append(max(-32768, min(32767, sample)))
    return struct.pack("<%dh" % len(samples), *samples)


def summarize_rms(values: list[int]) -> str:
    if not values:
        return "n/a"
    ordered = sorted(values)
    p95_index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * 0.95) - 1))
    return (
        f"mean={statistics.mean(values):.1f} "
        f"median={statistics.median(values):.1f} "
        f"p95={ordered[p95_index]} "
        f"max={max(values)}"
    )


def play_once(
    *,
    settings: Settings,
    gain: float,
    audio_bytes: bytes,
    measure_mic: bool,
) -> list[int]:
    player = RawAplayPlayer(
        sample_rate=settings.realtime_sample_rate,
        playback_device=resolve_playback_device(settings.playback_device),
        output_gain=gain,
    )
    mic_rms: list[int] = []
    microphone: MicrophoneStream | None = None
    if measure_mic:
        microphone = MicrophoneStream(
            device_index=resolve_input_device_index(settings.audio_device_index),
            frame_length=settings.input_frame_length,
        )

    try:
        if microphone is not None:
            microphone.start()

        def playback() -> None:
            chunk_bytes = 2400 * 2
            for offset in range(0, len(audio_bytes), chunk_bytes):
                player.play(audio_bytes[offset : offset + chunk_bytes])
            player.drain()

        thread = threading.Thread(target=playback)
        thread.start()

        if microphone is not None:
            while thread.is_alive():
                frame = microphone.read_frame_bytes()
                mic_rms.append(audioop.rms(frame, 2))
            # One extra frame after playback to catch tail energy.
            mic_rms.append(audioop.rms(microphone.read_frame_bytes(), 2))

        thread.join()
        return mic_rms
    finally:
        if microphone is not None:
            microphone.stop()
        player.close()


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    settings = Settings.load()
    test_pcm = build_test_pcm(
        sample_rate=settings.realtime_sample_rate,
        duration_seconds=args.duration,
    )

    print(
        "Testing output gain with",
        f"playback_device={resolve_playback_device(settings.playback_device) or 'default'}",
        f"input_device_index={resolve_input_device_index(settings.audio_device_index)}",
        f"measure_mic={args.measure_mic}",
    )

    for index, gain in enumerate(args.gains, start=1):
        print(f"\n[{index}/{len(args.gains)}] gain={gain:.2f}")
        mic_rms = play_once(
            settings=settings,
            gain=gain,
            audio_bytes=test_pcm,
            measure_mic=args.measure_mic,
        )
        if args.measure_mic:
            print("mic_rms", summarize_rms(mic_rms))
        else:
            print("played")
        if index < len(args.gains) and args.pause > 0:
            time.sleep(args.pause)


if __name__ == "__main__":
    main()
