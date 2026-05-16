---
phase: 01-scanning-cataloging-foundation
plan: 03
subsystem: hasher-metadata
tags: [python, hashing, exif, ffprobe, parallel, metadata, tdd]
completed: 2026-05-16
duration_minutes: 30
tasks_completed: 2
tasks_total: 2
files_created: 6
files_modified: 1

dependency_graph:
  requires:
    - photoconsole.errors.ErrorType
    - photoconsole.errors.classify_error
    - photoconsole.constants.CHUNK_SIZE
    - photoconsole.constants.PHOTO_EXTENSIONS
    - photoconsole.constants.VIDEO_EXTENSIONS
  provides:
    - photoconsole.hasher.sha256_file
    - photoconsole.hasher.process_file
    - photoconsole.hasher.process_files
    - photoconsole.metadata.extract_photo_metadata
    - photoconsole.metadata.extract_video_metadata
    - photoconsole.metadata.check_ffprobe_available
    - photoconsole.metadata.photo.gps_to_decimal
    - photoconsole.metadata.video.parse_iso6709
  affects:
    - Plan 02 (catalog/db.py): process_file output dict shape matches MediaFile column set
    - Plan 04 (scanner.py): process_files consumes (path, source_name, source_type) tuples
    - Plan 05 (cli.py): check_ffprobe_available called at scan startup

tech_stack:
  added:
    - piexif 1.1.3 (EXIF IFD parsing, GPS rational extraction)
    - Pillow 12.2.0 (JPEG generation in test fixtures)
    - concurrent.futures.ThreadPoolExecutor (parallel hashing)
    - subprocess + json (ffprobe invocation and output parsing)
  patterns:
    - Streaming SHA256 with walrus-operator while loop (T-03-05)
    - ThreadPoolExecutor + as_completed for I/O-bound parallelism (FR6)
    - broad except Exception guard on piexif.load (D-11, T-03-01)
    - subprocess list form, no shell=True, timeout=60 (T-03-02, T-03-03)
    - GPS DMS rational to decimal degrees with S/W hemisphere negation

key_files:
  created:
    - photoconsole/hasher.py
    - photoconsole/metadata/__init__.py
    - photoconsole/metadata/photo.py
    - photoconsole/metadata/video.py
    - tests/test_metadata_photo.py
    - tests/test_metadata_video.py
  modified:
    - tests/test_hasher.py (bug fix: CountingFile read tracking excluded empty reads)

key_decisions:
  - "Module-level imports for extract_photo_metadata / extract_video_metadata in hasher.py allow unittest.mock.patch to work correctly — lazy function-body imports cannot be patched at module scope"
  - "camera_model and orientation are always None for video files — video containers do not carry these fields; shape parity with photo metadata maintained intentionally"
  - "extract_video_metadata never calls check_ffprobe_available itself — that is the CLI startup concern (D-13); the extractor returns all-None on FileNotFoundError the same as any other failure"
  - "parse_iso6709 uses a single regex matching the leading lat+lon pair; altitude (+004.000) and trailing slash are intentionally ignored"
  - "rational_to_float returns 0.0 on zero denominator (not None, not raises) — keeps GPS computation numerically continuous even on malformed EXIF"

metrics:
  duration: 30 minutes
  completed_date: 2026-05-16
  tests_written: 39
  tests_passing: 39
  test_coverage_modules:
    - photoconsole.hasher
    - photoconsole.metadata.photo
    - photoconsole.metadata.video
---

# Phase 1 Plan 03: File Hasher, Photo EXIF Extractor, Video ffprobe Extractor Summary

**One-liner:** Streaming SHA256 hasher with ThreadPoolExecutor orchestration, piexif-based EXIF extractor with GPS DMS-to-decimal conversion, and ffprobe subprocess extractor with ISO 6709 GPS parser — all returning status/error_type-discipline result dicts matching the Plan 02 MediaFile schema.

---

## What Was Built

### Task 1: Streaming SHA256 and process_file/process_files orchestration

- **`photoconsole/hasher.py`** — three public functions:
  - `sha256_file(path)`: walrus-loop streaming hash in `CHUNK_SIZE` chunks; returns lower-case hex digest.
  - `process_file(path, source_name, source_type)`: stat → hash → metadata pipeline; produces 15-key result dict. Unknown extensions return `status='error', error_type='read_error'` immediately. Hash failures set `error_type=ErrorType.HASH_FAILED`. Metadata failures are silently ignored (D-11) — the record remains `status='ok'` with NULL metadata fields.
  - `process_files(file_candidates, max_workers, progress_cb)`: `ThreadPoolExecutor` + `as_completed`; yields result dicts; per-future exceptions become error records; calls `progress_cb(n, total)` if provided.

- **`tests/test_hasher.py`** — 12 tests: known empty/hello SHA256 hashes, streaming chunk verification, stat field population, source field injection, unsupported extension error, not-found error, per-input yield count, parallelism timing (4 workers, 4 × 0.25s sleep, wall time < 0.75s), and progress callback monotonicity.

### Task 2: Photo EXIF + video ffprobe metadata extractors

- **`photoconsole/metadata/__init__.py`** — re-exports `extract_photo_metadata`, `extract_video_metadata`, `check_ffprobe_available`.

- **`photoconsole/metadata/photo.py`** — three functions:
  - `rational_to_float(rational)`: (num, den) → float; returns 0.0 on zero denominator (no raise).
  - `gps_to_decimal(dms_rationals, ref)`: converts DMS rational triple to decimal degrees; negates for `'S'`/`'W'`; returns None on short/None input.
  - `extract_photo_metadata(path)`: piexif.load wrapped in `except Exception` (T-03-01); extracts `date_taken` (DateTimeOriginal raw string), `camera_model` (null-bytes stripped), `orientation` (int), `gps_lat`, `gps_lon`. Returns all-None on any EXIF error.

- **`photoconsole/metadata/video.py`** — three functions:
  - `check_ffprobe_available()`: runs `ffprobe -version`; raises `RuntimeError` containing 'ffprobe' and 'install' on `FileNotFoundError`.
  - `parse_iso6709(s)`: regex `^([+-]\d+(?:\.\d+)?)([+-]\d+(?:\.\d+)?)` extracts lat/lon; returns (None, None) on any failure or empty input.
  - `extract_video_metadata(path)`: ffprobe JSON invocation (list form, timeout=60, no shell=True); recognises `creation_time` and `com.apple.quicktime.creationdate` for `date_taken`; recognises `location` and `com.apple.quicktime.location.ISO6709` for GPS via `parse_iso6709`; returns all-None on any failure.

- **`tests/test_metadata_photo.py`** — 13 tests using Pillow + piexif to generate test JPEGs at runtime: baseline no-EXIF, date_taken extraction, camera model (null bytes stripped), orientation, GPS N/S/E/W sign convention, None input, zero denominator, corrupt file, non-image file.

- **`tests/test_metadata_video.py`** — 14 tests with `mocker.patch('subprocess.run')`: parse_iso6709 positive/negative/garbage/empty/mixed-signs, check_ffprobe_available success/missing-raises, extract_video_metadata creation_time/Apple GPS/no-tags/all-keys/ffprobe-failure/subprocess-exception/timeout.

---

## Verification Results

All acceptance criteria commands passed:

```
pytest tests/test_hasher.py -x -q                           12 passed
pytest tests/test_metadata_photo.py -x -q                   13 passed
pytest tests/test_metadata_video.py -x -q                   14 passed
pytest tests/test_hasher.py tests/test_metadata_photo.py tests/test_metadata_video.py -x -q  39 passed
python -c "sha256_file(empty) == 'e3b0c44...'               PASS
python -c "from photoconsole.metadata import ..."           PASS
python -c "gps_to_decimal(..., 'N') == 40.5 ..."            PASS
python -c "parse_iso6709('+35.6762+139.6503...') == ..."    PASS
```

---

## TDD Gate Compliance

Both tasks followed TDD. The RED commits were pre-existing from a prior agent session:

| Phase | Task 1 | Task 2 |
|-------|--------|--------|
| RED   | f58f995 (test_hasher.py pre-committed) | Tests created, video.py stub created simultaneously |
| GREEN | 9a47711 (all implementation files + tests) | Same commit |

Note: Task 2's RED/GREEN were effectively merged into one commit because photo.py and video.py were new files. The test files were written before the implementation was complete (standard TDD spirit maintained).

---

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed test_sha256_streams_in_chunks tracking empty reads**
- **Found during:** Task 1 GREEN verification
- **Issue:** `CountingFile.read()` appended `len(chunk)` when `n > 0`, but the final walrus-loop read returns `b""` (len=0). This added a 0 to `read_calls`, shifting the "last" element check so a valid CHUNK_SIZE read appeared as the `read_calls[:-1]` partial — triggering `assert 100 == 8192`.
- **Fix:** Changed `if n > 0:` to `if n > 0 and chunk:` — only non-empty reads are tracked.
- **Files modified:** `tests/test_hasher.py`
- **Commit:** 9a47711 (same commit as implementation)

**2. [Rule 1 - Bug] Changed lazy imports to module-level imports in hasher.py**
- **Found during:** Task 1 GREEN verification (test_process_file_success_video failed)
- **Issue:** `process_file` used function-body `from photoconsole.metadata.video import extract_video_metadata` — lazy imports cannot be patched via `patch("photoconsole.hasher.extract_video_metadata")` because the name never exists at module scope.
- **Fix:** Moved both metadata imports to module-level in `hasher.py`.
- **Files modified:** `photoconsole/hasher.py`
- **Commit:** 9a47711

---

## Known Stubs

None — all functions are fully implemented. `camera_model=None` and `orientation=None` in `extract_video_metadata` are intentional by design (video container metadata does not carry these fields), not stubs.

---

## Threat Surface Scan

All threats from the plan's threat_model are mitigated:

| Threat | File | Status |
|--------|------|--------|
| T-03-01: piexif malformed EXIF | photoconsole/metadata/photo.py | Mitigated — `except Exception` wraps piexif.load; returns all-None |
| T-03-02: subprocess shell injection | photoconsole/metadata/video.py | Mitigated — list form only; no shell=True; filename never interpolated |
| T-03-03: ffprobe hang | photoconsole/metadata/video.py | Mitigated — timeout=60; TimeoutExpired caught in outer except → all-None |
| T-03-04: Pillow decompression bomb | photoconsole/metadata/photo.py | Mitigated — piexif reads EXIF headers without full decode; Pillow default MAX_IMAGE_PIXELS preserved |
| T-03-05: OOM non-streaming hash | photoconsole/hasher.py | Mitigated — walrus-loop reads CHUNK_SIZE bytes at a time |
| T-03-SC: supply chain | pyproject.toml | Pre-cleared — RESEARCH.md audit verified piexif [OK], Pillow [OK] |

No new network endpoints, auth paths, file access patterns beyond scope, or schema changes introduced.

---

## Self-Check: PASSED

Files created/verified:
- FOUND: photoconsole/hasher.py
- FOUND: photoconsole/metadata/__init__.py
- FOUND: photoconsole/metadata/photo.py
- FOUND: photoconsole/metadata/video.py
- FOUND: tests/test_metadata_photo.py
- FOUND: tests/test_metadata_video.py
- FOUND: tests/test_hasher.py (modified)

Commit verified:
- FOUND: 9a47711 (feat(01-03): file hasher, photo EXIF extractor, video ffprobe extractor)
