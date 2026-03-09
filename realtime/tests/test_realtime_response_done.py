from __future__ import annotations

import unittest
from types import SimpleNamespace

from realtime.snowman_realtime.events import ResponseDone, ToolCallRequested
from realtime.snowman_realtime.realtime_client import RealtimeVoiceAgent


class RealtimeResponseDoneTests(unittest.TestCase):
    def test_response_done_with_tool_call_emits_tool_request_and_done_event(self) -> None:
        events: list[object] = []
        agent = RealtimeVoiceAgent(SimpleNamespace(), events.append, tools=[])

        agent._handle_message(
            {
                "type": "response.done",
                "response": {
                    "id": "resp_tool",
                    "status": "completed",
                    "output": [
                        {
                            "type": "function_call",
                            "call_id": "call_123",
                            "name": "web_search",
                            "arguments": '{"query":"oil price"}',
                        }
                    ],
                },
            }
        )

        self.assertEqual(len(events), 2)
        self.assertEqual(
            events[0],
            ToolCallRequested(
                call_id="call_123",
                name="web_search",
                arguments_json='{"query":"oil price"}',
            ),
        )
        self.assertEqual(
            events[1],
            ResponseDone(
                response_id="resp_tool",
                tool_call_count=1,
                status="completed",
                reason=None,
            ),
        )

    def test_response_done_without_tool_call_emits_done_event_only(self) -> None:
        events: list[object] = []
        agent = RealtimeVoiceAgent(SimpleNamespace(), events.append, tools=[])

        agent._handle_message(
            {
                "type": "response.done",
                "response": {
                    "id": "resp_final",
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "content": [],
                        }
                    ],
                },
            }
        )

        self.assertEqual(
            events,
            [
                ResponseDone(
                    response_id="resp_final",
                    tool_call_count=0,
                    status="completed",
                    reason=None,
                )
            ],
        )

    def test_incomplete_max_output_tokens_emits_soft_done_event(self) -> None:
        events: list[object] = []
        agent = RealtimeVoiceAgent(SimpleNamespace(), events.append, tools=[])

        agent._handle_message(
            {
                "type": "response.done",
                "response": {
                    "id": "resp_truncated",
                    "status": "incomplete",
                    "status_details": {
                        "reason": "max_output_tokens",
                    },
                    "output": [
                        {
                            "type": "message",
                            "content": [],
                        }
                    ],
                },
            }
        )

        self.assertEqual(
            events,
            [
                ResponseDone(
                    response_id="resp_truncated",
                    tool_call_count=0,
                    status="incomplete",
                    reason="max_output_tokens",
                )
            ],
        )


if __name__ == "__main__":
    unittest.main()
