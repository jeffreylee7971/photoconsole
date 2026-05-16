"""Error type enum and exception classification helper."""
from enum import StrEnum


class ErrorType(StrEnum):
    """Canonical set of error_type values stored in the catalog.

    These values are persisted to the database; do not rename members
    without a migration, as downstream queries filter on these strings.
    """
    PERMISSION_DENIED = 'permission_denied'
    READ_ERROR = 'read_error'
    HASH_FAILED = 'hash_failed'
    METADATA_FAILED = 'metadata_failed'
    NOT_FOUND = 'not_found'
    TIMEOUT = 'timeout'


def classify_error(exc: Exception) -> str:
    """Map an exception to one of the ErrorType string values.

    HASH_FAILED and METADATA_FAILED are intentionally excluded here —
    those are assigned by call sites that know which operation failed
    (the hasher and metadata extractors respectively).

    Args:
        exc: The exception that was caught.

    Returns:
        A string matching one of the ErrorType members.
    """
    if isinstance(exc, PermissionError):
        return ErrorType.PERMISSION_DENIED
    if isinstance(exc, FileNotFoundError):
        return ErrorType.NOT_FOUND
    if isinstance(exc, TimeoutError):
        return ErrorType.TIMEOUT
    return ErrorType.READ_ERROR
