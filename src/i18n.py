import json
import os

SUPPORTED_LANGUAGES = {
    "en": "English",
    "hi": "हिंदी",
    "mr": "मराठी"
}
DEFAULT_LANGUAGE = "en"

TRANSLATIONS_DIR = os.path.join(os.path.dirname(__file__), os.pardir, "translations")

_translations = {}


def _load_translations():
    global _translations
    if _translations:
        return _translations

    translations = {}
    for lang in SUPPORTED_LANGUAGES:
        path = os.path.join(TRANSLATIONS_DIR, f"{lang}.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                translations[lang] = json.load(f)
        except FileNotFoundError:
            translations[lang] = {}
        except json.JSONDecodeError:
            translations[lang] = {}
    _translations = translations
    return _translations


def get_translation(key, lang=None):
    lang = lang or DEFAULT_LANGUAGE
    translations = _load_translations()
    if lang not in translations:
        lang = DEFAULT_LANGUAGE
    data = translations.get(lang, {})
    value = data
    for part in key.split("."):
        if isinstance(value, dict) and part in value:
            value = value[part]
        else:
            value = None
            break
    if value is not None:
        return value
    if lang != DEFAULT_LANGUAGE:
        return get_translation(key, DEFAULT_LANGUAGE)
    return key


def get_language_label(lang_code):
    return SUPPORTED_LANGUAGES.get(lang_code, SUPPORTED_LANGUAGES[DEFAULT_LANGUAGE])
