"""Tests for photoconsole/metadata/photo.py — EXIF extraction and GPS helpers.

All tests that depend on piexif and Pillow are marked with skipif guards
so the suite degrades gracefully if those libraries are absent.
"""
from __future__ import annotations

import io
import struct

import pytest

# ─────────────────────────────────────────────────────────────────────────────
# Import guards — skip entire module if piexif / Pillow are absent
# ─────────────────────────────────────────────────────────────────────────────
piexif = pytest.importorskip("piexif", reason="piexif not installed")
PIL = pytest.importorskip("PIL", reason="Pillow not installed")
from PIL import Image

from photoconsole.metadata.photo import extract_photo_metadata, gps_to_decimal


# ─────────────────────────────────────────────────────────────────────────────
# Helpers for building test JPEG files
# ─────────────────────────────────────────────────────────────────────────────

def _make_jpeg_no_exif(tmp_path) -> "pathlib.Path":
    """Create a minimal 1×1 JPEG with NO EXIF data."""
    from pathlib import Path
    path = tmp_path / "no_exif.jpg"
    img = Image.new("RGB", (1, 1), color=(128, 128, 128))
    img.save(str(path), format="JPEG")
    return path


def _make_jpeg_with_exif(tmp_path, exif_dict: dict) -> "pathlib.Path":
    """Create a 1×1 JPEG with the given piexif-format EXIF dict embedded."""
    from pathlib import Path
    path = tmp_path / "with_exif.jpg"
    img = Image.new("RGB", (1, 1), color=(128, 128, 128))
    exif_bytes = piexif.dump(exif_dict)
    img.save(str(path), format="JPEG", exif=exif_bytes)
    return path


# ─────────────────────────────────────────────────────────────────────────────
# gps_to_decimal
# ─────────────────────────────────────────────────────────────────────────────

def test_gps_to_decimal_north():
    """40°30'0" N → 40.5 (positive)."""
    result = gps_to_decimal(((40, 1), (30, 1), (0, 1)), "N")
    assert result == pytest.approx(40.5)


def test_gps_to_decimal_south_negative():
    """40°30'0" S → -40.5 (southern hemisphere yields negative)."""
    result = gps_to_decimal(((40, 1), (30, 1), (0, 1)), "S")
    assert result == pytest.approx(-40.5)


def test_gps_to_decimal_west_negative():
    """73°58'0" W → -73.9666… (western hemisphere yields negative)."""
    result = gps_to_decimal(((73, 1), (58, 1), (0, 1)), "W")
    assert result == pytest.approx(-73.96666, rel=1e-4)


def test_gps_to_decimal_east():
    """139°39'1" E → positive value (east is positive)."""
    result = gps_to_decimal(((139, 1), (39, 1), (1, 1)), "E")
    assert result is not None
    assert result > 0


def test_gps_to_decimal_none_input():
    """None input → None (not an error)."""
    assert gps_to_decimal(None, "N") is None


def test_gps_to_decimal_short_sequence():
    """Tuple with fewer than 3 elements → None."""
    assert gps_to_decimal(((40, 1), (30, 1)), "N") is None


def test_gps_to_decimal_zero_denominator():
    """Zero denominator in rational → does NOT raise; returns a numeric result."""
    # rational_to_float returns 0.0 on zero denominator — so result is numeric
    result = gps_to_decimal(((40, 0), (30, 1), (0, 1)), "N")
    # Should be 0 + 30/60 + 0/3600 = 0.5 (since 40/0 → 0.0)
    assert result is not None  # must not raise


# ─────────────────────────────────────────────────────────────────────────────
# extract_photo_metadata — baseline (no EXIF)
# ─────────────────────────────────────────────────────────────────────────────

def test_exif_baseline_no_metadata(tmp_path):
    """JPEG with no EXIF data → all five fields are None, no exception raised."""
    path = _make_jpeg_no_exif(tmp_path)
    result = extract_photo_metadata(path)
    assert isinstance(result, dict)
    for key in ("date_taken", "camera_model", "orientation", "gps_lat", "gps_lon"):
        assert key in result
        assert result[key] is None, f"Expected {key}=None, got {result[key]!r}"


# ─────────────────────────────────────────────────────────────────────────────
# extract_photo_metadata — DateTimeOriginal
# ─────────────────────────────────────────────────────────────────────────────

def test_exif_date_taken_extracted(tmp_path):
    """JPEG with DateTimeOriginal set → date_taken matches raw EXIF string."""
    exif_dict = {
        "0th": {},
        "Exif": {
            piexif.ExifIFD.DateTimeOriginal: b"2024:01:15 12:34:56",
        },
        "GPS": {},
        "1st": {},
        "thumbnail": None,
    }
    path = _make_jpeg_with_exif(tmp_path, exif_dict)
    result = extract_photo_metadata(path)
    assert result["date_taken"] == "2024:01:15 12:34:56"


# ─────────────────────────────────────────────────────────────────────────────
# extract_photo_metadata — camera model
# ─────────────────────────────────────────────────────────────────────────────

def test_exif_camera_model_extracted(tmp_path):
    """JPEG with Model tag → camera_model matches (null bytes stripped)."""
    exif_dict = {
        "0th": {
            piexif.ImageIFD.Model: b"Canon EOS 5D\x00",
        },
        "Exif": {},
        "GPS": {},
        "1st": {},
        "thumbnail": None,
    }
    path = _make_jpeg_with_exif(tmp_path, exif_dict)
    result = extract_photo_metadata(path)
    assert result["camera_model"] == "Canon EOS 5D"


# ─────────────────────────────────────────────────────────────────────────────
# extract_photo_metadata — orientation
# ─────────────────────────────────────────────────────────────────────────────

def test_exif_orientation_extracted(tmp_path):
    """JPEG with Orientation=6 → orientation == 6."""
    exif_dict = {
        "0th": {
            piexif.ImageIFD.Orientation: 6,
        },
        "Exif": {},
        "GPS": {},
        "1st": {},
        "thumbnail": None,
    }
    path = _make_jpeg_with_exif(tmp_path, exif_dict)
    result = extract_photo_metadata(path)
    assert result["orientation"] == 6


# ─────────────────────────────────────────────────────────────────────────────
# extract_photo_metadata — corrupt/non-image file
# ─────────────────────────────────────────────────────────────────────────────

def test_corrupt_image_returns_all_none(tmp_path):
    """Corrupt file that piexif cannot parse → all-None dict, no exception."""
    corrupt = tmp_path / "corrupt.jpg"
    corrupt.write_bytes(b"\xFF\xD8" + b"\xAB\xCD\xEF" * 100)  # invalid JPEG body
    result = extract_photo_metadata(corrupt)
    assert isinstance(result, dict)
    for key in ("date_taken", "camera_model", "orientation", "gps_lat", "gps_lon"):
        assert result[key] is None


def test_non_image_file_returns_all_none(tmp_path):
    """Plain text file with .jpg extension → all-None dict, no exception."""
    fake = tmp_path / "text.jpg"
    fake.write_bytes(b"not an image at all")
    result = extract_photo_metadata(fake)
    assert isinstance(result, dict)
    for key in ("date_taken", "camera_model", "orientation", "gps_lat", "gps_lon"):
        assert result[key] is None
