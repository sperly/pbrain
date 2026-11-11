"""Dashboard history ownership, pagination, escaping, and device filters."""
from html.parser import HTMLParser
import os
from pathlib import Path
import re
import shutil
import unittest
from uuid import uuid4
import openai_keys_integration as env


class Page(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.links = []
        self.attributes = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.attributes.append((tag, attrs))
        if tag == 'a':
            self.links.append(attrs.get('href', ''))


class WebHistoryIntegration(unittest.TestCase):
    def setUp(self):
        env.sql('DELETE FROM conversations; DELETE FROM auth_rate_limits; UPDATE devices SET revoked_at=NULL;')
        self.browser = env.Browser().login('one@example.test')

    def save(self, question, token=None, conversation=None, reply='A saved answer.', **kwargs):
        status, result = env.call('turn-save', {'client_turn_id': str(uuid4()), 'conversation_id': conversation,
                                  'question_text': question, 'reply_text': reply, **kwargs}, token=token or env.TOKENS[0])
        self.assertEqual(status, 201, result)
        return result['conversation_id']

    def thread_titles(self, html):
        return re.findall(r'<span class="thread-title">(.*?)</span>', html, re.S)

    def test_device_filter_includes_shared_thread_and_full_transcript(self):
        shared = self.save('A weekend in Stockholm', reply='We could start with a walk through Gamla Stan.')
        self.save('And the weather?', token=env.TOKENS[1], conversation=shared,
                  reply='Check the forecast before heading out.\n\nSources:\nOpen-Meteo: https://open-meteo.com/')
        self.save('A separate desktop question', token=env.TOKENS[1])
        status, html = self.browser.page(params={'device': '1', 'conversation': shared})
        self.assertEqual(status, 200)
        self.assertEqual(self.thread_titles(html), ['A weekend in Stockholm'])
        self.assertIn('And the weather?', html)
        self.assertIn('Test device #1', html)
        self.assertIn('Test device #2', html)
        self.assertIn('https://open-meteo.com/', Page(html).links)
        self.assertEqual(len(self.thread_titles(self.browser.page(params={'device': '2'})[1])), 2)
        # Optional rendered fixture for actual browser screenshots, with test data only.
        if os.environ.get('PB_DASHBOARD_PREVIEW_DIRECTORY'):
            directory = Path(os.environ['PB_DASHBOARD_PREVIEW_DIRECTORY'])
            directory.mkdir(parents=True, exist_ok=True)
            (directory / 'index.html').write_text(html)
            shutil.copy(Path(__file__).resolve().parents[1] / 'backend/public_html/style.css', directory)

    def test_accounts_cannot_read_other_devices_or_threads_even_as_admin(self):
        other = self.save('Private other-account question', token=env.TOKENS[2])
        for role in ['member', 'admin']:
            env.sql(f"UPDATE users SET role='{role}' WHERE id=1;")
            try:
                for params in [{'device': '3'}, {'conversation': other}]:
                    status, html = self.browser.page(params=params)
                    self.assertEqual(status, 404)
                    self.assertNotIn('Private other-account question', html)
                self.assertNotIn('Private other-account question', self.browser.page()[1])
            finally:
                env.sql("UPDATE users SET role='member' WHERE id=1;")

    def test_filter_rejects_thread_without_turns_from_selected_device(self):
        key = self.save('Only the first device')
        self.assertEqual(self.browser.page(params={'device': '2', 'conversation': key})[0], 404)

    def test_unlinked_device_history_remains_available(self):
        key = self.save('Keep this history')
        env.sql('UPDATE devices SET revoked_at=CURRENT_TIMESTAMP WHERE id=1;')
        status, html = self.browser.page(params={'device': '1', 'conversation': key})
        self.assertEqual(status, 200)
        self.assertIn('Keep this history', html)
        self.assertIn('Unlinked', html)

    def test_question_reply_and_device_name_are_escaped(self):
        key = self.save('<script>alert(1)</script>', reply='<img src=x onerror=alert(1)>\nhttps://example.org/source\n[Source](https://example.org/wiki/Example_(topic))', reply_status='interrupted')
        status, html = self.browser.page(params={'conversation': key})
        self.assertEqual(status, 200)
        self.assertNotIn('<script>', html)
        self.assertNotIn('<img src=x', html)
        self.assertIn('&lt;script&gt;', html)
        self.assertIn('Interrupted', html)
        self.assertIn('https://example.org/source', Page(html).links)
        self.assertIn('https://example.org/wiki/Example_(topic)', Page(html).links)

    def test_pagination_for_thread_index_and_transcript(self):
        key = self.save('First question')
        for index in range(22):
            self.save(f'Follow-up {index}', conversation=key)
        status, html = self.browser.page(params={'conversation': key})
        self.assertEqual(status, 200)
        self.assertEqual(html.count('class="conversation-turn"'), 20)
        next_url = next(url for url in Page(html).links if 'after_id=' in url)
        from urllib.parse import parse_qs, urlsplit
        params = {name: values[0] for name, values in parse_qs(urlsplit(next_url).query).items()}
        _, next_html = self.browser.page(params=params)
        self.assertEqual(next_html.count('class="conversation-turn"'), 3)
        env.sql('DELETE FROM auth_rate_limits;')
        for index in range(26):
            self.save(f'New thread {index}')
        _, html = self.browser.page()
        self.assertEqual(len(self.thread_titles(html)), 25)
        _, html = self.browser.page(params={'offset': '25'})
        self.assertEqual(len(self.thread_titles(html)), 2)

    def test_invalid_links_and_empty_history(self):
        status, html = self.browser.page()
        self.assertEqual(status, 200)
        self.assertIn('No conversations yet', html)
        for params in [{'device': '1 OR 1=1'}, {'offset': '-1'}, {'conversation': 'nope'}]:
            status, html = self.browser.page(params=params)
            self.assertEqual(status, 400)
            self.assertNotIn('PDOException', html)

    def test_reading_does_not_change_device_selection(self):
        first = self.save('First thread')
        second = self.save('Second thread')
        self.browser.page(params={'conversation': first})
        self.assertEqual(env.call('conversations')[1]['active_conversation_id'], second)

    def test_signed_out_visitor_cannot_see_transcript(self):
        key = self.save('A private question')
        status, html = env.Browser().page(params={'conversation': key})
        self.assertEqual(status, 200)
        self.assertNotIn('A private question', html)
        self.assertNotIn('thread-index', html)
        self.assertIn('Sign in', html)
