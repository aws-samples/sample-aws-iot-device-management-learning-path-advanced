#!/usr/bin/env python3
"""
AWS API Helper Module for AWS IoT Workshop Scripts

This module vendors the shared ``safe_api_call`` construct used across the
AWS IoT Device Management learning-path scripts. In the basics repository this
helper lived as a per-script method duplicated in every script class; here it is
extracted into a single importable, standalone function so that every advanced
provisioning script (JITP/JITR, fleet provisioning by claim, trusted user,
Multi-Account Registration) wraps AWS control-plane calls consistently.

``safe_api_call`` provides:
- Consistent handling of "resource already exists" style conflicts.
- Graceful degradation: on error it returns ``None`` rather than raising, so
  workshop scripts can continue and report a friendly message.
- Optional debug output of the request parameters and API response.
- Gentle client-side rate limiting between calls.
"""

import json
import os
import sys
import time
from typing import Any, Callable, Optional

from botocore.exceptions import ClientError

# Add the repository root to sys.path for the i18n imports (3 levels up from
# iot_helpers/utils/api_helpers.py), the same way dependency_handler.py does.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from i18n.language_selector import peek_language  # noqa: E402
from i18n.loader import load_messages  # noqa: E402

# --- i18n message catalog (i18n/en/api_helpers.json) -----------------------
# Loaded lazily: scripts call set_language() from main() once the runtime
# language is resolved (so a language picked from the interactive menu applies
# here too). If set_language() is never called, the first message lookup loads
# the catalog for peek_language(), which never shows the language menu.
_messages = None


def set_language(code=None):
    """(Re)load this helper's message catalog for ``code`` (default: peek_language())."""
    global _messages
    _messages = load_messages("api_helpers", code or peek_language())


def _get_message(key, *args):
    """Resolve a nested dotted key with positional {} formatting; fall back to the key."""
    if _messages is None:
        set_language()
    msg = _messages
    for part in key.split("."):
        if isinstance(msg, dict) and part in msg:
            msg = msg[part]
        else:
            msg = key  # fall back to the raw key
            break
    if args and isinstance(msg, str):
        return msg.format(*args)
    return msg


# Error codes that indicate the resource already exists and can be treated as a
# non-fatal, idempotent outcome by workshop scripts.
ALREADY_EXISTS_ERROR_CODES = (
    "ResourceAlreadyExistsException",
    "ConflictException",
)

# Client-side rate limiting applied after every call (seconds).
RATE_LIMIT_SECONDS = 0.125

# Request/response field names that carry certificate or key material. Every
# script that calls safe_api_call eventually passes a caCertificate,
# certificatePem, verificationCertificate, or a create_keys_and_certificate
# response's keyPair/PrivateKey/PublicKey through here, so debug=True must
# never dump these verbatim. Matched case-insensitively so this also catches
# API-specific casings the exact-name list below might miss.
_SENSITIVE_FIELD_NAMES = {
    "cacertificate",
    "certificatepem",
    "verificationcertificate",
    "privatekey",
    "publickey",
    "keypair",
}


def _redact(value):
    """Recursively replace known-sensitive fields with a truncated preview.

    Mirrors the truncation style already used by fleet_provision_trusted_user.py's
    _fmt_payload (first line + a character count) rather than a bare
    "***REDACTED***" marker, so debug output still shows enough to confirm which
    PEM/key landed in a given field without printing the material itself.
    """
    if isinstance(value, dict):
        redacted = {}
        for key, val in value.items():
            if isinstance(key, str) and key.lower() in _SENSITIVE_FIELD_NAMES and isinstance(val, str):
                first_line = val.strip().splitlines()[0] if val.strip() else ""
                redacted[key] = _get_message("debug.truncated_value", first_line, len(val))
            else:
                redacted[key] = _redact(val)
        return redacted
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def safe_api_call(
    func: Callable[..., Any],
    operation_name: str,
    resource_name: str,
    debug: bool = False,
    **kwargs: Any,
) -> Optional[Any]:
    """
    Safely execute an AWS API call with error handling and optional debug info.

    This is the reusable control-plane wrapper the workshop uses in front of
    ``boto3`` / ``aws iot`` operations. It mirrors the behavior of the basics
    workshop scripts but is packaged as a standalone, importable function.

    Args:
        func: The bound boto3 client method to invoke (e.g. ``iot_client.create_thing``).
        operation_name: Human-readable operation label used in log output
            (e.g. "Create Thing"). Callers pass an already-localized label
            from their own catalog's "operations" category.
        resource_name: Human-readable resource label used in log output
            (e.g. the thing name).
        debug: When True, print the request parameters and the API response.
        **kwargs: Keyword arguments forwarded to ``func``.

    Returns:
        The API response dictionary on success, or ``None`` if the call failed
        or the resource already existed.

    Examples:
        >>> safe_api_call(
        ...     iot_client.create_thing,
        ...     "Create Thing",
        ...     "Vehicle-VIN-001",
        ...     thingName="Vehicle-VIN-001",
        ... )
    """
    try:
        if debug:
            print(_get_message("debug.header", operation_name, resource_name))
            print(_get_message("debug.api_call", func.__name__))
            print(_get_message("debug.input_parameters"))
            print(json.dumps(_redact(kwargs), indent=2, default=str))
        else:
            print(_get_message("status.in_progress", operation_name, resource_name))

        response = func(**kwargs)

        if debug:
            print(_get_message("debug.api_response"))
            print(json.dumps(_redact(response), indent=2, default=str))

        print(_get_message("status.ready", operation_name, resource_name))
        time.sleep(RATE_LIMIT_SECONDS)  # Rate limiting  # nosemgrep: arbitrary-sleep
        return response

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        if error_code in ALREADY_EXISTS_ERROR_CODES:
            print(_get_message("status.already_exists", operation_name, resource_name))
        else:
            # The AWS error message itself is passed through untranslated.
            error_message = e.response["Error"]["Message"]
            print(_get_message("errors.api_error", operation_name, resource_name, error_message))
            if debug:
                print(_get_message("debug.full_error"))
                print(json.dumps(_redact(e.response), indent=2, default=str))
        time.sleep(RATE_LIMIT_SECONDS)  # nosemgrep: arbitrary-sleep
        return None

    except Exception as e:  # noqa: BLE001 - workshop scripts degrade gracefully
        print(_get_message("errors.unexpected", str(e)))
        if debug:
            import traceback

            print(_get_message("debug.full_traceback"))
            traceback.print_exc()
        time.sleep(RATE_LIMIT_SECONDS)  # nosemgrep: arbitrary-sleep
        return None
