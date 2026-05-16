"""Unit tests for photoconsole.scanner — LocalScanner, RcloneScanner, scan_all."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from photoconsole.config import Config, Source
from photoconsole.constants import MEDIA_EXTENSIONS
from photoconsole.scanner import LocalScanner, RcloneScanner, check_rclone_available, scan_all


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _can_symlink(tmp_path: Path) -> bool:
    """Probe whether os.symlink works in the current environment.

    On Windows without Developer Mode or admin rights, os.symlink raises
    OSError / PermissionError even for non-existent targets.
    """
    probe_target = tmp_path / "_probe_target"
    probe_link = tmp_path / "_probe_link"
    probe_target.write_text("x")
    try:
        os.symlink(probe_target, probe_link)
        probe_link.unlink()
        return True
    except (OSError, NotImplementedError):
        return False


def _make_local_source(path: str, name: str = "TestLocal") -> Source:
    return Source(name=name, type="local", path=path, remote="")


def _make_local_config(path: str, name: str = "TestLocal") -> Config:
    return Config(
        sources=[_make_local_source(path, name)],
        catalog_path="/tmp/test_catalog.db",
        include_extensions=MEDIA_EXTENSIONS,
    )


# ---------------------------------------------------------------------------
# Task 1: LocalScanner tests
# ---------------------------------------------------------------------------


class TestLocalScannerRecursive:
    """LocalScanner discovers media files recursively across subdirectories."""

    def test_local_scan_recursive(self, tmp_path):
        """Files in subdirectories are found."""
        (tmp_path / "a.jpg").write_text("photo")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "d.gif").write_text("gif")

        source = _make_local_source(str(tmp_path))
        scanner = LocalScanner(source, MEDIA_EXTENSIONS)
        results = list(scanner.iter_candidates())

        paths = [r[0] for r in results]
        assert any("a.jpg" in p for p in paths), f"a.jpg not found in {paths}"
        assert any("d.gif" in p for p in paths), f"d.gif not found in {paths}"

    def test_skip_non_media_extensions(self, tmp_path):
        """Files whose extension is not in include_extensions are skipped."""
        (tmp_path / "a.jpg").write_text("photo")
        (tmp_path / "b.png").write_text("image")
        (tmp_path / "c.txt").write_text("text")

        source = _make_local_source(str(tmp_path))
        scanner = LocalScanner(source, MEDIA_EXTENSIONS)
        results = list(scanner.iter_candidates())

        paths = [r[0] for r in results]
        assert any("a.jpg" in p for p in paths)
        assert any("b.png" in p for p in paths)
        assert not any("c.txt" in p for p in paths), "c.txt should be excluded"

    def test_case_insensitive_extension_match(self, tmp_path):
        """Uppercase extensions (e.g. .JPG) are treated the same as lowercase."""
        (tmp_path / "photo.JPG").write_text("photo")

        source = _make_local_source(str(tmp_path))
        scanner = LocalScanner(source, MEDIA_EXTENSIONS)
        results = list(scanner.iter_candidates())

        paths = [r[0] for r in results]
        assert any("photo.JPG" in p for p in paths), (
            "photo.JPG should be yielded — extension match must be case-insensitive"
        )

    def test_yields_absolute_paths(self, tmp_path):
        """All yielded paths are absolute."""
        (tmp_path / "a.jpg").write_text("photo")

        source = _make_local_source(str(tmp_path))
        scanner = LocalScanner(source, MEDIA_EXTENSIONS)
        results = list(scanner.iter_candidates())

        for path, _, _ in results:
            assert os.path.isabs(path), f"Path {path!r} is not absolute"

    def test_yields_tuple_shape(self, tmp_path):
        """Each yielded item is a 3-tuple (path, source_name, 'local')."""
        (tmp_path / "a.jpg").write_text("photo")
        source_name = "MyLocalSource"

        source = _make_local_source(str(tmp_path), name=source_name)
        scanner = LocalScanner(source, MEDIA_EXTENSIONS)
        results = list(scanner.iter_candidates())

        assert len(results) == 1
        path, name, src_type = results[0]
        assert isinstance(path, str)
        assert name == source_name
        assert src_type == "local"

    def test_nonexistent_root_raises_fnf(self):
        """LocalScanner raises FileNotFoundError on a non-existent root."""
        source = _make_local_source("/this/path/does/not/exist/at/all/42")
        with pytest.raises(FileNotFoundError):
            LocalScanner(source, MEDIA_EXTENSIONS)

    def test_root_is_file_raises_notadirectory(self, tmp_path):
        """LocalScanner raises NotADirectoryError when root is a file, not a directory."""
        file_path = tmp_path / "not_a_dir.jpg"
        file_path.write_text("photo")

        source = _make_local_source(str(file_path))
        with pytest.raises(NotADirectoryError):
            LocalScanner(source, MEDIA_EXTENSIONS)

    def test_multiple_media_types(self, tmp_path):
        """LocalScanner finds all media types: photos and videos."""
        for fname in ("a.jpg", "b.png", "c.gif", "d.mp4", "e.mov", "f.avi"):
            (tmp_path / fname).write_text("data")

        source = _make_local_source(str(tmp_path))
        scanner = LocalScanner(source, MEDIA_EXTENSIONS)
        results = list(scanner.iter_candidates())

        assert len(results) == 6, f"Expected 6 media files, got {len(results)}: {[r[0] for r in results]}"


class TestLocalScannerSymlinks:
    """Symlink tests — gated on os.symlink availability (requires admin/dev-mode on Windows)."""

    def test_skip_file_symlink(self, tmp_path):
        """File symlinks are never yielded, even when target is a valid media file (D-04)."""
        if not _can_symlink(tmp_path):
            pytest.skip("os.symlink not available in this environment (Windows requires admin or Developer Mode)")

        real = tmp_path / "a.jpg"
        real.write_text("photo")
        link = tmp_path / "link_a.jpg"
        os.symlink(real, link)

        source = _make_local_source(str(tmp_path))
        scanner = LocalScanner(source, MEDIA_EXTENSIONS)
        results = list(scanner.iter_candidates())

        paths = [r[0] for r in results]
        assert not any("link_a.jpg" in p for p in paths), (
            "Symlinked file link_a.jpg must not appear in results (D-04)"
        )
        # The real file should still appear
        assert any("a.jpg" in p and "link_a" not in p for p in paths), (
            "Real file a.jpg should still appear"
        )

    def test_skip_directory_symlink(self, tmp_path):
        """Symlinked directories are never traversed — no files under them emitted (D-04)."""
        if not _can_symlink(tmp_path):
            pytest.skip("os.symlink not available in this environment (Windows requires admin or Developer Mode)")

        real_sub = tmp_path / "realsub"
        real_sub.mkdir()
        (real_sub / "hidden.jpg").write_text("photo")

        link_sub = tmp_path / "linksub"
        os.symlink(real_sub, link_sub)

        source = _make_local_source(str(tmp_path))
        scanner = LocalScanner(source, MEDIA_EXTENSIONS)
        results = list(scanner.iter_candidates())

        paths = [r[0] for r in results]
        assert not any("linksub" in p for p in paths), (
            "Files under symlinked directory linksub must not appear (D-04)"
        )
        # The real file under realsub should still appear
        assert any("realsub" in p for p in paths), (
            "Real file under realsub should still appear"
        )

    def test_verbose_symlink_logs_at_info(self, tmp_path, caplog):
        """When verbose=True, skipped symlinks are logged at INFO level (D-05)."""
        if not _can_symlink(tmp_path):
            pytest.skip("os.symlink not available in this environment (Windows requires admin or Developer Mode)")

        real = tmp_path / "a.jpg"
        real.write_text("photo")
        link = tmp_path / "link_a.jpg"
        os.symlink(real, link)

        source = _make_local_source(str(tmp_path))
        scanner = LocalScanner(source, MEDIA_EXTENSIONS, verbose=True)

        with caplog.at_level(logging.INFO, logger="photoconsole.scanner"):
            list(scanner.iter_candidates())

        assert any("link_a.jpg" in record.message or "symlink" in record.message.lower()
                   for record in caplog.records), (
            "verbose=True should log a message when a symlink is skipped"
        )

    def test_verbose_false_no_symlink_log(self, tmp_path, caplog):
        """When verbose=False (default), symlinks are skipped silently (D-05)."""
        if not _can_symlink(tmp_path):
            pytest.skip("os.symlink not available in this environment (Windows requires admin or Developer Mode)")

        real = tmp_path / "a.jpg"
        real.write_text("photo")
        link = tmp_path / "link_a.jpg"
        os.symlink(real, link)

        source = _make_local_source(str(tmp_path))
        scanner = LocalScanner(source, MEDIA_EXTENSIONS, verbose=False)

        with caplog.at_level(logging.INFO, logger="photoconsole.scanner"):
            list(scanner.iter_candidates())

        symlink_logs = [r for r in caplog.records if "link_a.jpg" in r.message]
        assert not symlink_logs, "verbose=False must not log symlink skips (D-05)"


# ---------------------------------------------------------------------------
# Task 2: RcloneScanner tests
# ---------------------------------------------------------------------------

_RCLONE_LSJSON_OUTPUT = json.dumps([
    {"Path": "a.jpg", "Name": "a.jpg", "Size": 1000, "MimeType": "image/jpeg", "ModTime": "2024-01-01T00:00:00Z", "IsDir": False},
    {"Path": "sub/b.png", "Name": "b.png", "Size": 2000, "MimeType": "image/png", "ModTime": "2024-01-02T00:00:00Z", "IsDir": False},
    {"Path": "sub", "Name": "sub", "Size": -1, "MimeType": "inode/directory", "ModTime": "2024-01-01T00:00:00Z", "IsDir": True},
    {"Path": "c.txt", "Name": "c.txt", "Size": 500, "MimeType": "text/plain", "ModTime": "2024-01-03T00:00:00Z", "IsDir": False},
])


def _make_rclone_source(remote: str = "gdrive:", name: str = "TestRclone") -> Source:
    return Source(name=name, type="rclone", path="", remote=remote)


def _make_rclone_config(remote: str = "gdrive:", name: str = "TestRclone") -> Config:
    return Config(
        sources=[_make_rclone_source(remote, name)],
        catalog_path="/tmp/test_catalog.db",
        include_extensions=MEDIA_EXTENSIONS,
    )


class TestRcloneScanner:
    """RcloneScanner tests — subprocess.run is always mocked."""

    def test_rclone_lsjson_argv_is_list_form(self, mocker):
        """subprocess.run must be called with a list (not a shell string) and never shell=True (T-04-01)."""
        mock_run = mocker.patch("photoconsole.scanner.subprocess.run")
        mock_run.return_value = MagicMock(returncode=0, stdout=_RCLONE_LSJSON_OUTPUT, stderr="")

        source = _make_rclone_source("gdrive:")
        scanner = RcloneScanner(source, MEDIA_EXTENSIONS)
        list(scanner.iter_candidates())

        mock_run.assert_called_once()
        call_args = mock_run.call_args

        # First positional arg must be a list
        cmd = call_args[0][0] if call_args[0] else call_args[1].get("args")
        assert isinstance(cmd, list), f"subprocess.run must receive a list, got: {type(cmd)}"
        assert cmd[:3] == ["rclone", "lsjson", "--recursive"], (
            f"Unexpected argv prefix: {cmd[:3]}"
        )

        # Must not use shell=True
        kwargs = call_args[1] if call_args[1] else {}
        assert kwargs.get("shell", False) is False, "shell=True is forbidden (T-04-01)"

    def test_rclone_filters_directories(self, mocker):
        """Entries with IsDir=True are never yielded."""
        mock_run = mocker.patch("photoconsole.scanner.subprocess.run")
        mock_run.return_value = MagicMock(returncode=0, stdout=_RCLONE_LSJSON_OUTPUT, stderr="")

        source = _make_rclone_source("gdrive:")
        scanner = RcloneScanner(source, MEDIA_EXTENSIONS)
        results = list(scanner.iter_candidates())

        paths = [r[0] for r in results]
        assert not any(p.endswith("/sub") or p == "gdrive:sub" for p in paths), (
            "Directory entries must not appear in results"
        )

    def test_rclone_filters_non_media(self, mocker):
        """Entries whose extension is not in include_extensions are skipped."""
        mock_run = mocker.patch("photoconsole.scanner.subprocess.run")
        mock_run.return_value = MagicMock(returncode=0, stdout=_RCLONE_LSJSON_OUTPUT, stderr="")

        source = _make_rclone_source("gdrive:")
        scanner = RcloneScanner(source, MEDIA_EXTENSIONS)
        results = list(scanner.iter_candidates())

        paths = [r[0] for r in results]
        assert not any("c.txt" in p for p in paths), "c.txt should be filtered out"

    def test_rclone_yields_remote_prefixed_path(self, mocker):
        """Each yielded path is prefixed with the source.remote value."""
        mock_run = mocker.patch("photoconsole.scanner.subprocess.run")
        mock_run.return_value = MagicMock(returncode=0, stdout=_RCLONE_LSJSON_OUTPUT, stderr="")

        source = _make_rclone_source("gdrive:")
        scanner = RcloneScanner(source, MEDIA_EXTENSIONS)
        results = list(scanner.iter_candidates())

        paths = [r[0] for r in results]
        assert "gdrive:a.jpg" in paths, f"Expected 'gdrive:a.jpg' in {paths}"
        assert "gdrive:sub/b.png" in paths, f"Expected 'gdrive:sub/b.png' in {paths}"

    def test_rclone_yields_correct_tuple_shape(self, mocker):
        """Yields (path, source_name, 'rclone') tuples."""
        mock_run = mocker.patch("photoconsole.scanner.subprocess.run")
        mock_run.return_value = MagicMock(returncode=0, stdout=_RCLONE_LSJSON_OUTPUT, stderr="")

        source = _make_rclone_source("gdrive:", name="GDrive")
        scanner = RcloneScanner(source, MEDIA_EXTENSIONS)
        results = list(scanner.iter_candidates())

        assert len(results) == 2  # a.jpg and sub/b.png
        for path, name, src_type in results:
            assert isinstance(path, str)
            assert name == "GDrive"
            assert src_type == "rclone"

    def test_rclone_missing_binary_raises_install_message(self, mocker):
        """When rclone binary is not found, RuntimeError contains 'rclone' and 'install'."""
        mock_run = mocker.patch("photoconsole.scanner.subprocess.run")
        mock_run.side_effect = FileNotFoundError("rclone not found")

        source = _make_rclone_source("gdrive:")
        scanner = RcloneScanner(source, MEDIA_EXTENSIONS)

        with pytest.raises(RuntimeError) as exc_info:
            list(scanner.iter_candidates())

        msg = str(exc_info.value).lower()
        assert "rclone" in msg, f"Error message should mention 'rclone': {msg}"
        assert "install" in msg, f"Error message should mention 'install': {msg}"

    def test_rclone_nonzero_returncode_raises_with_stderr(self, mocker):
        """When rclone exits non-zero, RuntimeError contains stderr text."""
        mock_run = mocker.patch("photoconsole.scanner.subprocess.run")
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="remote not found")

        source = _make_rclone_source("gdrive:")
        scanner = RcloneScanner(source, MEDIA_EXTENSIONS)

        with pytest.raises(RuntimeError) as exc_info:
            list(scanner.iter_candidates())

        assert "remote not found" in str(exc_info.value), (
            "RuntimeError should include rclone's stderr text"
        )

    def test_check_rclone_available_success(self, mocker):
        """check_rclone_available does not raise when rclone version succeeds."""
        mock_run = mocker.patch("photoconsole.scanner.subprocess.run")
        mock_run.return_value = MagicMock(returncode=0, stdout="rclone v1.66.0", stderr="")

        # Should not raise
        check_rclone_available()

    def test_check_rclone_available_failure(self, mocker):
        """check_rclone_available raises RuntimeError when rclone binary not found."""
        mock_run = mocker.patch("photoconsole.scanner.subprocess.run")
        mock_run.side_effect = FileNotFoundError("rclone not found")

        with pytest.raises(RuntimeError) as exc_info:
            check_rclone_available()

        msg = str(exc_info.value).lower()
        assert "rclone" in msg
        assert "install" in msg


# ---------------------------------------------------------------------------
# Task 2: scan_all dispatcher tests
# ---------------------------------------------------------------------------

class TestScanAll:
    """scan_all dispatches to LocalScanner and RcloneScanner by source type."""

    def test_scan_all_local_only(self, tmp_path):
        """scan_all with a local source yields local files."""
        (tmp_path / "a.jpg").write_text("photo")
        (tmp_path / "b.mp4").write_text("video")

        config = _make_local_config(str(tmp_path))
        results = list(scan_all(config))

        assert len(results) == 2
        for _, _, src_type in results:
            assert src_type == "local"

    def test_scan_all_concatenates_sources(self, tmp_path, mocker):
        """scan_all yields results from local AND rclone sources in config order."""
        # Local source
        local_dir = tmp_path / "local"
        local_dir.mkdir()
        (local_dir / "local_photo.jpg").write_text("photo")

        # Rclone source (mocked)
        rclone_output = json.dumps([
            {"Path": "remote_photo.png", "Name": "remote_photo.png", "Size": 1000,
             "MimeType": "image/png", "ModTime": "2024-01-01T00:00:00Z", "IsDir": False},
        ])
        mock_run = mocker.patch("photoconsole.scanner.subprocess.run")
        mock_run.return_value = MagicMock(returncode=0, stdout=rclone_output, stderr="")

        config = Config(
            sources=[
                Source(name="LocalSrc", type="local", path=str(local_dir), remote=""),
                Source(name="RemoteSrc", type="rclone", path="", remote="gdrive:"),
            ],
            catalog_path="/tmp/test_catalog.db",
            include_extensions=MEDIA_EXTENSIONS,
        )

        results = list(scan_all(config))

        assert len(results) == 2
        source_types = {r[2] for r in results}
        assert "local" in source_types
        assert "rclone" in source_types

        # Order: local first (config.sources order)
        assert results[0][2] == "local"
        assert results[1][2] == "rclone"

    def test_scan_all_unknown_source_type_raises(self):
        """scan_all raises ValueError for unknown source types."""
        bad_source = Source(name="Bad", type="ftp", path="/tmp", remote="")
        config = Config(
            sources=[bad_source],
            catalog_path="/tmp/test_catalog.db",
            include_extensions=MEDIA_EXTENSIONS,
        )

        with pytest.raises(ValueError, match="unknown.*source.*type|ftp"):
            list(scan_all(config))

    def test_scan_all_verbose_logs_per_source(self, tmp_path, caplog):
        """scan_all with verbose=True logs per-source counts at INFO."""
        (tmp_path / "a.jpg").write_text("photo")
        config = _make_local_config(str(tmp_path), name="VerboseSource")

        with caplog.at_level(logging.INFO, logger="photoconsole.scanner"):
            list(scan_all(config, verbose=True))

        # At least one log record should mention the source name or count
        assert any(
            "VerboseSource" in r.message or "1" in r.message
            for r in caplog.records
        ), f"Expected verbose count log; got: {[r.message for r in caplog.records]}"

    def test_scan_all_preserves_source_order(self, tmp_path, mocker):
        """scan_all yields results in config.sources order."""
        dir_a = tmp_path / "a"
        dir_a.mkdir()
        (dir_a / "first.jpg").write_text("photo")

        dir_b = tmp_path / "b"
        dir_b.mkdir()
        (dir_b / "second.jpg").write_text("photo")

        config = Config(
            sources=[
                Source(name="SourceA", type="local", path=str(dir_a), remote=""),
                Source(name="SourceB", type="local", path=str(dir_b), remote=""),
            ],
            catalog_path="/tmp/test_catalog.db",
            include_extensions=MEDIA_EXTENSIONS,
        )

        results = list(scan_all(config))
        names = [r[1] for r in results]
        assert names == ["SourceA", "SourceB"], (
            f"Results should be in source order; got names: {names}"
        )
