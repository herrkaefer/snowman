#!/usr/bin/env python3

from __future__ import annotations

import argparse
import base64
import json
import logging
import math
import struct
import time
from collections import Counter

import websocket

from snowman_realtime.audio import PCMResampler
from snowman_realtime.config import Settings, configure_logging


LOGGER = logging.getLogger("probe_realtime_connect")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Probe OpenAI Realtime connection success rate without the full voice loop."
    )
    parser.add_argument("--attempts", type=int, default=20, help="Number of attempts to run.")
    parser.add_argument("--delay", type=float, default=0.5, help="Delay between attempts in seconds.")
    parser.add_argument(
        "--with-audio",
        action="store_true",
        help="Also append synthetic audio, commit, and create a response.",
    )
    parser.add_argument(
        "--audio-ms",
        type=int,
        default=250,
        help="Synthetic audio length in milliseconds for --with-audio.",
    )
    parser.add_argument(
        "--response-wait",
        type=float,
        default=5.0,
        help="How long to wait for a response when --with-audio is enabled.",
    )
    parser.add_argument(
        "--upload-mode",
        choices=("single", "chunked-burst", "chunked-paced"),
        default="single",
        help="How to upload synthetic audio when --with-audio is enabled.",
    )
    parser.add_argument(
        "--frame-length",
        type=int,
        default=512,
        help="Source frame length for chunked upload modes.",
    )
    parser.add_argument(
        "--source-rate",
        type=int,
        default=16000,
        help="Source sample rate for chunked upload modes.",
    )
    parser.add_argument(
        "--pace-ms",
        type=float,
        default=0.0,
        help="Inter-chunk delay for chunked-paced mode; 0 means derive from frame length.",
    )
    return parser


def make_session_update(settings: Settings) -> dict[str, object]:
    return {
        "type": "session.update",
        "session": {
            "type": "realtime",
            "model": settings.openai_realtime_model,
            "output_modalities": ["audio"],
            "instructions": settings.system_prompt,
            "audio": {
                "input": {
                    "format": {
                        "type": "audio/pcm",
                        "rate": settings.realtime_sample_rate,
                    },
                    "turn_detection": None,
                },
                "output": {
                    "format": {
                        "type": "audio/pcm",
                        "rate": settings.realtime_sample_rate,
                    },
                    "voice": settings.openai_voice,
                },
            },
        },
    }


def make_synthetic_audio(sample_rate: int, duration_ms: int) -> bytes:
    frame_count = max(1, int(sample_rate * duration_ms / 1000))
    amplitude = 700
    frequency_hz = 220.0
    samples = []
    for index in range(frame_count):
        sample = int(amplitude * math.sin(2.0 * math.pi * frequency_hz * index / sample_rate))
        samples.append(sample)
    return struct.pack("<%dh" % len(samples), *samples)


def chunk_source_audio(
    audio_bytes: bytes,
    source_rate: int,
    frame_length: int,
) -> list[bytes]:
    bytes_per_frame = frame_length * 2
    if bytes_per_frame <= 0:
        return [audio_bytes]

    chunk_count = max(1, len(audio_bytes) // bytes_per_frame)
    chunks = [
        audio_bytes[offset : offset + bytes_per_frame]
        for offset in range(0, len(audio_bytes), bytes_per_frame)
    ]
    if not chunks:
        return [audio_bytes]

    expected_chunk_size = bytes_per_frame
    if len(chunks[-1]) < expected_chunk_size:
        chunks[-1] = chunks[-1] + (b"\x00" * (expected_chunk_size - len(chunks[-1])))
    return chunks


def upload_synthetic_audio(
    sock: websocket.WebSocket,
    settings: Settings,
    audio_ms: int,
    upload_mode: str,
    frame_length: int,
    source_rate: int,
    pace_ms: float,
) -> None:
    if upload_mode == "single":
        audio_bytes = make_synthetic_audio(settings.realtime_sample_rate, audio_ms)
        sock.send(
            json.dumps(
                {
                    "type": "input_audio_buffer.append",
                    "audio": base64.b64encode(audio_bytes).decode("ascii"),
                }
            )
        )
        return

    source_audio = make_synthetic_audio(source_rate, audio_ms)
    source_chunks = chunk_source_audio(
        audio_bytes=source_audio,
        source_rate=source_rate,
        frame_length=frame_length,
    )
    resampler = PCMResampler(source_rate=source_rate, target_rate=settings.realtime_sample_rate)

    if upload_mode == "chunked-paced":
        per_chunk_delay = pace_ms / 1000.0
        if per_chunk_delay <= 0:
            per_chunk_delay = frame_length / float(source_rate)
    else:
        per_chunk_delay = 0.0

    for index, chunk in enumerate(source_chunks):
        converted = resampler.convert(chunk)
        sock.send(
            json.dumps(
                {
                    "type": "input_audio_buffer.append",
                    "audio": base64.b64encode(converted).decode("ascii"),
                }
            )
        )
        if per_chunk_delay > 0 and index < len(source_chunks) - 1:
            time.sleep(per_chunk_delay)


def recv_json(sock: websocket.WebSocket) -> dict[str, object]:
    raw_message = sock.recv()
    if not raw_message:
        return {}
    return json.loads(raw_message)


def wait_for_message_type(
    sock: websocket.WebSocket,
    target_types: set[str],
    deadline: float,
) -> dict[str, object]:
    while time.monotonic() < deadline:
        remaining = max(0.05, deadline - time.monotonic())
        sock.settimeout(min(1.0, remaining))
        message = recv_json(sock)
        message_type = str(message.get("type", ""))
        if message_type in target_types:
            return message
        if message_type == "error":
            error = message.get("error") or {}
            if isinstance(error, dict):
                error_message = str(error.get("message", "unknown realtime error"))
            else:
                error_message = str(error)
            raise RuntimeError(error_message)
    raise TimeoutError(f"Timed out waiting for {sorted(target_types)}")


def observe_post_update(sock: websocket.WebSocket, grace_seconds: float) -> None:
    deadline = time.monotonic() + grace_seconds
    while time.monotonic() < deadline:
        remaining = max(0.05, deadline - time.monotonic())
        sock.settimeout(min(0.1, remaining))
        try:
            message = recv_json(sock)
        except websocket.WebSocketTimeoutException:
            continue

        message_type = str(message.get("type", ""))
        if message_type == "session.updated":
            return
        if message_type == "error":
            error = message.get("error") or {}
            if isinstance(error, dict):
                error_message = str(error.get("message", "unknown realtime error"))
            else:
                error_message = str(error)
            raise RuntimeError(error_message)
    return


def run_attempt(
    settings: Settings,
    with_audio: bool,
    audio_ms: int,
    response_wait: float,
    upload_mode: str,
    frame_length: int,
    source_rate: int,
    pace_ms: float,
) -> tuple[bool, str, float]:
    attempt_started_at = time.monotonic()
    headers = [f"Authorization: Bearer {settings.openai_api_key}"]
    sock: websocket.WebSocket | None = None

    try:
        sock = websocket.create_connection(
            settings.realtime_ws_url,
            header=headers,
            timeout=settings.realtime_connect_timeout_seconds,
            enable_multithread=False,
        )
        wait_for_message_type(
            sock,
            {"session.created"},
            deadline=time.monotonic() + settings.realtime_session_created_timeout_seconds,
        )
        sock.send(json.dumps(make_session_update(settings)))
        observe_post_update(sock, settings.realtime_post_update_grace_seconds)

        if not with_audio:
            return True, "connected", time.monotonic() - attempt_started_at

        upload_synthetic_audio(
            sock=sock,
            settings=settings,
            audio_ms=audio_ms,
            upload_mode=upload_mode,
            frame_length=frame_length,
            source_rate=source_rate,
            pace_ms=pace_ms,
        )
        sock.send(json.dumps({"type": "input_audio_buffer.commit"}))
        sock.send(
            json.dumps(
                {
                    "type": "response.create",
                    "response": {
                        "instructions": "Reply with exactly one short sentence.",
                        "max_output_tokens": 64,
                    },
                }
            )
        )
        wait_for_message_type(
            sock,
            {"response.output_audio.done", "response.audio.done", "response.done"},
            deadline=time.monotonic() + response_wait,
        )
        return True, "response_ok", time.monotonic() - attempt_started_at
    except TimeoutError:
        return False, "timeout", time.monotonic() - attempt_started_at
    except websocket.WebSocketConnectionClosedException:
        return False, "socket_closed", time.monotonic() - attempt_started_at
    except Exception as exc:
        return False, exc.__class__.__name__ + f": {exc}", time.monotonic() - attempt_started_at
    finally:
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    settings = Settings.load()
    configure_logging(settings.log_level)

    if args.with_audio:
        mode_label = f"connect+audio:{args.upload_mode}"
    else:
        mode_label = "connect-only"
    LOGGER.info(
        "Starting Realtime probe: attempts=%d delay=%.2fs mode=%s audio_ms=%d",
        args.attempts,
        args.delay,
        mode_label,
        args.audio_ms,
    )

    results: Counter[str] = Counter()
    durations: list[float] = []

    for attempt in range(1, args.attempts + 1):
        ok, outcome, duration = run_attempt(
            settings=settings,
            with_audio=args.with_audio,
            audio_ms=args.audio_ms,
            response_wait=args.response_wait,
            upload_mode=args.upload_mode,
            frame_length=args.frame_length,
            source_rate=args.source_rate,
            pace_ms=args.pace_ms,
        )
        durations.append(duration)
        results[outcome] += 1
        LOGGER.info(
            "Attempt %d/%d: ok=%s outcome=%s duration=%.2fs",
            attempt,
            args.attempts,
            ok,
            outcome,
            duration,
        )
        if attempt < args.attempts:
            time.sleep(args.delay)

    success_count = sum(
        count for outcome, count in results.items() if outcome in {"connected", "response_ok"}
    )
    average_duration = sum(durations) / len(durations) if durations else 0.0

    print()
    print("Probe summary")
    print(f"  mode: {mode_label}")
    print(f"  attempts: {args.attempts}")
    print(f"  successes: {success_count}/{args.attempts}")
    print(f"  average_duration: {average_duration:.2f}s")
    for outcome, count in sorted(results.items()):
        print(f"  {outcome}: {count}")


if __name__ == "__main__":
    main()
