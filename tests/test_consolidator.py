"""Unit tests for photoconsole.consolidator — Phase 02 Plan 03.

Covers:
    Task 1: compute_dest_path(), CopyAction dataclass, ConsolidationPlan dataclass
    Task 2: resolve_conflict(), copy_and_verify()

All tests use tmp_path (pytest fixture) for real filesystem I/O; no mocking of stdlib.
Tests are intentionally written *before* implementation (TDD RED phase).
"""
from __future__ import annotations

import hashlib
import pathlib

import pytest


# ---------------------------------------------------------------------------
# Task 1: compute_dest_path
# ---------------------------------------------------------------------------

class TestComputeDestPath:
    """compute_dest_path(filename, date_taken, mtime, destination_root) -> Path."""

    def test_exif_colon_format(self, tmp_path):
        """date_taken in canonical EXIF format '2023:06:15 10:30:00' → YYYY/MM/name."""
        from photoconsole.consolidator import compute_dest_path

        result = compute_dest_path("IMG_1234.jpg", "2023:06:15 10:30:00", None, str(tmp_path))
        assert result == tmp_path / "2023" / "06" / "IMG_1234.jpg"

    def test_exif_dash_format(self, tmp_path):
        """date_taken in ISO-like format '2023-06-15 10:30:00' → YYYY/MM/name."""
        from photoconsole.consolidator import compute_dest_path

        result = compute_dest_path("IMG_1234.jpg", "2023-06-15 10:30:00", None, str(tmp_path))
        assert result == tmp_path / "2023" / "06" / "IMG_1234.jpg"

    def test_exif_iso8601_format(self, tmp_path):
        """date_taken in ISO 8601 format '2023-06-15T10:30:00' → YYYY/MM/name."""
        from photoconsole.consolidator import compute_dest_path

        result = compute_dest_path("IMG_1234.jpg", "2023-06-15T10:30:00", None, str(tmp_path))
        assert result == tmp_path / "2023" / "06" / "IMG_1234.jpg"

    def test_mtime_fallback_no_date_taken(self, tmp_path):
        """date_taken=None, mtime provided → unknown/YYYY/MM/name using fromtimestamp."""
        from photoconsole.consolidator import compute_dest_path
        import datetime

        mtime = 1686823800.0  # a known timestamp
        dt = datetime.datetime.fromtimestamp(mtime)
        result = compute_dest_path("VID.mp4", None, mtime, str(tmp_path))
        expected = tmp_path / "unknown" / dt.strftime("%Y") / dt.strftime("%m") / "VID.mp4"
        assert result == expected

    def test_both_none_falls_to_unknown_flat(self, tmp_path):
        """date_taken=None, mtime=None → unknown/filename."""
        from photoconsole.consolidator import compute_dest_path

        result = compute_dest_path("VID.mp4", None, None, str(tmp_path))
        assert result == tmp_path / "unknown" / "VID.mp4"

    def test_unparseable_date_falls_through_to_mtime(self, tmp_path):
        """date_taken='not-a-date', mtime available → falls through to mtime/unknown/YYYY/MM."""
        from photoconsole.consolidator import compute_dest_path
        import datetime

        mtime = 1686823800.0
        dt = datetime.datetime.fromtimestamp(mtime)
        result = compute_dest_path("IMG.jpg", "not-a-date", mtime, str(tmp_path))
        expected = tmp_path / "unknown" / dt.strftime("%Y") / dt.strftime("%m") / "IMG.jpg"
        assert result == expected

    def test_only_filename_basename_used(self, tmp_path):
        """compute_dest_path uses only the basename of filename, not the full path."""
        from photoconsole.consolidator import compute_dest_path

        result = compute_dest_path("/some/long/path/to/IMG_1234.jpg", "2023:06:15 10:30:00", None, str(tmp_path))
        assert result.name == "IMG_1234.jpg"


# ---------------------------------------------------------------------------
# Task 1: CopyAction dataclass
# ---------------------------------------------------------------------------

class TestCopyAction:
    """CopyAction dataclass: src_path, dest_path, hash, source_name, action."""

    def test_valid_copy_action(self):
        """CopyAction can be instantiated with all required fields."""
        from photoconsole.consolidator import CopyAction

        ca = CopyAction(
            src_path="x/file.jpg",
            dest_path="y/file.jpg",
            hash="abc123",
            source_name="OneDrive",
            action="copy",
        )
        assert ca.src_path == "x/file.jpg"
        assert ca.dest_path == "y/file.jpg"
        assert ca.hash == "abc123"
        assert ca.source_name == "OneDrive"
        assert ca.action == "copy"

    def test_action_skip_idempotent(self):
        """action='skip_idempotent' is a valid CopyAction action."""
        from photoconsole.consolidator import CopyAction

        ca = CopyAction(
            src_path="x", dest_path="y", hash="h", source_name="S",
            action="skip_idempotent",
        )
        assert ca.action == "skip_idempotent"

    def test_action_error(self):
        """action='error' is a valid CopyAction action."""
        from photoconsole.consolidator import CopyAction

        ca = CopyAction(
            src_path="x", dest_path="y", hash="h", source_name="S",
            action="error",
        )
        assert ca.action == "error"


# ---------------------------------------------------------------------------
# Task 1: ConsolidationPlan dataclass
# ---------------------------------------------------------------------------

class TestConsolidationPlan:
    """ConsolidationPlan dataclass with four default-empty list fields."""

    def test_default_empty_lists(self):
        """ConsolidationPlan() has empty to_copy, to_manifest, skipped, errors."""
        from photoconsole.consolidator import ConsolidationPlan

        plan = ConsolidationPlan()
        assert plan.to_copy == []
        assert plan.to_manifest == []
        assert plan.skipped == []
        assert plan.errors == []

    def test_mutable_lists_are_independent(self):
        """Each ConsolidationPlan instance has independent list fields."""
        from photoconsole.consolidator import ConsolidationPlan

        plan1 = ConsolidationPlan()
        plan2 = ConsolidationPlan()
        plan1.to_copy.append("something")
        assert plan2.to_copy == []  # must be a separate list

    def test_can_populate_fields(self):
        """ConsolidationPlan fields can be populated after construction."""
        from photoconsole.consolidator import CopyAction, ConsolidationPlan

        ca = CopyAction(src_path="a", dest_path="b", hash="h", source_name="S", action="copy")
        plan = ConsolidationPlan()
        plan.to_copy.append(ca)
        assert len(plan.to_copy) == 1
        assert plan.to_copy[0] is ca


# ---------------------------------------------------------------------------
# Task 2: resolve_conflict
# ---------------------------------------------------------------------------

class TestResolveConflict:
    """resolve_conflict(desired_dest: Path, src_hash: str) -> Path | None."""

    def test_non_existent_dest_returns_dest(self, tmp_path):
        """Non-existent destination is returned as-is."""
        from photoconsole.consolidator import resolve_conflict

        fresh = tmp_path / "2023" / "06" / "IMG.jpg"
        result = resolve_conflict(fresh, "any_hash")
        assert result == fresh

    def test_same_hash_returns_none(self, tmp_path):
        """Existing dest with same hash returns None (idempotent skip per D-09)."""
        from photoconsole.consolidator import resolve_conflict

        existing = tmp_path / "existing.jpg"
        existing.write_bytes(b"hello world")
        real_hash = hashlib.sha256(b"hello world").hexdigest()
        result = resolve_conflict(existing, real_hash)
        assert result is None

    def test_different_hash_returns_stem_2(self, tmp_path):
        """Existing dest with different hash returns parent/stem_2.ext (D-08)."""
        from photoconsole.consolidator import resolve_conflict

        existing = tmp_path / "IMG.jpg"
        existing.write_bytes(b"original")
        result = resolve_conflict(existing, "different_hash_value")
        assert result == tmp_path / "IMG_2.jpg"

    def test_stem_2_occupied_same_hash_returns_none(self, tmp_path):
        """stem_2.ext exists with same hash → idempotent at conflict slot → None."""
        from photoconsole.consolidator import resolve_conflict

        # Both the original and stem_2 exist
        existing = tmp_path / "IMG.jpg"
        existing.write_bytes(b"original")
        stem2 = tmp_path / "IMG_2.jpg"
        stem2.write_bytes(b"target_content")
        target_hash = hashlib.sha256(b"target_content").hexdigest()

        # src_hash matches stem2, so resolve_conflict should short-circuit and return None
        result = resolve_conflict(existing, target_hash)
        assert result is None

    def test_stem_2_occupied_different_hash_tries_stem_3(self, tmp_path):
        """stem_2.ext occupied with different hash → try stem_3.ext."""
        from photoconsole.consolidator import resolve_conflict

        existing = tmp_path / "IMG.jpg"
        existing.write_bytes(b"original")
        stem2 = tmp_path / "IMG_2.jpg"
        stem2.write_bytes(b"another_file")
        # stem_3 does not exist; src_hash does not match either existing file
        result = resolve_conflict(existing, "completely_different_hash")
        assert result == tmp_path / "IMG_3.jpg"


# ---------------------------------------------------------------------------
# Task 2: copy_and_verify
# ---------------------------------------------------------------------------

class TestCopyAndVerify:
    """copy_and_verify(src_path: str, dest_path: Path, expected_hash: str) -> bool."""

    def test_success_returns_true(self, tmp_path):
        """copy_and_verify copies file and returns True when hash matches."""
        from photoconsole.consolidator import copy_and_verify

        src = tmp_path / "src.jpg"
        src.write_bytes(b"photo data")
        src_hash = hashlib.sha256(b"photo data").hexdigest()
        dest = tmp_path / "subdir" / "dest.jpg"

        result = copy_and_verify(str(src), dest, src_hash)
        assert result is True
        assert dest.exists()
        assert dest.read_bytes() == b"photo data"

    def test_creates_intermediate_directories(self, tmp_path):
        """copy_and_verify creates dest.parent directories if they do not exist."""
        from photoconsole.consolidator import copy_and_verify

        src = tmp_path / "src.jpg"
        src.write_bytes(b"data")
        src_hash = hashlib.sha256(b"data").hexdigest()
        dest = tmp_path / "a" / "b" / "c" / "dest.jpg"

        copy_and_verify(str(src), dest, src_hash)
        assert dest.exists()

    def test_hash_mismatch_removes_dest_returns_false(self, tmp_path):
        """copy_and_verify removes dest and returns False when hash mismatches (D-10)."""
        from photoconsole.consolidator import copy_and_verify

        src = tmp_path / "src.jpg"
        src.write_bytes(b"photo data")
        dest = tmp_path / "dest.jpg"

        result = copy_and_verify(str(src), dest, "wrong_hash_value")
        assert result is False
        assert not dest.exists()  # corrupt copy must be removed

    def test_missing_src_returns_false(self, tmp_path):
        """copy_and_verify returns False (not raises) when source does not exist."""
        from photoconsole.consolidator import copy_and_verify

        dest = tmp_path / "dest.jpg"
        result = copy_and_verify(str(tmp_path / "nonexistent.jpg"), dest, "any_hash")
        assert result is False

    def test_source_file_not_touched(self, tmp_path):
        """copy_and_verify never modifies or removes the source file."""
        from photoconsole.consolidator import copy_and_verify

        src = tmp_path / "src.jpg"
        src.write_bytes(b"precious photo")
        src_hash = hashlib.sha256(b"precious photo").hexdigest()
        dest = tmp_path / "dest.jpg"

        copy_and_verify(str(src), dest, src_hash)
        # Source must still exist and be unchanged
        assert src.exists()
        assert src.read_bytes() == b"precious photo"
