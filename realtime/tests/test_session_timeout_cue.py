from __future__ import annotations

import tempfile
import threading
import unittest
from types import SimpleNamespace

from realtime.snowman_realtime.assistant import SnowmanRealtimeAssistant


class _DummyWakeDetector:
    def stop(self) -> None:
        return


class _DummyStatusLed:
    def user_can_speak(self) -> None:
        return

    def processing(self) -> None:
        return

    def off(self) -> None:
        return


class _DummyPlayer:
    def __init__(self) -> None:
        self.played_wavs: list[str] = []

    def play_wav_file(self, path: str, *, blocking: bool, gain: float) -> None:
        self.played_wavs.append(path)

    def close(self) -> None:
        return


class _DummyMicrophone:
    def stop(self) -> None:
        return


class InitialTurnTimeoutCueTests(unittest.TestCase):
    def test_initial_turn_timeout_plays_session_end_cue(self) -> None:
        assistant = SnowmanRealtimeAssistant.__new__(SnowmanRealtimeAssistant)
        player = _DummyPlayer()
        microphone = _DummyMicrophone()

        with tempfile.NamedTemporaryFile(suffix=".wav") as cue_file:
            assistant._settings = SimpleNamespace(
                session_max_turns=0,
                ready_cue_path="/nonexistent-ready.wav",
                cue_output_gain=0.65,
                recording_start_timeout=8.0,
                session_followup_timeout=6.0,
                session_end_cue_path=cue_file.name,
            )
            assistant._wake_detector = _DummyWakeDetector()
            assistant._status_led = _DummyStatusLed()
            assistant._tool_registry = SimpleNamespace(tools=[])
            assistant._health_state = "starting"
            assistant._health_state_lock = threading.Lock()

            assistant._build_session_io = lambda: (player, microphone, None)
            assistant._capture_utterance = lambda *args, **kwargs: []
            assistant._play_failure_cue = lambda player: None

            assistant._run_session_window()

        self.assertEqual(player.played_wavs, [cue_file.name])


if __name__ == "__main__":
    unittest.main()
