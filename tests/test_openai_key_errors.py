"""Actionable desktop errors without exposing upstream key/account details."""
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "desktop"))
import transport


class OpenaiKeyErrors(unittest.TestCase):
    def test_key_errors_explain_next_step_without_echoing_upstream_details(self):
        for status, reason, expected in [
            (503, "openai_key_required", "web dashboard"),
            (503, "openai_key_unavailable", "Replace"),
            (502, "openai_key_rejected", "permissions"),
            (502, "openai_quota_or_rate_limit", "billing"),
        ]:
            with self.subTest(reason=reason):
                error = HTTPError("https://example.test/api.php", status, "Error", {},
                                  io.BytesIO(json.dumps({"error": reason, "message": "sk-private-do-not-display"}).encode()))
                with patch.object(transport, "build_opener") as opener:
                    opener.return_value.open.side_effect = error
                    with self.assertRaises(transport.DeviceError) as raised:
                        transport.api("https://example.test", "realtime-secret", "token")
                self.assertIn(expected, str(raised.exception))
                self.assertNotIn("sk-private", str(raised.exception))

    def test_non_json_failure_remains_readable(self):
        error = HTTPError("https://example.test/api.php", 502, "Error", {}, io.BytesIO(b"<html>proxy error</html>"))
        with patch.object(transport, "build_opener") as opener:
            opener.return_value.open.side_effect = error
            with self.assertRaisesRegex(transport.DeviceError, "Voice is unavailable"):
                transport.api("https://example.test", "realtime-secret", "token")
