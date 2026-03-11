from __future__ import annotations

import unittest
from unittest.mock import patch

from realtime.snowman_realtime.audio import _filtered_input_device_entries, _parse_playback_device_lines, list_input_devices


class AudioDeviceTests(unittest.TestCase):
    def test_parse_playback_device_lines_extracts_hw_ids(self) -> None:
        stdout = """
card 1: Device [USB Audio Device], device 0: USB Audio [USB Audio]
card 2: sndrpigooglevoi [snd_rpi_googlevoicehat_soundcar], device 0: Google voiceHAT SoundCard HiFi voicehat-hifi-0 [Google voiceHAT SoundCard HiFi voicehat-hifi-0]
"""

        self.assertEqual(
            _parse_playback_device_lines(stdout),
            [
                {
                    "value": "plughw:1,0",
                    "label": "card 1: Device [USB Audio Device], device 0: USB Audio [USB Audio]",
                },
                {
                    "value": "plughw:2,0",
                    "label": "card 2: sndrpigooglevoi [snd_rpi_googlevoicehat_soundcar], device 0: Google voiceHAT SoundCard HiFi voicehat-hifi-0 [Google voiceHAT SoundCard HiFi voicehat-hifi-0]",
                },
            ],
        )

    def test_list_input_devices_wraps_pvrecorder_names(self) -> None:
        with patch(
            "realtime.snowman_realtime.audio.PvRecorder.get_available_devices",
            return_value=["Built-in Mic", "USB Mic"],
        ):
            self.assertEqual(
                list_input_devices(),
                [
                    {"value": "0", "label": "Built-in Mic"},
                    {"value": "1", "label": "USB Mic"},
                ],
            )

    def test_filtered_input_device_entries_removes_virtual_alsa_nodes(self) -> None:
        entries = _filtered_input_device_entries(
            [
                "Discard all samples (playback) or generate zero samples (capture)",
                "Default Audio Device",
                "PulseAudio Sound Server",
                "snd_rpi_googlevoicehat_soundcar, Google voiceHAT SoundCard HiFi voicehat-hifi-0",
            ]
        )

        self.assertEqual(
            entries,
            [(3, "snd_rpi_googlevoicehat_soundcar, Google voiceHAT SoundCard HiFi voicehat-hifi-0")],
        )


if __name__ == "__main__":
    unittest.main()
