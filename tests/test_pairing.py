"""Pairing protocol and account lifecycle checks without network or hardware."""
from pathlib import Path
import sys
import tempfile
from threading import Event
from types import ModuleType
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "desktop"))
import store
import transport


class Clock:
    def __init__(self):
        self.now = 0
        self.waits = []
        self.stopped = False

    def wait(self, seconds):
        self.waits.append(seconds)
        self.now += seconds
        return self.stopped

    def is_set(self):
        return self.stopped


class PairingTests(unittest.TestCase):
    def details(self, **changes):
        return {"code": "ABCD-2345", "polling_secret": "secret", "expires_in": 300,
                "poll_interval": 5, "verification_uri": "https://example.test/index.php#devices", **changes}

    def test_pending_then_linked_respects_interval_and_displays_address(self):
        clock, emit = Clock(), Mock()
        with patch.object(transport, "monotonic", lambda: clock.now), patch.object(
                transport, "api", side_effect=[self.details(poll_interval=1),
                    {"status": "pending"}, {"status": "linked", "device_credential": "A" * 64}]) as api:
            transport.pair("https://example.test", clock, emit)
        self.assertEqual(clock.waits, [5, 5])
        self.assertEqual(api.call_args.args, ("https://example.test", "pair-poll", "secret"))
        self.assertEqual(emit.call_args_list[0].args,
                         ("pair_code", ("ABCD-2345", self.details()["verification_uri"], 300)))
        emit.assert_called_with("paired", "A" * 64)

    def test_expiry_never_polls_after_deadline(self):
        clock, emit = Clock(), Mock()
        with patch.object(transport, "monotonic", lambda: clock.now), patch.object(
                transport, "api", return_value=self.details(expires_in=3)) as api:
            with self.assertRaisesRegex(transport.DeviceError, "expired"):
                transport.pair("https://example.test", clock, emit)
        self.assertEqual(clock.waits, [3])
        self.assertEqual(api.call_count, 1)

    def test_cancellation_during_poll_does_not_install_credential(self):
        clock, emit = Clock(), Mock()
        def request(base, action, *args):
            if action == "pair-start":
                return self.details()
            clock.stopped = True
            return {"status": "linked", "device_credential": "a" * 64}
        with patch.object(transport, "monotonic", lambda: clock.now), patch.object(transport, "api", request):
            transport.pair("https://example.test", clock, emit)
        self.assertEqual(emit.call_count, 1)

    def test_cancelled_before_start_response_displays_no_code(self):
        stop, emit = Event(), Mock()
        stop.set()
        with patch.object(transport, "api", return_value=self.details()):
            transport.pair("https://example.test", stop, emit)
        emit.assert_not_called()

    def test_temporary_poll_failure_keeps_same_code_and_retries(self):
        clock, emit = Clock(), Mock()
        with patch.object(transport, "monotonic", lambda: clock.now), patch.object(
                transport, "api", side_effect=[self.details(), URLError("connection lost"),
                    transport.PairPollUnavailable("HTTP 503"),
                    {"status": "linked", "device_credential": "a" * 64}]) as api:
            transport.pair("https://example.test", clock, emit)
        self.assertEqual(clock.waits, [5, 5, 5])
        self.assertEqual(sum(call.args[1] == "pair-start" for call in api.call_args_list), 1)
        self.assertEqual(sum(call.args[0] == "pair_code" for call in emit.call_args_list), 1)
        emit.assert_called_with("paired", "a" * 64)

    def test_invalid_response_and_credential_fail_without_linking(self):
        for changes in ({"expires_in": 0}, {"expires_in": 901}, {"expires_in": "300"},
                        {"poll_interval": False}, {"polling_secret": ""}, {"verification_uri": None}):
            with self.subTest(changes=changes), patch.object(transport, "api", return_value=self.details(**changes)):
                with self.assertRaises(transport.DeviceError):
                    transport.pair("https://example.test", Clock(), Mock())
        clock, emit = Clock(), Mock()
        with patch.object(transport, "monotonic", lambda: clock.now), patch.object(
                transport, "api", side_effect=[self.details(), {"status": "linked", "device_credential": "invalid"}]):
            with self.assertRaisesRegex(transport.DeviceError, "credential"):
                transport.pair("https://example.test", clock, emit)
        self.assertEqual(emit.call_count, 1)

    def test_poll_rate_limit_retries_but_expired_code_fails(self):
        with patch.object(transport, "build_opener") as opener:
            opener.return_value.open.side_effect = HTTPError("https://example.test", 429, "Limit", {}, None)
            self.assertEqual(transport.api("https://example.test", "pair-poll", "secret"), {"status": "pending"})
            with self.assertRaisesRegex(transport.DeviceError, "rate limit"):
                transport.api("https://example.test", "pair-start")
            opener.return_value.open.side_effect = HTTPError("https://example.test", 404, "Expired", {}, None)
            with self.assertRaisesRegex(transport.DeviceError, "expired"):
                transport.api("https://example.test", "pair-poll", "secret")


class AccountLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        audio_stub, display_stub = ModuleType("audio"), ModuleType("display")
        display_stub.OLED = object
        with patch.dict(sys.modules, {"audio": audio_stub, "display": display_stub}):
            import pocketbrain
        cls.Simulator = pocketbrain.Simulator

    def simulator(self, directory, token="a" * 64):
        sim = self.Simulator.__new__(self.Simulator)
        sim.directory = Path(directory)
        sim.config_path = sim.directory / "settings.json"
        sim.config = {}
        sim.base = Mock(get=Mock(return_value="https://example.test"))
        sim.mode = Mock(get=Mock(return_value="Live"))
        sim.input = sim.output = Mock(get=Mock(return_value="System default"))
        sim.notice, sim.root, sim.oled = Mock(), Mock(), Mock()
        sim.mute, sim.volume = False, 70
        sim.credentials = {"https://example.test": token, "https://other.test": "b" * 64} if token else {}
        sim.held = sim.recording = False
        sim.job = sim.playback = sim.progress = None
        sim.generation = 0
        sim.menus = []
        sim.start_job = Mock()
        sim.load_profile(sync=False)
        return sim

    def test_link_is_in_wheel_menu_and_linked_account_cannot_be_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            sim = self.simulator(directory)
            sim.main_menu()
            self.assertIn("Link account", [label for label, fn in sim.menus[-1][1]])
            sim.start_pairing()
            sim.start_job.assert_not_called()
            self.assertEqual(sim.token, "a" * 64)
            self.assertIn("Already linked", sim.notice.set.call_args.args[0])

    def test_unlink_requires_confirmation_and_clears_only_this_account(self):
        with tempfile.TemporaryDirectory() as directory:
            sim = self.simulator(directory)
            old_history, old_pending = sim.history_path, sim.pending_path
            store.write(old_history, {"private": "transcript"})
            store.write(old_pending, {"private": "recording"})
            untouched = Path(directory) / "demo-history.json"
            store.write(untouched, {"demo": True})
            sim.confirm_unlink()
            self.assertTrue(old_history.exists())
            self.assertEqual(sim.token, "a" * 64)
            sim.menus[-1][1][1][1]()
            self.assertFalse(old_history.exists())
            self.assertFalse(old_pending.exists())
            self.assertTrue(untouched.exists())
            self.assertEqual(sim.token, "")
            self.assertEqual(store.read(Path(directory) / "credentials.json", {}),
                             {"https://other.test": "b" * 64})

    def test_link_screen_uses_verification_uri_and_back_cancels(self):
        with tempfile.TemporaryDirectory() as directory:
            sim = self.simulator(directory, token="")
            sim.start_pairing()
            stop = Event()
            sim.job = ("pair", stop)
            sim.on_message("pair_code", ("ABCD-2345", "https://example.test/link", 99999999999))
            sim.draw()
            screen_text = sim.oled.show.call_args.args[1]
            self.assertIn("https://example.test/link", screen_text)
            self.assertIn("ABCD-2345", screen_text)
            sim.press_talk()
            sim.release_timer = None
            sim.release_talk()
            self.assertTrue(stop.is_set())
            self.assertIsNone(sim.job)
            self.assertIsNone(sim.pair_code)
            self.assertFalse(sim.recording)

    def test_failed_data_clear_keeps_credential_for_unlink_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            sim = self.simulator(directory)
            with patch.object(Path, "unlink", side_effect=OSError("disk failure")):
                sim.unlink_local()
            self.assertEqual(sim.token, "a" * 64)
            self.assertEqual(sim.credentials[sim.current_base], sim.token)
            self.assertIn("Could not finish local unlink", sim.notice.set.call_args.args[0])

    def test_poll_error_keeps_code_and_reason_visible_until_explicit_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            sim = self.simulator(directory, token="")
            sim.start_pairing()
            sim.job = ("pair", Event())
            sim.on_message("pair_code", ("ABCD-2345", "https://example.test/link", 99999999999))
            sim.on_message("error", "Polling secret rejected")
            sim.draw()
            self.assertIn("ABCD-2345", sim.oled.show.call_args.args[1])
            self.assertIn("Polling secret rejected", sim.oled.show.call_args.args[1])
            self.assertIsNone(sim.job)
            sim.start_job.reset_mock()
            sim.push()
            self.assertIsNone(sim.pair_error)
            self.assertEqual(sim.start_job.call_args.args[0], "pair")

    def test_switching_to_browser_does_not_cancel_pairing(self):
        with tempfile.TemporaryDirectory() as directory:
            sim = self.simulator(directory, token="")
            stop = Event()
            sim.job = ("pair", stop)
            sim.on_message("pair_code", ("ABCD-2345", "https://example.test/link", 99999999999))
            sim.root.focus_get.return_value = None
            sim.on_focus_out(Mock())
            sim.release_if_unfocused()
            sim.draw()
            self.assertFalse(stop.is_set())
            self.assertEqual(sim.pair_code, "ABCD-2345")
            self.assertIn("ABCD-2345", sim.oled.show.call_args.args[1])

    def test_queued_shortcuts_after_focus_loss_do_not_cancel_pairing(self):
        with tempfile.TemporaryDirectory() as directory:
            sim = self.simulator(directory, token="")
            stop = Event()
            sim.job = ("pair", stop)
            sim.on_message("pair_code", ("ABCD-2345", "https://example.test/link", 99999999999))
            sim.root.focus_get.return_value = None
            sim.key(Mock(), sim.key_talk)
            sim.key(Mock(), sim.back)
            self.assertFalse(stop.is_set())
            self.assertEqual(sim.pair_code, "ABCD-2345")
            self.assertFalse(sim.held)

    def test_keyboard_cancel_still_works_when_emulator_has_focus(self):
        with tempfile.TemporaryDirectory() as directory:
            sim = self.simulator(directory, token="")
            stop = Event()
            sim.job = ("pair", stop)
            sim.root.focus_get.return_value = sim.root
            sim.root.winfo_toplevel.return_value = sim.root
            sim.key(Mock(), sim.back)
            self.assertTrue(stop.is_set())
            self.assertIsNone(sim.job)

    def test_credential_is_persisted_before_loading_linked_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            sim = self.simulator(directory, token="")
            sim.sync_history = Mock()
            sim.on_message("paired", "C" * 64)
            self.assertEqual(sim.token, "C" * 64)
            self.assertEqual(store.read(Path(directory) / "credentials.json", {})[sim.current_base], "C" * 64)
            sim.sync_history.assert_called_once()


if __name__ == "__main__":
    unittest.main()
