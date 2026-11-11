"""Versioned legal pages and atomic agreement recording for invited signup."""
import hashlib
from html.parser import HTMLParser
import os
from pathlib import Path
import re
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4
import openai_keys_integration as env


class Inputs(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.fields = {}
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == 'input':
            attributes = dict(attrs)
            self.fields[attributes.get('name')] = attributes


class LegalSignupIntegration(unittest.TestCase):
    def setUp(self):
        env.sql('DELETE FROM auth_rate_limits;')
        self.token = uuid4().hex + uuid4().hex
        self.digest = hashlib.sha256(self.token.encode()).hexdigest()
        env.sql("INSERT INTO invitations (token_hash,created_by_user_id,expires_at) "
                f"VALUES (UNHEX('{self.digest}'),1,CURRENT_TIMESTAMP + INTERVAL 1 DAY);")
        self.browser = env.Browser()
        self.browser.page(params={'invite': self.token})
        _, self.signup_html = self.browser.page()
        fields = Inputs(self.signup_html).fields
        self.email = 'legal-' + uuid4().hex + '@example.test'
        self.body = {name: fields[name]['value'] for name in ('terms_version', 'privacy_version', 'legal_revision')}
        self.body.update(action='sign-up', csrf=self.browser.csrf, email=self.email,
                         password='test-password-long-enough', confirmation='test-password-long-enough',
                         accept_terms='1', acknowledge_privacy='1')

    def invite_unused(self):
        return env.sql(f"SELECT redeemed_at IS NULL FROM invitations WHERE token_hash=UNHEX('{self.digest}');").splitlines()[-1] == '1'

    def user_count(self):
        return env.sql(f"SELECT COUNT(*) FROM users WHERE email='{self.email}';").splitlines()[-1]

    def test_checkboxes_start_unchecked_and_documents_are_linked(self):
        fields = Inputs(self.signup_html).fields
        for name in ('accept_terms', 'acknowledge_privacy'):
            self.assertEqual(fields[name]['type'], 'checkbox')
            self.assertIn('required', fields[name])
            self.assertNotIn('checked', fields[name])
        self.assertIn('legal.php?document=terms', self.signup_html)
        self.assertIn('legal.php?document=privacy', self.signup_html)
        self.assertIn('Optional-cookie choices are separate', self.signup_html)
        if os.environ.get('PB_DASHBOARD_PREVIEW_DIRECTORY'):
            (Path(os.environ['PB_DASHBOARD_PREVIEW_DIRECTORY']) / 'signup.html').write_text(self.signup_html)

    def test_terms_and_privacy_are_enforced_on_server(self):
        for field in ('accept_terms', 'acknowledge_privacy'):
            body = dict(self.body)
            body.pop(field)
            self.assertEqual(self.browser.page(body)[0], 303)
            self.assertEqual(self.user_count(), '0')
            self.assertTrue(self.invite_unused())
            _, html = self.browser.page()
            self.assertIn('Agree to the terms and acknowledge', html)

    def test_stale_version_or_changed_text_requires_fresh_agreement(self):
        for field in ('terms_version', 'privacy_version', 'legal_revision'):
            body = {**self.body, field: 'old-version'}
            self.assertEqual(self.browser.page(body)[0], 303)
            self.assertEqual(self.user_count(), '0')
            self.assertTrue(self.invite_unused())
            self.assertIn('Read the current versions', self.browser.page()[1])

    def test_success_records_versions_snapshots_and_timestamp_atomically(self):
        self.assertEqual(self.browser.page(self.body)[0], 303)
        self.assertEqual(self.user_count(), '1')
        self.assertFalse(self.invite_unused())
        receipt = env.sql(f"SELECT a.terms_version,a.privacy_version,a.accepted_at IS NOT NULL, "
                          f"OCTET_LENGTH(a.terms_sha256),OCTET_LENGTH(a.privacy_sha256) "
                          f"FROM user_legal_acceptances a JOIN users u ON u.id=a.user_id WHERE u.email='{self.email}';")
        self.assertIn('2026-11-11\t2026-11-11\t1\t32\t32', receipt)
        self.assertEqual(env.sql('SELECT COUNT(*) FROM legal_documents WHERE document_sha256=UNHEX(SHA2(document_html,256));').splitlines()[-1], '2')
        self.assertEqual(self.browser.page(self.body)[0], 303)
        self.assertEqual(self.user_count(), '1')

    def test_receipt_failure_rolls_back_user_and_invitation(self):
        env.sql("CREATE TRIGGER reject_legal_test BEFORE INSERT ON user_legal_acceptances "
                "FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='test receipt failure';")
        try:
            status, html = self.browser.page(self.body)
            self.assertEqual(status, 500)
            self.assertEqual(self.user_count(), '0')
            self.assertTrue(self.invite_unused())
            self.assertNotIn('test receipt failure', html)
        finally:
            env.sql('DROP TRIGGER reject_legal_test;')

    def test_signup_csrf_is_still_required(self):
        status, _ = self.browser.page({**self.body, 'csrf': 'wrong'})
        self.assertEqual(status, 403)
        self.assertEqual(self.user_count(), '0')
        self.assertTrue(self.invite_unused())

    def legal_page(self, query):
        try:
            response = urlopen(env.BASE + '/legal.php?' + query, timeout=15)
        except HTTPError as error:
            response = error
        return response.code, response.read().decode(), response.headers

    def test_legal_pages_are_public_without_setting_a_session_cookie(self):
        for document in ('terms', 'privacy'):
            status, html, headers = self.legal_page('document=' + document + '&version=2026-11-11')
            self.assertEqual(status, 200)
            self.assertIn('Draft for operator review', html)
            self.assertIn('Version 2026-11-11', html)
            self.assertIsNone(headers.get('Set-Cookie'))
            self.assertIn('Cookie preferences', html)
            if document == 'privacy' and os.environ.get('PB_DASHBOARD_PREVIEW_DIRECTORY'):
                (Path(os.environ['PB_DASHBOARD_PREVIEW_DIRECTORY']) / 'privacy.html').write_text(html)

    def test_legal_query_cannot_include_other_files(self):
        for query in ('document=../../config.php', 'document=terms&version=../../config.php',
                      'document[]=terms', 'document=privacy&version=unknown'):
            status, html, _ = self.legal_page(query)
            self.assertEqual(status, 404)
            self.assertNotIn('db_password', html)
