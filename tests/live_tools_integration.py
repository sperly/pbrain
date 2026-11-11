"""Live-tool endpoints exercised through PHP with fake upstreams only."""
import hashlib
import unittest
import openai_keys_integration as keys


class LiveToolsIntegration(unittest.TestCase):
    def setUp(self):
        keys.sql("DELETE FROM user_openai_keys; DELETE FROM auth_rate_limits;")
        self.browser = keys.Browser().login("one@example.test")
        self.browser.save(keys.KEY_ONE)

    def tool(self, name, arguments, **kwargs):
        return keys.call("tool-call", {"name": name, "arguments": arguments}, **kwargs)

    def test_realtime_advertises_weather_and_search(self):
        status, reply = keys.call("realtime-secret", {})
        self.assertEqual(status, 200, reply)
        self.assertEqual({tool["name"] for tool in reply["tools"]}, {"get_weather", "search_web"})

    def test_weather_resolves_location_and_returns_units_dates_sources(self):
        status, reply = self.tool("get_weather", {"location": "Stockholm", "country_code": "SE"})
        self.assertEqual(status, 200, reply)
        self.assertEqual(reply["location"]["country"], "Sweden")
        self.assertEqual(reply["current_units"]["temperature_2m"], "°C")
        self.assertEqual(reply["timezone"], "Europe/Stockholm")
        self.assertIn('open-meteo.com', reply["sources"][0]["url"])
        self.assertIn('fetched_at', reply)
        self.assertNotIn(keys.KEY_ONE, str(reply))

    def test_search_uses_owner_key_and_citations(self):
        status, reply = self.tool("search_web", {"query": "What is new today?"})
        self.assertEqual(status, 200, reply)
        self.assertIn(hashlib.sha256(keys.KEY_ONE.encode()).hexdigest()[:12], reply["answer"])
        self.assertEqual(reply["sources"][0]["url"], "https://example.org/fact")
        status, reply = self.tool("search_web", {"query": "What is new today?"}, token=keys.TOKENS[2])
        self.assertEqual((status, reply["error"]), (503, 'openai_key_required'))

    def test_missing_sources_and_incomplete_results_are_errors(self):
        for query, reason in [('no sources', 'lookup_no_sources'), ('incomplete', 'lookup_incomplete')]:
            status, reply = self.tool("search_web", {"query": query})
            self.assertEqual((status, reply["error"]), (502, reason))

    def test_validation_and_authentication(self):
        for name, arguments in [('fetch_url', {'url': 'http://127.0.0.1'}),
                                ('search_web', {'query': ''}), ('search_web', {'query': 'x' * 1001}),
                                ('search_web', {'query': []}), ('get_weather', {'location': 'X', 'country_code': '../'}),
                                ('search_web', [])]:
            self.assertEqual(self.tool(name, arguments)[0], 400)
        self.assertEqual(self.tool('search_web', {'query': 'news'}, token='invalid')[0], 401)
        status, reply = self.tool('get_weather', {'location': 'Unknown', 'country_code': None})
        self.assertEqual((status, reply['error']), (404, 'weather_location_not_found'))

    def test_key_rejection_does_not_echo_key(self):
        self.browser.save('sk-rejected-' + 'r' * 40)
        status, reply = self.tool('search_web', {'query': 'news'})
        self.assertEqual((status, reply['error']), (502, 'openai_key_rejected'))
        self.assertNotIn('sk-', str(reply))

    def test_host_can_disable_both_tools(self):
        result = keys.docker("exec", "-e", "PB_TEST_DISABLE_TOOLS=1", keys.APP, "php", "-r",
            "require '/app/app/bootstrap.php'; require '/app/app/conversations.php'; require '/app/app/tools.php'; "
            "echo json_encode(liveTools()), '\n'; "
            "try { runLiveTool('1', ['name'=>'search_web', 'arguments'=>(object)['query'=>'news']]); } "
            "catch (HistoryError $e) { echo $e->status, ':', $e->getMessage(); }")
        self.assertIn('[]', result)
        self.assertIn('400:tool_not_available', result)

    def test_device_lookup_limit_is_enforced(self):
        for _ in range(10):
            self.assertEqual(self.tool('get_weather', {'location': 'Stockholm', 'country_code': 'SE'})[0], 200)
        self.assertEqual(self.tool('get_weather', {'location': 'Stockholm', 'country_code': 'SE'})[0], 429)
