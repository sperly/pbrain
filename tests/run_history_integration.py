"""Isolated PHP 8.4/MariaDB integration suite. Requires Docker; no production config.
Run: python3 tests/run_history_integration.py
"""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
TOKENS = [str(n) * 64 for n in (1, 2, 3)]
BASE = ""
DB = ""


def docker(*args, data=None):
    return subprocess.run(["docker", *args], input=data, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout.strip()


def sql(statement):
    return docker("exec", "-i", DB, "mariadb", "-uroot", "-pisolated-test-only", "history_test", data=statement)


def call(action, payload=None, token=TOKENS[0], method=None, **params):
    from urllib.parse import urlencode
    method = method or ("POST" if payload is not None else "GET")
    req = Request(BASE + "/api.php?" + urlencode({"action": action, **params}),
                  data=json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None,
                  method=method, headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=20) as response:
            return response.status, json.load(response)
    except HTTPError as exc:
        return exc.code, json.load(exc)


def turn(conversation=None, **fields):
    return {"client_turn_id": str(uuid4()), "conversation_id": conversation,
            "question_text": "Hej, hur mår du?", "reply_text": "Bra, tack!", **fields}


class HistoryIntegration(unittest.TestCase):
    def setUp(self):
        sql("DELETE FROM conversations; DELETE FROM auth_rate_limits;")

    def test_new_turn_and_retry_are_atomic(self):
        payload = turn(language_tag="sv-SE")
        status, first = call("turn-save", payload)
        self.assertEqual(status, 201, first)
        status, retry = call("turn-save", payload)
        self.assertEqual(status, 200, retry)
        self.assertEqual(first["turn_id"], retry["turn_id"])
        self.assertEqual(sql("SELECT COUNT(*) FROM conversations; SELECT COUNT(*) FROM conversation_turns;"),
                         "COUNT(*)\n1\nCOUNT(*)\n1")
        _, page = call("conversation", id=first["conversation_id"])
        self.assertEqual(page["conversation"]["language_tag"], "sv-SE")
        self.assertEqual(page["turns"][0]["question_text"], payload["question_text"])

    def test_concurrent_first_turn_retries(self):
        payload = turn()
        with ThreadPoolExecutor(max_workers=4) as pool:
            replies = list(pool.map(lambda _: call("turn-save", payload), range(4)))
        self.assertEqual(sorted(status for status, _ in replies), [200, 200, 200, 201], replies)
        self.assertEqual(len({body["conversation_id"] for _, body in replies}), 1)
        self.assertEqual(sql("SELECT COUNT(*) FROM conversations;"), "COUNT(*)\n1")

    def test_conflicting_retry_rejected(self):
        payload = turn()
        call("turn-save", payload)
        status, body = call("turn-save", {**payload, "reply_text": "Different"})
        self.assertEqual((status, body["error"]), (409, "turn_id_conflict"))

    def test_other_account_cannot_read_select_append_or_delete(self):
        _, first = call("turn-save", turn())
        key = first["conversation_id"]
        for action, payload, params in [
            ("conversation", None, {"id": key}),
            ("conversation-active", {"conversation_id": key}, {}),
            ("turn-save", turn(key), {}),
        ]:
            status, body = call(action, payload, token=TOKENS[2], **params)
            self.assertEqual(status, 404, (action, body))
        _, rows = call("conversations", token=TOKENS[2])
        self.assertEqual(rows["conversations"], [])
        self.assertEqual(call("conversation-delete", {"conversation_id": key}, token=TOKENS[2])[0], 200)
        self.assertEqual(call("conversation", id=key)[0], 200)

    def test_preview_does_not_change_selection_and_deletion_clears_all_devices(self):
        _, first = call("turn-save", turn())
        key = first["conversation_id"]
        call("conversation-active", {"conversation_id": key}, token=TOKENS[1])
        call("conversation-active", {"conversation_id": None})
        call("conversation", id=key)
        self.assertIsNone(call("conversations")[1]["active_conversation_id"])
        call("conversation-delete", {"conversation_id": key})
        self.assertIsNone(call("conversations", token=TOKENS[1])[1]["active_conversation_id"])
        self.assertEqual(call("conversation", id=key)[0], 404)
        self.assertEqual(call("turn-save", turn(key))[0], 404)
        self.assertEqual(sql("SELECT COUNT(*) FROM conversation_turns;"), "COUNT(*)\n0")

    def test_shared_history_separate_device_selection_and_language(self):
        _, first = call("turn-save", turn(language_tag="sv"))
        key = first["conversation_id"]
        self.assertIsNone(call("conversations", token=TOKENS[1])[1]["active_conversation_id"])
        call("turn-save", turn(key, language_tag="en"), token=TOKENS[1])
        page = call("conversation", token=TOKENS[1], id=key)[1]
        self.assertEqual(len(page["turns"]), 2)
        self.assertEqual(page["conversation"]["language_tag"], "sv")

    def test_transcript_and_title_pagination(self):
        _, first = call("turn-save", turn())
        key = first["conversation_id"]
        for _ in range(22):
            self.assertEqual(call("turn-save", turn(key))[0], 201)
        _, page = call("conversation", id=key)
        self.assertEqual(len(page["turns"]), 20)
        _, rest = call("conversation", id=key, after_id=page["next_after_id"])
        self.assertEqual(len(rest["turns"]), 3)
        self.assertIsNone(rest["next_after_id"])
        for _ in range(51):
            self.assertEqual(call("turn-save", turn())[0], 201)
        _, listing = call("conversations")
        self.assertEqual(len(listing["conversations"]), 50)
        _, remaining = call("conversations", offset=listing["next_offset"])
        self.assertEqual(len(remaining["conversations"]), 2)

    def test_validation_authentication_and_methods(self):
        self.assertEqual(call("turn-save", turn(), token="bad")[0], 401)
        self.assertEqual(call("turn-save", method="GET")[0], 405)
        self.assertEqual(call("conversation", id="1 OR 1=1")[0], 400)
        self.assertEqual(call("conversations", offset="-1")[0], 400)
        self.assertEqual(call("turn-save", turn(client_turn_id="bad"))[0], 400)
        self.assertEqual(call("turn-save", turn(reply_text="x" * 32769))[0], 400)
        self.assertEqual(call("turn-save", turn(language_tag="bad_tag"))[0], 400)
        self.assertEqual(call("turn-save", [1, 2])[0], 400)
        self.assertEqual(call("turn-save", turn(reply_text="x" * 131073))[0], 413)

    def test_revoked_device_and_disabled_user(self):
        sql("UPDATE devices SET revoked_at=CURRENT_TIMESTAMP WHERE id=1;")
        try:
            self.assertEqual(call("conversations")[0], 401)
        finally:
            sql("UPDATE devices SET revoked_at=NULL WHERE id=1;")
        sql("UPDATE users SET disabled_at=CURRENT_TIMESTAMP WHERE id=1;")
        try:
            self.assertEqual(call("turn-save", turn())[0], 401)
        finally:
            sql("UPDATE users SET disabled_at=NULL WHERE id=1;")


def main():
    global DB, BASE
    prefix = "pbrain-history-" + uuid4().hex[:10]
    network, DB, app = prefix + "-net", prefix + "-db", prefix + "-php"
    image = "pbrain-history-test"
    try:
        with tempfile.TemporaryDirectory(prefix="pbrain-history-") as directory:
            context = Path(directory)
            shutil.copytree(ROOT / "backend", context / "backend", ignore=shutil.ignore_patterns("config.php"))
            shutil.copy(ROOT / "tests/integration/Dockerfile", context)
            shutil.copy(ROOT / "tests/integration/router.php", context)
            shutil.copy(ROOT / "tests/integration/mock_realtime.php", context)
            (context / "backend/config.php").write_text("""<?php
return ['db_host'=>'db','db_port'=>3306,'db_name'=>'history_test',
'db_user'=>'root','db_password'=>'isolated-test-only',
'base_url'=>'https://example.test','app_key'=>str_repeat('a',64),
'allow_shared_openai_key'=>getenv('PB_TEST_ALLOW_SHARED') === '1',
'openai_api_key'=>'sk-shared-' . str_repeat('s',40),
'enable_weather'=>getenv('PB_TEST_DISABLE_TOOLS') !== '1',
'enable_web_search'=>getenv('PB_TEST_DISABLE_TOOLS') !== '1'];
""")
            print("Building isolated PHP test image...", flush=True)
            docker("build", "-t", image, str(context))
        docker("network", "create", network)
        docker("run", "-d", "--name", DB, "--network", network, "--network-alias", "db",
               "-e", "MARIADB_ROOT_PASSWORD=isolated-test-only", "-e", "MARIADB_DATABASE=history_test", "mariadb:11.4")
        for _ in range(60):
            try:
                sql("SELECT 1;")
                break
            except subprocess.CalledProcessError:
                time.sleep(1)
        else:
            raise RuntimeError("MariaDB did not start")
        for file in ("001_initial.sql", "002_auth_rate_limits.sql", "003_user_openai_keys.sql"):
            sql((ROOT / "backend/sql" / file).read_text())
        sql("INSERT INTO users (email,password_hash) VALUES ('one@example.test','unused'),('two@example.test','unused');")
        for number, token in enumerate(TOKENS):
            owner = 1 if number < 2 else 2
            sql(f"INSERT INTO devices (user_id,display_name,credential_hash) VALUES ({owner},'Test device',UNHEX('{hashlib.sha256(token.encode()).hexdigest()}'));")
        print(docker("run", "--rm", "--entrypoint", "sh", image, "-c", "find /app -name '*.php' -exec php -l {} \\;"))
        docker("run", "-d", "--name", app, "--network", network, "-p", "127.0.0.1::8080",
               "-e", "PHP_CLI_SERVER_WORKERS=4", "-e", "PB_MOCK_REALTIME=1", image,
               "php", "-d", "disable_functions=curl_init,curl_setopt_array,curl_exec,curl_getinfo,curl_errno",
               "-S", "0.0.0.0:8080", "-t", "/app/public_html", "/router.php")
        port = docker("port", app, "8080/tcp").rsplit(":", 1)[1]
        BASE = "http://127.0.0.1:" + port
        for _ in range(30):
            try:
                call("conversations")
                break
            except OSError:
                time.sleep(.2)
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(HistoryIntegration)
        from openai_keys_integration import OpenaiKeysIntegration
        import openai_keys_integration
        openai_keys_integration.configure(BASE, DB, app, docker, sql, call, TOKENS)
        suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(OpenaiKeysIntegration))
        from live_tools_integration import LiveToolsIntegration
        suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(LiveToolsIntegration))
        from web_history_integration import WebHistoryIntegration
        suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(WebHistoryIntegration))
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        if not result.wasSuccessful():
            print(docker("logs", app))
        return 0 if result.wasSuccessful() else 1
    finally:
        for container in (app, DB):
            subprocess.run(["docker", "rm", "-fv", container], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["docker", "network", "rm", network], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == "__main__":
    raise SystemExit(main())
