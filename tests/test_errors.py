"""Tests for photoconsole.errors — ErrorType enum and classify_error helper."""
import pytest
from photoconsole.errors import ErrorType, classify_error


class TestErrorType:
    def test_error_type_has_six_members(self):
        members = list(ErrorType)
        assert len(members) == 6

    def test_permission_denied_value(self):
        assert ErrorType.PERMISSION_DENIED == "permission_denied"

    def test_read_error_value(self):
        assert ErrorType.READ_ERROR == "read_error"

    def test_hash_failed_value(self):
        assert ErrorType.HASH_FAILED == "hash_failed"

    def test_metadata_failed_value(self):
        assert ErrorType.METADATA_FAILED == "metadata_failed"

    def test_not_found_value(self):
        assert ErrorType.NOT_FOUND == "not_found"

    def test_timeout_value(self):
        assert ErrorType.TIMEOUT == "timeout"

    def test_error_type_is_str(self):
        """StrEnum members must behave as plain strings."""
        assert isinstance(ErrorType.PERMISSION_DENIED, str)
        assert ErrorType.PERMISSION_DENIED == "permission_denied"

    def test_all_values_are_lower_snake_case(self):
        for member in ErrorType:
            assert member.value == member.value.lower()
            assert " " not in member.value


class TestClassifyError:
    def test_permission_error_returns_permission_denied(self):
        assert classify_error(PermissionError()) == "permission_denied"

    def test_file_not_found_returns_not_found(self):
        assert classify_error(FileNotFoundError()) == "not_found"

    def test_timeout_error_returns_timeout(self):
        assert classify_error(TimeoutError()) == "timeout"

    def test_runtime_error_returns_read_error(self):
        assert classify_error(RuntimeError()) == "read_error"

    def test_default_is_read_error(self):
        assert classify_error(Exception()) == "read_error"
        assert classify_error(ValueError()) == "read_error"
        assert classify_error(OSError()) == "read_error"

    def test_returns_string_not_enum(self):
        """classify_error should return a str (StrEnum is-a str)."""
        result = classify_error(PermissionError())
        assert isinstance(result, str)

    def test_classify_error_permission_is_checked_before_oserror(self):
        """PermissionError is a subclass of OSError; must match PermissionError first."""
        # PermissionError is OSError subclass; ensure it hits 'permission_denied', not default
        exc = PermissionError("no access")
        assert classify_error(exc) == "permission_denied"
