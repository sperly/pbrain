"""Realtime tool round trips without a microphone, network, or paid requests."""
import json
from pathlib import Path
import sys
from threading import Event
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "desktop"))
import transport


def call_response(name="get_weather", call_id="call_1", arguments=None):
    return {"type": "response.done", "response": {"status": "completed", "output": [
        {"type": "function_call", "name": name, "call_id": call_id,
         "arguments": json.dumps(arguments or {"location": "Stockholm", "country_code": "SE"})}]}}


class FakeSocket:
    def __init__(self, events):
        self.events = iter(events)
        self.sent = []

    def __enter__(self): return self
    def __exit__(self, *args): pass
    def send(self, text): self.sent.append(json.loads(text))
    def recv(self, timeout): return json.dumps(next(self.events))


class VoiceTools(unittest.TestCase):
    def run_voice(self, middle, fail=False, cancel=False):
        stop = Event()
        ws = FakeSocket([
            {"type": "session.updated"},
            {"type": "conversation.item.input_audio_transcription.completed", "transcript": "Weather in Stockholm?"},
            *middle,
            {"type": "response.output_text.delta", "delta": "It is 6 degrees in Stockholm."},
            {"type": "response.done", "response": {"status": "completed", "output": []}},
        ])
        tool_requests = []
        def request(base, action, credential, payload=None):
            if action == 'realtime-secret':
                return {"model": "test-model", "value": "short-lived", "tools": [{"name": "get_weather", "type": "function"}]}
            tool_requests.append(payload)
            if cancel:
                stop.set()
            if fail:
                raise transport.DeviceError('Lookup provider is unavailable')
            return {"current": {"temperature_2m": 6},
                    "sources": [{"title": "Open-Meteo", "url": "https://open-meteo.com/"}]}
        emit = Mock()
        transport.voice('https://example.test', 'credential', b'\0' * 4800, True, [], stop, emit,
                        connector=lambda *a, **kw: ws, request=request)
        return ws, tool_requests, emit

    def test_tool_results_follow_complete_response_and_sources_are_saved(self):
        ws, requests, emit = self.run_voice([
            {"type": "response.function_call_arguments.done", "name": "get_weather", "call_id": "call_1", "arguments": '{}'},
            call_response(),
        ])
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]['arguments']['location'], 'Stockholm')
        results = [event['item'] for event in ws.sent if event.get('item', {}).get('type') == 'function_call_output']
        self.assertEqual(results[0]['call_id'], 'call_1')
        self.assertIn('temperature_2m', results[0]['output'])
        self.assertEqual(len([event for event in ws.sent if event['type'] == 'response.create']), 2)
        emitted_text = ''.join(call.args[1] for call in emit.call_args_list if call.args[0] == 'text')
        self.assertIn('https://open-meteo.com/', emitted_text)
        emit.assert_called_with('done', 'Weather in Stockholm?')

    def test_failed_lookup_returns_explicit_error_to_model(self):
        ws, requests, emit = self.run_voice([call_response()], fail=True)
        output = [event['item']['output'] for event in ws.sent if event.get('item', {}).get('type') == 'function_call_output'][0]
        self.assertIn('lookup_failed', output)
        self.assertIn('Do not invent', output)
        self.assertFalse(any(call.args[0] == 'text' and 'Sources:' in call.args[1] for call in emit.call_args_list))

    def test_tool_rounds_have_a_limit(self):
        ws, requests, emit = self.run_voice([call_response(call_id=f'call_{i}') for i in range(4)])
        self.assertEqual(len(requests), 3)
        self.assertEqual([event for event in ws.sent if event['type'] == 'response.create'][-1]['response']['tool_choice'], 'none')
        self.assertIn('tool_limit', [event['item']['output'] for event in ws.sent
                                    if event.get('item', {}).get('type') == 'function_call_output'][-1])

    def test_cancellation_during_lookup_drops_late_results(self):
        ws, requests, emit = self.run_voice([call_response()], cancel=True)
        self.assertEqual(len(requests), 1)
        self.assertFalse(any(event.get('item', {}).get('type') == 'function_call_output' for event in ws.sent))
        emit.assert_not_called()
