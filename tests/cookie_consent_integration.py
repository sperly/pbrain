"""Cookie preferences through the real PHP session/CSRF flow."""
from http.cookies import SimpleCookie
import unittest
import openai_keys_integration as env


class CookieConsentIntegration(unittest.TestCase):
    def setUp(self):
        env.sql('DELETE FROM auth_rate_limits;')
        self.browser = env.Browser()
        self.browser.page()

    def test_initial_banner_explains_essential_cookies(self):
        status, html = self.browser.page()
        self.assertEqual(status, 200)
        self.assertIn('id="cookie-banner"', html)
        self.assertIn('Accept optional cookies', html)
        self.assertIn('Reject optional cookies', html)
        self.assertIn('They stay active with either option.', html)
        self.assertIn('No optional analytics or advertising cookies are currently used.', html)

    def test_accept_is_remembered_and_can_be_changed(self):
        status, _ = self.browser.page({'action': 'cookie-accept', 'csrf': self.browser.csrf})
        self.assertEqual(status, 303)
        self.assertIn('PocketBrainCookieConsent=accepted', self.browser.cookie)
        _, html = self.browser.page()
        self.assertNotIn('id="cookie-banner"', html)
        self.assertIn('Cookie preferences', html)
        _, html = self.browser.page(params={'cookie-settings': '1'})
        self.assertIn('id="cookie-banner"', html)
        self.assertIn('Your saved choice: accept optional cookies.', html)
        self.browser.page({'action': 'cookie-reject', 'csrf': self.browser.csrf})
        self.assertIn('PocketBrainCookieConsent=rejected', self.browser.cookie)

    def test_reject_keeps_login_working_and_sets_secure_preference(self):
        status, _ = self.browser.page({'action': 'cookie-reject', 'csrf': self.browser.csrf})
        self.assertEqual(status, 303)
        cookies = SimpleCookie()
        for header in self.browser.last_headers.get_all('Set-Cookie', []):
            cookies.load(header)
        preference = cookies['PocketBrainCookieConsent']
        self.assertTrue(preference['secure'])
        self.assertTrue(preference['httponly'])
        self.assertEqual(preference['samesite'], 'Lax')
        self.assertTrue(preference['expires'])
        self.browser.login('one@example.test')
        _, html = self.browser.page()
        self.assertIn('My devices', html)
        self.assertNotIn('id="cookie-banner"', html)
        self.assertIn('PocketBrainCookieConsent=rejected', self.browser.cookie)

    def test_bad_csrf_cannot_change_choice(self):
        status, _ = self.browser.page({'action': 'cookie-accept', 'csrf': 'wrong'})
        self.assertEqual(status, 403)
        self.assertNotIn('PocketBrainCookieConsent=', self.browser.cookie)

    def test_invalid_preference_is_not_treated_as_consent(self):
        self.browser.cookie += '; PocketBrainCookieConsent=unknown'
        self.assertIn('id="cookie-banner"', self.browser.page()[1])

    def test_choice_redirect_keeps_conversation_context_and_is_local(self):
        status, _ = self.browser.page({'action': 'cookie-reject', 'csrf': self.browser.csrf},
                                     params={'device': '1', 'conversation': '12', 'cookie-settings': '1', 'next': 'https://evil.example'})
        self.assertEqual(status, 303)
        self.assertEqual(self.browser.last_headers['Location'], 'index.php?device=1&conversation=12')
