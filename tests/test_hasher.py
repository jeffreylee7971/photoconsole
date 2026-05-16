"""Tests for photoconsole/hasher.py — SHA256 streaming, process_file, process_files."""
import hashlib
import os
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ──────────────────────────────────────────────────────────────────────────────
# sha256_file
# ──────────────────────────────────────────────────────────────────────────────

def test_sha256_known_empty(tmp_path):
    """Empty file → well-known SHA256 for the empty string."""
    from photoconsole.hasher import sha256_file

    empty = tmp_path / "empty.bin"
    empty.write_bytes(b"")
    result = sha256_file(empty)
    assert result == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def test_sha256_known_hello(tmp_path):
    """b'hello' → well-known SHA256."""
    from photoconsole.hasher import sha256_file

    f = tmp_path / "hello.bin"
    f.write_bytes(b"hello")
    result = sha256_file(f)
    assert result == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"


def test_sha256_streams_in_chunks(tmp_path):
    """sha256_file reads in CHUNK_SIZE increments — verified by counting read() calls."""
    from photoconsole.hasher import sha256_file
    from photoconsole.constants import CHUNK_SIZE

    # Write a file slightly larger than 2 × CHUNK_SIZE to ensure multiple reads.
    data = b"x" * (CHUNK_SIZE * 2 + 100)
    f = tmp_path / "big.bin"
    f.write_bytes(data)

    read_calls = []
    original_open = open

    class CountingFile:
        def __init__(self, path, mode):
            self._f = original_open(path, mode)

        def read(self, n=-1):
            chunk = self._f.read(n)
            if n > 0 and chunk:  # Only record non-empty reads
                read_calls.append(len(chunk))
            return chunk

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self._f.close()

    with patch("builtins.open", side_effect=lambda path, mode="r": CountingFile(str(path), mode)):
        sha256_file(f)

    # Should have been called at least 3 times (2 full chunks + 1 remainder)
    assert len(read_calls) >= 3, f"Expected ≥3 read calls, got {len(read_calls)}"
    # Each full chunk must equal CHUNK_SIZE (except possibly the last)
    for size in read_calls[:-1]:
        assert size == CHUNK_SIZE


def test_process_file_success_photo(tmp_path):
    """process_file on a real .jpg file → status='ok', media_type='photo', all EXIF keys present."""
    from photoconsole.hasher import process_file, sha256_file

    jpg = tmp_path / "photo.jpg"
    # Minimal valid JPEG with no EXIF
    jpg.write_bytes(bytes([
        0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10,
        0x4A, 0x46, 0x49, 0x46, 0x00,
        0x01, 0x01, 0x00, 0x00, 0x01, 0x00, 0x01,
        0x00, 0x00,
        0xFF, 0xD9,
    ]))

    result = process_file(str(jpg), "TestSource", "local")

    assert result["status"] == "ok"
    assert result["media_type"] == "photo"
    assert result["hash"] == sha256_file(jpg)
    assert result["source_name"] == "TestSource"
    assert result["source_type"] == "local"
    # All five EXIF keys must be present
    for key in ("date_taken", "camera_model", "orientation", "gps_lat", "gps_lon"):
        assert key in result


def test_process_file_success_video(tmp_path):
    """process_file on a .mp4 file → status='ok', media_type='video'."""
    from photoconsole.hasher import process_file

    mp4 = tmp_path / "clip.mp4"
    mp4.write_bytes(b"\x00" * 64)  # Not a real MP4 — ffprobe will fail silently

    with patch("photoconsole.hasher.extract_video_metadata", return_value={
        "date_taken": None, "camera_model": None,
        "orientation": None, "gps_lat": None, "gps_lon": None,
    }):
        result = process_file(str(mp4), "Cam", "local")

    assert result["status"] == "ok"
    assert result["media_type"] == "video"


def test_process_file_not_found_returns_error(tmp_path):
    """process_file on a nonexistent path → status='error', error_type='not_found', hash=None."""
    from photoconsole.hasher import process_file

    result = process_file(str(tmp_path / "nonexistent.jpg"), "S", "local")

    assert result["status"] == "error"
    assert result["error_type"] == "not_found"
    assert result["hash"] is None


def test_process_file_unsupported_extension_returns_error(tmp_path):
    """process_file on an unsupported extension → status='error', error_type='read_error'."""
    from photoconsole.hasher import process_file

    f = tmp_path / "document.pdf"
    f.write_bytes(b"%PDF")

    result = process_file(str(f), "S", "local")

    assert result["status"] == "error"
    assert result["error_type"] == "read_error"


def test_process_file_populates_stat_fields(tmp_path):
    """process_file populates size/mtime/ctime from os.stat for existing files."""
    from photoconsole.hasher import process_file

    f = tmp_path / "photo.jpg"
    f.write_bytes(b"\xFF\xD8\xFF\xD9")  # Minimal JPEG

    with patch("photoconsole.hasher.extract_photo_metadata", return_value={
        "date_taken": None, "camera_model": None,
        "orientation": None, "gps_lat": None, "gps_lon": None,
    }):
        result = process_file(str(f), "S", "local")

    stat = os.stat(str(f))
    assert result["size"] == stat.st_size
    assert result["mtime"] == pytest.approx(stat.st_mtime)
    assert result["ctime"] == pytest.approx(stat.st_ctime)


def test_process_file_injects_source_fields(tmp_path):
    """source_name and source_type are passed verbatim into the result."""
    from photoconsole.hasher import process_file

    f = tmp_path / "img.jpg"
    f.write_bytes(b"\xFF\xD8\xFF\xD9")

    with patch("photoconsole.hasher.extract_photo_metadata", return_value={
        "date_taken": None, "camera_model": None,
        "orientation": None, "gps_lat": None, "gps_lon": None,
    }):
        result = process_file(str(f), "My NAS", "rclone")

    assert result["source_name"] == "My NAS"
    assert result["source_type"] == "rclone"


def test_process_files_yields_one_per_input(tmp_path):
    """process_files yields exactly one result dict per input candidate."""
    from photoconsole.hasher import process_files

    candidates = []
    for i in range(5):
        f = tmp_path / f"photo_{i}.jpg"
        f.write_bytes(b"\xFF\xD8\xFF\xD9")
        candidates.append((str(f), "Src", "local"))

    with patch("photoconsole.hasher.extract_photo_metadata", return_value={
        "date_taken": None, "camera_model": None,
        "orientation": None, "gps_lat": None, "gps_lon": None,
    }):
        results = list(process_files(candidates, max_workers=2))

    assert len(results) == 5


def test_process_files_parallel_workers(tmp_path):
    """process_files with max_workers=4 actually executes concurrently (wall time < sum of sleeps)."""
    from photoconsole.hasher import process_files

    # Create 4 small JPEG files
    candidates = []
    for i in range(4):
        f = tmp_path / f"img_{i}.jpg"
        f.write_bytes(b"\xFF\xD8\xFF\xD9")
        candidates.append((str(f), "S", "local"))

    sleep_duration = 0.25  # 4 × 0.25s = 1.0s serial; parallel should be ~0.25s

    def slow_process_file(path, source_name, source_type):
        time.sleep(sleep_duration)
        return {
            "path": path, "hash": "aa", "size": 4, "mtime": 0.0, "ctime": 0.0,
            "source_name": source_name, "source_type": source_type,
            "media_type": "photo", "status": "ok", "error_type": None,
            "date_taken": None, "camera_model": None,
            "orientation": None, "gps_lat": None, "gps_lon": None,
        }

    with patch("photoconsole.hasher.process_file", side_effect=slow_process_file):
        t0 = time.monotonic()
        results = list(process_files(candidates, max_workers=4))
        elapsed = time.monotonic() - t0

    assert len(results) == 4
    # If parallel, wall time should be well under 4× the sleep
    assert elapsed < sleep_duration * 4 * 0.75, (
        f"Expected parallel execution (< {sleep_duration * 4 * 0.75:.2f}s), "
        f"got {elapsed:.2f}s"
    )


def test_process_files_progress_cb(tmp_path):
    """progress_cb is called with (n, total) where n increases 1..total."""
    from photoconsole.hasher import process_files

    n_files = 3
    candidates = []
    for i in range(n_files):
        f = tmp_path / f"img_{i}.jpg"
        f.write_bytes(b"\xFF\xD8\xFF\xD9")
        candidates.append((str(f), "S", "local"))

    calls = []

    def cb(completed, total):
        calls.append((completed, total))

    with patch("photoconsole.hasher.extract_photo_metadata", return_value={
        "date_taken": None, "camera_model": None,
        "orientation": None, "gps_lat": None, "gps_lon": None,
    }):
        list(process_files(candidates, max_workers=2, progress_cb=cb))

    assert len(calls) == n_files
    totals = [t for _, t in calls]
    assert all(t == n_files for t in totals)
    completed_vals = sorted(c for c, _ in calls)
    assert completed_vals == list(range(1, n_files + 1))
