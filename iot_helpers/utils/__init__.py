"""
Utility Functions Module

Provides utility functions for naming conventions, resource tagging,
dependency management, and the shared ``safe_api_call`` control-plane wrapper.
"""

from .naming_conventions import (
    generate_thing_name,
    validate_thing_prefix,
    matches_workshop_pattern,
    NAMING_PATTERNS,
)
from .resource_tagger import apply_workshop_tags, WORKSHOP_TAGS
from .dependency_handler import DependencyHandler, DELETION_ORDER, check_openssl_available
from .api_helpers import safe_api_call

__all__ = [
    "generate_thing_name",
    "validate_thing_prefix",
    "matches_workshop_pattern",
    "NAMING_PATTERNS",
    "apply_workshop_tags",
    "WORKSHOP_TAGS",
    "DependencyHandler",
    "DELETION_ORDER",
    "check_openssl_available",
    "safe_api_call",
]
