from __future__ import annotations

import audioop
import logging
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
    def __init__(self, sample_rate: int) -> None:
        self._sample_rate = sample_rate
        self._process: subprocess.Popen[bytes] | None = None
        self._lock = threading.Lock()

    def _spawn(self) -> None:
        if self._process is not None and self._process.poll() is None:
            return
        self._process = subprocess.Popen(
            [
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
            ],
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
            try:
                self._process.stdin.write(audio_bytes)
                self._process.stdin.flush()
            except BrokenPipeError:
                LOGGER.warning("Playback process closed unexpectedly; restarting")
                self._shutdown_locked(force=True)
                self._spawn()
                assert self._process is not None and self._process.stdin is not None
                self._process.stdin.write(audio_bytes)
                self._process.stdin.flush()

    def interrupt(self) -> None:
        with self._lock:
            self._shutdown_locked(force=True)

    def close(self) -> None:
        with self._lock:
            self._shutdown_locked(force=False)

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
            self._process.wait(timeout=0.5 if force else 1.0)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait(timeout=1.0)
        self._process = None
