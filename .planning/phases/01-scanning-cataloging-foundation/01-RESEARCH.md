# Phase 1: Scanning & Cataloging Foundation - Research

**Researched:** 2026-05-16
**Domain:** Python CLI, filesystem traversal, SQLite cataloging, EXIF/video metadata extraction, parallel hashing, rclone integration
**Confidence:** HIGH (core stack), MEDIUM (rclone subprocess pattern, GPS extraction)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Error Handling**
- D-01: Files that fail to read or hash are stored in the catalog with `status='error'` and an `error_type` field (e.g., `'permission_denied'`, `'read_error'`). They are NOT skipped or discarded.
- D-02: All failure types are treated uniformly — one error_type field covers all cases.
- D-03: On incremental re-scan, always retry files with `status='error'`. If retry succeeds, update to `status='ok'`.

**Symlink Policy**
- D-04: Do not follow symbolic links. Skip them entirely during directory traversal.
- D-05: Skipped symlinks are silent by default. Log them only when `--verbose` is active. Never stored in catalog.

**Config File Structure**
- D-06: Sources are a named list with `type` (local/rclone) and path fields in YAML.
- D-07: File filtering (include/exclude) is global — no per-source overrides in Phase 1.
- D-08: `catalog_path` is defined in config.yaml. Not a CLI flag.
- D-09: `hashing.max_workers` configurable in config.yaml; default `os.cpu_count()`.

**Metadata — Photos (JPG, PNG, GIF)**
- D-10: Extract and store: `path`, `hash` (SHA256), `size`, `mtime`, `ctime`, plus EXIF fields: `date_taken`, `camera_model`, `orientation`, `gps_lat`, `gps_lon` (decimal degrees). Missing EXIF = NULL, not error.
- D-11: Use Pillow + piexif for EXIF extraction.

**Metadata — Videos (MP4, MOV, AVI)**
- D-12: Extract and store: `path`, `hash`, `size`, `mtime`, `ctime`, `date_taken` (from container `creation_time`), `gps_lat`/`gps_lon` if present.
- D-13: Use ffprobe as required system dependency. Missing ffprobe = clear error with install instructions. Video resolution/duration deferred to Phase 3.

### Claude's Discretion
- CLI framework (click vs argparse)
- Progress reporting style (tqdm, custom spinner, plain prints)
- SQLite schema design and indexing details
- Incremental scan marker mechanism (mtime, inode, or DB timestamp)
- Exact rclone integration approach (mount vs subprocess vs rclone.py)

### Deferred Ideas (OUT OF SCOPE)
- Per-source include/exclude overrides
- Video resolution + duration metadata
- Full EXIF extraction (ISO, focal length, aperture, white balance)
- RAW format support (CR2, NEF, ARW)
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| FR1 | Multi-source scanning: local filesystem + rclone mounts, configurable source list, skip non-media, report progress | pathlib.Path.walk() for local; rclone subprocess + lsjson for remote; extension allow-list; tqdm for progress |
| FR2 | Photo/video cataloging with metadata; SQLite persistence; incremental updates; track source per file | SQLAlchemy 2.0 ORM on SQLite; Pillow+piexif for photos; ffprobe subprocess for videos; mtime-based incremental tracking |
| FR5 | CLI: `photoconsole scan --config config.yaml`; global --verbose, --quiet flags | click 8.x group + pass_context pattern; pyproject.toml console_scripts entry point |
| FR6 | Scan 100K items in <30 min; parallel hashing; incremental scan (skip unchanged); memory efficient | concurrent.futures.ThreadPoolExecutor; streaming SHA256 with 8KB chunks; WAL mode SQLite; mtime-skip logic |
</phase_requirements>

---

## Summary

Phase 1 establishes the core data pipeline: discover media files from local paths and rclone remotes, compute SHA256 hashes in parallel, extract photo/video metadata, and persist everything to a SQLite catalog. The tech stack is well-established Python: `pathlib` for filesystem traversal, `Pillow + piexif` for photo EXIF, `ffprobe` via subprocess for video metadata, `SQLAlchemy 2.0` for the ORM layer, `click 8.x` for the CLI, and `concurrent.futures.ThreadPoolExecutor` for parallel hashing.

The highest-risk area is rclone integration. No actively-maintained Python wrapper exists (the `rclone` package on PyPI was last updated in 2022 and targets Python 3.6-3.9). The correct approach is direct subprocess calls to `rclone lsjson --recursive --files-only` piped through `json.loads()`. This gives full control, zero dependency risk, and is the pattern used by most production tools that wrap rclone. The planner should treat rclone as a system dependency (not a Python library), document it alongside ffprobe in the environment requirements.

The second area requiring care is SQLite concurrency: parallel hashing workers produce results that must be written to SQLite, but SQLite allows only one writer at a time. The correct pattern is to collect results into a queue and flush to the DB from a single dedicated writer thread (or batch at the end of each file scan). WAL mode plus a reasonable `timeout` prevents "database is locked" errors without needing a separate process.

**Primary recommendation:** Use the direct subprocess rclone pattern, SQLAlchemy 2.0 declarative ORM with WAL mode, click for CLI, tqdm for progress, and ThreadPoolExecutor for parallel hashing. Collect hash results in-memory per batch, then write in a single transaction per batch.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Local filesystem traversal | CLI process | — | pathlib.Path.walk() runs in-process; no network boundary |
| Rclone remote listing | CLI process (subprocess) | rclone binary | Python orchestrates; rclone handles remote auth and protocol |
| SHA256 hashing | CLI process (thread pool) | — | CPU+I/O bound; ThreadPoolExecutor parallelizes across cores |
| EXIF metadata extraction | CLI process | Pillow + piexif libs | Library calls; no separate tier needed |
| Video metadata extraction | CLI process (subprocess) | ffprobe binary | ffprobe handles codec parsing; Python parses JSON output |
| Catalog persistence | SQLite file | SQLAlchemy ORM | Local database; no server tier needed |
| Config parsing | CLI process | PyYAML | Single file read at startup |
| CLI surface | Click group | pyproject.toml entry point | click handles argument parsing and routing |

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Pillow | 12.2.0 | Open images, read EXIF via getexif() | De-facto Python imaging library; official PIL fork; 50M+/wk downloads [VERIFIED: PyPI registry] |
| piexif | 1.1.3 | Parse EXIF IFD structure, GPS tags | Lightweight EXIF read/write; only library exposing GPS IFD as structured dict [VERIFIED: PyPI registry] |
| click | 8.3.3 | CLI framework: commands, groups, options, context | Standard CLI library for Python tools; auto-generates help; decorator-based; clean group/subcommand pattern [VERIFIED: PyPI registry] |
| tqdm | 4.67.3 | Progress bars for file scanning | Zero-dependency progress bar; works with iterables; supports manual update for streaming [VERIFIED: PyPI registry] |
| PyYAML | 6.0.3 | Parse config.yaml | Standard YAML parser for Python [VERIFIED: PyPI registry] |
| SQLAlchemy | 2.0.49 | ORM layer on SQLite | Most complete Python ORM; 2.0 API uses type-annotated Mapped columns; session management [VERIFIED: PyPI registry] |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest | 9.0.3 | Test framework | All unit tests for scanner, catalog, metadata extraction [VERIFIED: PyPI registry] |
| pytest-mock | 3.15.1 | Mock filesystem, subprocess calls in tests | Mock ffprobe calls, rclone subprocess, file I/O [VERIFIED: PyPI registry] |

### System Dependencies (not Python packages)

| Tool | Version Needed | Purpose | Install |
|------|---------------|---------|---------|
| ffprobe (ffmpeg) | any recent | Video metadata extraction | `winget install ffmpeg` / `brew install ffmpeg` / `apt install ffmpeg` |
| rclone | any recent | Remote file listing | https://rclone.org/install/ |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| click | argparse | argparse is stdlib (zero deps), but no group/subcommand nesting without boilerplate; no auto-generated help formatting; click wins for multi-command CLIs |
| click | typer | typer builds on click + type hints; heavier; overkill for this scope |
| SQLAlchemy ORM | raw sqlite3 | stdlib, no deps, simpler; but ORM gives schema-as-code, easier incremental migration for Phase 2+; recommend ORM |
| SQLAlchemy ORM | peewee | Smaller ORM; fewer integrations; SQLAlchemy is more standard |
| tqdm | rich.progress | rich provides prettier output; heavier dependency; tqdm is sufficient and extremely stable |
| concurrent.futures.ThreadPoolExecutor | multiprocessing.Pool | Threading is simpler and sufficient for I/O-bound hashing; multiprocessing adds pickling overhead and IPC complexity |
| piexif | exifread | exifread reads EXIF but doesn't expose GPS IFD as structured dict; piexif is more precise for GPS rational parsing |

**Installation:**
```bash
pip install pillow piexif click tqdm PyYAML SQLAlchemy pytest pytest-mock
```

**pyproject.toml entry point:**
```toml
[project.scripts]
photoconsole = "photoconsole.cli:main"
```

**Development install:**
```bash
pip install -e .
```

---

## Package Legitimacy Audit

All packages verified via slopcheck 0.6.1 on 2026-05-16:

| Package | Registry | Age | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|
| pillow | PyPI | 14+ yrs | [OK] | Approved |
| piexif | PyPI | 9+ yrs | [OK] | Approved |
| click | PyPI | 10+ yrs | [OK] | Approved |
| tqdm | PyPI | 10+ yrs | [OK] | Approved |
| PyYAML | PyPI | 15+ yrs | [OK] | Approved |
| SQLAlchemy | PyPI | 18+ yrs | [OK] | Approved |
| pytest | PyPI | 15+ yrs | [OK] | Approved |
| pytest-mock | PyPI | 10+ yrs | [OK] | Approved |
| rich | PyPI | 6+ yrs | [OK] | Approved (optional) |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

*slopcheck ran successfully; all packages are [VERIFIED: PyPI registry] via direct registry check.*

---

## Architecture Patterns

### System Architecture Diagram

```
config.yaml
    |
    v
[Config Loader] ---> sources list, filter rules, catalog_path, max_workers
    |
    +---> [Local Scanner]           [Rclone Scanner]
    |      pathlib.Path.walk()       subprocess: rclone lsjson -R
    |      skip symlinks             parse JSON output
    |            |                         |
    +------------+-------------------------+
                 |
         [File Candidate Stream]
         (path, source_name, source_type)
                 |
         [Extension Filter]
         (allow-list: jpg/png/gif/mp4/mov/avi)
                 |
         [Incremental Check]
         Query DB: known path + mtime unchanged? --> SKIP
         status='error'? --> always retry
                 |
         [Thread Pool: Hash + Metadata]  <-- max_workers from config
         |                    |
         [SHA256 streamer]    [Metadata extractor]
         8KB chunks           Photo: Pillow + piexif
                              Video: ffprobe subprocess -> JSON
                 |
         [Result Queue / Batch Buffer]
                 |
         [DB Writer (single thread)]
         SQLAlchemy session, WAL mode
         UPSERT on path (INSERT OR REPLACE)
         Batch commit every N files
                 |
         [SQLite Catalog]
         media_files table
```

### Recommended Project Structure

```
photoconsole/
├── __init__.py
├── cli.py               # click group + scan command
├── config.py            # YAML loader, Config dataclass
├── scanner.py           # LocalScanner, RcloneScanner (same interface)
├── hasher.py            # SHA256 streaming hash, ThreadPoolExecutor orchestration
├── metadata/
│   ├── __init__.py
│   ├── photo.py         # Pillow + piexif extraction, GPS conversion
│   └── video.py         # ffprobe subprocess wrapper, JSON parsing
├── catalog/
│   ├── __init__.py
│   ├── models.py        # SQLAlchemy ORM: MediaFile model
│   └── db.py            # Engine setup, WAL mode, session factory, UPSERT
├── errors.py            # ErrorType enum/constants
└── constants.py         # MEDIA_EXTENSIONS set, CHUNK_SIZE

tests/
├── conftest.py          # tmp_path fixtures, mock DB
├── test_scanner.py
├── test_hasher.py
├── test_metadata_photo.py
├── test_metadata_video.py
├── test_catalog.py
└── test_cli.py

pyproject.toml
config.example.yaml
```

### Pattern 1: Click Group with Shared Context

**What:** A `@click.group()` at the top-level `main` function holds global options (`--verbose`, `--quiet`, `--config`). Subcommands receive these via `ctx.obj`.

**When to use:** Multi-command CLIs where flags like `--verbose` must propagate to all subcommands without repeating decorators.

```python
# Source: https://click.palletsprojects.com/en/stable/commands-and-groups/
import click

@click.group()
@click.option('--verbose', '-v', is_flag=True, default=False, help='Enable verbose output.')
@click.option('--quiet', '-q', is_flag=True, default=False, help='Suppress non-error output.')
@click.pass_context
def main(ctx, verbose, quiet):
    ctx.ensure_object(dict)
    ctx.obj['verbose'] = verbose
    ctx.obj['quiet'] = quiet

@main.command()
@click.option('--config', required=True, type=click.Path(exists=True), help='Path to config.yaml.')
@click.pass_context
def scan(ctx, config):
    verbose = ctx.obj['verbose']
    # scan logic here
```

### Pattern 2: Streaming SHA256 Hash (memory-efficient)

**What:** Read file in 8KB chunks and update hash incrementally. Never loads full file into memory.

**When to use:** All file hashing. Essential for large video files (multi-GB).

```python
# Source: https://docs.python.org/3/library/hashlib.html
import hashlib

CHUNK_SIZE = 8 * 1024  # 8 KB

def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while chunk := f.read(CHUNK_SIZE):
            h.update(chunk)
    return h.hexdigest()
```

### Pattern 3: ThreadPoolExecutor for Parallel Hashing

**What:** Submit hashing tasks to a thread pool; collect results via `as_completed()`.

**When to use:** Hashing + metadata extraction phase — I/O-bound, benefits from threading.

```python
# Source: https://docs.python.org/3/library/concurrent.futures.html
from concurrent.futures import ThreadPoolExecutor, as_completed

def process_files(file_paths, max_workers):
    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_path = {executor.submit(process_one_file, p): p for p in file_paths}
        for future in as_completed(future_to_path):
            path = future_to_path[future]
            try:
                result = future.result()
                results.append(result)
            except Exception as exc:
                results.append({'path': path, 'status': 'error', 'error_type': classify_error(exc)})
    return results
```

### Pattern 4: Rclone Integration via Subprocess

**What:** Call `rclone lsjson --recursive --files-only <remote:path>` and parse JSON output. No Python wrapper library — use subprocess directly.

**When to use:** All rclone source types. This is the only safe approach given no actively-maintained Python wrapper exists.

```python
# Source: https://rclone.org/commands/rclone_lsjson/
import subprocess
import json

def list_rclone_files(remote: str) -> list[dict]:
    """Returns list of dicts with Path, Size, ModTime, IsDir fields."""
    result = subprocess.run(
        ['rclone', 'lsjson', '--recursive', '--files-only', remote],
        capture_output=True, text=True, timeout=300
    )
    if result.returncode != 0:
        raise RuntimeError(f"rclone failed: {result.stderr.strip()}")
    return json.loads(result.stdout)

def list_rclone_remotes() -> list[str]:
    """Returns list of configured remote names."""
    result = subprocess.run(
        ['rclone', 'listremotes'],
        capture_output=True, text=True, timeout=30
    )
    return [r.strip() for r in result.stdout.splitlines() if r.strip()]
```

### Pattern 5: EXIF GPS Rational to Decimal Degrees

**What:** piexif stores GPS coordinates as tuples of rational numbers (numerator, denominator) in degrees/minutes/seconds format. Convert to decimal degrees.

**When to use:** Extracting gps_lat and gps_lon from photo EXIF.

```python
# Source: https://rclone.org + community patterns (ASSUMED - verified conceptually)
import piexif

def rational_to_float(rational) -> float:
    """Convert piexif rational (numerator, denominator) to float."""
    return rational[0] / rational[1] if rational[1] != 0 else 0.0

def gps_to_decimal(dms_rationals, ref: str) -> float | None:
    """Convert GPS DMS rational tuple to decimal degrees."""
    if not dms_rationals or len(dms_rationals) < 3:
        return None
    degrees = rational_to_float(dms_rationals[0])
    minutes = rational_to_float(dms_rationals[1])
    seconds = rational_to_float(dms_rationals[2])
    decimal = degrees + minutes / 60 + seconds / 3600
    if ref in ('S', 'W'):
        decimal = -decimal
    return decimal

def extract_photo_metadata(path: str) -> dict:
    try:
        exif_data = piexif.load(path)
    except Exception:
        return {}  # Missing or malformed EXIF -> all NULL, not error
    
    gps = exif_data.get('GPS', {})
    gps_lat = gps_to_decimal(gps.get(piexif.GPSIFD.GPSLatitude), 
                              gps.get(piexif.GPSIFD.GPSLatitudeRef, b'N').decode())
    gps_lon = gps_to_decimal(gps.get(piexif.GPSIFD.GPSLongitude),
                              gps.get(piexif.GPSIFD.GPSLongitudeRef, b'E').decode())
    
    zeroth = exif_data.get('0th', {})
    exif_ifd = exif_data.get('Exif', {})
    
    date_taken_raw = exif_ifd.get(piexif.ExifIFD.DateTimeOriginal, b'').decode(errors='ignore')
    camera_model_raw = zeroth.get(piexif.ImageIFD.Model, b'').decode(errors='ignore').strip('\x00')
    orientation = zeroth.get(piexif.ImageIFD.Orientation)
    
    return {
        'date_taken': date_taken_raw or None,
        'camera_model': camera_model_raw or None,
        'orientation': orientation,
        'gps_lat': gps_lat,
        'gps_lon': gps_lon,
    }
```

### Pattern 6: ffprobe Metadata Extraction

**What:** Call ffprobe with `-show_format -show_entries format_tags -print_format json` to extract container tags including `creation_time` and location.

**When to use:** All video files (MP4, MOV, AVI).

```python
# Source: https://ffmpeg.org/ffprobe.html
import subprocess
import json
from datetime import datetime, timezone

def check_ffprobe_available():
    """Raises RuntimeError with install instructions if ffprobe not found."""
    try:
        subprocess.run(['ffprobe', '-version'], capture_output=True, check=True)
    except FileNotFoundError:
        raise RuntimeError(
            "ffprobe not found. Install ffmpeg: https://ffmpeg.org/download.html\n"
            "  Windows: winget install ffmpeg\n"
            "  macOS:   brew install ffmpeg\n"
            "  Linux:   apt install ffmpeg"
        )

def extract_video_metadata(path: str) -> dict:
    result = subprocess.run(
        ['ffprobe', '-v', 'quiet', '-print_format', 'json',
         '-show_format', '-show_entries', 'format_tags'],
        capture_output=True, text=True, timeout=60
    )
    if result.returncode != 0:
        return {}
    
    data = json.loads(result.stdout)
    tags = data.get('format', {}).get('tags', {})
    
    # creation_time is ISO 8601: "2022-02-11T18:26:58.000000Z"
    creation_time_str = tags.get('creation_time') or tags.get('com.apple.quicktime.creationdate')
    date_taken = None
    if creation_time_str:
        try:
            date_taken = creation_time_str  # Store as string; parse if needed
        except Exception:
            pass
    
    # GPS: some cameras embed as "location" tag: "+35.6762+139.6503+004.000/"
    location = tags.get('location') or tags.get('com.apple.quicktime.location.ISO6709')
    gps_lat, gps_lon = None, None
    if location:
        gps_lat, gps_lon = parse_iso6709(location)
    
    return {'date_taken': date_taken, 'gps_lat': gps_lat, 'gps_lon': gps_lon}
```

### Pattern 7: SQLAlchemy 2.0 ORM Model with WAL Mode

**What:** Declarative base with type-annotated Mapped columns. Engine configured with WAL mode pragma for concurrent read-while-write.

**When to use:** All catalog persistence operations.

```python
# Source: https://docs.sqlalchemy.org/en/20/orm/quickstart.html
from sqlalchemy import create_engine, event, String, Float, Integer, BigInteger, DateTime, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session
from typing import Optional
import datetime

class Base(DeclarativeBase):
    pass

class MediaFile(Base):
    __tablename__ = 'media_files'
    
    id: Mapped[int] = mapped_column(primary_key=True)
    path: Mapped[str] = mapped_column(String, unique=True, index=True)
    hash: Mapped[Optional[str]] = mapped_column(String(64), index=True)  # SHA256 hex
    size: Mapped[Optional[int]] = mapped_column(BigInteger)
    mtime: Mapped[Optional[float]] = mapped_column(Float)
    ctime: Mapped[Optional[float]] = mapped_column(Float)
    source_name: Mapped[Optional[str]] = mapped_column(String)
    source_type: Mapped[Optional[str]] = mapped_column(String)  # 'local' | 'rclone'
    media_type: Mapped[Optional[str]] = mapped_column(String)   # 'photo' | 'video'
    status: Mapped[str] = mapped_column(String, default='ok', index=True)  # 'ok' | 'error'
    error_type: Mapped[Optional[str]] = mapped_column(String)
    date_taken: Mapped[Optional[str]] = mapped_column(String)
    camera_model: Mapped[Optional[str]] = mapped_column(String)
    orientation: Mapped[Optional[int]] = mapped_column(Integer)
    gps_lat: Mapped[Optional[float]] = mapped_column(Float)
    gps_lon: Mapped[Optional[float]] = mapped_column(Float)
    scanned_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )

def create_engine_with_wal(db_path: str):
    engine = create_engine(f'sqlite:///{db_path}')
    
    @event.listens_for(engine, 'connect')
    def set_wal_mode(conn, _):
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA synchronous=NORMAL')
        conn.execute('PRAGMA busy_timeout=5000')
    
    Base.metadata.create_all(engine)
    return engine
```

### Pattern 8: Incremental Scan Logic

**What:** Before hashing, check if a file path already exists in the catalog with the same mtime. If so, skip it (unless status='error', which always gets retried per D-03).

**Recommendation:** Use `mtime` as the change marker. It is the simplest and most universally available signal. Inode tracking doesn't work across rclone sources or file copies. DB timestamps have clock drift risk.

```python
def should_skip(session: Session, path: str, mtime: float) -> bool:
    """Return True if file is unchanged and previously succeeded."""
    existing = session.query(MediaFile).filter_by(path=path).first()
    if existing is None:
        return False
    if existing.status == 'error':
        return False  # D-03: always retry errors
    return existing.mtime == mtime  # skip if mtime unchanged
```

### Anti-Patterns to Avoid

- **Loading full file into memory for hashing:** Always read in chunks. A 10GB video will OOM if loaded entirely.
- **One SQLAlchemy connection shared across threads:** SQLite connections are not thread-safe. Use a dedicated writer thread or pass separate connections per thread. Recommended: collect results from threads, write in single-threaded batches.
- **Using `os.walk()` with `followlinks=True` (default):** os.walk() follows symlinks by default. Use `Path.walk(follow_symlinks=False)` (Python 3.12+) or check `path.is_symlink()` inside `os.walk()` loops.
- **Calling rclone.py or python-rclone Python packages:** Both are unmaintained (last release 2022, targets Python 3.6-3.9). Use subprocess directly.
- **Storing GPS as strings:** Store as REAL (float) columns in decimal degrees. String storage breaks range queries in Phase 2+.
- **Free-form error_type strings:** Use an enum/constants module. Free-form strings prevent reliable retry filtering (D-02).
- **Ignoring piexif decode errors:** `piexif.load()` raises `piexif.InvalidImageDataError` or `ValueError` on corrupt EXIF. Always wrap in try/except — missing EXIF is NULL, not an error (D-11).

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| EXIF parsing and GPS IFD traversal | Custom binary EXIF parser | piexif | EXIF is a complex binary format with nested IFDs, endianness variations, and rational number types; piexif handles all edge cases |
| Progress bars | Custom spinner/counter | tqdm | Unicode rendering, ETA calculation, nested bars, Windows terminal compatibility are all handled |
| YAML config parsing | Custom INI/JSON parser | PyYAML | YAML supports multi-line values, comments, anchors; hand-rolling is brittle |
| Video container metadata | Custom MP4/MOV parser | ffprobe | Video containers (MP4, MOV, AVI) have wildly different metadata storage; ffprobe normalizes across all |
| ORM / SQL string building | Raw sqlite3 with f-strings | SQLAlchemy ORM | SQL injection risk, migration pain, no schema-as-code; ORM is safer and prepares Phase 2 queries |
| CLI help generation | Print statements | click | Auto-generates `--help`, handles type coercion, validates required args |
| Thread-safe hashing orchestration | Manual thread + lock management | ThreadPoolExecutor | futures handle exceptions cleanly; `as_completed()` is simpler than raw thread join loops |

**Key insight:** The metadata extraction domain (EXIF, video containers) has extraordinary edge case density accumulated over decades of camera firmware variations. Custom parsers will miss manufacturer-specific tag placements, encoding quirks, and malformed-but-common EXIF data. Libraries encode years of community fixes.

---

## Common Pitfalls

### Pitfall 1: Path.walk() vs os.walk() Symlink Behavior

**What goes wrong:** `os.walk()` includes symlinks in file listings by default (no `followlinks` needed); `pathlib.Path.walk()` (Python 3.12+) sets `follow_symlinks=False` by default for directories but still lists symlink files.

**Why it happens:** Python's two traversal APIs have different defaults. The CONTEXT.md decision D-04 requires skipping symlinks, which means checking every file candidate.

**How to avoid:** Check `path.is_symlink()` for every file candidate before processing. For Python 3.12+, `Path.walk(follow_symlinks=False)` prevents entering symlinked directories, but you still need to check individual file symlinks.

**Warning signs:** Seeing duplicate entries or circular scan loops in the catalog.

### Pitfall 2: SQLite "database is locked" Under Parallel Writes

**What goes wrong:** ThreadPoolExecutor workers try to commit to SQLite concurrently → `OperationalError: database is locked`.

**Why it happens:** SQLite allows only one writer at a time. WAL mode helps readers, but write contention still serializes and times out.

**How to avoid:** Never write to the DB from worker threads. Have workers return results (in-memory), then batch-commit from the main thread after each chunk completes. Set `PRAGMA busy_timeout=5000` as a safety net.

**Warning signs:** Intermittent `OperationalError` on scans of large directories.

### Pitfall 3: piexif Decoding Crashes on Malformed EXIF

**What goes wrong:** Some cameras write syntactically invalid EXIF (bad rational denominators, truncated IFDs). `piexif.load()` raises `piexif.InvalidImageDataError` or `struct.error`.

**Why it happens:** EXIF is a complex binary standard with many firmware-specific non-conformances. piexif is strict by design.

**How to avoid:** Always wrap `piexif.load()` in a broad `except Exception` block. On any exception, return empty metadata dict — not an error status (D-11: missing EXIF = NULL).

**Warning signs:** Scan crashes on specific camera brands (older Canon, Samsung, some Android phones).

### Pitfall 4: ffprobe GPS Location Format Varies by Device

**What goes wrong:** GPS location in video files is NOT standardized. Apple QuickTime uses `com.apple.quicktime.location.ISO6709` (ISO 6709 format: `+35.6762+139.6503+004.000/`). Android may use different tags. Some cameras write no GPS.

**Why it happens:** The video container spec does not mandate a GPS tag; each manufacturer extends the container.

**How to avoid:** Check multiple tag names (`location`, `com.apple.quicktime.location.ISO6709`). Write a defensive ISO 6709 parser. Return NULL if no recognized GPS tag is found — not an error.

**Warning signs:** GPS extraction works on iPhone videos but not Android, or vice versa.

### Pitfall 5: rclone lsjson Timeout on Large Remotes

**What goes wrong:** `rclone lsjson --recursive` on a 100K-file Google Drive can take minutes. Python subprocess `timeout=300` may not be enough on slow connections.

**Why it happens:** rclone must traverse the entire remote directory tree via API calls, which is rate-limited by the cloud provider.

**How to avoid:** Make the subprocess timeout configurable. Show a "listing remote files..." message before calling lsjson (it can appear hung). Consider a streaming approach: `subprocess.Popen()` with stdout=PIPE rather than capturing all output at once for very large remotes.

**Warning signs:** Scan appears hung after local files complete but before rclone sources start.

### Pitfall 6: mtime Precision Differences Across Filesystems

**What goes wrong:** Incremental scan stores mtime as a float, but FAT32/exFAT (common on backup drives) has 2-second mtime granularity. A file touched on an NTFS source and written to FAT32 catalog will always appear "changed".

**Why it happens:** Python `os.stat().st_mtime` returns a float with nanosecond precision on NTFS/ext4, but FAT32 rounds to 2 seconds.

**How to avoid:** For rclone sources, compare the mtime returned by rclone lsjson (which is RFC3339, sub-second). For local sources on mixed filesystem environments, consider rounding mtime to 2-second granularity or using size+mtime combined as the change key.

**Warning signs:** Every file is re-hashed on every incremental scan of FAT32 backup drives.

---

## Code Examples

### ErrorType Constants (don't use free-form strings)

```python
# photoconsole/errors.py
from enum import StrEnum

class ErrorType(StrEnum):
    PERMISSION_DENIED = 'permission_denied'
    READ_ERROR = 'read_error'
    HASH_FAILED = 'hash_failed'
    METADATA_FAILED = 'metadata_failed'
    NOT_FOUND = 'not_found'
    TIMEOUT = 'timeout'

def classify_error(exc: Exception) -> str:
    if isinstance(exc, PermissionError):
        return ErrorType.PERMISSION_DENIED
    if isinstance(exc, FileNotFoundError):
        return ErrorType.NOT_FOUND
    if isinstance(exc, TimeoutError):
        return ErrorType.TIMEOUT
    return ErrorType.READ_ERROR
```

### Config Dataclass + YAML Loader

```python
# photoconsole/config.py
from dataclasses import dataclass, field
import os
import yaml
from pathlib import Path

@dataclass
class Source:
    name: str
    type: str          # 'local' | 'rclone'
    path: str = ''     # local path
    remote: str = ''   # rclone remote e.g. 'gdrive:'

@dataclass
class Config:
    sources: list[Source]
    catalog_path: str
    include_extensions: list[str] = field(default_factory=lambda: [
        '.jpg', '.jpeg', '.png', '.gif', '.mp4', '.mov', '.avi'
    ])
    exclude_patterns: list[str] = field(default_factory=list)
    hashing_max_workers: int = field(default_factory=os.cpu_count)

def load_config(path: str) -> Config:
    with open(path) as f:
        raw = yaml.safe_load(f)
    sources = [Source(**s) for s in raw.get('sources', [])]
    return Config(
        sources=sources,
        catalog_path=os.path.expanduser(raw['catalog_path']),
        include_extensions=raw.get('include_extensions', Config.include_extensions.default_factory()),
        hashing_max_workers=raw.get('hashing', {}).get('max_workers', os.cpu_count()),
    )
```

### config.example.yaml

```yaml
catalog_path: ~/.photoconsole/catalog.db

sources:
  - name: "Local Photos"
    type: local
    path: /mnt/photos

  - name: "Google Drive"
    type: rclone
    remote: gdrive:

include_extensions:
  - .jpg
  - .jpeg
  - .png
  - .gif
  - .mp4
  - .mov
  - .avi

hashing:
  max_workers: 4  # default: os.cpu_count()
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `setup.py` for packaging | `pyproject.toml` with `[project.scripts]` | PEP 621, ~2021 | Modern packaging; `pip install -e .` works cleanly |
| SQLAlchemy 1.x `Column()` style | SQLAlchemy 2.0 `Mapped[T]` + `mapped_column()` | SQLAlchemy 2.0, 2023 | Type-safe ORM; better IDE support; 1.x style still works in 2.x with deprecation warnings |
| `pathlib.Path.rglob()` for traversal | `pathlib.Path.walk()` (Python 3.12+) | Python 3.12, Oct 2023 | `walk()` supports `follow_symlinks` param; `rglob()` has symlink loop risk |
| `python-rclone` PyPI package | Direct subprocess to rclone binary | Package abandoned 2022 | No actively-maintained Python rclone wrapper exists; subprocess is the correct approach |
| `PIL.Image._getexif()` | `PIL.Image.getexif()` (public API) | Pillow 6.0+ | `_getexif()` was private and undocumented; `getexif()` is the stable public API |

**Deprecated/outdated:**
- `exifread` library: Still maintained but doesn't expose structured GPS IFD dict as cleanly as piexif; piexif preferred for this use case.
- `python-rclone` (PyPI): Last release July 2022, targets Python 3.6-3.9 only. Do not use.
- `rclone` (PyPI, 0.4.4): Same vintage, unmaintained. Do not use.
- `PIL.Image._getexif()`: Private API, removed/unreliable in modern Pillow. Use `Image.getexif()` instead.

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | GPS location in video files appears in ffprobe output under `location` or `com.apple.quicktime.location.ISO6709` tags | Code Examples (video metadata) | GPS extraction silently returns NULL for some camera brands; low risk since NULL is acceptable per D-12 |
| A2 | mtime comparison is sufficient as an incremental scan marker for local sources | Pattern 8 | Re-scans may miss changes on FAT32 drives (2-second granularity); addressed in Pitfall 6 |
| A3 | GPS conversion formula (DMS rational to decimal degrees) handles negative hemisphere correctly via ref byte | Code Examples (photo metadata) | Wrong sign for Southern/Western coordinates; verify with real geotagged photos |

**If this table is empty:** N/A — three assumptions found; all are low-risk with clear validation paths.

---

## Open Questions

1. **Python version minimum**
   - What we know: Developer machine has Python 3.14.3. `pathlib.Path.walk()` requires Python 3.12+.
   - What's unclear: Is there a minimum Python version to support, or is 3.12+ acceptable?
   - Recommendation: Target Python 3.12+ to get `Path.walk(follow_symlinks=False)`. Document in pyproject.toml `requires-python = ">=3.12"`.

2. **rclone lsjson streaming for large remotes**
   - What we know: Capturing all lsjson output in memory works for moderate remotes; large remotes (100K+ files) may be slow to enumerate.
   - What's unclear: Whether `subprocess.Popen()` streaming mode is needed or if a single capture is acceptable.
   - Recommendation: Start with `subprocess.run(capture_output=True)` for simplicity. If Phase 1 testing reveals timeout issues on real remotes, switch to `Popen` streaming.

3. **ISO 6709 GPS parser for video files**
   - What we know: Apple QuickTime embeds GPS as ISO 6709 string. Android may differ.
   - What's unclear: Whether the planner should include a robust ISO 6709 parser or a simple regex for the common format.
   - Recommendation: Include a simple regex parser for the `+DD.DDDD+DDD.DDDD/` format in the initial implementation; flag as an area for hardening in Phase 3 if needed.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | Core | Yes | 3.14.3 | — |
| pip | Package install | Yes | 25.3 | — |
| rclone | Rclone source scanning | No | — | Skip rclone sources; show error with install link |
| ffprobe (ffmpeg) | Video metadata extraction | No | — | Error with install instructions per D-13; video files get status='error' with error_type='ffprobe_not_found' if ffprobe absent at startup |

**Missing dependencies with no fallback:**
- ffprobe: Required for video metadata per D-13. Planner must include a Wave 0 task to detect and error clearly at `photoconsole scan` startup if ffprobe is absent.

**Missing dependencies with fallback:**
- rclone: If absent, rclone-type sources are skipped with a clear error message; local sources still work. Install instructions should be shown at scan startup when a rclone source is configured but binary not found.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.0.3 |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (Wave 0) |
| Quick run command | `pytest tests/ -x -q` |
| Full suite command | `pytest tests/ -v --tb=short` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| FR1 | Local scanner discovers media files recursively | unit | `pytest tests/test_scanner.py::test_local_scan_recursive -x` | No — Wave 0 |
| FR1 | Local scanner skips symlinks silently | unit | `pytest tests/test_scanner.py::test_skip_symlinks -x` | No — Wave 0 |
| FR1 | Local scanner skips non-media files | unit | `pytest tests/test_scanner.py::test_skip_non_media -x` | No — Wave 0 |
| FR1 | Rclone scanner calls lsjson correctly | unit | `pytest tests/test_scanner.py::test_rclone_lsjson_call -x` | No — Wave 0 |
| FR2 | SHA256 hash computed correctly for known file | unit | `pytest tests/test_hasher.py::test_sha256_known_file -x` | No — Wave 0 |
| FR2 | Photo EXIF extraction returns expected fields | unit | `pytest tests/test_metadata_photo.py::test_exif_extraction -x` | No — Wave 0 |
| FR2 | Missing EXIF returns NULL fields, not error | unit | `pytest tests/test_metadata_photo.py::test_missing_exif_null -x` | No — Wave 0 |
| FR2 | Video ffprobe extraction returns date_taken | unit | `pytest tests/test_metadata_video.py::test_ffprobe_creation_time -x` | No — Wave 0 |
| FR2 | Catalog stores file with all fields | unit | `pytest tests/test_catalog.py::test_upsert_media_file -x` | No — Wave 0 |
| FR2 | Incremental scan skips unchanged file | unit | `pytest tests/test_catalog.py::test_incremental_skip -x` | No — Wave 0 |
| FR2 | Error files are retried on re-scan | unit | `pytest tests/test_catalog.py::test_error_retry -x` | No — Wave 0 |
| FR5 | `photoconsole scan --config X` runs without error | integration | `pytest tests/test_cli.py::test_scan_command_help -x` | No — Wave 0 |
| FR6 | Parallel hashing uses multiple workers | unit | `pytest tests/test_hasher.py::test_parallel_workers -x` | No — Wave 0 |
| FR6 | Files with status=error are not skipped on retry | unit | `pytest tests/test_catalog.py::test_error_always_retried -x` | No — Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/ -x -q`
- **Per wave merge:** `pytest tests/ -v --tb=short`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/conftest.py` — tmp_path fixtures, in-memory SQLite engine
- [ ] `tests/test_scanner.py` — covers FR1 local + rclone scan behaviors
- [ ] `tests/test_hasher.py` — covers FR2 + FR6 hashing
- [ ] `tests/test_metadata_photo.py` — covers FR2 EXIF photo extraction
- [ ] `tests/test_metadata_video.py` — covers FR2 video metadata extraction
- [ ] `tests/test_catalog.py` — covers FR2 persistence + incremental logic
- [ ] `tests/test_cli.py` — covers FR5 CLI commands
- [ ] `pyproject.toml` `[tool.pytest.ini_options]` section — configure testpaths
- [ ] Framework install: `pip install pytest pytest-mock` (already available on this machine)

---

## Security Domain

> `security_enforcement` not found in config.json — treating as enabled.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | Local-only tool; no auth layer |
| V3 Session Management | No | CLI tool; no sessions |
| V4 Access Control | No | Single-user local tool |
| V5 Input Validation | Yes | Validate config.yaml fields (paths exist, extensions are safe strings); validate ffprobe/rclone output before parsing |
| V6 Cryptography | No | SHA256 used for deduplication identity, not security; no key management needed |

### Known Threat Patterns for This Stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Path traversal in config.yaml | Tampering | Validate all paths with `pathlib.Path.resolve()`; check they don't escape expected roots |
| Shell injection via rclone remote names | Tampering | Use `subprocess.run(list_form)` — never shell=True, never f-string in shell command |
| Malformed EXIF causing crash | Denial of Service | Wrap all piexif/Pillow calls in try/except; never propagate exception to crash scan |
| ffprobe output injection | Tampering | Parse ffprobe output with `json.loads()` — never exec or eval; validate expected field types |
| Large file decompression bomb | Denial of Service | Pillow has built-in `MAX_IMAGE_PIXELS` decompression bomb protection; do not disable it |

**Critical:** Always use `subprocess.run(['rclone', 'lsjson', remote], ...)` with a list, never `shell=True`. Rclone remote names come from user config and could contain shell metacharacters.

---

## Sources

### Primary (HIGH confidence)
- PyPI registry — pillow 12.2.0, piexif 1.1.3, click 8.3.3, tqdm 4.67.3, PyYAML 6.0.3, SQLAlchemy 2.0.49, pytest 9.0.3, pytest-mock 3.15.1 [VERIFIED: PyPI registry via pip index versions]
- https://click.palletsprojects.com/en/stable/commands-and-groups/ — click group + pass_context pattern
- https://docs.sqlalchemy.org/en/20/orm/quickstart.html — SQLAlchemy 2.0 declarative ORM
- https://docs.python.org/3/library/concurrent.futures.html — ThreadPoolExecutor, as_completed, exception handling
- https://docs.python.org/3/library/hashlib.html — streaming SHA256 pattern
- https://rclone.org/commands/rclone_lsjson/ — lsjson output format, flags, recursive listing
- https://rclone.org/commands/rclone_listremotes/ — listremotes command and JSON output
- https://ffmpeg.org/ffprobe.html — ffprobe -show_format, -print_format json, TAG output

### Secondary (MEDIUM confidence)
- https://pillow.readthedocs.io/en/stable/reference/Image.html — Image.open(), getexif(), error types
- https://pypi.org/project/piexif/ — piexif load/dump API, IFD structure
- WebSearch result: piexif GPS rational conversion formula (degrees + minutes/60 + seconds/3600) — verified conceptually against EXIF spec
- WebSearch result: ffprobe creation_time in ISO 8601 format; location tag names for Apple QuickTime
- WebSearch result: SQLite WAL mode + busy_timeout pattern for concurrent writes
- WebSearch result: rclone Python packages (rclone, python-rclone) are unmaintained — confirmed via PyPI last-release dates

### Tertiary (LOW confidence)
- GPS tag name variations in Android video files — not verified against Android specification; treated as implementation detail to test against real files

---

## Metadata

**Confidence breakdown:**
- Standard stack (libraries + versions): HIGH — verified on PyPI registry, slopcheck clean
- Architecture (module structure, data flow): HIGH — derived from locked decisions + standard Python patterns
- rclone subprocess pattern: MEDIUM — rclone docs verified; subprocess approach standard but not from Python-specific authoritative source
- GPS extraction (photo + video): MEDIUM — piexif IFD structure confirmed; GPS rational formula widely documented; video tag names have device variation
- Pitfalls: HIGH — SQLite concurrency, symlink behavior, piexif error types verified via official Python/SQLite docs

**Research date:** 2026-05-16
**Valid until:** 2026-11-16 (6 months — all core libraries are stable; piexif is slow-moving)
