from __future__ import annotations

import unittest

from realtime.snowman_realtime.assistant import SnowmanRealtimeAssistant


class EndPhraseDetectionTests(unittest.TestCase):
    def test_exact_end_phrase_matches(self) -> None:
        assistant = SnowmanRealtimeAssistant.__new__(SnowmanRealtimeAssistant)

        self.assertTrue(assistant._is_end_transcript("thank you"))
        self.assertTrue(assistant._is_end_transcript("Thanks"))
        self.assertTrue(assistant._is_end_transcript("就这样吧"))

    def test_embedded_end_phrase_does_not_match(self) -> None:
        assistant = SnowmanRealtimeAssistant.__new__(SnowmanRealtimeAssistant)

        self.assertFalse(
            assistant._is_end_transcript(
                "Can you explain why people say thank you very much indeed here?"
            )
        )
        self.assertFalse(
            assistant._is_end_transcript(
                "You got it. Thank you very much indeed."
            )
        )
        self.assertFalse(
            assistant._is_end_transcript(
                "谢谢这个我懂了，但是我还有一个问题"
            )
        )


if __name__ == "__main__":
    unittest.main()
