from __future__ import annotations

import audioop
import logging
import math
from pathlib import Path
import re
import struct
import subprocess
import threading
import time
import wave
from dataclasses import dataclass

from pvrecorder import PvRecorder


LOGGER = logging.getLogger(__name__)


@dataclass
class PCMResampler:
    source_rate: int
    target_rate: int
    sample_width: int = 2

    def __post_init__(self) -> None:
        self._state = None

    def convert(self, pcm_bytes: bytes) -> bytes:
        if self.source_rate == self.target_rate:
            return pcm_bytes
        converted, self._state = audioop.ratecv(
            pcm_bytes,
            self.sample_width,
            1,
            self.source_rate,
            self.target_rate,
            self._state,
        )
        return converted


def generate_sine_pcm(
    sample_rate: int,
    duration_ms: int,
    amplitude: int = 700,
    frequency_hz: float = 220.0,
) -> bytes:
    frame_count = max(1, int(sample_rate * duration_ms / 1000))
    samples = []
    for index in range(frame_count):
        sample = int(amplitude * math.sin(2.0 * math.pi * frequency_hz * index / sample_rate))
        samples.append(sample)
    return struct.pack("<%dh" % len(samples), *samples)


@dataclass
class InputAudioProcessor:
    noise_suppression_enabled: bool = False
    agc_enabled: bool = False
    noise_floor_margin: float = 1.8
    noise_suppression_min_rms: int = 25
    noise_suppression_attenuation: float = 0.35
    agc_target_rms: int = 1100
    agc_max_gain: float = 4.0
    agc_attack: float = 0.35
    agc_release: float = 0.08
    sample_width: int = 2

    def __post_init__(self) -> None:
        self._noise_floor_rms = 0.0
        self._current_gain = 1.0

    def reset(self) -> None:
        self._noise_floor_rms = 0.0
        self._current_gain = 1.0

    def process(self, pcm_bytes: bytes) -> bytes:
        if not pcm_bytes:
            return pcm_bytes

        rms = audioop.rms(pcm_bytes, self.sample_width)
        self._update_noise_floor(rms)

        processed = pcm_bytes
        if self.noise_suppression_enabled:
            processed = self._apply_noise_suppression(processed, rms)

        if self.agc_enabled:
            processed = self._apply_agc(processed)

        return processed

    def _update_noise_floor(self, rms: int) -> None:
        if rms <= 0:
            rms = 1
        if self._noise_floor_rms <= 0:
            self._noise_floor_rms = float(rms)
            return

        alpha = 0.05 if rms <= self._noise_floor_rms * self.noise_floor_margin else 0.005
        self._noise_floor_rms = (
            (1.0 - alpha) * self._noise_floor_rms + alpha * float(rms)
        )

    def _apply_noise_suppression(self, pcm_bytes: bytes, rms: int) -> bytes:
        threshold = max(
            self.noise_suppression_min_rms,
            int(self._noise_floor_rms * self.noise_floor_margin),
        )
        if rms >= threshold:
            return pcm_bytes
        return audioop.mul(pcm_bytes, self.sample_width, self.noise_suppression_attenuation)

    def _apply_agc(self, pcm_bytes: bytes) -> bytes:
        rms = audioop.rms(pcm_bytes, self.sample_width)
        if rms <= 0:
            target_gain = self.agc_max_gain
        else:
            target_gain = min(self.agc_target_rms / rms, self.agc_max_gain)

        if target_gain > self._current_gain:
            step = self.agc_attack
        else:
            step = self.agc_release
        self._current_gain += (target_gain - self._current_gain) * step

        if abs(self._current_gain - 1.0) < 0.02:
            return pcm_bytes
        return audioop.mul(pcm_bytes, self.sample_width, self._current_gain)


def resolve_input_device_index(configured_index: int) -> int:
    if configured_index >= 0:
        return configured_index

    devices = _safe_input_device_names()
    preferred_markers = ("google voicehat", "voicehat", "microphone", "mic", "usb")

    for index, name in enumerate(devices):
        normalized = name.lower()
        if any(marker in normalized for marker in preferred_markers):
            LOGGER.info("Auto-selected input device %d: %s", index, name)
            return index

    LOGGER.info("No preferred input device found; using configured default index %d", configured_index)
    return configured_index


def resolve_playback_device(configured_device: str) -> str | None:
    if configured_device and configured_device != "auto":
        return configured_device

    preferred_markers = ("google voicehat", "voicehat", "usb", "speaker")
    for option in list_playback_devices():
        normalized = option["label"].lower()
        if not any(marker in normalized for marker in preferred_markers):
            continue
        device = option["value"]
        LOGGER.info("Auto-selected playback device %s from line: %s", device, option["label"])
        return device

    LOGGER.info("No preferred playback device found; using ALSA default output")
    return None


def list_input_devices() -> list[dict[str, str]]:
    names = _safe_input_device_names()
    filtered = _filtered_input_device_entries(names)
    entries = filtered or list(enumerate(names))
    return [
        {"value": str(index), "label": name}
        for index, name in entries
    ]


def list_playback_devices() -> list[dict[str, str]]:
    try:
        result = subprocess.run(
            ["aplay", "-l"],
            capture_output=True,
            text=True,
            timeout=3,
            check=True,
        )
    except Exception:
        LOGGER.info("Could not inspect playback devices; using ALSA default output")
        return []
    return _parse_playback_device_lines(result.stdout)


def play_speaker_test(
    *,
    sample_rate: int,
    playback_device: str | None,
    cue_path: str | Path | None,
    gain: float,
) -> None:
    player = RawAplayPlayer(
        sample_rate=sample_rate,
        playback_device=playback_device,
        output_gain=1.0,
    )
    try:
        if cue_path and Path(cue_path).exists():
            player.play_wav_file(cue_path, blocking=True, gain=gain)
            return
        player.play(generate_sine_pcm(sample_rate=sample_rate, duration_ms=700, amplitude=1400, frequency_hz=660.0))
        player.drain()
    finally:
        player.close()


def sample_microphone_level(
    *,
    device_index: int,
    frame_length: int,
    duration_seconds: float = 1.5,
) -> dict[str, object]:
    stream = MicrophoneStream(device_index=device_index, frame_length=frame_length)
    peak_rms = 0
    total_rms = 0
    frame_count = 0
    started_at = time.monotonic()
    try:
        stream.start()
        while time.monotonic() - started_at < duration_seconds:
            frame = stream.read_frame_bytes()
            rms = audioop.rms(frame, 2)
            peak_rms = max(peak_rms, rms)
            total_rms += rms
            frame_count += 1
    finally:
        stream.stop()
    average_rms = 0 if frame_count == 0 else total_rms / frame_count
    return {
        "device_name": stream.selected_device_name or f"device_index={device_index}",
        "peak_rms": peak_rms,
        "average_rms": round(average_rms, 1),
        "detected_sound": peak_rms >= 45,
        "duration_seconds": duration_seconds,
    }


def _safe_input_device_names() -> list[str]:
    try:
        return list(PvRecorder.get_available_devices())
    except Exception:
        LOGGER.info("Could not inspect input devices", exc_info=True)
        return []


def _parse_playback_device_lines(stdout: str) -> list[dict[str, str]]:
    options: list[dict[str, str]] = []
    for line in stdout.splitlines():
        match = re.search(r"card (\d+): .*device (\d+):", line)
        if not match:
            continue
        options.append(
            {
                "value": f"plughw:{match.group(1)},{match.group(2)}",
                "label": line.strip(),
            }
        )
    return options


def _filtered_input_device_entries(names: list[str]) -> list[tuple[int, str]]:
    hidden_markers = (
        "discard all samples",
        "default audio device",
        "rate converter plugin",
        "jack audio connection kit",
        "open sound system",
        "pulseaudio sound server",
        "plugin using speex dsp",
        "plugin for channel upmix",
        "plugin for channel downmix",
    )
    preferred_markers = (
        "voicehat",
        "microphone",
        "mic",
        "usb",
        "snd_",
        "soundcard",
        "webcam",
        "input",
    )

    filtered: list[tuple[int, str]] = []
    seen_labels: set[str] = set()
    for index, name in enumerate(names):
        normalized = name.strip().lower()
        if not normalized:
            continue
        if any(marker in normalized for marker in hidden_markers):
            continue
        if preferred_markers and not any(marker in normalized for marker in preferred_markers):
            continue
        if normalized in seen_labels:
            continue
        seen_labels.add(normalized)
        filtered.append((index, name))
    return filtered


class MicrophoneStream:
    def __init__(
        self,
        device_index: int,
        frame_length: int,
        processor: InputAudioProcessor | None = None,
    ) -> None:
        self._device_index = device_index
        self._frame_length = frame_length
        self._processor = processor
        self._recorder: PvRecorder | None = None

    def start(self) -> None:
        if self._recorder is not None:
            return
        self._recorder = PvRecorder(
            device_index=self._device_index,
            frame_length=self._frame_length,
        )
        self._recorder.start()
        if self._processor is not None:
            self._processor.reset()
        LOGGER.info("Microphone started on device: %s", self._recorder.selected_device)

    def read_frame_bytes(self) -> bytes:
        if self._recorder is None:
            raise RuntimeError("MicrophoneStream is not started")
        pcm = self._recorder.read()
        pcm_bytes = struct.pack("<%dh" % len(pcm), *pcm)
        if self._processor is None:
            return pcm_bytes
        return self._processor.process(pcm_bytes)

    def stop(self) -> None:
        if self._recorder is None:
            return
        self._recorder.stop()
        self._recorder.delete()
        self._recorder = None
        LOGGER.info("Microphone stopped")

    @property
    def selected_device_name(self) -> str:
        if self._recorder is None:
            return ""
        return str(self._recorder.selected_device)


class RawAplayPlayer:
    def __init__(
        self,
        sample_rate: int,
        playback_device: str | None = None,
        output_gain: float = 1.0,
    ) -> None:
        self._sample_rate = sample_rate
        self._playback_device = playback_device
        self._output_gain = output_gain
        self._process: subprocess.Popen[bytes] | None = None
        self._lock = threading.Lock()
        self._playback_available_at = 0.0
        self._max_buffer_seconds = 0.2

    def _spawn(self) -> None:
        if self._process is not None and self._process.poll() is None:
            return
        cmd = [
            "aplay",
            "-q",
            "-t",
            "raw",
            "-f",
            "S16_LE",
            "-r",
            str(self._sample_rate),
            "-c",
            "1",
        ]
        if self._playback_device:
            cmd.extend(["-D", self._playback_device])
        self._process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def play(self, audio_bytes: bytes) -> None:
        self._play_with_gain(audio_bytes, gain=self._output_gain)

    def _play_with_gain(self, audio_bytes: bytes, gain: float) -> None:
        if not audio_bytes:
            return
        with self._lock:
            self._spawn()
            assert self._process is not None
            if self._process.stdin is None:
                raise RuntimeError("aplay stdin is not available")
            scaled_bytes = self._apply_gain(audio_bytes, gain)
            chunk_duration_seconds = len(scaled_bytes) / (2 * self._sample_rate)
            now = time.monotonic()
            if self._playback_available_at <= 0:
                self._playback_available_at = now
            backlog_seconds = self._playback_available_at - now
            if backlog_seconds > self._max_buffer_seconds:
                time.sleep(backlog_seconds - self._max_buffer_seconds)
                now = time.monotonic()
            try:
                self._process.stdin.write(scaled_bytes)
                self._process.stdin.flush()
            except BrokenPipeError:
                LOGGER.warning("Playback process closed unexpectedly; restarting")
                self._shutdown_locked(force=True)
                self._spawn()
                assert self._process is not None and self._process.stdin is not None
                self._process.stdin.write(scaled_bytes)
                self._process.stdin.flush()
            self._playback_available_at = max(now, self._playback_available_at) + chunk_duration_seconds

    def interrupt(self) -> None:
        with self._lock:
            self._shutdown_locked(force=True)

    def drain(self) -> None:
        with self._lock:
            self._shutdown_locked(force=False)

    def finish_current_playback(
        self,
        *,
        grace_seconds: float = 0.08,
        max_wait_seconds: float = 0.75,
    ) -> None:
        with self._lock:
            if self._process is None:
                return
            remaining_seconds = max(0.0, self._playback_available_at - time.monotonic())
        wait_seconds = min(max_wait_seconds, remaining_seconds + grace_seconds)
        if wait_seconds > 0:
            time.sleep(wait_seconds)
        with self._lock:
            self._shutdown_locked(force=False)

    def close(self) -> None:
        with self._lock:
            self._shutdown_locked(force=False)

    def play_wav_file(
        self,
        path: str | Path,
        blocking: bool = True,
        gain: float | None = None,
    ) -> None:
        wav_path = Path(path)
        effective_gain = self._output_gain if gain is None else gain
        LOGGER.info(
            "Playing cue wav: %s (blocking=%s gain=%.2f)",
            wav_path,
            blocking,
            effective_gain,
        )
        with wave.open(str(wav_path), "rb") as wav_file:
            sample_rate = wav_file.getframerate()
            sample_width = wav_file.getsampwidth()
            channels = wav_file.getnchannels()
            audio_bytes = wav_file.readframes(wav_file.getnframes())

        if channels == 2:
            audio_bytes = audioop.tomono(audio_bytes, sample_width, 0.5, 0.5)
            channels = 1
        elif channels != 1:
            raise RuntimeError(f"Unsupported cue channel count: {channels}")

        if sample_width != 2:
            audio_bytes = audioop.lin2lin(audio_bytes, sample_width, 2)
            sample_width = 2

        if sample_rate != self._sample_rate:
            audio_bytes, _ = audioop.ratecv(
                audio_bytes,
                sample_width,
                channels,
                sample_rate,
                self._sample_rate,
                None,
            )

        if blocking:
            self._play_with_gain(audio_bytes, gain=effective_gain)
            self.drain()
            LOGGER.info("Cue playback finished: %s", wav_path)
            return

        threading.Thread(
            target=self._play_wav_async,
            args=(audio_bytes, effective_gain),
            daemon=True,
        ).start()

    def _play_wav_async(self, audio_bytes: bytes, gain: float) -> None:
        try:
            self._play_with_gain(audio_bytes, gain=gain)
            self.drain()
        except Exception:
            LOGGER.exception("Failed to play async wav cue")

    def _apply_gain(self, audio_bytes: bytes, gain: float) -> bytes:
        if gain == 1.0:
            return audio_bytes
        return audioop.mul(audio_bytes, 2, gain)

    def _shutdown_locked(self, force: bool) -> None:
        if self._process is None:
            return
        try:
            if self._process.stdin is not None and not self._process.stdin.closed:
                self._process.stdin.close()
        except BrokenPipeError:
            pass
        if force:
            self._process.terminate()
        try:
            self._process.wait(timeout=0.5 if force else 5.0)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait(timeout=1.0)
        self._process = None
        self._playback_available_at = 0.0
