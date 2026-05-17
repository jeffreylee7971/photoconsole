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


# ---------------------------------------------------------------------------
# Plan 04 — Task 1: write_manifest
# ---------------------------------------------------------------------------

class TestWriteManifest:
    """write_manifest(rows, dest_dir) -> tuple[Path, Path]."""

    def test_returns_two_paths(self, tmp_path):
        """write_manifest returns a 2-tuple of (csv_path, bat_path)."""
        from photoconsole.consolidator import write_manifest

        result = write_manifest([], tmp_path)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_csv_has_correct_columns(self, tmp_path):
        """CSV contains header row with original_path,hash,destination_path,source_name."""
        import csv as _csv
        from photoconsole.consolidator import write_manifest

        rows = [
            {
                'original_path': r'C:\photos\a.jpg',
                'hash': 'aabbcc',
                'destination_path': r'D:\Library\2023\06\a.jpg',
                'source_name': 'OneDrive',
                'source_type': 'rclone',
            }
        ]
        csv_path, _ = write_manifest(rows, tmp_path)
        assert csv_path.exists()
        with open(csv_path, newline='', encoding='utf-8') as f:
            reader = _csv.DictReader(f)
            data = list(reader)
        assert set(data[0].keys()) >= {'original_path', 'hash', 'destination_path', 'source_name'}
        assert data[0]['original_path'] == r'C:\photos\a.jpg'
        assert data[0]['hash'] == 'aabbcc'

    def test_bat_has_echo_off_and_chcp(self, tmp_path):
        """The .bat file starts with @echo off and chcp 65001 >nul."""
        from photoconsole.consolidator import write_manifest

        _, bat_path = write_manifest([], tmp_path)
        text = bat_path.read_text(encoding='utf-8-sig')
        assert '@echo off' in text
        assert 'chcp 65001' in text

    def test_bat_utf8_sig_encoding(self, tmp_path):
        """The .bat file is written with utf-8-sig (BOM) encoding."""
        from photoconsole.consolidator import write_manifest

        _, bat_path = write_manifest([], tmp_path)
        raw = bat_path.read_bytes()
        assert raw[:3] == b'\xef\xbb\xbf', "Expected UTF-8 BOM at start of .bat file"

    def test_local_row_emits_del_f(self, tmp_path):
        """Local-source rows emit 'del /f \"path\"' in the .bat file."""
        from photoconsole.consolidator import write_manifest

        rows = [
            {
                'original_path': r'D:\old\photo.jpg',
                'hash': 'deadbeef',
                'destination_path': r'D:\Library\2023\06\photo.jpg',
                'source_name': 'D: SSD',
                'source_type': 'local',
            }
        ]
        _, bat_path = write_manifest(rows, tmp_path)
        text = bat_path.read_text(encoding='utf-8-sig')
        assert 'del /f' in text
        assert r'D:\old\photo.jpg' in text

    def test_rclone_row_emits_comment(self, tmp_path):
        """rclone-source rows emit ':: rclone deletefile ...' (not del /f)."""
        from photoconsole.consolidator import write_manifest

        rows = [
            {
                'original_path': 'onedrive:Photos/a.jpg',
                'hash': 'cafebabe',
                'destination_path': r'D:\Library\2023\06\a.jpg',
                'source_name': 'OneDrive',
                'source_type': 'rclone',
            }
        ]
        _, bat_path = write_manifest(rows, tmp_path)
        text = bat_path.read_text(encoding='utf-8-sig')
        assert ':: rclone deletefile' in text
        assert 'del /f' not in text

    def test_bat_crlf_line_endings(self, tmp_path):
        """The .bat file uses \\r\\n line endings."""
        from photoconsole.consolidator import write_manifest

        _, bat_path = write_manifest([], tmp_path)
        raw = bat_path.read_bytes()
        # Strip BOM and check for \r\n
        content = raw[3:]  # skip UTF-8 BOM
        assert b'\r\n' in content

    def test_timestamp_filenames(self, tmp_path):
        """Files are named deletion_manifest_TIMESTAMP.csv and delete_originals_TIMESTAMP.bat."""
        from photoconsole.consolidator import write_manifest
        import re

        csv_path, bat_path = write_manifest([], tmp_path)
        assert re.match(r'deletion_manifest_\d{8}_\d{6}\.csv', csv_path.name)
        assert re.match(r'delete_originals_\d{8}_\d{6}\.bat', bat_path.name)


# ---------------------------------------------------------------------------
# Plan 04 — Task 1: check_destination_writable
# ---------------------------------------------------------------------------

class TestCheckDestinationWritable:
    """check_destination_writable(dest_path_str) -> None or raises RuntimeError."""

    def test_empty_string_raises_runtime_error(self):
        """Empty string raises RuntimeError mentioning destination_path."""
        from photoconsole.consolidator import check_destination_writable

        with pytest.raises(RuntimeError, match='destination_path'):
            check_destination_writable('')

    def test_whitespace_string_raises_runtime_error(self):
        """All-whitespace string raises RuntimeError (treated as empty)."""
        from photoconsole.consolidator import check_destination_writable

        with pytest.raises(RuntimeError, match='destination_path'):
            check_destination_writable('   ')

    def test_creates_directory_if_absent(self, tmp_path):
        """Valid path that does not yet exist is created without error."""
        from photoconsole.consolidator import check_destination_writable

        new_dir = tmp_path / 'new_subdir'
        assert not new_dir.exists()
        check_destination_writable(str(new_dir))
        assert new_dir.exists()

    def test_existing_writable_dir_returns_none(self, tmp_path):
        """Existing writable directory returns None (no error)."""
        from photoconsole.consolidator import check_destination_writable

        result = check_destination_writable(str(tmp_path))
        assert result is None


# ---------------------------------------------------------------------------
# Plan 04 — Task 1: setup_consolidation_logger
# ---------------------------------------------------------------------------

class TestSetupConsolidationLogger:
    """setup_consolidation_logger(log_path) -> logging.Logger."""

    def test_returns_logger(self, tmp_path):
        """setup_consolidation_logger returns a logging.Logger."""
        import logging
        from photoconsole.consolidator import setup_consolidation_logger

        logger = setup_consolidation_logger(tmp_path / 'test.log')
        assert isinstance(logger, logging.Logger)

    def test_appends_to_log_file(self, tmp_path):
        """Logger writes messages append-mode to the given log_path."""
        from photoconsole.consolidator import setup_consolidation_logger

        log_path = tmp_path / 'cons.log'
        logger = setup_consolidation_logger(log_path)
        logger.info('TEST | src=a | dest=b | hash=c | outcome=ok')
        assert log_path.exists()
        text = log_path.read_text(encoding='utf-8')
        assert 'TEST' in text

    def test_no_duplicate_handlers_on_second_call(self, tmp_path):
        """Calling setup_consolidation_logger twice does not add duplicate handlers."""
        import logging
        from photoconsole.consolidator import setup_consolidation_logger

        log_path = tmp_path / 'dedup.log'
        logger1 = setup_consolidation_logger(log_path)
        handler_count_after_first = len(logger1.handlers)
        logger2 = setup_consolidation_logger(log_path)
        # handler count must not grow on second call
        assert len(logger2.handlers) == handler_count_after_first

    def test_creates_parent_directories(self, tmp_path):
        """setup_consolidation_logger creates missing parent directories."""
        from photoconsole.consolidator import setup_consolidation_logger

        nested_log = tmp_path / 'subdir' / 'logs' / 'cons.log'
        setup_consolidation_logger(nested_log)
        assert nested_log.parent.exists()


# ---------------------------------------------------------------------------
# Plan 04 — Task 2: run_consolidation
# ---------------------------------------------------------------------------

class TestRunConsolidation:
    """run_consolidation(groups, config, dry_run, log_path) -> ConsolidationPlan."""

    def _make_media_file(self, path: str, hash_: str, source_name: str, source_type: str,
                          date_taken: str | None = '2023:06:15 10:30:00') -> object:
        """Build a minimal MediaFile-like object for testing."""
        from photoconsole.catalog.models import MediaFile
        f = MediaFile()
        f.path = path
        f.hash = hash_
        f.source_name = source_name
        f.source_type = source_type
        f.date_taken = date_taken
        f.mtime = None
        return f

    def _make_config(self, dest_root: str, catalog_path: str) -> object:
        """Build a minimal Config for testing."""
        from photoconsole.config import Config, ConsolidationConfig
        return Config(
            sources=[],
            catalog_path=catalog_path,
            consolidation=ConsolidationConfig(
                destination_path=dest_root,
                source_priority=['D: SSD', 'OneDrive'],
            ),
        )

    def test_dry_run_returns_plan_with_to_copy(self, tmp_path):
        """dry_run=True populates to_copy but writes no files."""
        import hashlib
        from photoconsole.consolidator import run_consolidation
        from photoconsole.dedup import DuplicateGroup

        src = tmp_path / 'src.jpg'
        src.write_bytes(b'photobytes')
        h = hashlib.sha256(b'photobytes').hexdigest()

        f = self._make_media_file(str(src), h, 'OneDrive', 'rclone')
        group = DuplicateGroup(hash=h, canonical=f, redundants=[], needs_copy=True)
        dest_root = tmp_path / 'Library'
        cfg = self._make_config(str(dest_root), str(tmp_path / 'catalog.db'))

        plan = run_consolidation([group], cfg, dry_run=True)

        assert len(plan.to_copy) == 1
        # Dry run: no files written to dest_root
        if dest_root.exists():
            assert list(dest_root.rglob('*')) == [], "dry_run must write no media files"

    def test_dry_run_writes_no_manifest_files(self, tmp_path):
        """dry_run=True writes no CSV, no .bat, no log."""
        import hashlib
        from photoconsole.consolidator import run_consolidation
        from photoconsole.dedup import DuplicateGroup

        src = tmp_path / 'src.jpg'
        src.write_bytes(b'photobytes')
        h = hashlib.sha256(b'photobytes').hexdigest()

        f = self._make_media_file(str(src), h, 'OneDrive', 'rclone')
        group = DuplicateGroup(hash=h, canonical=f, redundants=[], needs_copy=True)
        dest_root = tmp_path / 'Library'
        cfg = self._make_config(str(dest_root), str(tmp_path / 'catalog.db'))

        run_consolidation([group], cfg, dry_run=True)

        # No .csv or .bat written
        assert list(tmp_path.rglob('*.csv')) == []
        assert list(tmp_path.rglob('*.bat')) == []

    def test_live_run_copies_file_to_destination(self, tmp_path):
        """dry_run=False copies the canonical file into dest_root/YYYY/MM/filename."""
        import hashlib
        from photoconsole.consolidator import run_consolidation
        from photoconsole.dedup import DuplicateGroup

        src = tmp_path / 'src.jpg'
        src.write_bytes(b'photobytes')
        h = hashlib.sha256(b'photobytes').hexdigest()

        f = self._make_media_file(str(src), h, 'OneDrive', 'rclone')
        group = DuplicateGroup(hash=h, canonical=f, redundants=[], needs_copy=True)
        dest_root = tmp_path / 'Library'
        cfg = self._make_config(str(dest_root), str(tmp_path / 'catalog.db'))

        plan = run_consolidation([group], cfg, dry_run=False)

        assert len(plan.to_copy) == 1
        expected_dest = dest_root / '2023' / '06' / 'src.jpg'
        assert expected_dest.exists()

    def test_needs_copy_false_adds_to_skipped(self, tmp_path):
        """needs_copy=False group goes to plan.skipped, not plan.to_copy."""
        import hashlib
        from photoconsole.consolidator import run_consolidation
        from photoconsole.dedup import DuplicateGroup

        src = tmp_path / 'local.jpg'
        src.write_bytes(b'local')
        h = hashlib.sha256(b'local').hexdigest()

        f = self._make_media_file(str(src), h, 'D: SSD', 'local')
        group = DuplicateGroup(hash=h, canonical=f, redundants=[], needs_copy=False)
        dest_root = tmp_path / 'Library'
        cfg = self._make_config(str(dest_root), str(tmp_path / 'catalog.db'))

        plan = run_consolidation([group], cfg, dry_run=False)

        assert len(plan.skipped) == 1
        assert len(plan.to_copy) == 0

    def test_needs_copy_false_redundants_go_to_manifest(self, tmp_path):
        """needs_copy=False group: redundants go to plan.to_manifest."""
        import hashlib
        from photoconsole.consolidator import run_consolidation
        from photoconsole.dedup import DuplicateGroup

        h = hashlib.sha256(b'same').hexdigest()
        canonical = self._make_media_file(str(tmp_path / 'local.jpg'), h, 'D: SSD', 'local')
        redundant = self._make_media_file('onedrive:Photos/a.jpg', h, 'OneDrive', 'rclone')
        group = DuplicateGroup(hash=h, canonical=canonical, redundants=[redundant], needs_copy=False)
        dest_root = tmp_path / 'Library'
        cfg = self._make_config(str(dest_root), str(tmp_path / 'catalog.db'))

        plan = run_consolidation([group], cfg, dry_run=False)

        assert len(plan.to_manifest) == 1
        assert plan.to_manifest[0]['original_path'] == 'onedrive:Photos/a.jpg'

    def test_live_run_writes_manifest_when_non_empty(self, tmp_path):
        """dry_run=False with non-empty to_manifest writes a CSV and .bat file."""
        import hashlib
        from photoconsole.consolidator import run_consolidation
        from photoconsole.dedup import DuplicateGroup

        h = hashlib.sha256(b'same').hexdigest()
        canonical = self._make_media_file(str(tmp_path / 'local.jpg'), h, 'D: SSD', 'local')
        (tmp_path / 'local.jpg').write_bytes(b'same')
        redundant = self._make_media_file('onedrive:Photos/a.jpg', h, 'OneDrive', 'rclone')
        group = DuplicateGroup(hash=h, canonical=canonical, redundants=[redundant], needs_copy=False)
        dest_root = tmp_path / 'Library'
        dest_root.mkdir()
        cfg = self._make_config(str(dest_root), str(tmp_path / 'catalog.db'))

        run_consolidation([group], cfg, dry_run=False)

        assert list(dest_root.rglob('*.csv')) != []
        assert list(dest_root.rglob('*.bat')) != []

    def test_resolve_conflict_none_adds_to_skipped(self, tmp_path):
        """When resolve_conflict returns None (already present), adds to skipped."""
        import hashlib
        from photoconsole.consolidator import run_consolidation
        from photoconsole.dedup import DuplicateGroup

        content = b'photobytes'
        h = hashlib.sha256(content).hexdigest()
        src = tmp_path / 'src.jpg'
        src.write_bytes(content)

        # Pre-place file at the expected dest so resolve_conflict returns None
        dest_root = tmp_path / 'Library'
        expected_dest = dest_root / '2023' / '06' / 'src.jpg'
        expected_dest.parent.mkdir(parents=True, exist_ok=True)
        expected_dest.write_bytes(content)

        f = self._make_media_file(str(src), h, 'OneDrive', 'rclone')
        group = DuplicateGroup(hash=h, canonical=f, redundants=[], needs_copy=True)
        cfg = self._make_config(str(dest_root), str(tmp_path / 'catalog.db'))

        plan = run_consolidation([group], cfg, dry_run=False)

        assert len(plan.skipped) == 1
        assert len(plan.to_copy) == 0
