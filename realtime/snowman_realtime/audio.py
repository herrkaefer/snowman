from __future__ import annotations

import audioop
import logging
from pathlib import Path
import re
import struct
import subprocess
import threading
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


def resolve_input_device_index(configured_index: int) -> int:
    if configured_index >= 0:
        return configured_index

    devices = PvRecorder.get_available_devices()
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
        return None

    preferred_markers = ("google voicehat", "voicehat", "usb", "speaker")
    for line in result.stdout.splitlines():
        normalized = line.lower()
        if not any(marker in normalized for marker in preferred_markers):
            continue
        match = re.search(r"card (\d+): .*device (\d+):", line)
        if match:
            device = f"plughw:{match.group(1)},{match.group(2)}"
            LOGGER.info("Auto-selected playback device %s from line: %s", device, line.strip())
            return device

    LOGGER.info("No preferred playback device found; using ALSA default output")
    return None


class MicrophoneStream:
    def __init__(self, device_index: int, frame_length: int) -> None:
        self._device_index = device_index
        self._frame_length = frame_length
        self._recorder: PvRecorder | None = None

    def start(self) -> None:
        if self._recorder is not None:
            return
        self._recorder = PvRecorder(
            device_index=self._device_index,
            frame_length=self._frame_length,
        )
        self._recorder.start()
        LOGGER.info("Microphone started on device: %s", self._recorder.selected_device)

    def read_frame_bytes(self) -> bytes:
        if self._recorder is None:
            raise RuntimeError("MicrophoneStream is not started")
        pcm = self._recorder.read()
        return struct.pack("<%dh" % len(pcm), *pcm)

    def stop(self) -> None:
        if self._recorder is None:
            return
        self._recorder.stop()
        self._recorder.delete()
        self._recorder = None
        LOGGER.info("Microphone stopped")


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
        if not audio_bytes:
            return
        with self._lock:
            self._spawn()
            assert self._process is not None
            if self._process.stdin is None:
                raise RuntimeError("aplay stdin is not available")
            scaled_bytes = audio_bytes
            if self._output_gain != 1.0:
                scaled_bytes = audioop.mul(audio_bytes, 2, self._output_gain)
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

    def interrupt(self) -> None:
        with self._lock:
            self._shutdown_locked(force=True)

    def drain(self) -> None:
        with self._lock:
            self._shutdown_locked(force=False)

    def close(self) -> None:
        with self._lock:
            self._shutdown_locked(force=False)

    def play_wav_file(self, path: str | Path, blocking: bool = True) -> None:
        wav_path = str(path)
        cmd = ["aplay", "-q"]
        if self._playback_device:
            cmd.extend(["-D", self._playback_device])
        cmd.append(wav_path)
        if blocking:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

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
