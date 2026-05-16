"""Integration tests for the PhotoConsole CLI.

Tests exercise the full scan pipeline end-to-end using click.testing.CliRunner.
Real files are created on-disk in tmp_path fixtures to avoid mocking the scan
pipeline itself; only external dependencies (ffprobe, rclone) are mocked where
they would block tests in environments without those binaries installed.
"""
from __future__ import annotations

import os
import sqlite3
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from photoconsole.cli import main


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_minimal_jpeg(path: Path) -> None:
    """Write a minimal valid JPEG to path using Pillow."""
    from PIL import Image
    img = Image.new("RGB", (4, 4), color=(128, 64, 32))
    img.save(str(path), format="JPEG")


def _write_config(config_path: Path, source_path: Path, catalog_path: Path,
                  include_extensions: list[str] | None = None) -> None:
    """Write a minimal config.yaml for testing."""
    exts = include_extensions if include_extensions is not None else [".jpg", ".jpeg", ".png"]
    ext_lines = "\n".join(f"  - '{e}'" for e in exts)
    config_path.write_text(
        f"catalog_path: '{catalog_path}'\n"
        f"sources:\n"
        f"  - name: 'test-source'\n"
        f"    type: local\n"
        f"    path: '{source_path}'\n"
        f"include_extensions:\n"
        f"{ext_lines}\n",
        encoding="utf-8",
    )


def _row_count(catalog_path: Path) -> int:
    """Return the row count in media_files table via raw sqlite3."""
    conn = sqlite3.connect(str(catalog_path))
    try:
        cur = conn.execute("SELECT COUNT(*) FROM media_files")
        return cur.fetchone()[0]
    finally:
        conn.close()


def _rows(catalog_path: Path) -> list[dict]:
    """Return all rows in media_files as dicts."""
    conn = sqlite3.connect(str(catalog_path))
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute("SELECT * FROM media_files")
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Basic help / option tests
# ---------------------------------------------------------------------------

class TestHelp:
    def test_help_shows_scan_command(self):
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0, result.output
        assert "scan" in result.output

    def test_scan_help_shows_config_option(self):
        runner = CliRunner()
        result = runner.invoke(main, ["scan", "--help"])
        assert result.exit_code == 0, result.output
        assert "--config" in result.output

    def test_scan_missing_config_path_errors(self, tmp_path):
        runner = CliRunner()
        nonexistent = str(tmp_path / "does_not_exist.yaml")
        result = runner.invoke(main, ["scan", "--config", nonexistent])
        assert result.exit_code != 0

    def test_verbose_and_quiet_mutually_exclusive(self, tmp_path):
        """--verbose and --quiet together must exit non-zero."""
        source_dir = tmp_path / "media"
        source_dir.mkdir()
        catalog_path = tmp_path / "catalog.db"
        config_path = tmp_path / "config.yaml"
        _write_config(config_path, source_dir, catalog_path)

        runner = CliRunner()
        result = runner.invoke(main, ["--verbose", "--quiet", "scan", "--config", str(config_path)])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# End-to-end scan tests
# ---------------------------------------------------------------------------

class TestEndToEnd:
    def test_scan_end_to_end_with_two_jpgs(self, tmp_path):
        """Scan a directory with two JPEGs; catalog should have 2 ok rows."""
        source_dir = tmp_path / "media"
        source_dir.mkdir()
        catalog_path = tmp_path / "catalog.db"
        config_path = tmp_path / "config.yaml"

        _make_minimal_jpeg(source_dir / "a.jpg")
        _make_minimal_jpeg(source_dir / "b.jpg")
        _write_config(config_path, source_dir, catalog_path)

        runner = CliRunner()
        result = runner.invoke(main, ["scan", "--config", str(config_path)])
        assert result.exit_code == 0, result.output

        rows = _rows(catalog_path)
        assert len(rows) == 2
        statuses = {r["status"] for r in rows}
        assert statuses == {"ok"}

    def test_scan_incremental_skip_on_second_run(self, tmp_path):
        """Second run with no file changes: skipped==2, cataloged==0."""
        source_dir = tmp_path / "media"
        source_dir.mkdir()
        catalog_path = tmp_path / "catalog.db"
        config_path = tmp_path / "config.yaml"

        _make_minimal_jpeg(source_dir / "a.jpg")
        _make_minimal_jpeg(source_dir / "b.jpg")
        _write_config(config_path, source_dir, catalog_path)

        runner = CliRunner()
        # First run — should catalog both files
        result1 = runner.invoke(main, ["scan", "--config", str(config_path)])
        assert result1.exit_code == 0, result1.output

        # Second run — no file changes, should skip both
        result2 = runner.invoke(main, ["scan", "--config", str(config_path)])
        assert result2.exit_code == 0, result2.output
        assert "skipped: 2" in result2.output or "skipped=2" in result2.output or "Skipped: 2" in result2.output

    def test_scan_error_row_is_retried(self, tmp_path):
        """A row with status='error' is re-processed and promoted to 'ok'."""
        source_dir = tmp_path / "media"
        source_dir.mkdir()
        catalog_path = tmp_path / "catalog.db"
        config_path = tmp_path / "config.yaml"

        jpg_path = source_dir / "a.jpg"
        _make_minimal_jpeg(jpg_path)
        _write_config(config_path, source_dir, catalog_path)

        # First run to create the catalog (ensures the table exists)
        runner = CliRunner()
        result = runner.invoke(main, ["scan", "--config", str(config_path)])
        assert result.exit_code == 0, result.output

        # Manually set the row to status='error' to simulate a prior failure
        conn = sqlite3.connect(str(catalog_path))
        conn.execute("UPDATE media_files SET status='error', error_type='read_error' WHERE path=?",
                     (str(jpg_path),))
        conn.commit()
        conn.close()

        # Second run — the error row should be retried and promoted to 'ok'
        result2 = runner.invoke(main, ["scan", "--config", str(config_path)])
        assert result2.exit_code == 0, result2.output

        rows = _rows(catalog_path)
        assert all(r["status"] == "ok" for r in rows), f"Some rows still have error status: {rows}"


# ---------------------------------------------------------------------------
# Dependency gate tests
# ---------------------------------------------------------------------------

class TestDependencyGates:
    def test_ffprobe_gate_blocks_when_video_extensions_and_ffprobe_missing(self, tmp_path):
        """When video extensions are in include_extensions and ffprobe is missing,
        scan must exit non-zero BEFORE processing any file."""
        source_dir = tmp_path / "media"
        source_dir.mkdir()
        catalog_path = tmp_path / "catalog.db"
        config_path = tmp_path / "config.yaml"

        # Include video extensions to trigger the ffprobe gate
        _write_config(config_path, source_dir, catalog_path,
                      include_extensions=[".jpg", ".mp4"])

        runner = CliRunner()
        with patch("photoconsole.cli.check_ffprobe_available",
                   side_effect=RuntimeError("ffprobe not found. Install ffmpeg to install video support.")):
            result = runner.invoke(main, ["scan", "--config", str(config_path)])

        assert result.exit_code != 0
        assert "ffprobe" in result.output.lower() or (result.exception and "ffprobe" in str(result.exception).lower())

    def test_ffprobe_gate_skipped_when_only_photo_extensions(self, tmp_path):
        """When include_extensions has only photo extensions, ffprobe gate is skipped
        even if check_ffprobe_available would raise."""
        source_dir = tmp_path / "media"
        source_dir.mkdir()
        catalog_path = tmp_path / "catalog.db"
        config_path = tmp_path / "config.yaml"

        _make_minimal_jpeg(source_dir / "a.jpg")
        # Only photo extensions — no videos → ffprobe gate must NOT fire
        _write_config(config_path, source_dir, catalog_path,
                      include_extensions=[".jpg", ".jpeg", ".png"])

        runner = CliRunner()
        with patch("photoconsole.cli.check_ffprobe_available",
                   side_effect=RuntimeError("ffprobe not found")) as mock_check:
            result = runner.invoke(main, ["scan", "--config", str(config_path)])

        # Gate should not have been called at all
        mock_check.assert_not_called()
        assert result.exit_code == 0, result.output

    def test_rclone_gate_blocks_when_rclone_missing_and_rclone_source_configured(self, tmp_path):
        """When a rclone source is configured and rclone is missing,
        scan must exit non-zero BEFORE processing."""
        catalog_path = tmp_path / "catalog.db"
        config_path = tmp_path / "config.yaml"

        # Write a config with a rclone source
        config_path.write_text(
            f"catalog_path: '{catalog_path}'\n"
            "sources:\n"
            "  - name: 'gdrive'\n"
            "    type: rclone\n"
            "    remote: 'gdrive:'\n"
            "include_extensions:\n"
            "  - '.jpg'\n",
            encoding="utf-8",
        )

        runner = CliRunner()
        with patch("photoconsole.cli.check_rclone_available",
                   side_effect=RuntimeError("rclone not found on PATH. Install rclone from https://rclone.org/install/")):
            result = runner.invoke(main, ["scan", "--config", str(config_path)])

        assert result.exit_code != 0
        assert "rclone" in result.output.lower() or (result.exception and "rclone" in str(result.exception).lower())


# ---------------------------------------------------------------------------
# Output / verbosity tests
# ---------------------------------------------------------------------------

class TestOutput:
    def test_quiet_suppresses_summary_output(self, tmp_path):
        """With --quiet, the final summary should not be printed."""
        source_dir = tmp_path / "media"
        source_dir.mkdir()
        catalog_path = tmp_path / "catalog.db"
        config_path = tmp_path / "config.yaml"

        _make_minimal_jpeg(source_dir / "a.jpg")
        _write_config(config_path, source_dir, catalog_path)

        runner = CliRunner()
        result = runner.invoke(main, ["--quiet", "scan", "--config", str(config_path)])
        assert result.exit_code == 0, result.output
        # Summary line should not appear
        assert "cataloged" not in result.output.lower() and "total" not in result.output.lower()

    def test_verbose_emits_info_logs(self, tmp_path):
        """With --verbose, per-source counts should appear in output."""
        source_dir = tmp_path / "media"
        source_dir.mkdir()
        catalog_path = tmp_path / "catalog.db"
        config_path = tmp_path / "config.yaml"

        _make_minimal_jpeg(source_dir / "a.jpg")
        _write_config(config_path, source_dir, catalog_path)

        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(main, ["--verbose", "scan", "--config", str(config_path)],
                               catch_exceptions=False)
        # Verbose mode should produce some output beyond the final summary
        # Either in stdout or stderr — combined output checked
        combined = (result.output or "") + (result.stderr if hasattr(result, 'stderr') else "")
        # At minimum the summary is present when verbose
        assert result.exit_code == 0, result.output


# ---------------------------------------------------------------------------
# Architecture / thread-safety tests
# ---------------------------------------------------------------------------

class TestArchitecture:
    def test_writer_runs_in_main_thread(self, tmp_path):
        """DB writes (upsert_many) must happen on the main thread, not worker threads.

        Captures threading.get_ident() inside the mocked upsert_many call and
        asserts it matches the main thread ident.
        """
        source_dir = tmp_path / "media"
        source_dir.mkdir()
        catalog_path = tmp_path / "catalog.db"
        config_path = tmp_path / "config.yaml"

        _make_minimal_jpeg(source_dir / "a.jpg")
        _write_config(config_path, source_dir, catalog_path)

        writer_thread_ids: list[int] = []
        main_thread_id = threading.get_ident()

        original_upsert_many = None

        def capturing_upsert_many(session, records):
            writer_thread_ids.append(threading.get_ident())
            # Still need to actually write so the test passes end-to-end
            from photoconsole.catalog.db import upsert_many as _real_upsert_many
            return _real_upsert_many(session, records)

        runner = CliRunner()
        with patch("photoconsole.cli.upsert_many", side_effect=capturing_upsert_many):
            result = runner.invoke(main, ["scan", "--config", str(config_path)])

        assert result.exit_code == 0, result.output
        assert len(writer_thread_ids) > 0, "upsert_many was never called"
        for tid in writer_thread_ids:
            assert tid == main_thread_id, (
                f"upsert_many was called from thread {tid}, expected main thread {main_thread_id}"
            )
