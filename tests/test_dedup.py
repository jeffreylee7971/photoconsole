"""Unit tests for photoconsole.dedup — Plan 02-06.

Covers:
    find_duplicate_groups(session, source_priority) — duplicate detection
    classify_group(files, source_priority) — canonical selection and needs_copy

All tests use in-memory SQLite (no real filesystem required).
MediaFile objects are constructed via attribute assignment (no __init__ kwargs).
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from photoconsole.catalog.models import Base, MediaFile
from photoconsole.dedup import classify_group, find_duplicate_groups


# ---------------------------------------------------------------------------
# In-memory engine factory
# ---------------------------------------------------------------------------

def _make_engine():
    """Create a fresh in-memory SQLite engine with the catalog schema."""
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    return engine


# ---------------------------------------------------------------------------
# Helper: build a MediaFile with attribute assignment (no __init__ kwargs)
# ---------------------------------------------------------------------------

def _make_file(
    path: str,
    hash_: str | None,
    source_name: str,
    source_type: str,
    status: str = "ok",
    size: int = 1024,
    mtime: float = 1686823800.0,
) -> MediaFile:
    """Construct a MediaFile using attribute assignment (plan-specified pattern)."""
    f = MediaFile()
    f.path = path
    f.hash = hash_
    f.source_name = source_name
    f.source_type = source_type
    f.status = status
    f.size = size
    f.mtime = mtime
    return f


# ---------------------------------------------------------------------------
# find_duplicate_groups tests
# ---------------------------------------------------------------------------

class TestFindDuplicateGroups:
    """Tests for find_duplicate_groups(session, source_priority)."""

    def test_find_duplicate_groups_returns_group(self):
        """3 files with same hash ('aaa') → 1 group containing all 3 files."""
        engine = _make_engine()
        priority = ["D: SSD", "OneDrive", "iCloud"]

        with Session(engine) as session:
            # Three files with the duplicate hash
            f1 = _make_file("/d/photo.jpg", "aaa", "D: SSD", "local")
            f2 = _make_file("onedrive:photo.jpg", "aaa", "OneDrive", "rclone")
            f3 = _make_file("icloud:photo.jpg", "aaa", "iCloud", "rclone")
            # One unique file — must NOT appear in any group
            f4 = _make_file("/d/unique.jpg", "bbb", "D: SSD", "local")
            session.add_all([f1, f2, f3, f4])
            session.commit()

            groups = find_duplicate_groups(session, priority)

        assert len(groups) == 1
        group = groups[0]
        assert group.hash == "aaa"
        # canonical + redundants = 3 files total
        total_in_group = 1 + len(group.redundants)
        assert total_in_group == 3

    def test_find_duplicate_groups_empty_when_no_dups(self):
        """2 files with different hashes → no duplicate groups."""
        engine = _make_engine()
        priority = ["D: SSD", "OneDrive"]

        with Session(engine) as session:
            f1 = _make_file("/d/alpha.jpg", "hash_a", "D: SSD", "local")
            f2 = _make_file("/d/beta.jpg", "hash_b", "D: SSD", "local")
            session.add_all([f1, f2])
            session.commit()

            groups = find_duplicate_groups(session, priority)

        assert groups == []

    def test_find_duplicate_groups_excludes_error_status(self):
        """2 rows with same hash, one status='error' → no group (only 1 ok row)."""
        engine = _make_engine()
        priority = ["D: SSD", "OneDrive"]

        with Session(engine) as session:
            f_ok = _make_file("/d/photo.jpg", "ccc", "D: SSD", "local", status="ok")
            f_err = _make_file("onedrive:photo.jpg", "ccc", "OneDrive", "rclone", status="error")
            session.add_all([f_ok, f_err])
            session.commit()

            groups = find_duplicate_groups(session, priority)

        # Only 1 ok row with hash 'ccc' — not a duplicate
        assert groups == []

    def test_find_duplicate_groups_excludes_null_hash(self):
        """Row with hash=None must not be grouped (NULL hashes excluded)."""
        engine = _make_engine()
        priority = ["D: SSD", "OneDrive"]

        with Session(engine) as session:
            f_null = _make_file("/d/broken.jpg", None, "D: SSD", "local")
            f_ok = _make_file("/d/normal.jpg", "ddd", "D: SSD", "local")
            session.add_all([f_null, f_ok])
            session.commit()

            groups = find_duplicate_groups(session, priority)

        assert groups == []


# ---------------------------------------------------------------------------
# classify_group tests
# ---------------------------------------------------------------------------

class TestClassifyGroup:
    """Tests for classify_group(files, source_priority)."""

    def test_classify_group_d_source_wins(self):
        """D: SSD local source is always canonical, even if listed after cloud files."""
        priority = ["D: SSD", "OneDrive"]

        rclone_file = _make_file("onedrive:photo.jpg", "eee", "OneDrive", "rclone")
        local_d_file = _make_file("/d/photo.jpg", "eee", "D: SSD", "local")

        group = classify_group([rclone_file, local_d_file], priority)

        assert group.canonical.source_name == "D: SSD"
        assert group.needs_copy is False

    def test_classify_group_cloud_only_needs_copy(self):
        """All rclone sources → needs_copy=True; highest-priority cloud is canonical."""
        priority = ["D: SSD", "OneDrive", "iCloud"]

        onedrive_file = _make_file("onedrive:photo.jpg", "fff", "OneDrive", "rclone")
        icloud_file = _make_file("icloud:photo.jpg", "fff", "iCloud", "rclone")

        group = classify_group([onedrive_file, icloud_file], priority)

        assert group.needs_copy is True
        # OneDrive appears before iCloud in priority list → should be canonical
        assert group.canonical.source_name == "OneDrive"

    def test_classify_group_unknown_source_is_lowest_priority(self):
        """Unknown source_name gets sentinel priority (last) — known source wins."""
        priority = ["D: SSD", "OneDrive"]

        unknown_file = _make_file("/mystery/photo.jpg", "ggg", "Unknown Source", "local")
        onedrive_file = _make_file("onedrive:photo.jpg", "ggg", "OneDrive", "rclone")

        group = classify_group([unknown_file, onedrive_file], priority)

        # OneDrive is in priority list; "Unknown Source" is not → sentinel, sorts last
        assert group.canonical.source_name == "OneDrive"

    def test_classify_group_redundants_count(self):
        """N files in group → N-1 redundants."""
        priority = ["D: SSD", "OneDrive", "iCloud"]

        files = [
            _make_file("/d/photo.jpg", "hhh", "D: SSD", "local"),
            _make_file("onedrive:photo.jpg", "hhh", "OneDrive", "rclone"),
            _make_file("icloud:photo.jpg", "hhh", "iCloud", "rclone"),
        ]

        group = classify_group(files, priority)

        assert len(group.redundants) == 2
