"""Run with: python3 -m unittest discover -s tests -p 'test_*.py'."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "desktop"))
import history
import store
import transport


class SharedHistoryTests(unittest.TestCase):
    def test_transcript_pages_keep_order_and_interruption(self):
        def request(base, action, token, params):
            after = params["after_id"]
            return {"conversation": {"title": "Hej", "language_tag": "sv"},
                    "turns": [{"id": "1" if after == "0" else "2", "client_turn_id": after,
                               "question_text": "Hej", "reply_text": "Svar",
                               "reply_status": "complete" if after == "0" else "interrupted"}],
                    "next_after_id": "1" if after == "0" else None}
        result = history.transcript("https://example.test", "token", "3", request)
        self.assertEqual([t["id"] for t in result["turns"]], ["0", "1"])
        self.assertTrue(result["turns"][1]["interrupted"])
        self.assertEqual(result["language_tag"], "sv")

    def test_sync_removes_deleted_cache_and_loads_active(self):
        def request(base, action, token, params):
            if action == "conversations":
                return {"conversations": [{"id": "2", "title": "Shared", "language_tag": None}],
                        "next_offset": None, "active_conversation_id": "2"}
            return {"conversation": {"title": "Shared", "language_tag": None},
                    "turns": [], "next_after_id": None}
        result = history.sync("https://example.test", "token", {"1": {"title": "Deleted"}}, request)
        self.assertEqual(set(result["threads"]), {"2"})
        self.assertEqual(result["active"], "2")

    def test_save_retry_preserves_original_payload_after_restart(self):
        calls = []
        def request(base, action, token, payload):
            calls.append(payload)
            if len(calls) == 1:
                raise OSError("Response lost after server commit")
            return {"created": False, "conversation_id": "2", "turn_id": "9"}
        pending = {"id": "b87840a5-165c-4358-9a99-7b73c57dcddf", "thread": None,
                   "audio": "AA==", "transcript": {"question_text": "Hej", "reply_text": "Svar",
                                                       "reply_status": "complete"}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pending.json"
            store.write(path, pending)
            with self.assertRaises(OSError):
                history.save("https://example.test", "token", pending, request)
            reply = history.save("https://example.test", "token", store.read(path, None), request)
        self.assertFalse(reply["created"])
        self.assertEqual(calls[0], calls[1])
        self.assertNotIn("audio", calls[0])

    def test_http_reads_history_and_posts_utf8_json(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, size): return b'{"ok":true}'
        with patch.object(transport, "build_opener") as opener:
            opener.return_value.open.return_value = Response()
            transport.api("https://example.test", "conversation", "token", params={"id": "12"})
            req = opener.return_value.open.call_args.args[0]
            self.assertEqual(req.method, "GET")
            self.assertIn("id=12", req.full_url)
            transport.api("https://example.test", "turn-save", "token", payload={"question_text": "Hej åäö"})
            req = opener.return_value.open.call_args.args[0]
            self.assertEqual(req.method, "POST")
            self.assertEqual(json.loads(req.data)["question_text"], "Hej åäö")
            self.assertEqual(req.get_header("Authorization"), "Bearer token")


if __name__ == "__main__":
    unittest.main()


class SimulatorPersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # No microphone, speaker, display, or Tk window is needed for these state tests.
        from types import ModuleType
        audio_stub, display_stub = ModuleType("audio"), ModuleType("display")
        display_stub.OLED = object
        with patch.dict(sys.modules, {"audio": audio_stub, "display": display_stub}):
            import pocketbrain
        cls.Simulator = pocketbrain.Simulator

    def make_simulator(self, directory):
        from unittest.mock import Mock
        simulator = self.Simulator.__new__(self.Simulator)
        simulator.current_mode = "Live"
        simulator.current_base = "https://example.test"
        simulator.token = "token"
        simulator.pending_path = Path(directory) / "pending.json"
        simulator.history_path = Path(directory) / "history.json"
        simulator.history = {"active": None, "threads": {}}
        simulator.pending = {"id": "b87840a5-165c-4358-9a99-7b73c57dcddf", "thread": None, "audio": "AA=="}
        simulator.reply = "A completed answer"
        simulator.menus = []
        simulator.sync_history = Mock()
        simulator.start_job = Mock()
        return simulator

    def test_reply_is_on_disk_before_save_starts(self):
        with tempfile.TemporaryDirectory() as directory:
            sim = self.make_simulator(directory)
            def start(kind, work):
                self.assertEqual(kind, "save")
                saved = store.read(sim.pending_path, None)
                self.assertEqual(saved["transcript"]["reply_text"], sim.reply)
            sim.start_job.side_effect = start
            sim.save_reply("Original question")
            self.assertEqual(sim.pending["transcript"]["question_text"], "Original question")

    def test_restart_retry_uses_saved_transcript_without_voice(self):
        with tempfile.TemporaryDirectory() as directory:
            sim = self.make_simulator(directory)
            sim.save_reply("Original question")
            sim.pending = {"id": "stale"}
            sim.start_job.reset_mock()
            sim.send_pending()
            self.assertEqual(sim.start_job.call_args.args[0], "save")
            self.assertEqual(sim.pending["transcript"]["reply_text"], "A completed answer")

    def test_acknowledged_reply_cached_before_pending_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            sim = self.make_simulator(directory)
            sim.save_reply("Original question")
            sim.on_message("turn_saved", {"conversation_id": "5", "turn_id": "9", "created": True})
            self.assertIsNone(sim.pending)
            self.assertFalse(sim.pending_path.exists())
            cached = store.read(sim.history_path, None)
            self.assertEqual(cached["threads"]["5"]["turns"][0]["reply"], "A completed answer")
            sim.sync_history.assert_called_once()
