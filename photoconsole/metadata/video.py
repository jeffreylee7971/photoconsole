"""Video metadata extraction using ffprobe subprocess.

Public API:
    check_ffprobe_available()    — raises RuntimeError with install instructions if absent
    extract_video_metadata(path) — returns dict with date_taken, camera_model,
                                    orientation, gps_lat, gps_lon (all may be None)
    parse_iso6709(s)             — parses ISO 6709 GPS string; returns (lat, lon) or (None, None)
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path


_NULL_METADATA = {
    "date_taken": None,
    "camera_model": None,
    "orientation": None,
    "gps_lat": None,
    "gps_lon": None,
}

_FFPROBE_INSTALL = (
    "ffprobe not found. Install ffmpeg to enable video metadata extraction:\n"
    "  Windows: winget install ffmpeg\n"
    "  macOS:   brew install ffmpeg\n"
    "  Linux:   sudo apt install ffmpeg\n"
    "  Other:   https://ffmpeg.org/download.html"
)


def check_ffprobe_available() -> None:
    """Raise RuntimeError with install instructions if ffprobe is not on PATH.

    Runs `ffprobe -version` as a quick availability check.

    Raises:
        RuntimeError: If ffprobe cannot be found, containing 'ffprobe' and 'install'
            as required substrings (D-13 mitigation).
    """
    try:
        subprocess.run(
            ["ffprobe", "-version"],
            capture_output=True,
            check=True,
            timeout=10,
        )
    except FileNotFoundError:
        raise RuntimeError(_FFPROBE_INSTALL)


def parse_iso6709(s: str) -> tuple[float | None, float | None]:
    """Parse an ISO 6709 GPS location string into (latitude, longitude) decimal degrees.

    Recognises the common format used by Apple QuickTime:
        +35.6762+139.6503+004.000/
        -22.9519-043.2106/

    Returns (None, None) on any parse failure.

    Args:
        s: ISO 6709 location string.

    Returns:
        Tuple of (latitude, longitude) floats, or (None, None).
    """
    if not s:
        return (None, None)
    try:
        pattern = r"^([+-]\d+(?:\.\d+)?)([+-]\d+(?:\.\d+)?)"
        match = re.match(pattern, s)
        if match:
            lat = float(match.group(1))
            lon = float(match.group(2))
            return (lat, lon)
    except Exception:
        pass
    return (None, None)


def extract_video_metadata(path: str | Path) -> dict:
    """Extract container metadata from a video file using ffprobe.

    Runs ffprobe in JSON output mode and extracts creation_time and GPS
    location from format tags. Never raises — any ffprobe failure or
    missing tag yields an all-None dict (D-12 / NFR1).

    The subprocess is always invoked with a list (not shell=True) to prevent
    shell injection from filenames with special characters (T-03-02 mitigation).
    A 60-second timeout protects against ffprobe hanging on corrupt containers
    (T-03-03 mitigation).

    Args:
        path: Path to the video file.

    Returns:
        Dict with keys: date_taken, camera_model (always None), orientation
        (always None), gps_lat, gps_lon.
    """
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                "-show_entries", "format_tags",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            return dict(_NULL_METADATA)

        data = json.loads(result.stdout)
        tags: dict = data.get("format", {}).get("tags", {})

        # --- date_taken ---
        # Prefer creation_time; fall back to com.apple.quicktime.creationdate
        date_taken: str | None = (
            tags.get("creation_time")
            or tags.get("com.apple.quicktime.creationdate")
            or None
        )

        # --- GPS ---
        location_str: str | None = (
            tags.get("location")
            or tags.get("com.apple.quicktime.location.ISO6709")
            or None
        )
        gps_lat, gps_lon = parse_iso6709(location_str) if location_str else (None, None)

        return {
            "date_taken": date_taken,
            "camera_model": None,   # not available via container tags
            "orientation": None,    # not available via container tags
            "gps_lat": gps_lat,
            "gps_lon": gps_lon,
        }

    except Exception:
        # Covers TimeoutExpired, json.JSONDecodeError, FileNotFoundError,
        # and any other unexpected error — all yield all-None (NFR1).
        return dict(_NULL_METADATA)
