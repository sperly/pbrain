"""Run through run_history_integration.py; uses only fake API keys and transport."""
import hashlib
from http.cookies import SimpleCookie
import re
import unittest
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

KEY_ONE = "sk-personal-one-" + "a" * 40
KEY_TWO = "sk-personal-two-" + "b" * 40


def configure(base, db, app, docker_fn, sql_fn, api_fn, tokens):
    global BASE, APP, docker, sql, call, TOKENS
    BASE, APP, docker, sql, call, TOKENS = base, app, docker_fn, sql_fn, api_fn, tokens


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


class Browser:
    def __init__(self):
        self.cookie = ""
        self.csrf = ""

    def page(self, data=None, params=None):
        url = BASE + "/index.php" + ("?" + urlencode(params) if params else "")
        req = Request(url, data=urlencode(data).encode() if data is not None else None,
                      headers={"Cookie": self.cookie})
        try:
            reply = build_opener(NoRedirect()).open(req, timeout=15)
        except HTTPError as exc:
            reply = exc
        cookies = SimpleCookie()
        for value in reply.headers.get_all("Set-Cookie", []):
            cookies.load(value)
        if "PocketBrain" in cookies:
            # Test router emulates HTTPS on a localhost HTTP listener.
            self.cookie = "PocketBrain=" + cookies["PocketBrain"].value
        text = reply.read().decode()
        match = re.search(r'name="csrf" value="([a-f0-9]{64})"', text)
        if match:
            self.csrf = match[1]
        return reply.code, text

    def login(self, email):
        self.page()
        status, _ = self.page({"action": "sign-in", "email": email,
                               "password": "test-password-long-enough", "csrf": self.csrf})
        assert status == 303, status
        status, text = self.page()
        assert "My OpenAI API key" in text, text
        return self

    def save(self, key, **fields):
        return self.page({"action": "save-openai-key", "openai_api_key": key, "csrf": self.csrf, **fields})


class OpenaiKeysIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        password_hash = docker("exec", APP, "php", "-r",
                               "echo password_hash('test-password-long-enough', PASSWORD_BCRYPT, ['cost'=>4]);")
        sql(f"UPDATE users SET password_hash='{password_hash}';")

    def setUp(self):
        sql("DELETE FROM user_openai_keys; DELETE FROM auth_rate_limits;")
        self.one = Browser().login("one@example.test")
        self.two = Browser().login("two@example.test")

    def expected_secret(self, key):
        return "ephemeral-test-" + hashlib.sha256(key.encode()).hexdigest()[:12]

    def test_encrypted_storage_and_owner_billing(self):
        self.assertEqual(self.one.save(KEY_ONE)[0], 303)
        self.assertEqual(self.two.save(KEY_TWO)[0], 303)
        for token, key in [(TOKENS[0], KEY_ONE), (TOKENS[1], KEY_ONE), (TOKENS[2], KEY_TWO)]:
            status, body = call("realtime-secret", {}, token=token)
            self.assertEqual(status, 200, body)
            self.assertEqual(body["value"], self.expected_secret(key))
            self.assertNotIn(key, str(body))
        encrypted = sql("SELECT HEX(encrypted_key) FROM user_openai_keys WHERE user_id=1;").splitlines()[1]
        self.assertNotIn(KEY_ONE.encode(), bytes.fromhex(encrypted))
        self.assertNotEqual(KEY_ONE.encode(), bytes.fromhex(encrypted))
        dashboard = self.one.page()[1]
        self.assertIn("Personal key saved", dashboard)
        self.assertNotIn(KEY_ONE, dashboard)
        self.assertNotIn(KEY_TWO, dashboard)

    def test_replace_remove_and_submitted_owner_ignored(self):
        self.one.save(KEY_ONE, user_id="2")
        self.assertEqual(call("realtime-secret", {}, token=TOKENS[2])[1]["error"], "openai_key_required")
        self.one.save(KEY_TWO)
        self.assertEqual(call("realtime-secret", {})[1]["value"], self.expected_secret(KEY_TWO))
        self.assertEqual(self.one.page({"action": "remove-openai-key", "csrf": self.one.csrf})[0], 303)
        status, body = call("realtime-secret", {})
        self.assertEqual((status, body["error"]), (503, "openai_key_required"))

    def test_anonymous_and_csrf_requests_cannot_change_keys(self):
        self.one.save(KEY_ONE)
        anonymous = Browser()
        anonymous.page()
        self.assertEqual(anonymous.save(KEY_TWO)[0], 303)
        self.assertEqual(self.one.save(KEY_TWO, csrf="wrong")[0], 403)
        self.assertEqual(self.one.page({"action": "remove-openai-key", "csrf": "wrong"})[0], 403)
        self.assertEqual(call("realtime-secret", {})[1]["value"], self.expected_secret(KEY_ONE))

    def test_bad_format_does_not_replace_saved_key_or_echo_secret(self):
        self.one.save(KEY_ONE)
        for key in ["", "sk-bad\r\nAuthorization: Bearer injected", "sk-" + "a" * 1022]:
            self.assertEqual(self.one.save(key)[0], 303)
            self.assertNotIn(key if key else "not-a-secret", self.one.page()[1])
        self.assertEqual(call("realtime-secret", {})[1]["value"], self.expected_secret(KEY_ONE))

    def test_ciphertext_is_bound_to_owner_and_authenticated(self):
        self.one.save(KEY_ONE)
        sql("INSERT INTO user_openai_keys (user_id,encrypted_key) SELECT 2,encrypted_key FROM user_openai_keys WHERE user_id=1;")
        self.assertEqual(call("realtime-secret", {}, token=TOKENS[2])[1]["error"], "openai_key_unavailable")
        sql("UPDATE user_openai_keys SET encrypted_key=CONCAT(SUBSTR(encrypted_key,1,29),X'00') WHERE user_id=1;")
        status, body = call("realtime-secret", {})
        self.assertEqual((status, body["error"]), (503, "openai_key_unavailable"))

    def test_invalid_upstream_key_and_quota_are_safe_errors(self):
        for key, reason in [("sk-rejected-" + "r" * 40, "openai_key_rejected"),
                            ("sk-quota-" + "q" * 40, "openai_quota_or_rate_limit")]:
            self.one.save(key)
            status, body = call("realtime-secret", {})
            self.assertEqual((status, body["error"]), (502, reason))
            self.assertNotIn(key, str(body))

    def test_shared_key_is_opt_in_and_never_replaces_personal_key(self):
        self.assertEqual(call("realtime-secret", {})[1]["error"], "openai_key_required")
        def key_for_user():
            return docker("exec", "-e", "PB_TEST_ALLOW_SHARED=1", APP, "php", "-r",
                          "require '/app/app/bootstrap.php'; require '/app/app/openai_keys.php'; echo openaiKeyForUser('1');")
        self.assertEqual(key_for_user(), "sk-shared-" + "s" * 40)
        self.one.save(KEY_ONE)
        self.assertEqual(key_for_user(), KEY_ONE)
        self.one.save("sk-rejected-" + "r" * 40)
        result = docker("exec", "-e", "PB_TEST_ALLOW_SHARED=1", APP, "php", "-d",
                        "disable_functions=curl_init,curl_setopt_array,curl_exec,curl_getinfo,curl_errno", "-r",
                        "require '/mock_realtime.php'; require '/app/app/bootstrap.php'; require '/app/app/realtime.php'; echo json_encode(issueRealtimeSecret('1'));")
        self.assertIn('openai_key_rejected', result)
        self.assertNotIn('ephemeral-test', result)
