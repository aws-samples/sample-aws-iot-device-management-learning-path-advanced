import json
import os

DEFAULT_LANGUAGE = "en"


def load_messages(script_name, language):
    """Load messages for a specific script and language, with an English fallback.

    English is always loaded first, then the requested language's catalog is
    overlaid on top of it with a deep, per-key merge (see ``_deep_merge``).
    Any key the translated catalog does not provide, at any nesting level,
    keeps its English text, so a language with a partial or no catalog still
    prints real text instead of raw dotted keys such as
    ``status.discovering_cas``. New language catalogs are picked up with no
    code change.
    """
    base_path = os.path.dirname(__file__)

    # Load common messages
    common_file = os.path.join(base_path, "common.json")
    messages = {}
    if os.path.exists(common_file):
        with open(common_file, "r", encoding="utf-8") as f:
            messages.update(json.load(f))
    # Optional per-language overlay of the shared keys (i18n/<lang>/common.json),
    # merged key by key so untranslated shared keys keep their English text.
    if language != DEFAULT_LANGUAGE:
        common_lang_file = os.path.join(base_path, language, "common.json")
        if os.path.exists(common_lang_file):
            with open(common_lang_file, "r", encoding="utf-8") as f:
                _deep_merge(messages, json.load(f))

    # Load the English script-specific catalog first, unconditionally, as the
    # fallback base.
    default_file = os.path.join(base_path, DEFAULT_LANGUAGE, f"{script_name}.json")
    if os.path.exists(default_file):
        with open(default_file, "r", encoding="utf-8") as f:
            messages.update(json.load(f))

    # Overlay the requested language's catalog on top, if it differs from the
    # default and actually exists. The overlay is a deep, per-key merge: a
    # translated catalog that is missing a single nested key keeps the English
    # text for that key instead of hiding the whole English category.
    if language != DEFAULT_LANGUAGE:
        script_file = os.path.join(base_path, language, f"{script_name}.json")
        if os.path.exists(script_file):
            with open(script_file, "r", encoding="utf-8") as f:
                _deep_merge(messages, json.load(f))

    return messages


def _deep_merge(base, overlay):
    """Recursively merge ``overlay`` into ``base`` in place, key by key.

    Nested dicts are merged; any other value (string, list) in ``overlay``
    replaces the value in ``base``. Keys only present in ``base`` are kept, so
    they act as the English fallback.
    """
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base
