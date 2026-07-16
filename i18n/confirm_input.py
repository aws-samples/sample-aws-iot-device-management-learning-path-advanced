# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Localized yes/no input confirmation utility.

Provides a single function to check if user input is an affirmative response,
supporting all languages available in this project.

Vendored from the AWS IoT Core Learning SDK (sample-aws-iot-core-learning-path-basics)
because the reused device-plane construct `certificate_manager.py` imports
`is_yes` from this module. It coexists with `confirmation.py` (the Device
Management basics helper used by the control-plane constructs).
"""

# Accepted affirmative responses per language
# Each language maps to its common "yes" variants (full word + single letter shortcut)
_YES_RESPONSES = {
    "en": ["y", "yes"],
    "es": ["s", "si", "sí", "yes", "y"],
    "ja": ["y", "yes", "はい", "hai"],
    "zh": ["y", "yes", "是", "是的", "shi"],
    "zh-CN": ["y", "yes", "是", "是的", "shi"],
    "ko": ["y", "yes", "네", "예", "ne"],
    "pt": ["s", "sim", "yes", "y"],
    "pt-BR": ["s", "sim", "yes", "y"],
    "de": ["j", "ja", "yes", "y"],
    "it": ["s", "si", "sì", "yes", "y"],
    "fr": ["o", "oui", "yes", "y"],
}

# Flat set of ALL accepted yes responses across all languages
_ALL_YES = set()
for _responses in _YES_RESPONSES.values():
    _ALL_YES.update(_responses)


def is_yes(user_input, language=None):
    """
    Check if user input is an affirmative (yes) response.

    Args:
        user_input: The raw string from input(), will be stripped and lowercased.
        language: Optional language code (e.g. 'it', 'fr', 'de').
                  If provided, checks only that language's accepted values plus English.
                  If None, accepts any language's affirmative response.

    Returns:
        True if the input is a recognized "yes" in the given (or any) language.
    """
    normalized = user_input.strip().lower()

    if language is None:
        return normalized in _ALL_YES

    # Check specific language + English fallback
    accepted = set(_YES_RESPONSES.get("en", []))
    accepted.update(_YES_RESPONSES.get(language, []))
    return normalized in accepted
