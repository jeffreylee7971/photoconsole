"""Photo EXIF metadata extraction using piexif.

Public API:
    extract_photo_metadata(path) — returns dict with date_taken, camera_model,
                                    orientation, gps_lat, gps_lon (all may be None)
    gps_to_decimal(dms_rationals, ref) — exported for testing
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import piexif


def rational_to_float(rational: tuple[int, int]) -> float:
    """Convert a piexif rational (numerator, denominator) to float.

    Returns 0.0 when the denominator is zero (avoids ZeroDivisionError per
    the threat model — malformed denominators must not crash the scan).

    Args:
        rational: A (numerator, denominator) integer pair from piexif.

    Returns:
        Float value or 0.0 on zero denominator.
    """
    num, den = rational
    return num / den if den != 0 else 0.0


def gps_to_decimal(
    dms_rationals: Any,
    ref: str,
) -> float | None:
    """Convert GPS degrees-minutes-seconds rationals to decimal degrees.

    Handles the 'S'/'W' hemisphere convention (negative result).

    Args:
        dms_rationals: A sequence of three (num, den) rational pairs representing
            degrees, minutes, and seconds.  None or short sequences return None.
        ref: Hemisphere reference string: 'N', 'S', 'E', or 'W'.

    Returns:
        Decimal degrees as float, or None if input is invalid.
    """
    if not dms_rationals or len(dms_rationals) < 3:
        return None

    degrees = rational_to_float(dms_rationals[0])
    minutes = rational_to_float(dms_rationals[1])
    seconds = rational_to_float(dms_rationals[2])

    decimal = degrees + minutes / 60.0 + seconds / 3600.0

    if ref in ("S", "W"):
        decimal = -decimal

    return decimal


def extract_photo_metadata(path: str | Path) -> dict:
    """Extract EXIF metadata from a JPEG/image file using piexif.

    Never raises — malformed or missing EXIF yields a dict with all five
    fields set to None (D-11: missing EXIF is NULL, not an error; T-03-01
    mitigation via broad except Exception guard).

    Args:
        path: Path to the image file.

    Returns:
        Dict with keys: date_taken, camera_model, orientation, gps_lat, gps_lon.
        All values may be None.
    """
    _null = {
        "date_taken": None,
        "camera_model": None,
        "orientation": None,
        "gps_lat": None,
        "gps_lon": None,
    }

    try:
        exif_data = piexif.load(str(path))
    except Exception:
        # Covers piexif.InvalidImageDataError, struct.error, ValueError, etc.
        # (Pitfall 3 / T-03-01 mitigation)
        return _null

    try:
        gps_ifd = exif_data.get("GPS", {})
        zeroth_ifd = exif_data.get("0th", {})
        exif_ifd = exif_data.get("Exif", {})

        # GPS
        lat_rationals = gps_ifd.get(piexif.GPSIFD.GPSLatitude)
        lat_ref_raw = gps_ifd.get(piexif.GPSIFD.GPSLatitudeRef, b"N")
        lat_ref = (
            lat_ref_raw.decode(errors="ignore").strip("\x00").strip()
            if isinstance(lat_ref_raw, bytes)
            else str(lat_ref_raw)
        )

        lon_rationals = gps_ifd.get(piexif.GPSIFD.GPSLongitude)
        lon_ref_raw = gps_ifd.get(piexif.GPSIFD.GPSLongitudeRef, b"E")
        lon_ref = (
            lon_ref_raw.decode(errors="ignore").strip("\x00").strip()
            if isinstance(lon_ref_raw, bytes)
            else str(lon_ref_raw)
        )

        gps_lat = gps_to_decimal(lat_rationals, lat_ref)
        gps_lon = gps_to_decimal(lon_rationals, lon_ref)

        # DateTimeOriginal
        date_raw = exif_ifd.get(piexif.ExifIFD.DateTimeOriginal, b"")
        date_taken: str | None = None
        if isinstance(date_raw, bytes):
            date_str = date_raw.decode(errors="ignore").strip("\x00").strip()
            date_taken = date_str or None
        elif date_raw:
            date_taken = str(date_raw).strip() or None

        # Camera model
        model_raw = zeroth_ifd.get(piexif.ImageIFD.Model, b"")
        camera_model: str | None = None
        if isinstance(model_raw, bytes):
            model_str = model_raw.decode(errors="ignore").strip("\x00").strip()
            camera_model = model_str or None
        elif model_raw:
            camera_model = str(model_raw).strip() or None

        # Orientation
        orientation: int | None = zeroth_ifd.get(piexif.ImageIFD.Orientation)

        return {
            "date_taken": date_taken,
            "camera_model": camera_model,
            "orientation": orientation,
            "gps_lat": gps_lat,
            "gps_lon": gps_lon,
        }

    except Exception:
        # Secondary defensive guard — any per-field extraction error
        # falls back to all-None rather than propagating.
        return _null
