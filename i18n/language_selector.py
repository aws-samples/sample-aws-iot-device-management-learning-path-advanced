import os
import sys

LANGUAGE_SELECTION = {
    "header": "🌍 Language Selection / Selección de Idioma / 言語選択 / 语言选择 / Seleção de Idioma / 언어 선택 / Sprachauswahl / Selezione della Lingua / Sélection de la Langue",
    "options": [
        "1. English",
        "2. Español (Spanish)",
        "3. 日本語 (Japanese)",
        "4. 中文 (Chinese)",
        "5. Português (Portuguese)",
        "6. 한국어 (Korean)",
        "7. Deutsch (German)",
        "8. Italiano (Italian)",
        "9. Français (French)",
    ],
    "prompt": "Select language (1-9): ",
    "invalid": "❌ Invalid selection. Please enter 1-9.",
}

LANGUAGE_CODES = {"1": "en", "2": "es", "3": "ja", "4": "zh", "5": "pt", "6": "ko", "7": "de", "8": "it", "9": "fr"}


def _normalize_env_language():
    """Return the normalized language code for AWS_IOT_LANG, or None if unset/unknown."""
    env_lang = os.getenv("AWS_IOT_LANG", "").lower()
    if env_lang in ["es", "spanish", "español"]:
        return "es"
    elif env_lang in ["en", "english"]:
        return "en"
    elif env_lang in ["ja", "japanese", "日本語", "jp"]:
        return "ja"
    elif env_lang in ["zh-cn", "chinese", "中文", "zh"]:
        return "zh"
    elif env_lang in ["pt", "pt-br", "portuguese", "português"]:
        return "pt"
    elif env_lang in ["ko", "korean", "한국어", "kr"]:
        return "ko"
    elif env_lang in ["de", "german", "deutsch"]:
        return "de"
    elif env_lang in ["it", "italian", "italiano"]:
        return "it"
    elif env_lang in ["fr", "french", "français", "francais"]:
        return "fr"
    return None


def peek_language():
    """Return the language for AWS_IOT_LANG without ever prompting.

    Returns the same normalized code get_language() would return for the
    AWS_IOT_LANG environment variable, or "en" when it is unset or unknown.
    Used to localize argparse help text, which is built before the language
    is chosen, so ``--help`` never shows the interactive language menu.
    """
    return _normalize_env_language() or "en"


def get_language():
    """Get language from environment or user selection"""
    # Check environment variable first
    env_code = _normalize_env_language()
    if env_code:
        return env_code

    # Interactive selection
    print(LANGUAGE_SELECTION["header"])
    for option in LANGUAGE_SELECTION["options"]:
        print(option)

    while True:
        try:
            choice = input(LANGUAGE_SELECTION["prompt"]).strip()
            if choice in LANGUAGE_CODES:
                return LANGUAGE_CODES[choice]
            print(LANGUAGE_SELECTION["invalid"])
        except KeyboardInterrupt:
            print("\n\nGoodbye! / ¡Adiós! / さようなら！ / 再见！ / Tchau! / 안녕히 가세요!")
            sys.exit(0)
