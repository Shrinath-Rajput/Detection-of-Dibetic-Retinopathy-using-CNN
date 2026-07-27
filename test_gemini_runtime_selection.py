import sys

sys.path.insert(0, 'd:\\e drive\\Only_Project\\dr_cnn')

import src.chatbot.bot as bot


class DummyResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload


def test_discover_supported_models_prefers_generate_content_models(monkeypatch):
    monkeypatch.setattr(bot, 'GEMINI_API_KEY', 'AQ.test-key')
    monkeypatch.setattr(bot, 'GEMINI_MODELS', ['gemini-2.5-flash', 'gemini-1.5-flash'])

    payload = {
        'models': [
            {
                'name': 'models/gemini-2.5-flash',
                'supportedGenerationMethods': ['generateContent', 'countTokens'],
            },
            {
                'name': 'models/gemini-2.0-flash',
                'supportedGenerationMethods': ['generateContent'],
            },
            {
                'name': 'models/gemini-1.5-flash',
                'supportedGenerationMethods': ['countTokens'],
            },
        ]
    }

    monkeypatch.setattr(bot.requests, 'get', lambda url, timeout=20: DummyResponse(200, payload))

    models = bot.discover_supported_gemini_models('AQ.test-key')

    assert models == ['gemini-2.5-flash', 'gemini-2.0-flash']
