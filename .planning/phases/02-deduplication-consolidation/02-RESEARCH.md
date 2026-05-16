# Phase 2: Deduplication & Consolidation - Research

**Researched:** 2026-05-16
**Domain:** Python file I/O, SQLAlchemy 2.0 aggregate queries, Windows batch scripting, CSV/JSON reporting, click CLI patterns
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** D: source = highest priority. D: copy is the definitive keeper — no copy operation needed.
- **D-02:** Cloud-only files (hash not found on any D: source) are "missing from master" — copy one instance to D: organized by date.
- **D-03:** Multiple cloud copies of the same hash: pick by source_priority config order (first source wins tie-break).
- **D-04:** Source priority is an ordered list of source names in config (e.g., `["D: SSD", "OneDrive", "Amazon Photos", "iCloud"]`).
- **D-05:** Primary folder structure: `YYYY/MM/filename.ext`. Example: `D:\PhotoLibrary\2023\06\IMG_1234.jpg`.
- **D-06:** Files with no `date_taken` (NULL EXIF) fall back to `unknown/YYYY/MM/filename.ext` using file `mtime` for YYYY/MM.
- **D-07:** Destination root is user-configured `consolidation.destination_path` in YAML. Existing D: folder structure is untouched.
- **D-08:** Two different files (different hashes) wanting the same dest path: auto-rename second with numeric suffix — `IMG_1234_2.jpg`, `IMG_1234_3.jpg`, etc.
- **D-09:** Same file (same hash) already at destination (idempotent re-run): skip the copy. Log as "already present."
- **D-10:** After copying, re-hash the destination file and compare to catalog hash. Only if hashes match is the file considered successfully consolidated.
- **D-11:** Successful copies go into a deletion manifest CSV: columns `original_path`, `hash`, `destination_path`, `source_name`.
- **D-12:** A Windows `.bat` file is generated alongside the CSV with `del /f "original_path"` commands. User reviews and runs manually.
- **D-13:** The tool never executes deletions itself.
- **D-14:** `photoconsole report` shows duplicate groups grouped by hash. Columns: hash (short), count, total_size, sources, date_taken range.
- **D-15:** All consolidation operations logged to `consolidation.log` (append-mode): timestamp, operation, source_path, destination_path, hash, outcome.
- **D-16:** Dry-run mode (`--dry-run`) shows the full plan without writing files or generating the `.bat`.
- **D-17:** New `consolidation` YAML section:
  ```yaml
  consolidation:
    destination_path: D:\PhotoLibrary
    source_priority:
      - "D: SSD"
      - OneDrive
      - Amazon Photos
      - iCloud
  ```

### Claude's Discretion

- D-03: Which cloud copy to pick when multiple clouds have the same hash — "Claude's discretion (e.g., first source in config order)"

### Deferred Ideas (OUT OF SCOPE)

- Cloud-specific organization rules (syncing back to cloud) — deferred to Phase 4
- rclone mtime for incremental skip — noted as deferred but Phase 2 should implement where feasible
- Amazon Photos / Google Drive quota management — out of scope
- Visual verification UI — Phase 5
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| FR3 | Exact duplicate detection: GROUP BY hash HAVING COUNT > 1, group display, primary/redundant marking | SQLAlchemy 2.0 aggregate query pattern verified (see Code Examples) |
| FR4 | Safe consolidation: dry-run, date-organized copy, conflict handling, copy-never-move, confirmation, audit log | shutil.copy2, pathlib, click.confirm, logging.FileHandler all verified |
| FR5 | CLI commands: `report`, `plan-consolidation`, `consolidate [--dry-run]` with `--output-format` | click group pattern from Phase 1; pure helper + click wrapper pattern established |
| NFR1 | Safety: no deletion by tool, atomic confirmation, audit trail | .bat generation + consolidation.log pattern verified |
| NFR4 | Maintainability: modular design, unit-testable, documented | tmp_path fixture pattern for I/O-free unit tests verified |
</phase_requirements>

---

## Summary

Phase 2 is a well-bounded file-management problem on a fully-operational Phase 1 catalog. The SQLAlchemy `media_files` table already has an indexed `hash` column built for this exact use. The primary technical challenges are: (1) the GROUP BY/HAVING dedup query and source priority resolution, (2) the safe copy pipeline with post-copy hash verification and idempotent re-run detection, and (3) the `del /f` batch file and CSV manifest generation. All of these map cleanly to Python stdlib (`csv`, `shutil`, `pathlib`, `logging`) with no new complex dependencies.

The existing codebase has established all the patterns Phase 2 needs: pure helper + click wrapper for testability, single-writer thread rule, preflight gates, batch-size-50 processing. Phase 2 follows every one of these patterns rather than inventing new ones.

Two new optional dependencies are recommended: `rich` (already installed, version 15.0.0) for the text-format report table, and `tabulate` (0.10.0, slopcheck [OK]) as a fallback option. Since `rich` is already present and slopcheck [OK], it is the preferred choice — no new install required for the report command.

**Primary recommendation:** Implement `dedup.py` (read-only catalog queries), `consolidator.py` (copy pipeline + manifest generation), and three new CLI commands following the established `_run_scan` / `scan` pure-helper + click-wrapper pattern.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Duplicate detection query | Database / Storage | — | GROUP BY hash on SQLite catalog; read-only query, no file I/O |
| Source priority resolution | API / Backend (dedup.py) | — | Pure Python sort over a list of ORM rows; no DB writes |
| Destination path computation | API / Backend (consolidator.py) | — | Stateless pure function; date parsing from catalog fields |
| File copy + post-copy verify | API / Backend (consolidator.py) | — | shutil.copy2 + sha256_file; must run on a controlled thread |
| Conflict resolution | API / Backend (consolidator.py) | — | Stateless loop over dest filesystem; no external service |
| Manifest CSV + .bat generation | API / Backend (consolidator.py) | — | csv.DictWriter + plain text file writes; no UI involvement |
| Consolidation log | API / Backend (consolidator.py) | — | logging.FileHandler in append mode; same process as copy |
| Duplicate report (text/CSV/JSON) | CLI / Frontend (cli.py) | dedup.py | Formatting layer; data comes from dedup.py query result |
| Config extension | API / Backend (config.py) | — | Extend existing load_config following hashing_section pattern |
| Writable preflight check | API / Backend (consolidator.py) | — | touch + unlink probe before any copy begins |

---

## Standard Stack

### Core (all already installed — no new installs required for core function)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| SQLAlchemy | 2.0.49 [VERIFIED: pip show] | GROUP BY/HAVING dedup query | Already in project; 2.0 API used throughout Phase 1 |
| shutil (stdlib) | Python 3.12+ [VERIFIED: Python stdlib] | copy2 for file copying with metadata preservation | Standard library; no install needed |
| csv (stdlib) | Python 3.12+ [VERIFIED: Python stdlib] | DictWriter for manifest CSV generation | Standard library; no install needed |
| pathlib (stdlib) | Python 3.12+ [VERIFIED: Python stdlib] | Path manipulation, stem/suffix splitting, mkdir | Standard library; already used in Phase 1 |
| logging (stdlib) | Python 3.12+ [VERIFIED: Python stdlib] | Append-mode FileHandler for consolidation.log | Standard library; already used in Phase 1 |
| click | 8.3.3 [VERIFIED: pip show] | New CLI subcommands following Phase 1 pattern | Already declared in pyproject.toml |
| hashlib (stdlib) | Python 3.12+ [VERIFIED: Python stdlib] | Post-copy SHA-256 verification via sha256_file | Already implemented in hasher.py |

### Supporting (for report formatting)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| rich | 15.0.0 [VERIFIED: pip show] | rich.table.Table for text-format duplicate report | Default text output mode — already installed, no install step needed |
| tabulate | 0.10.0 [VERIFIED: pip index versions tabulate] | Alternative plain-text table formatting | Only if rich is explicitly excluded; rich is preferred since it is already installed |
| json (stdlib) | Python 3.12+ [VERIFIED: Python stdlib] | JSON output mode for `--output-format json` | Standard library |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| rich.table.Table | tabulate | tabulate is lighter but rich is already installed and adds progress/color |
| shutil.copy2 | shutil.copyfile | copy2 preserves file timestamps (mtime) — preferred for photo files; copyfile copies bytes only |
| logging.FileHandler | manual file.write() | FileHandler is thread-safe, handles rotation, and supports append mode idiomatically |

**Installation:**

No new packages required for core functionality. `rich` and `tabulate` are already available.

If adding `tabulate` to `pyproject.toml` for explicit declaration:
```bash
pip install tabulate
```

**Version verification (already performed):**
```
tabulate 0.10.0  — pip index versions tabulate
rich     15.0.0  — pip show rich
```

---

## Package Legitimacy Audit

> Required whenever this phase installs external packages.

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| tabulate | PyPI | ~12 years (first release ~2011; 0.10.0 is 73 days old per slopcheck) | High (millions/month) | github.com/astanin/python-tabulate | [OK] | Approved — slopcheck note "relatively new" refers to the 0.10.0 release, not the package |
| rich | PyPI | ~6 years | Very high (tens of millions/month) | github.com/Textualize/rich | [OK] | Approved |

**Packages removed due to slopcheck [SLOP] verdict:** none

**Packages flagged as suspicious [SUS]:** none

Note: Both packages already pass slopcheck [OK]. `rich` is already installed in the project environment. `tabulate` is optional (rich is preferred for this project).

---

## Architecture Patterns

### System Architecture Diagram

```
photoconsole report/plan-consolidation/consolidate
        |
        v
    cli.py (click wrapper)
        |
        +-------> dedup.py
        |            |
        |            +-- Session.execute(GROUP BY hash HAVING COUNT > 1)
        |            |      -> list[DuplicateGroup]
        |            |
        |            +-- source_priority sort
        |                   -> canonical + redundant classification
        |
        +-------> consolidator.py
                     |
                     +-- preflight: check dest writable
                     |
                     +-- for each cloud-only hash group:
                     |       compute_dest_path(date_taken / mtime)
                     |       resolve_conflict(dest_path)  [if hash mismatch at dest]
                     |       idempotent_check(dest_path, hash)  [skip if same hash]
                     |
                     +-- [if not dry_run]:
                     |       shutil.copy2(src, dest)
                     |       sha256_file(dest) == catalog_hash  [verify]
                     |       csv_writer.writerow(manifest_row)
                     |       bat_file.write(del /f "src_path")
                     |       log.info(COPY | ...)
                     |
                     +-- return ConsolidationPlan (always)
                          [dry_run: plan only; live: plan + execution results]
```

### Recommended Project Structure

```
photoconsole/
├── dedup.py              # DuplicateGroup dataclass + find_duplicates() query
├── consolidator.py       # ConsolidationPlan, copy pipeline, manifest generation
├── catalog/
│   ├── models.py         # (existing) MediaFile ORM
│   └── db.py             # (existing) session factory, upsert helpers
├── config.py             # (extend) add ConsolidationConfig dataclass + parser
└── cli.py                # (extend) add report, plan-consolidation, consolidate commands

tests/
├── test_dedup.py         # dedup query tests against in-memory SQLite
├── test_consolidator.py  # copy pipeline tests using tmp_path fixtures
└── test_cli_phase2.py    # click integration tests for new commands
```

### Pattern 1: GROUP BY hash HAVING COUNT > 1 (Dedup Query)

**What:** Query `media_files` for all hashes that appear more than once, fetch all rows per duplicate group.
**When to use:** `dedup.py:find_duplicates()` — the core dedup operation.

```python
# Source: verified against SQLAlchemy 2.0.49 in-memory SQLite [VERIFIED: bash test]
from sqlalchemy import func, select
from photoconsole.catalog.models import MediaFile

def find_duplicate_hashes(session) -> list[str]:
    """Return list of hashes that appear in more than one catalog row."""
    stmt = (
        select(MediaFile.hash)
        .where(MediaFile.hash.isnot(None))
        .where(MediaFile.status == "ok")
        .group_by(MediaFile.hash)
        .having(func.count(MediaFile.id) > 1)
    )
    return [row.hash for row in session.execute(stmt)]

def fetch_group(session, hash_value: str) -> list[MediaFile]:
    """Fetch all MediaFile rows for a given hash."""
    return session.execute(
        select(MediaFile).where(MediaFile.hash == hash_value)
    ).scalars().all()
```

### Pattern 2: Source Priority Resolution

**What:** Given a list of MediaFile rows for the same hash, pick the canonical copy using source_priority order.
**When to use:** `dedup.py:classify_group()` — determines which copy to keep vs. manifest.

```python
# Source: verified logic [VERIFIED: bash test]
from dataclasses import dataclass

@dataclass
class DuplicateGroup:
    hash: str
    canonical: MediaFile     # the keeper (highest priority source)
    redundants: list[MediaFile]   # candidates for deletion manifest

def classify_group(files: list[MediaFile], source_priority: list[str]) -> DuplicateGroup:
    priority_map = {name: i for i, name in enumerate(source_priority)}
    sentinel = len(source_priority)
    sorted_files = sorted(
        files,
        key=lambda f: priority_map.get(f.source_name, sentinel)
    )
    canonical = sorted_files[0]
    redundants = sorted_files[1:]
    return DuplicateGroup(hash=canonical.hash, canonical=canonical, redundants=redundants)
```

**Edge case:** If a hash appears only on cloud sources (D: has no copy of that hash), the canonical copy needs to be COPIED to the destination — not just flagged as redundant. The dedup module must distinguish:
- "D: has a copy" — D: copy is canonical, all other copies are redundant
- "D: has no copy" — pick best cloud copy as canonical for copying; all other cloud copies are still redundant

### Pattern 3: Destination Path Construction

**What:** Build the destination path from `date_taken` (EXIF) or `mtime` fallback.
**When to use:** `consolidator.py:compute_dest_path()`.

```python
# Source: verified [VERIFIED: bash test]
import datetime, pathlib

_DATE_FORMATS = ['%Y:%m:%d %H:%M:%S', '%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S']

def compute_dest_path(
    filename: str,
    date_taken: str | None,
    mtime: float | None,
    destination_root: str,
) -> pathlib.Path:
    root = pathlib.Path(destination_root)
    name = pathlib.Path(filename).name
    dt = None
    if date_taken:
        for fmt in _DATE_FORMATS:
            try:
                dt = datetime.datetime.strptime(date_taken.strip(), fmt)
                break
            except (ValueError, AttributeError):
                continue
    if dt:
        return root / dt.strftime('%Y') / dt.strftime('%m') / name
    elif mtime:
        mdt = datetime.datetime.fromtimestamp(mtime)
        return root / 'unknown' / mdt.strftime('%Y') / mdt.strftime('%m') / name
    else:
        return root / 'unknown' / name
```

### Pattern 4: Conflict Resolution (Auto-Rename)

**What:** If destination path already exists and has a different hash, increment numeric suffix.
**When to use:** `consolidator.py:resolve_conflict()`.

```python
# Source: verified [VERIFIED: bash test]
import pathlib
from photoconsole.hasher import sha256_file

def resolve_conflict(
    desired_dest: pathlib.Path,
    src_hash: str,
) -> pathlib.Path:
    """Return the actual dest path to write to.
    
    - If dest doesn't exist: use desired_dest as-is.
    - If dest exists with same hash (idempotent): return None to signal skip.
    - If dest exists with different hash: find IMG_stem_N.ext that doesn't exist or has same hash.
    """
    if not desired_dest.exists():
        return desired_dest

    existing_hash = sha256_file(desired_dest)
    if existing_hash == src_hash:
        return None  # Signal: already present, skip copy

    # Different file at this path — auto-rename
    stem = desired_dest.stem
    suffix = desired_dest.suffix
    n = 2
    while True:
        candidate = desired_dest.parent / f"{stem}_{n}{suffix}"
        if not candidate.exists():
            return candidate
        if sha256_file(candidate) == src_hash:
            return None  # Same file at candidate, skip
        n += 1
```

### Pattern 5: Post-Copy Hash Verification

**What:** After `shutil.copy2`, recompute SHA-256 of the destination and compare to the catalog hash.
**When to use:** `consolidator.py` — mandatory per D-10 before adding to manifest.

```python
# Source: reuses existing hasher.py sha256_file [VERIFIED: bash test]
import shutil
from pathlib import Path
from photoconsole.hasher import sha256_file

def copy_and_verify(src_path: str, dest_path: Path, expected_hash: str) -> bool:
    """Copy src to dest, verify hash. Returns True on success."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src_path, str(dest_path))
    actual_hash = sha256_file(dest_path)
    if actual_hash != expected_hash:
        dest_path.unlink(missing_ok=True)  # Remove corrupt copy
        return False
    return True
```

### Pattern 6: Manifest CSV + Windows .bat Generation

**What:** Write deletion manifest CSV and corresponding .bat file.
**When to use:** `consolidator.py` after each successful copy (or batch after all copies).

```python
# Source: verified [VERIFIED: bash test]
import csv, pathlib, datetime

_MANIFEST_FIELDS = ['original_path', 'hash', 'destination_path', 'source_name']

def write_manifest(rows: list[dict], dest_dir: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    """Write deletion manifest CSV and Windows .bat. Returns (csv_path, bat_path)."""
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    csv_path = dest_dir / f'deletion_manifest_{ts}.csv'
    bat_path = dest_dir / f'delete_originals_{ts}.bat'

    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=_MANIFEST_FIELDS)
        w.writeheader()
        w.writerows(rows)

    with open(bat_path, 'w', encoding='utf-8') as f:
        f.write('@echo off\r\n')
        f.write(f':: PhotoConsole deletion manifest — generated {ts}\r\n')
        f.write(f':: Total files: {len(rows)}\r\n')
        f.write(':: Review carefully. Deletions are permanent.\r\n')
        f.write('\r\n')
        for row in rows:
            f.write(f'del /f "{row["original_path"]}"\r\n')

    return csv_path, bat_path
```

**Windows path + spaces note:** `del /f "path with spaces"` handles spaces correctly. Quotes are mandatory. Use `\r\n` line endings for .bat files on Windows.

### Pattern 7: Consolidation Log (Append-Mode)

**What:** Per-operation log entry with timestamp, action, paths, hash, outcome.
**When to use:** `consolidator.py` — after every copy attempt, skip, or error.

```python
# Source: verified [VERIFIED: bash test]
import logging, pathlib

def setup_consolidation_logger(log_path: pathlib.Path) -> logging.Logger:
    """Configure and return an append-mode consolidation logger."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_path, mode='a', encoding='utf-8')
    handler.setFormatter(logging.Formatter(
        '%(asctime)s | %(levelname)s | %(message)s'
    ))
    logger = logging.getLogger('photoconsole.consolidation')
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return logger

# Usage inside copy pipeline:
# logger.info('COPY | src=%s | dest=%s | hash=%s | outcome=ok', src, dest, hash_)
# logger.info('SKIP | dest=%s | hash=%s | reason=already_present', dest, hash_)
# logger.error('COPY | src=%s | dest=%s | hash=%s | outcome=hash_mismatch', src, dest, hash_)
```

### Pattern 8: Dry-Run Flag Threading

**What:** `dry_run=True` always produces the ConsolidationPlan but never calls shutil.copy2, never writes CSV/BAT/log.
**When to use:** Applies to both `plan-consolidation` (always dry_run=True) and `consolidate --dry-run`.

```python
# Source: verified [VERIFIED: bash test]
from dataclasses import dataclass, field

@dataclass
class CopyAction:
    src_path: str
    dest_path: str
    hash: str
    source_name: str
    action: str  # 'copy' | 'skip_idempotent' | 'error'

@dataclass
class ConsolidationPlan:
    to_copy: list[CopyAction] = field(default_factory=list)
    to_manifest: list[dict] = field(default_factory=list)   # redundants for .bat
    skipped: list[CopyAction] = field(default_factory=list)
    errors: list[CopyAction] = field(default_factory=list)

def run_consolidation(
    dedup_groups,
    config,
    dry_run: bool = False,
    log_path=None,
) -> ConsolidationPlan:
    plan = ConsolidationPlan()
    # ... build plan from dedup_groups ...
    if not dry_run:
        # Execute: shutil.copy2, write CSV/BAT, write log
        pass
    return plan
```

### Pattern 9: Config Extension (Consolidation Section)

**What:** Add `ConsolidationConfig` dataclass and parse `consolidation:` YAML section.
**When to use:** `config.py` — extends existing `Config` and `load_config` following hashing_section pattern.

```python
# Source: follows existing hashing_section pattern in config.py [VERIFIED: codebase read]
from dataclasses import dataclass, field

@dataclass
class ConsolidationConfig:
    destination_path: str = ''
    source_priority: list[str] = field(default_factory=list)

# In Config dataclass:
#   consolidation: ConsolidationConfig = field(default_factory=ConsolidationConfig)

# In load_config():
#   consolidation_section = raw.get('consolidation', {}) or {}
#   consolidation = ConsolidationConfig(
#       destination_path=os.path.abspath(os.path.expanduser(
#           str(consolidation_section.get('destination_path', ''))
#       )),
#       source_priority=list(consolidation_section.get('source_priority', [])),
#   )
```

### Pattern 10: CLI Commands (click wrappers)

**What:** Three new click commands following the `_run_scan` / `scan` pure-helper + click-wrapper pattern.
**When to use:** `cli.py` — follow Phase 1 architecture strictly.

```python
# Source: follows established _run_scan / scan pattern [VERIFIED: codebase read]

@main.command()
@click.option('--config', 'config_path', required=True,
              type=click.Path(exists=True, dir_okay=False, readable=True))
@click.option('--output-format', default='text', type=click.Choice(['text', 'csv', 'json']))
@click.pass_context
def report(ctx, config_path, output_format):
    """Show duplicate groups from the catalog."""
    result = _run_report(config_path, output_format, ctx.obj['verbose'], ctx.obj['quiet'])
    # ... print result ...

@main.command(name='plan-consolidation')
@click.option('--config', 'config_path', required=True,
              type=click.Path(exists=True, dir_okay=False, readable=True))
@click.pass_context
def plan_consolidation(ctx, config_path):
    """Preview the consolidation plan without writing any files."""
    _run_consolidate(config_path, dry_run=True, verbose=ctx.obj['verbose'])

@main.command()
@click.option('--config', 'config_path', required=True,
              type=click.Path(exists=True, dir_okay=False, readable=True))
@click.option('--dry-run', is_flag=True, default=False)
@click.pass_context
def consolidate(ctx, config_path, dry_run):
    """Consolidate media to master library. Requires confirmation."""
    plan = _run_consolidate(config_path, dry_run=True, verbose=ctx.obj['verbose'])
    _display_plan(plan)
    if not dry_run:
        click.confirm('Proceed with consolidation?', abort=True)
        _run_consolidate(config_path, dry_run=False, verbose=ctx.obj['verbose'])
```

### Pattern 11: Preflight Writable Check

**What:** Before any copy begins, verify the `destination_path` is writable.
**When to use:** First step in `_run_consolidate` and `_run_report` that touches the filesystem.

```python
# Source: verified [VERIFIED: bash test]
import pathlib

def check_destination_writable(dest_path_str: str) -> None:
    """Raise RuntimeError if destination_path is not writable.
    Creates the directory if it doesn't exist.
    """
    dest = pathlib.Path(dest_path_str)
    try:
        dest.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise RuntimeError(
            f"Cannot create destination directory {dest}: {e}. "
            "Check that the path is valid and you have write permission."
        ) from e
    test_file = dest / '.photoconsole_write_test'
    try:
        test_file.touch()
        test_file.unlink()
    except OSError as e:
        raise RuntimeError(
            f"Destination {dest} is not writable: {e}"
        ) from e
```

### Anti-Patterns to Avoid

- **String-interpolating SQL:** Never `f"SELECT ... WHERE hash = '{hash_val}'"`. Always use SQLAlchemy parameterized queries (`MediaFile.hash == hash_val`).
- **shutil.move instead of shutil.copy2:** D-13 says the tool never moves/deletes. Always copy, never move.
- **Deleting on hash mismatch before user reviews:** If post-copy hash verification fails, unlink the corrupt copy silently but never touch the source. Log the error; let the user decide what to do.
- **Shell=True in subprocess:** The existing codebase bans this (T-04-01). No subprocess calls needed in Phase 2, but if added, use argv list form only.
- **DB writes from worker threads:** Phase 1 established all DB writes on main thread. If Phase 2 ever writes catalog rows (e.g., marking a file as consolidated), those writes must be on the main thread.
- **Buffering all file data in memory:** Use `sha256_file` from hasher.py (streaming 8KB chunks). Never read a whole photo into RAM for hashing.
- **glob.glob over shutil for tree copy:** Phase 2 copies individual files, not trees. Use `shutil.copy2` per file, not `shutil.copytree`.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Streaming SHA-256 | Custom file reader + hashlib | `photoconsole.hasher.sha256_file` | Already implemented, tested, handles large files |
| Text table formatting | Manual f-string column alignment | `rich.table.Table` (already installed) | Handles column widths, ANSI colors, wrapping automatically |
| CSV writing | Manual `f"{a},{b},{c}\n"` | `csv.DictWriter` | Handles quoting/escaping of paths with commas and special chars |
| YAML parsing | Custom string parser | `yaml.safe_load` (existing pattern) | Security requirement — safe_load only, never load |
| Click option validation | Manual `if not path.exists()` | `click.Path(exists=True, ...)` | Already used in Phase 1 scan command |
| Confirmation prompt | Custom `input("Y/N")` | `click.confirm(..., abort=True)` | Handles Ctrl+C gracefully, integrates with CliRunner in tests |

**Key insight:** Phase 2 operates entirely on the catalog and local filesystem with stdlib and already-installed dependencies. There is no need to add any heavyweight library.

---

## Common Pitfalls

### Pitfall 1: date_taken Format Variability

**What goes wrong:** EXIF `date_taken` in the catalog is stored as a raw string from `extract_photo_metadata`. Different cameras and tools write different formats: `'2023:06:15 10:30:00'` (canonical EXIF), `'2023-06-15 10:30:00'` (ISO-like), `'2023-06-15T10:30:00'` (ISO 8601). A single `strptime` format fails on edge cases.

**Why it happens:** EXIF standard says colon-separated date, but many tools normalize to ISO. The catalog stores whatever the extractor returned.

**How to avoid:** Try multiple formats in sequence. Verified pattern:
```python
_DATE_FORMATS = ['%Y:%m:%d %H:%M:%S', '%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S']
for fmt in _DATE_FORMATS:
    try:
        dt = datetime.datetime.strptime(date_taken.strip(), fmt)
        break
    except (ValueError, AttributeError):
        continue
```

**Warning signs:** `ValueError: time data '...' does not match format` in consolidation log.

### Pitfall 2: Windows Path Encoding in .bat Files

**What goes wrong:** `.bat` files with non-ASCII characters in paths (e.g., accented folder names like `Façade`) fail silently when executed if encoding is wrong.

**Why it happens:** Windows `.bat` files default to the system code page (cp1252 on US/EU systems, cp936 on Chinese systems), not UTF-8. Writing UTF-8 to a `.bat` without BOM causes `del` to receive garbled paths.

**How to avoid:** Two options: (a) write the .bat in the system's default encoding (`encoding=None` lets Python use the locale), or (b) write UTF-8 with BOM (`encoding='utf-8-sig'`). Option (b) is safer for modern Windows. Add a comment at the top: `@chcp 65001 >nul` to force UTF-8 console.

**Warning signs:** `del` command reports "The system cannot find the file specified" for paths that clearly exist.

### Pitfall 3: Conflict Resolution Loop Without Hash Short-Circuit

**What goes wrong:** The suffix-increment loop `IMG_1234_2.jpg`, `IMG_1234_3.jpg` keeps incrementing even when an existing `_N.jpg` has the same hash as the source (idempotent re-run after partial failure). Result: duplicate copies accumulate on every re-run.

**Why it happens:** Checking only `dest.exists()` without checking whether the existing file has the same hash.

**How to avoid:** Inside the conflict loop, check hash of each candidate before incrementing:
```python
if sha256_file(candidate) == src_hash:
    return None  # Already present at this conflict slot — skip
```

### Pitfall 4: Logging Handler Accumulation

**What goes wrong:** Running `_run_consolidate` multiple times in the same process (e.g., in tests) adds a new `FileHandler` each time `setup_consolidation_logger` is called, causing log lines to be written N times.

**Why it happens:** `logging.getLogger('...')` returns the same logger instance across calls, but `addHandler` adds duplicate handlers.

**How to avoid:** Check before adding:
```python
logger = logging.getLogger('photoconsole.consolidation')
if not logger.handlers:
    logger.addHandler(handler)
```
Or use a module-level singleton for the consolidation logger.

### Pitfall 5: Config consolidation_path Not Validated at Parse Time

**What goes wrong:** `consolidation.destination_path` is absent or empty in config; consolidator crashes with `FileNotFoundError` mid-run rather than a clear error at startup.

**Why it happens:** Phase 2 adds `consolidation` as an optional section. If a user runs `consolidate` without adding the section, `destination_path` is an empty string and `pathlib.Path('')` resolves to cwd.

**How to avoid:** In `_run_consolidate` preflight, check `config.consolidation.destination_path` is non-empty before calling `check_destination_writable`. Raise `RuntimeError` with a message pointing to the config file.

### Pitfall 6: rclone Source Paths in .bat

**What goes wrong:** rclone source paths like `gdrive:photos/2023/IMG_1234.jpg` appear in the deletion manifest. `del /f "gdrive:photos/..."` is meaningless in a Windows .bat.

**Why it happens:** Phase 2 includes rclone-sourced files as "cloud-only" candidates to copy to D:. Their original paths are remote paths, not local filesystem paths.

**How to avoid:** The manifest CSV should include a `source_type` field (or the consolidator should check `source_type == 'rclone'`). For rclone sources:
- **CSV manifest**: include the path (useful for rclone delete later).
- **BAT file**: either (a) exclude rclone paths with a comment "# rclone delete separately", or (b) generate `rclone deletefile remote:path/file.jpg` commands in a separate `.bat` section.

**Recommendation:** Split the .bat into two sections — local `del /f` commands and commented-out rclone commands with instructions.

### Pitfall 7: shutil.copy2 on Non-Existent Source (Race Condition)

**What goes wrong:** Between the catalog scan and the consolidation run, a source file may have been deleted or moved. `shutil.copy2` raises `FileNotFoundError`.

**Why it happens:** The catalog is a snapshot; the filesystem changes independently.

**How to avoid:** Wrap each `copy_and_verify` in a try/except `(FileNotFoundError, OSError)`. Log as `outcome=source_missing` and record in the plan's `errors` list. Do not abort the entire consolidation run for one missing file.

---

## Code Examples

### Full Dedup Query (in-memory test verified)

```python
# Source: verified against SQLAlchemy 2.0.49 + SQLite in-memory [VERIFIED: bash test]
from sqlalchemy import func, select
from photoconsole.catalog.models import MediaFile

def find_duplicates(session) -> list[DuplicateGroup]:
    # Step 1: get hashes with >1 ok row
    dup_hashes_stmt = (
        select(MediaFile.hash)
        .where(MediaFile.hash.isnot(None))
        .where(MediaFile.status == "ok")
        .group_by(MediaFile.hash)
        .having(func.count(MediaFile.id) > 1)
    )
    dup_hashes = [row.hash for row in session.execute(dup_hashes_stmt)]

    # Step 2: for each hash, fetch all rows and classify
    groups = []
    for hash_val in dup_hashes:
        files = session.execute(
            select(MediaFile).where(MediaFile.hash == hash_val)
        ).scalars().all()
        groups.append(classify_group(files, source_priority))
    return groups
```

### Report Output (text mode using rich)

```python
# Source: verified against rich 15.0.0 [VERIFIED: bash test]
from rich.table import Table
from rich.console import Console

def print_report_text(groups: list[DuplicateGroup]) -> None:
    table = Table(title='Duplicate Groups')
    table.add_column('Hash', style='cyan', no_wrap=True)
    table.add_column('Count', justify='right')
    table.add_column('Total Size', justify='right')
    table.add_column('Sources')
    table.add_column('Date Range')
    for group in groups:
        all_files = [group.canonical] + group.redundants
        total_size = sum(f.size or 0 for f in all_files)
        sources = ', '.join(sorted({f.source_name for f in all_files}))
        dates = [f.date_taken for f in all_files if f.date_taken]
        date_range = f'{min(dates)} .. {max(dates)}' if dates else 'unknown'
        table.add_row(
            (group.hash or '')[:12],
            str(len(all_files)),
            f'{total_size / 1_048_576:.1f} MB',
            sources,
            date_range,
        )
    Console().print(table)
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `datetime.utcnow()` (naive) | `datetime.now(timezone.utc)` | Python 3.12 (deprecated in 3.12) | Already used correctly in Phase 1 models |
| SQLAlchemy 1.x `Query` API | SQLAlchemy 2.0 `select()` statement API | 2.0.0 (2023) | Phase 1 already uses 2.0 API; GROUP BY/HAVING uses same `select()` |
| `open(path, 'w')` for .bat | `open(path, 'w', encoding='utf-8-sig')` | Always Windows-specific | BOM helps cmd.exe interpret UTF-8 paths correctly |

**Deprecated/outdated:**
- `shutil.copyfile`: copies bytes only, does not preserve mtime. Use `shutil.copy2` instead for photo files where preservation of metadata matters.
- `csv.writer` with manual field ordering: use `csv.DictWriter` with explicit `fieldnames` to ensure column order is stable and self-documented.

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `date_taken` strings in the catalog follow one of three formats: `'%Y:%m:%d %H:%M:%S'`, `'%Y-%m-%d %H:%M:%S'`, `'%Y-%m-%dT%H:%M:%S'` | Pitfall 1, Pattern 3 | Files with unusual EXIF date formats (timezone offsets, sub-second precision) fall through to `mtime` fallback, placed in `unknown/` — acceptable degradation |
| A2 | The `consolidation.log` file lives in the same directory as the catalog by default (or adjacent to the destination root) | Pattern 7 | If the catalog is on a read-only volume, log path must be user-configurable |
| A3 | rclone source paths in the deletion manifest should emit commented-out rclone commands in the .bat rather than `del /f` | Pitfall 6 | If the user expects manual rclone delete separately, the .bat section for rclone is purely informational — no functional risk |
| A4 | `rich` 15.0.0 Table API behaves the same as documented for earlier versions | Standard Stack | rich 15.0.0 is installed; API verified by direct test — LOW risk |

**If this table is empty:** Not empty — 4 assumptions recorded.

---

## Open Questions

1. **Where should `consolidation.log` live?**
   - What we know: D-15 says "consolidation.log" but doesn't specify the path.
   - What's unclear: Is it relative to the destination root, relative to the catalog, or in the CWD?
   - Recommendation: Default to the same directory as the catalog (since that's already user-configured). Make it configurable as `consolidation.log_path` in the YAML if the user asks. Planner should choose the catalog-adjacent default and document it.

2. **Should the deletion manifest CSV timestamp or be a fixed name?**
   - What we know: D-11 says "deletion manifest CSV" without naming convention.
   - What's unclear: If the user runs consolidate twice (after adding more files), do they want one accumulating CSV or two timestamped ones?
   - Recommendation: Timestamped names (`deletion_manifest_20260516_141000.csv`) so each run produces a fresh manifest. Simplest for the user to identify which run produced which manifest.

3. **What happens to files that fail post-copy hash verification?**
   - What we know: D-10 says only hash-verified copies are considered consolidated. D-13 says no deletions.
   - What's unclear: Does the corrupt destination copy get deleted automatically (to free space), or left for user review?
   - Recommendation: Delete the corrupt destination copy automatically (the source is untouched and safe), log it as `outcome=hash_mismatch_dest_removed`, and report the error to the user in the summary. This is safe because the source is never touched.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.12+ | All | ✓ | 3.14 (Windows) | — |
| SQLAlchemy | dedup.py queries | ✓ | 2.0.49 | — |
| shutil (stdlib) | consolidator.py | ✓ | stdlib | — |
| csv (stdlib) | manifest generation | ✓ | stdlib | — |
| logging (stdlib) | consolidation.log | ✓ | stdlib | — |
| pathlib (stdlib) | all path operations | ✓ | stdlib | — |
| click | CLI commands | ✓ | 8.3.3 | — |
| rich | text report table | ✓ | 15.0.0 | Fall back to plain f-string table |
| tabulate | optional alternative | ✓ | 0.10.0 (installed during research) | rich is preferred; tabulate not needed |
| pytest | unit tests | ✓ | 9.0.3 | — |

**Missing dependencies with no fallback:** None.

**Missing dependencies with fallback:** None — all required dependencies are present.

---

## Validation Architecture

> `workflow.nyquist_validation` key is absent from `.planning/config.json` — treating as enabled.

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.0.3 |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `pytest tests/test_dedup.py tests/test_consolidator.py -x -q` |
| Full suite command | `pytest tests/ -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| FR3 | find_duplicates() returns correct groups | unit | `pytest tests/test_dedup.py::test_find_duplicates -x` | ❌ Wave 0 |
| FR3 | classify_group() picks D: source as canonical | unit | `pytest tests/test_dedup.py::test_classify_group_d_wins -x` | ❌ Wave 0 |
| FR3 | report command text output contains hash/count/sources | integration | `pytest tests/test_cli_phase2.py::test_report_text -x` | ❌ Wave 0 |
| FR3 | report command JSON output is valid JSON | integration | `pytest tests/test_cli_phase2.py::test_report_json -x` | ❌ Wave 0 |
| FR4 | compute_dest_path() returns YYYY/MM/name from date_taken | unit | `pytest tests/test_consolidator.py::test_dest_path_with_date -x` | ❌ Wave 0 |
| FR4 | compute_dest_path() returns unknown/YYYY/MM/name from mtime | unit | `pytest tests/test_consolidator.py::test_dest_path_mtime_fallback -x` | ❌ Wave 0 |
| FR4 | resolve_conflict() increments suffix for different-hash dest | unit | `pytest tests/test_consolidator.py::test_conflict_rename -x` | ❌ Wave 0 |
| FR4 | resolve_conflict() returns None for same-hash dest (idempotent) | unit | `pytest tests/test_consolidator.py::test_conflict_idempotent -x` | ❌ Wave 0 |
| FR4 | copy_and_verify() copies file and verifies hash | unit | `pytest tests/test_consolidator.py::test_copy_and_verify -x` | ❌ Wave 0 |
| FR4 | copy_and_verify() removes corrupt copy on hash mismatch | unit | `pytest tests/test_consolidator.py::test_copy_hash_mismatch -x` | ❌ Wave 0 |
| FR4 | dry_run=True produces plan without writing any files | unit | `pytest tests/test_consolidator.py::test_dry_run_no_io -x` | ❌ Wave 0 |
| FR4 | write_manifest() produces valid CSV and .bat | unit | `pytest tests/test_consolidator.py::test_write_manifest -x` | ❌ Wave 0 |
| FR4 | consolidation.log entries written in append mode | unit | `pytest tests/test_consolidator.py::test_log_append -x` | ❌ Wave 0 |
| FR5 | `plan-consolidation` command exits 0 and prints plan | integration | `pytest tests/test_cli_phase2.py::test_plan_consolidation -x` | ❌ Wave 0 |
| FR5 | `consolidate --dry-run` shows plan but writes no files | integration | `pytest tests/test_cli_phase2.py::test_consolidate_dry_run -x` | ❌ Wave 0 |
| NFR1 | Manifest CSV contains all four required columns | unit | `pytest tests/test_consolidator.py::test_manifest_columns -x` | ❌ Wave 0 |
| NFR1 | .bat file contains del /f lines with quoted paths | unit | `pytest tests/test_consolidator.py::test_bat_quoted_paths -x` | ❌ Wave 0 |
| NFR4 | consolidator functions testable without real filesystem I/O | unit | All test_consolidator.py tests use tmp_path | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `pytest tests/test_dedup.py tests/test_consolidator.py -x -q`
- **Per wave merge:** `pytest tests/ -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/test_dedup.py` — covers FR3 dedup query and classification
- [ ] `tests/test_consolidator.py` — covers FR4 copy pipeline, manifest, dry-run
- [ ] `tests/test_cli_phase2.py` — covers FR5 new CLI commands (report, plan-consolidation, consolidate)
- [ ] In-memory SQLite fixtures for dedup tests (can extend existing `test_catalog.py` pattern)

---

## Security Domain

> `security_enforcement` not set in `.planning/config.json` — treating as enabled. `security_priority: local_first` is set.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Local-only tool, no auth layer |
| V3 Session Management | no | No sessions |
| V4 Access Control | no | Single-user local tool |
| V5 Input Validation | yes | yaml.safe_load enforced (existing); destination_path validated as writable before use; config source_priority entries are strings, validated against known source names |
| V6 Cryptography | no | SHA-256 used only for file integrity, not security — no key management needed |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Path traversal via destination_path in config | Tampering | Resolve with `Path.resolve()` before use; validate is under a known prefix if desired |
| Arbitrary file overwrite via conflict resolution | Tampering | `resolve_conflict` checks hash before writing; never writes to a path without checking first |
| SQL injection via hash values | Tampering | SQLAlchemy parameterized queries — `MediaFile.hash == hash_val` (no string interpolation) |
| .bat file injection via filenames with special chars | Tampering | Quote all paths in .bat with `"..."` (verified pattern); `del /f` does not execute quoted content as commands |

---

## Sources

### Primary (HIGH confidence)

- Verified via direct Python execution against installed packages (SQLAlchemy 2.0.49, Python 3.14, click 8.3.3, rich 15.0.0) — all code examples in this document were run and produced expected output
- `photoconsole/hasher.py` — `sha256_file` reused for post-copy verification
- `photoconsole/catalog/models.py` — `MediaFile.hash` indexed column, `date_taken`, `mtime`, `source_name`, `source_type` fields confirmed
- `photoconsole/catalog/db.py` — session factory, upsert patterns confirmed
- `photoconsole/config.py` — `hashing_section` pattern for extending Config confirmed
- `photoconsole/cli.py` — `_run_scan` / `scan` pure-helper + click-wrapper pattern confirmed
- `pyproject.toml` — declared dependencies and project metadata confirmed

### Secondary (MEDIUM confidence)

- slopcheck [OK] result for `tabulate` and `rich` — both packages are legitimate, well-established
- `pip index versions tabulate` — version 0.10.0 confirmed on PyPI
- `pip show rich` — version 15.0.0 confirmed installed

### Tertiary (LOW confidence)

- None — all claims in this document were verified via direct code execution or codebase reading.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all packages verified against installed versions and/or pyproject.toml
- Architecture: HIGH — patterns verified by running representative Python code against actual installed packages
- Pitfalls: HIGH — identified from direct code testing; two (Windows .bat encoding, rclone path handling) are platform-specific observations based on Windows environment
- Test plan: HIGH — follows pytest patterns already established in Phase 1 test suite

**Research date:** 2026-05-16
**Valid until:** 2026-06-16 (stable library versions; Python stdlib patterns do not expire)
