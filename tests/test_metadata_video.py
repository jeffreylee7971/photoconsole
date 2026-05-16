"""Tests for photoconsole/metadata/video.py — ffprobe wrapper, ISO 6709 parser.

All subprocess calls are mocked — no real ffprobe binary is required.
"""
from __future__ import annotations

import json
import subprocess

import pytest

from photoconsole.metadata.video import (
    check_ffprobe_available,
    extract_video_metadata,
    parse_iso6709,
)


# ─────────────────────────────────────────────────────────────────────────────
# parse_iso6709
# ─────────────────────────────────────────────────────────────────────────────

def test_parse_iso6709_positive():
    """Standard Apple QuickTime ISO 6709 string → positive lat/lon."""
    lat, lon = parse_iso6709("+35.6762+139.6503+004.000/")
    assert lat == pytest.approx(35.6762, abs=1e-4)
    assert lon == pytest.approx(139.6503, abs=1e-4)


def test_parse_iso6709_negative():
    """Negative lat/lon (southern/western hemisphere)."""
    lat, lon = parse_iso6709("-22.9519-043.2106/")
    assert lat == pytest.approx(-22.9519, abs=1e-4)
    assert lon == pytest.approx(-43.2106, abs=1e-4)


def test_parse_iso6709_garbage():
    """Garbage string → (None, None), no exception."""
    assert parse_iso6709("garbage") == (None, None)


def test_parse_iso6709_empty():
    """Empty string → (None, None), no exception."""
    assert parse_iso6709("") == (None, None)


def test_parse_iso6709_mixed_signs():
    """West longitude (negative) with North latitude (positive)."""
    lat, lon = parse_iso6709("+40.7128-074.0060/")
    assert lat == pytest.approx(40.7128, abs=1e-4)
    assert lon == pytest.approx(-74.006, abs=1e-4)


# ─────────────────────────────────────────────────────────────────────────────
# check_ffprobe_available
# ─────────────────────────────────────────────────────────────────────────────

def test_check_ffprobe_available_success(mocker):
    """When ffprobe -version returns rc=0, check_ffprobe_available returns without error."""
    mocker.patch(
        "photoconsole.metadata.video.subprocess.run",
        return_value=mocker.MagicMock(returncode=0),
    )
    # Should not raise
    check_ffprobe_available()


def test_check_ffprobe_available_missing_raises(mocker):
    """When ffprobe is not on PATH, RuntimeError is raised containing 'ffprobe' and 'install'."""
    mocker.patch(
        "photoconsole.metadata.video.subprocess.run",
        side_effect=FileNotFoundError("No such file or directory: 'ffprobe'"),
    )
    with pytest.raises(RuntimeError) as exc_info:
        check_ffprobe_available()

    error_msg = str(exc_info.value)
    assert "ffprobe" in error_msg.lower()
    assert "install" in error_msg.lower()


# ─────────────────────────────────────────────────────────────────────────────
# extract_video_metadata — happy paths
# ─────────────────────────────────────────────────────────────────────────────

def _mock_ffprobe(mocker, tags: dict, returncode: int = 0):
    """Helper to mock subprocess.run returning the given format tags."""
    payload = {"format": {"tags": tags}}
    stdout = json.dumps(payload) if returncode == 0 else ""
    mocker.patch(
        "photoconsole.metadata.video.subprocess.run",
        return_value=mocker.MagicMock(
            returncode=returncode,
            stdout=stdout,
            stderr="",
        ),
    )


def test_extract_video_metadata_creation_time(mocker, tmp_path):
    """creation_time tag → date_taken set to the ISO string."""
    _mock_ffprobe(mocker, {"creation_time": "2022-02-11T18:26:58.000000Z"})
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"\x00")
    result = extract_video_metadata(path)
    assert result["date_taken"] == "2022-02-11T18:26:58.000000Z"
    assert result["camera_model"] is None
    assert result["orientation"] is None


def test_extract_video_metadata_apple_gps(mocker, tmp_path):
    """Apple QuickTime ISO6709 location tag → gps_lat and gps_lon parsed correctly."""
    _mock_ffprobe(mocker, {
        "creation_time": "2022-02-11T18:26:58.000000Z",
        "com.apple.quicktime.location.ISO6709": "+35.6762+139.6503+004.000/",
    })
    path = tmp_path / "iphone.mov"
    path.write_bytes(b"\x00")
    result = extract_video_metadata(path)
    assert result["gps_lat"] == pytest.approx(35.6762, abs=1e-4)
    assert result["gps_lon"] == pytest.approx(139.6503, abs=1e-4)


def test_extract_video_metadata_no_tags(mocker, tmp_path):
    """ffprobe succeeds but tags dict is empty → all-None dict returned."""
    _mock_ffprobe(mocker, {})
    path = tmp_path / "notags.mp4"
    path.write_bytes(b"\x00")
    result = extract_video_metadata(path)
    for key in ("date_taken", "camera_model", "orientation", "gps_lat", "gps_lon"):
        assert result[key] is None


def test_extract_video_metadata_result_has_all_keys(mocker, tmp_path):
    """Result dict always contains exactly the five expected keys."""
    _mock_ffprobe(mocker, {"creation_time": "2023-06-01T00:00:00.000000Z"})
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"\x00")
    result = extract_video_metadata(path)
    expected_keys = {"date_taken", "camera_model", "orientation", "gps_lat", "gps_lon"}
    assert set(result.keys()) == expected_keys


# ─────────────────────────────────────────────────────────────────────────────
# extract_video_metadata — failure paths
# ─────────────────────────────────────────────────────────────────────────────

def test_extract_video_metadata_ffprobe_failure_returns_none(mocker, tmp_path):
    """Non-zero ffprobe return code → all-None dict, no exception."""
    _mock_ffprobe(mocker, {}, returncode=1)
    path = tmp_path / "bad.mp4"
    path.write_bytes(b"\x00")
    result = extract_video_metadata(path)
    for key in ("date_taken", "camera_model", "orientation", "gps_lat", "gps_lon"):
        assert result[key] is None


def test_extract_video_metadata_subprocess_exception_returns_none(mocker, tmp_path):
    """If subprocess.run raises (e.g. FileNotFoundError), all-None dict returned."""
    mocker.patch(
        "photoconsole.metadata.video.subprocess.run",
        side_effect=FileNotFoundError("ffprobe not found"),
    )
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"\x00")
    result = extract_video_metadata(path)
    for key in ("date_taken", "camera_model", "orientation", "gps_lat", "gps_lon"):
        assert result[key] is None


def test_extract_video_metadata_timeout_returns_none(mocker, tmp_path):
    """TimeoutExpired from subprocess → all-None dict, no exception."""
    mocker.patch(
        "photoconsole.metadata.video.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="ffprobe", timeout=60),
    )
    path = tmp_path / "long.mp4"
    path.write_bytes(b"\x00")
    result = extract_video_metadata(path)
    for key in ("date_taken", "camera_model", "orientation", "gps_lat", "gps_lon"):
        assert result[key] is None
