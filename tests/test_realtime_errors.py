"""Exercise Realtime billing errors through the same voice client as the UI."""
import json
from pathlib import Path
import sys
from threading import Event
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'desktop'))
import transport


class RealtimeErrors(unittest.TestCase):
    def voice_failure(self, events):
        socket = Mock()
        socket.recv.side_effect = [json.dumps(event) for event in events]
        connector = Mock()
        connector.return_value.__enter__ = Mock(return_value=socket)
        connector.return_value.__exit__ = Mock(return_value=False)
        emit = Mock()
        with self.assertRaises(transport.DeviceError) as raised:
            transport.voice('https://example.test', 'device-token', b'\0' * 12000,
                            False, [], Event(), emit, connector=connector,
                            request=Mock(return_value={'value': 'short-lived-test-secret', 'model': 'test-model'}))
        emit.assert_not_called()
        return str(raised.exception)

    def test_session_credit_error_explains_billing_action(self):
        message = self.voice_failure([{'type': 'error', 'error': {
            'code': 'credit_balance_exhausted', 'type': 'insufficient_quota',
            'message': 'private account details must not be displayed',
        }}])
        self.assertIn('OpenAI API credits are exhausted', message)
        self.assertIn('OpenAI Platform billing', message)
        self.assertIn('retry the saved question', message)
        self.assertNotIn('private account details', message)

    def test_failed_response_also_explains_credit_error(self):
        message = self.voice_failure([
            {'type': 'session.updated'},
            {'type': 'response.done', 'response': {'status': 'failed', 'status_details': {
                'error': {'code': 'credit_balance_exhausted'},
            }}},
        ])
        self.assertIn('OpenAI API credits are exhausted', message)

    def test_other_errors_retain_code_without_upstream_message(self):
        message = self.voice_failure([{'type': 'error', 'error': {
            'code': 'invalid_event', 'message': 'private details',
        }}])
        self.assertIn('invalid_event', message)
        self.assertNotIn('private details', message)


if __name__ == '__main__':
    unittest.main()
