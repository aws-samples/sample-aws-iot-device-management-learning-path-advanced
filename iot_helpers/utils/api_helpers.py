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
import time
from typing import Any, Callable, Optional

from botocore.exceptions import ClientError

# Error codes that indicate the resource already exists and can be treated as a
# non-fatal, idempotent outcome by workshop scripts.
ALREADY_EXISTS_ERROR_CODES = (
    "ResourceAlreadyExistsException",
    "ConflictException",
)

# Client-side rate limiting applied after every call (seconds).
RATE_LIMIT_SECONDS = 0.125


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
            (e.g. "Create Thing").
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
            print(f"\n🔍 DEBUG: {operation_name} -> {resource_name}")
            print(f"   API call: {func.__name__}")
            print("   Input parameters:")
            print(json.dumps(kwargs, indent=2, default=str))
        else:
            print(f"⚙️  {operation_name}: creating {resource_name}...")

        response = func(**kwargs)

        if debug:
            print("   API response:")
            print(json.dumps(response, indent=2, default=str))

        print(f"✅ {operation_name}: {resource_name} ready")
        time.sleep(RATE_LIMIT_SECONDS)  # Rate limiting  # nosemgrep: arbitrary-sleep
        return response

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        if error_code in ALREADY_EXISTS_ERROR_CODES:
            print(f"ℹ️  {operation_name}: {resource_name} already exists, continuing")
        else:
            error_message = e.response["Error"]["Message"]
            print(f"❌ {operation_name}: error creating {resource_name}: {error_message}")
            if debug:
                print("   Full error:")
                print(json.dumps(e.response, indent=2, default=str))
        time.sleep(RATE_LIMIT_SECONDS)  # nosemgrep: arbitrary-sleep
        return None

    except Exception as e:  # noqa: BLE001 - workshop scripts degrade gracefully
        print(f"❌ Error: {str(e)}")
        if debug:
            import traceback

            print("   Full traceback:")
            traceback.print_exc()
        time.sleep(RATE_LIMIT_SECONDS)  # nosemgrep: arbitrary-sleep
        return None
