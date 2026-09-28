import json
import os

DEFAULT_LANGUAGE = "en"


def load_messages(script_name, language):
    """Load messages for a specific script and language, with an English fallback.

    English is always loaded first, then the requested language's catalog is
    overlaid on top of it (a shallow, top-level-key merge, same as the two
    ``messages.update(...)`` calls below). Only ``i18n/en/`` ships catalogs
    today (see ``i18n/README.md``); every other advertised language silently
    fell back to raw, untranslated message keys (for example
    ``status.discovering_cas``) rather than English text, because nothing
    loaded ``en`` first when a non-English language was requested. Loading
    English unconditionally means every language selection produces real
    text now, in English until a language's own catalog exists — and a
    catalog that ships later for that language is picked up with no code
    change, since it simply overlays more keys on top of the same English
    base.
    """
    base_path = os.path.dirname(__file__)

    # Load common messages
    common_file = os.path.join(base_path, "common.json")
    messages = {}
    if os.path.exists(common_file):
        with open(common_file, "r", encoding="utf-8") as f:
            messages.update(json.load(f))

    # Load the English script-specific catalog first, unconditionally, as the
    # fallback base.
    default_file = os.path.join(base_path, DEFAULT_LANGUAGE, f"{script_name}.json")
    if os.path.exists(default_file):
        with open(default_file, "r", encoding="utf-8") as f:
            messages.update(json.load(f))

    # Overlay the requested language's catalog on top, if it differs from the
    # default and actually exists.
    if language != DEFAULT_LANGUAGE:
        script_file = os.path.join(base_path, language, f"{script_name}.json")
        if os.path.exists(script_file):
            with open(script_file, "r", encoding="utf-8") as f:
                messages.update(json.load(f))

    return messages
