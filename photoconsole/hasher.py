"""Streaming SHA256 hasher and thread-pool orchestration for media file processing.

Public API:
    sha256_file(path)        — streams file in CHUNK_SIZE chunks, returns hex digest
    process_file(path, ...)  — hashes + extracts metadata, returns result dict
    process_files(...)       — parallel orchestration via ThreadPoolExecutor
"""
from __future__ import annotations

import hashlib
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Iterator

from photoconsole.constants import CHUNK_SIZE, PHOTO_EXTENSIONS, VIDEO_EXTENSIONS
from photoconsole.errors import ErrorType, classify_error
from photoconsole.metadata.photo import extract_photo_metadata
from photoconsole.metadata.video import extract_video_metadata


def sha256_file(path: str | Path) -> str:
    """Compute the SHA256 hex digest of a file using streaming reads.

    Reads the file in CHUNK_SIZE byte chunks to avoid loading large files
    into memory (NFR1, T-03-05 mitigation).

    Args:
        path: Path to the file to hash.

    Returns:
        Lower-case hexadecimal SHA256 digest string.

    Raises:
        OSError: If the file cannot be opened or read.
    """
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK_SIZE):
            h.update(chunk)
    return h.hexdigest()


def process_file(path: str, source_name: str, source_type: str) -> dict:
    """Hash a single media file and extract its metadata.

    Produces a dict with the exact column set expected by upsert_media_file
    (Plan 02 schema). Size/mtime/ctime are always populated when the file
    exists, even if hashing or metadata extraction subsequently fails.

    Unknown extensions immediately return status='error', error_type='read_error'
    without reading the file — the scanner should filter those out first, but
    we are defensive here per the interface spec.

    Metadata failures (D-11) are NOT stored as errors: missing/malformed EXIF
    simply yields NULL metadata fields; the record is still status='ok'.

    Args:
        path: Absolute or relative path to the media file.
        source_name: Display name of the source (e.g. "NAS Photos").
        source_type: Source type string ('local' or 'rclone').

    Returns:
        Dict with keys: path, hash, size, mtime, ctime, source_name, source_type,
        media_type, status, error_type, date_taken, camera_model, orientation,
        gps_lat, gps_lon.
    """
    # Determine media type from extension
    ext = Path(path).suffix.lower()
    if ext in PHOTO_EXTENSIONS:
        media_type = "photo"
        metadata_fn = extract_photo_metadata
    elif ext in VIDEO_EXTENSIONS:
        media_type = "video"
        metadata_fn = extract_video_metadata
    else:
        return {
            "path": path,
            "hash": None,
            "size": None,
            "mtime": None,
            "ctime": None,
            "source_name": source_name,
            "source_type": source_type,
            "media_type": None,
            "status": "error",
            "error_type": ErrorType.READ_ERROR,
            "date_taken": None,
            "camera_model": None,
            "orientation": None,
            "gps_lat": None,
            "gps_lon": None,
        }

    # Initialise result scaffold — stat fields are populated before any I/O
    # that could fail, so even a partial error record has size/mtime/ctime.
    result: dict = {
        "path": path,
        "hash": None,
        "size": None,
        "mtime": None,
        "ctime": None,
        "source_name": source_name,
        "source_type": source_type,
        "media_type": media_type,
        "status": "ok",
        "error_type": None,
        "date_taken": None,
        "camera_model": None,
        "orientation": None,
        "gps_lat": None,
        "gps_lon": None,
    }

    # Step 1: stat — always first so size/mtime/ctime survive later failures
    try:
        stat = os.stat(path)
        result["size"] = stat.st_size
        result["mtime"] = stat.st_mtime
        result["ctime"] = stat.st_ctime
    except FileNotFoundError as exc:
        result["status"] = "error"
        result["error_type"] = ErrorType.NOT_FOUND
        return result
    except OSError as exc:
        result["status"] = "error"
        result["error_type"] = classify_error(exc)
        return result

    # Step 2: hash — failure marks the record as error
    try:
        result["hash"] = sha256_file(path)
    except Exception as exc:
        result["status"] = "error"
        result["error_type"] = ErrorType.HASH_FAILED
        return result

    # Step 3: metadata — failure is NOT an error per D-11 (photo) / D-12 (video)
    try:
        meta = metadata_fn(path)
        result["date_taken"] = meta.get("date_taken")
        result["camera_model"] = meta.get("camera_model")
        result["orientation"] = meta.get("orientation")
        result["gps_lat"] = meta.get("gps_lat")
        result["gps_lon"] = meta.get("gps_lon")
    except Exception:
        # Defensive: extractors should never raise, but if they do, treat as
        # metadata failure — file is still ok, metadata fields remain None.
        result["error_type"] = ErrorType.METADATA_FAILED

    return result


def process_files(
    file_candidates: list[tuple[str, str, str]],
    max_workers: int,
    progress_cb: Callable[[int, int], None] | None = None,
) -> Iterator[dict]:
    """Process a list of (path, source_name, source_type) candidates in parallel.

    Uses ThreadPoolExecutor for I/O-bound parallelism (FR6). Results are
    yielded as workers complete via as_completed — order is non-deterministic.

    Per-file exceptions are captured and turned into status='error' records;
    this function never raises.

    Args:
        file_candidates: List of (path, source_name, source_type) tuples.
        max_workers: Thread pool size.
        progress_cb: Optional callback called as (completed_count, total) after
            each file is processed.

    Yields:
        Result dicts (same shape as process_file).
    """
    total = len(file_candidates)
    completed = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_candidate = {
            executor.submit(process_file, path, source_name, source_type): (path, source_name, source_type)
            for path, source_name, source_type in file_candidates
        }

        for future in as_completed(future_to_candidate):
            path, source_name, source_type = future_to_candidate[future]
            try:
                result = future.result()
            except Exception as exc:
                result = {
                    "path": path,
                    "hash": None,
                    "size": None,
                    "mtime": None,
                    "ctime": None,
                    "source_name": source_name,
                    "source_type": source_type,
                    "media_type": None,
                    "status": "error",
                    "error_type": classify_error(exc),
                    "date_taken": None,
                    "camera_model": None,
                    "orientation": None,
                    "gps_lat": None,
                    "gps_lon": None,
                }

            completed += 1
            yield result

            if progress_cb is not None:
                progress_cb(completed, total)
