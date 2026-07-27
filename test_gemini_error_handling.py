import json
import sys

import pytest

sys.path.insert(0, 'd:\\e drive\\Only_Project\\dr_cnn')

import src.chatbot.bot as bot


class DummyResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


def test_chatbot_response_surfaces_gemini_429_details(monkeypatch, capsys):
    monkeypatch.setattr(bot, 'GEMINI_API_KEY', 'AQ.test-key')
    monkeypatch.setattr(bot, 'GEMINI_MODELS', ['gemini-2.5-flash'])
    monkeypatch.setattr(bot, 'GENAI_AVAILABLE', False)
    monkeypatch.setattr(bot, 'rate_limit_check', lambda: True)
    monkeypatch.setattr(bot.time, 'sleep', lambda *_: None)

    payload = {
        'error': {
            'code': 429,
            'message': 'You exceeded your current quota',
            'status': 'RESOURCE_EXHAUSTED',
            'details': [{
                '@type': 'type.googleapis.com/google.rpc.QuotaFailure',
                'violations': [{
                    'quotaMetric': 'generativelanguage.googleapis.com/generate_content_free_tier_requests',
                    'quotaId': 'GenerateRequestsPerDayPerProjectPerModel-FreeTier',
                    'quotaDimensions': {'model': 'gemini-2.5-flash'},
                    'quotaValue': '20'
                }]
            }]
        }
    }

    def fake_post(url, headers, json, timeout):
        return DummyResponse(429, payload)

    monkeypatch.setattr(bot.requests, 'post', fake_post)

    with pytest.raises(RuntimeError) as exc_info:
        bot.chatbot_response('Hello', strict=True)

    message = str(exc_info.value)
    assert '429' in message
    assert 'quota' in message.lower()

    captured = capsys.readouterr().out
    assert 'HTTP Status' in captured
    assert 'Error Code' in captured
    assert 'Full JSON Response' in captured
    assert 'quota exceeded' in captured.lower()


def test_chatbot_response_falls_back_to_next_supported_model(monkeypatch):
    monkeypatch.setattr(bot, 'GEMINI_API_KEY', 'AQ.test-key')
    monkeypatch.setattr(bot, 'GEMINI_MODELS', ['gemini-2.5-flash', 'gemini-1.5-flash'])
    monkeypatch.setattr(bot, 'GENAI_AVAILABLE', False)
    monkeypatch.setattr(bot, 'rate_limit_check', lambda: True)
    monkeypatch.setattr(bot.time, 'sleep', lambda *_: None)

    quota_payload = {
        'error': {
            'code': 429,
            'message': 'You exceeded your current quota',
            'status': 'RESOURCE_EXHAUSTED',
            'details': [{
                '@type': 'type.googleapis.com/google.rpc.QuotaFailure',
                'violations': [{
                    'quotaMetric': 'generativelanguage.googleapis.com/generate_content_free_tier_requests',
                    'quotaId': 'GenerateRequestsPerDayPerProjectPerModel-FreeTier',
                    'quotaDimensions': {'model': 'gemini-2.5-flash'},
                    'quotaValue': '20'
                }]
            }]
        }
    }

    success_payload = {
        'candidates': [{
            'content': {'parts': [{'text': 'fallback reply'}]}
        }]
    }

    responses = iter([DummyResponse(429, quota_payload), DummyResponse(200, success_payload)])

    def fake_post(url, headers, json, timeout):
        return next(responses)

    monkeypatch.setattr(bot.requests, 'post', fake_post)

    reply = bot.chatbot_response('Hello', strict=True)

    assert reply == 'fallback reply'
