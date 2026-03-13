from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from realtime.snowman_realtime.assistant import SnowmanRealtimeAssistant
from realtime.snowman_realtime.memory import DEFAULT_RECENT_SESSION_LIMIT, MemoryStore
from realtime.snowman_realtime.recent_conversation import (
    SessionTurnBuffer,
    build_recent_session_record,
    compact_recent_conversation,
)


class SessionTurnBufferTests(unittest.TestCase):
    def test_session_turn_buffer_collects_turns_and_metadata(self) -> None:
        buffer = SessionTurnBuffer()
        buffer.record_session_started("sess_123")
        buffer.append_user_text("Who is Mira?")
        buffer.record_tool_name("profile_memory_get")
        buffer.append_assistant_text("Mira is your daughter.")

        snapshot = buffer.snapshot()

        self.assertEqual(snapshot.session_id, "sess_123")
        self.assertEqual(
            snapshot.turns,
            (
                {"role": "user", "text": "Who is Mira?"},
                {"role": "assistant", "text": "Mira is your daughter."},
            ),
        )
        self.assertEqual(snapshot.tool_names, ("profile_memory_get",))
        self.assertTrue(snapshot.has_user_content())

    def test_session_turn_buffer_is_thread_safe_for_concurrent_appends(self) -> None:
        buffer = SessionTurnBuffer()

        def append_many() -> None:
            for _ in range(100):
                buffer.append_user_text("hello")

        threads = [threading.Thread(target=append_many) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        snapshot = buffer.snapshot()
        self.assertEqual(len(snapshot.turns), 400)

    def test_session_turn_buffer_falls_back_to_generated_session_id(self) -> None:
        buffer = SessionTurnBuffer()
        snapshot = buffer.snapshot()

        self.assertTrue(snapshot.session_id.startswith("sess_"))
        self.assertTrue(snapshot.started_at.endswith("Z"))


class RecentConversationMemoryStoreTests(unittest.TestCase):
    def test_append_recent_session_writes_single_jsonl_line(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(Path(temp_dir))
            store.append_recent_session(
                {
                    "session_id": "sess_1",
                    "started_at": "2026-03-13T12:00:00Z",
                    "ended_at": "2026-03-13T12:00:10Z",
                    "source": "voice",
                    "summary": "User asked about Mira.",
                    "language": "en",
                    "entities": ["Mira"],
                    "topics": ["family"],
                }
            )

            raw = store.paths.recent_sessions_path.read_text(encoding="utf-8")
            self.assertEqual(len(raw.splitlines()), 1)
            self.assertEqual(store.read_recent_sessions()[0]["session_id"], "sess_1")

    def test_append_recent_session_prunes_to_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(Path(temp_dir))
            for index in range(DEFAULT_RECENT_SESSION_LIMIT + 3):
                store.append_recent_session(
                    {
                        "session_id": f"sess_{index}",
                        "started_at": "2026-03-13T12:00:00Z",
                        "ended_at": "2026-03-13T12:00:10Z",
                        "source": "voice",
                        "summary": f"Summary {index}",
                    }
                )

            records = store.read_recent_sessions()
            self.assertEqual(len(records), DEFAULT_RECENT_SESSION_LIMIT)
            self.assertEqual(records[0]["session_id"], "sess_3")

    def test_read_recent_sessions_discards_malformed_lines(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(Path(temp_dir))
            store.ensure_initialized()
            store.paths.recent_sessions_path.write_text(
                '{"session_id":"sess_ok","summary":"ok"}\nnot-json\n{"session_id":"sess_2","summary":"two"}\n',
                encoding="utf-8",
            )

            records = store.read_recent_sessions()
            self.assertEqual([record["session_id"] for record in records], ["sess_ok", "sess_2"])


class RecentConversationCompactTests(unittest.TestCase):
    def test_compact_recent_conversation_parses_json_object_response(self) -> None:
        settings = SimpleNamespace(openai_api_key="test-key")
        buffer = SessionTurnBuffer()
        buffer.record_session_started("sess_123")
        buffer.append_user_text("Who is Mira?")
        buffer.append_assistant_text("Mira is your daughter.")
        snapshot = buffer.snapshot()

        class _FakeResponse:
            def read(self) -> bytes:
                return json.dumps(
                    {
                        "choices": [
                            {
                                "message": {
                                    "content": json.dumps(
                                        {
                                            "summary": "User asked who Mira is.",
                                            "language": "en",
                                            "entities": ["Mira"],
                                            "topics": ["family"],
                                        }
                                    )
                                }
                            }
                        ]
                    }
                ).encode("utf-8")

            def __enter__(self) -> "_FakeResponse":
                return self

            def __exit__(self, exc_type, exc, tb) -> None:
                return None

        def fake_urlopen(req, timeout=15):
            self.assertEqual(timeout, 15)
            self.assertEqual(req.full_url, "https://api.openai.com/v1/chat/completions")
            body = json.loads(req.data.decode("utf-8"))
            self.assertEqual(body["response_format"], {"type": "json_object"})
            return _FakeResponse()

        with patch("realtime.snowman_realtime.recent_conversation.request.urlopen", fake_urlopen):
            compact = compact_recent_conversation(settings, snapshot)

        self.assertEqual(compact["summary"], "User asked who Mira is.")
        self.assertEqual(compact["entities"], ["Mira"])

    def test_build_recent_session_record_includes_required_fields(self) -> None:
        buffer = SessionTurnBuffer()
        buffer.record_session_started("sess_123")
        buffer.append_user_text("Hello")
        snapshot = buffer.snapshot()

        record = build_recent_session_record(
            snapshot,
            {
                "summary": "User said hello.",
                "language": "en",
                "entities": [],
                "topics": ["greeting"],
            },
            ended_at="2026-03-13T12:00:10Z",
        )

        self.assertEqual(record["session_id"], "sess_123")
        self.assertEqual(record["ended_at"], "2026-03-13T12:00:10Z")
        self.assertEqual(record["source"], "voice")


class RecentConversationAssistantPersistenceTests(unittest.TestCase):
    def test_persist_recent_conversation_skips_empty_transcript(self) -> None:
        assistant = SnowmanRealtimeAssistant.__new__(SnowmanRealtimeAssistant)
        assistant._settings = SimpleNamespace(memory_enabled=True, memory_dir="/tmp/unused", openai_api_key="test")

        buffer = SessionTurnBuffer()
        with patch("realtime.snowman_realtime.assistant.MemoryStore.from_path") as store_cls:
            assistant._persist_recent_conversation(buffer)
        store_cls.assert_not_called()

    def test_persist_recent_conversation_appends_record(self) -> None:
        assistant = SnowmanRealtimeAssistant.__new__(SnowmanRealtimeAssistant)
        assistant._settings = SimpleNamespace(memory_enabled=True, memory_dir="/tmp/memory", openai_api_key="test")
        buffer = SessionTurnBuffer()
        buffer.record_session_started("sess_123")
        buffer.append_user_text("Who is Mira?")

        fake_store = SimpleNamespace(append_recent_session=lambda record: setattr(fake_store, "record", record))
        with patch(
            "realtime.snowman_realtime.assistant.compact_recent_conversation",
            return_value={
                "summary": "User asked who Mira is.",
                "language": "en",
                "entities": ["Mira"],
                "topics": ["family"],
            },
        ), patch(
            "realtime.snowman_realtime.assistant.MemoryStore.from_path",
            return_value=fake_store,
        ):
            assistant._persist_recent_conversation(buffer)

        self.assertEqual(fake_store.record["session_id"], "sess_123")
        self.assertEqual(fake_store.record["summary"], "User asked who Mira is.")

    def test_persist_recent_conversation_swallows_compact_failure(self) -> None:
        assistant = SnowmanRealtimeAssistant.__new__(SnowmanRealtimeAssistant)
        assistant._settings = SimpleNamespace(memory_enabled=True, memory_dir="/tmp/memory", openai_api_key="test")
        buffer = SessionTurnBuffer()
        buffer.record_session_started("sess_123")
        buffer.append_user_text("Who is Mira?")

        with patch(
            "realtime.snowman_realtime.assistant.compact_recent_conversation",
            side_effect=RuntimeError("boom"),
        ):
            assistant._persist_recent_conversation(buffer)


if __name__ == "__main__":
    unittest.main()
