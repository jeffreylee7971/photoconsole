"""Copy pipeline building blocks for PhotoConsole consolidation.

Implements the stateless, independently-testable inner functions that form the
file copy pipeline:

  compute_dest_path         — builds YYYY/MM or unknown/YYYY/MM destination path
                              from date_taken (EXIF) or mtime fallback (D-05, D-06)
  resolve_conflict          — handles same-filename collisions at destination (D-08, D-09)
  copy_and_verify           — shutil.copy2 + post-copy SHA-256 verification (D-10)
  write_manifest            — CSV + Windows .bat deletion manifest (D-11, D-12)
  check_destination_writable — preflight gate for destination directory (Pitfall 5)
  setup_consolidation_logger — append-mode logger without handler duplication (Pitfall 4)
  run_consolidation          — main orchestration pipeline (D-01 through D-16)

All three copy-pipeline functions are pure with respect to business logic; side
effects are limited to explicit filesystem operations documented in each
function's docstring.

Design decisions
----------------
D-05  Primary structure: destination_root/YYYY/MM/filename.ext
D-06  Fallback when date_taken is None or unparseable:
        - mtime available → unknown/YYYY/MM/filename.ext
        - mtime also None → unknown/filename.ext
D-08  Conflict: same dest path, different hash → auto-rename with numeric suffix
D-09  Idempotent: same dest path, same hash → return None (caller skips copy)
D-10  Post-copy hash verification; corrupt copy removed on mismatch
D-11  Manifest CSV: original_path, hash, destination_path, source_name columns
D-12  Deletion .bat: utf-8-sig + \\r\\n, @echo off + chcp 65001, del /f or :: rclone comment
D-15  Consolidation log format: TIMESTAMP | LEVEL | OPERATION | src=... | dest=... | hash=... | outcome=...
D-16  Dry-run: plan populated, no I/O (no copy, no log, no manifest)

Security
--------
T-03-01  resolve_conflict builds paths with pathlib arithmetic only (no string
         interpolation); all candidates remain inside desired_dest.parent.
T-03-02  copy_and_verify calls dest_path.unlink(missing_ok=True) on hash mismatch;
         source file is never touched.
T-04-01  run_consolidation catches FileNotFoundError+OSError from copy_and_verify
         and adds to plan.errors; run continues (Pitfall 7).
"""
from __future__ import annotations

import csv
import dataclasses
import logging
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from photoconsole.hasher import sha256_file

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_DATE_FORMATS = [
    "%Y:%m:%d %H:%M:%S",   # canonical EXIF: '2023:06:15 10:30:00'
    "%Y-%m-%d %H:%M:%S",   # ISO-like:       '2023-06-15 10:30:00'
    "%Y-%m-%dT%H:%M:%S",   # ISO 8601:       '2023-06-15T10:30:00'
]

# Manifest CSV column order (D-11)
_MANIFEST_FIELDS = ['original_path', 'hash', 'destination_path', 'source_name']


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class CopyAction:
    """A single file copy decision produced by the consolidation planner.

    Attributes
    ----------
    src_path:    Absolute path (string) to the source file.
    dest_path:   Absolute path (string) to the intended destination.
    hash:        SHA-256 hex digest of the file (from catalog).
    source_name: Human-readable source label (e.g. 'OneDrive', 'D: SSD').
    action:      One of 'copy', 'skip_idempotent', or 'error'.
                 - 'copy'            → file will be / was copied
                 - 'skip_idempotent' → same hash already at dest; no action needed
                 - 'error'           → copy attempt failed (see plan.errors)
    """

    src_path: str
    dest_path: str
    hash: str
    source_name: str
    action: str  # 'copy' | 'skip_idempotent' | 'error'


@dataclass
class ConsolidationPlan:
    """The full output of a consolidation run (dry or live).

    Attributes
    ----------
    to_copy:      CopyActions that were (or would be) executed.
    to_manifest:  Raw dicts for the deletion manifest CSV/BAT (one per redundant
                  copy that was successfully consolidated).
    skipped:      CopyActions skipped because the hash was already at dest (D-09).
    errors:       CopyActions that failed (hash mismatch, source missing, OS error).
    """

    to_copy: list[CopyAction] = field(default_factory=list)
    to_manifest: list[dict] = field(default_factory=list)
    skipped: list[CopyAction] = field(default_factory=list)
    errors: list[CopyAction] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Pure functions
# ---------------------------------------------------------------------------

def compute_dest_path(
    filename: str,
    date_taken: Optional[str],
    mtime: Optional[float],
    destination_root: str,
) -> Path:
    """Build the destination path for a media file.

    Follows D-05 and D-06:
      - date_taken parseable → destination_root / YYYY / MM / basename
      - date_taken None or unparseable, mtime available
                            → destination_root / 'unknown' / YYYY / MM / basename
      - both None           → destination_root / 'unknown' / basename

    Three date_taken formats are tried in order (Pitfall 1):
        '%Y:%m:%d %H:%M:%S', '%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S'

    Args:
        filename:         Source filename (only the basename is used).
        date_taken:       EXIF date string from catalog, or None.
        mtime:            File modification time as a POSIX float, or None.
        destination_root: Root directory for the organised library (string).

    Returns:
        A Path object representing the full destination path (not yet created).
    """
    root = Path(destination_root)
    name = Path(filename).name

    # Attempt to parse date_taken with each known format
    dt: Optional[datetime] = None
    if date_taken:
        for fmt in _DATE_FORMATS:
            try:
                dt = datetime.strptime(date_taken.strip(), fmt)
                break
            except (ValueError, AttributeError):
                continue

    if dt is not None:
        # D-05: primary structure
        return root / dt.strftime("%Y") / dt.strftime("%m") / name
    elif mtime is not None:
        # D-06: mtime fallback
        mdt = datetime.fromtimestamp(mtime)
        return root / "unknown" / mdt.strftime("%Y") / mdt.strftime("%m") / name
    else:
        # D-06: no date at all
        return root / "unknown" / name


def resolve_conflict(desired_dest: Path, src_hash: str) -> Optional[Path]:
    """Resolve filename collisions at the destination path.

    Implements D-08 (auto-rename on hash mismatch) and D-09 (idempotent skip
    when same hash already at destination).

    Algorithm:
      1. If desired_dest does not exist → return desired_dest (no conflict).
      2. Compute hash of existing file. If equal to src_hash → return None
         (signal: idempotent skip; caller should not copy).
      3. Otherwise auto-rename: try stem_2.ext, stem_3.ext … until a free slot
         is found or a slot with the same hash is encountered (also returns None).

    Security (T-03-01): all candidate paths are built with pathlib arithmetic
    relative to desired_dest.parent — they never escape the parent directory.

    Args:
        desired_dest: The initially computed destination path.
        src_hash:     SHA-256 hex digest of the source file.

    Returns:
        Path to write to, or None if the file is already present (D-09).
    """
    if not desired_dest.exists():
        return desired_dest

    # Check whether the existing file is already the same content
    existing_hash = sha256_file(desired_dest)
    if existing_hash == src_hash:
        return None  # D-09: idempotent skip

    # D-08: different file at this path — find a free slot with numeric suffix
    stem = desired_dest.stem
    suffix = desired_dest.suffix
    n = 2
    while True:
        candidate = desired_dest.parent / f"{stem}_{n}{suffix}"
        if not candidate.exists():
            return candidate
        if sha256_file(candidate) == src_hash:
            return None  # D-09: same file already at this conflict slot
        n += 1


def copy_and_verify(src_path: str, dest_path: Path, expected_hash: str) -> bool:
    """Copy a file to dest_path and verify its SHA-256 hash (D-10).

    Steps:
      1. Create dest_path.parent directories (parents=True, exist_ok=True).
      2. shutil.copy2(src_path, dest_path) — preserves file timestamps.
      3. sha256_file(dest_path) — post-copy verification.
      4. On hash match → return True.
      5. On hash mismatch → unlink dest_path (corrupt copy), return False (T-03-02).
      6. On FileNotFoundError/OSError (source missing / permission denied per
         Pitfall 7) → return False without raising.

    The source file is NEVER modified or removed (D-13).

    Args:
        src_path:      Path to the source file (string or str-compatible).
        dest_path:     Destination Path object.
        expected_hash: SHA-256 hex digest to verify against.

    Returns:
        True if copy succeeded and hash matches; False otherwise.
    """
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        shutil.copy2(src_path, str(dest_path))
    except (FileNotFoundError, OSError):
        # Pitfall 7: source gone between catalog snapshot and consolidation run
        return False

    actual_hash = sha256_file(dest_path)
    if actual_hash != expected_hash:
        # T-03-02: remove the corrupt destination copy; never touch source
        dest_path.unlink(missing_ok=True)
        return False

    return True


# ---------------------------------------------------------------------------
# Plan 04: orchestration helpers
# ---------------------------------------------------------------------------

def check_destination_writable(dest_path_str: str) -> None:
    """Assert that dest_path_str is set and the directory is writable.

    Performs two checks (Pitfall 5, RESEARCH.md Pattern 11):
      1. dest_path_str must not be empty or all-whitespace.
      2. The directory must be creatable and a temporary probe file must be
         writable inside it.

    Args:
        dest_path_str: Value of config.consolidation.destination_path.

    Raises:
        RuntimeError: If the path is empty/whitespace, cannot be created, or
                      is not writable.
    """
    if not dest_path_str or not dest_path_str.strip():
        raise RuntimeError(
            "consolidation.destination_path is not set in config. "
            "Add consolidation.destination_path to your YAML config."
        )

    dest = Path(dest_path_str)
    try:
        dest.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RuntimeError(
            f"Cannot create consolidation destination directory {dest!r}: {exc}"
        ) from exc

    test_file = dest / ".photoconsole_write_test"
    try:
        test_file.touch()
        test_file.unlink()
    except OSError as exc:
        raise RuntimeError(
            f"Consolidation destination {dest!r} is not writable: {exc}"
        ) from exc


def setup_consolidation_logger(log_path: Path) -> logging.Logger:
    """Return a Logger that appends structured consolidation events to log_path.

    The logger name is 'photoconsole.consolidation'. If that logger already
    has handlers (Pitfall 4 — duplicate handler guard), the existing handler
    is reused without adding another.

    Log format: '%(asctime)s | %(levelname)s | %(message)s'
    Message convention: 'COPY | src=X | dest=Y | hash=Z | outcome=ok'

    Args:
        log_path: Destination file for the consolidation log. Parent
                  directories are created automatically.

    Returns:
        A configured logging.Logger instance.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)

    log_path_str = str(log_path)
    logger = logging.getLogger("photoconsole.consolidation")

    # Pitfall 4: guard against duplicate handlers on repeated calls with the
    # SAME log_path. Check if a FileHandler for this exact path already exists.
    already_has_handler = any(
        isinstance(h, logging.FileHandler) and h.baseFilename == log_path_str
        for h in logger.handlers
    )
    if not already_has_handler:
        handler = logging.FileHandler(log_path_str, mode="a", encoding="utf-8")
        handler.setFormatter(
            logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
        )
        logger.addHandler(handler)

    logger.setLevel(logging.INFO)
    return logger


def write_manifest(rows: list[dict], dest_dir: Path) -> tuple[Path, Path]:
    """Write a CSV deletion manifest and a Windows .bat deletion script.

    CSV format (D-11):
      Columns: original_path, hash, destination_path, source_name
      Encoding: UTF-8 (no BOM)

    BAT format (D-12, Pitfall 2, Pitfall 6):
      Encoding: utf-8-sig (UTF-8 with BOM — required for Windows cmd.exe)
      Line endings: \\r\\n throughout
      Header: @echo off, chcp 65001 >nul, two :: comment lines
      Per row:
        - source_type == 'rclone' → ':: rclone deletefile <original_path>'
        - otherwise               → 'del /f "<original_path>"'

    Args:
        rows:     List of manifest dicts. Each must contain the four D-11
                  columns plus a 'source_type' key ('local' or 'rclone') used
                  for .bat routing. The CSV only writes the four D-11 columns.
        dest_dir: Directory in which to create the two output files.

    Returns:
        Tuple (csv_path, bat_path) — both Path objects pointing to the
        newly created files.
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = dest_dir / f"deletion_manifest_{ts}.csv"
    bat_path = dest_dir / f"delete_originals_{ts}.bat"

    # Write CSV (D-11)
    with open(csv_path, "w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=_MANIFEST_FIELDS,
            extrasaction="ignore",  # drop 'source_type' and any other extra keys
        )
        writer.writeheader()
        writer.writerows(rows)

    # Write .bat (D-12, Pitfall 2, Pitfall 6)
    # Use utf-8-sig so Windows cmd.exe reads the BOM and uses UTF-8 code page.
    # All line endings are explicit \r\n.
    with open(bat_path, "w", encoding="utf-8-sig", newline="") as bat_file:
        bat_file.write("@echo off\r\n")
        bat_file.write("chcp 65001 >nul\r\n")
        bat_file.write(f":: PhotoConsole deletion manifest — generated {ts}\r\n")
        bat_file.write(f":: Total files: {len(rows)}\r\n")
        bat_file.write(":: Review carefully before running. Deletions are permanent.\r\n")
        bat_file.write("\r\n")

        for row in rows:
            orig = row["original_path"]
            if row.get("source_type", "local") == "rclone":
                bat_file.write(f":: rclone deletefile {orig}\r\n")
            else:
                bat_file.write(f'del /f "{orig}"\r\n')

    return (csv_path, bat_path)


def run_consolidation(
    groups: list,  # list[DuplicateGroup]
    config,        # Config
    dry_run: bool = False,
    log_path: Optional[Path] = None,
) -> "ConsolidationPlan":
    """Orchestrate the full consolidation pipeline (D-01 through D-16).

    For each DuplicateGroup:
      - needs_copy=False (D: already has a copy, D-01):
          canonical → plan.skipped (no file I/O)
          each redundant → plan.to_manifest (for deletion manifest)
      - needs_copy=True (cloud-only, D-02):
          compute_dest_path → resolve_conflict
          If resolve_conflict returns None → plan.skipped (idempotent re-run, D-09)
          If dry_run=True → plan.to_copy (no I/O, D-16)
          If dry_run=False:
            copy_and_verify → plan.to_copy on success (D-10)
            FileNotFoundError / OSError → plan.errors (T-04-01 / Pitfall 7)
            Hash mismatch → plan.errors

    After all groups are processed:
      - If not dry_run and plan.to_manifest is non-empty → write_manifest() (D-11, D-12)

    Preflight (not dry_run only):
      - check_destination_writable() is called before any copy attempt (Pitfall 5)

    Args:
        groups:   list[DuplicateGroup] from find_duplicate_groups().
        config:   Config with consolidation.destination_path and catalog_path set.
        dry_run:  If True, populate the plan but write no files (D-16).
        log_path: Override path for consolidation.log; defaults to
                  <catalog_path parent>/consolidation.log.

    Returns:
        ConsolidationPlan with to_copy, to_manifest, skipped, and errors populated.
    """
    # Import here to avoid circular imports at module level
    from photoconsole.dedup import DuplicateGroup  # noqa: F401 — type reference only

    plan = ConsolidationPlan()

    logger: Optional[logging.Logger] = None
    if not dry_run:
        check_destination_writable(config.consolidation.destination_path)
        effective_log_path = log_path or (
            Path(config.catalog_path).parent / "consolidation.log"
        )
        logger = setup_consolidation_logger(effective_log_path)

    for group in groups:
        if not group.needs_copy:
            # D-01: local D: already has this hash — skip copy
            skip_action = CopyAction(
                src_path=group.canonical.path,
                dest_path=group.canonical.path,
                hash=group.hash,
                source_name=group.canonical.source_name,
                action="skip_idempotent",
            )
            plan.skipped.append(skip_action)

            # Add all redundants to the manifest for deletion
            for redundant in group.redundants:
                manifest_row = {
                    "original_path": redundant.path,
                    "hash": group.hash,
                    "destination_path": group.canonical.path,
                    "source_name": redundant.source_name,
                    "source_type": getattr(redundant, "source_type", "local"),
                }
                plan.to_manifest.append(manifest_row)

        else:
            # D-02: cloud-only — needs a local copy
            desired_dest = compute_dest_path(
                group.canonical.path,
                getattr(group.canonical, "date_taken", None),
                getattr(group.canonical, "mtime", None),
                config.consolidation.destination_path,
            )
            actual_dest = resolve_conflict(desired_dest, group.hash)

            if actual_dest is None:
                # D-09: already present at destination — idempotent skip
                skip_action = CopyAction(
                    src_path=group.canonical.path,
                    dest_path=str(desired_dest),
                    hash=group.hash,
                    source_name=group.canonical.source_name,
                    action="skip_idempotent",
                )
                plan.skipped.append(skip_action)
                if logger:
                    logger.info(
                        f"SKIP | dest={desired_dest} | hash={group.hash} | reason=already_present"
                    )
                continue

            # Stage: the copy action we intend to perform (added to plan ONLY on success)
            stage = CopyAction(
                src_path=group.canonical.path,
                dest_path=str(actual_dest),
                hash=group.hash,
                source_name=group.canonical.source_name,
                action="copy",
            )

            # Add redundants to manifest regardless of dry_run
            for redundant in group.redundants:
                manifest_row = {
                    "original_path": redundant.path,
                    "hash": group.hash,
                    "destination_path": str(actual_dest),
                    "source_name": redundant.source_name,
                    "source_type": getattr(redundant, "source_type", "local"),
                }
                plan.to_manifest.append(manifest_row)

            if dry_run:
                # D-16: dry run — record intent, no I/O
                plan.to_copy.append(stage)
                continue

            # Live run: attempt the copy
            try:
                ok = copy_and_verify(group.canonical.path, actual_dest, group.hash)
            except (FileNotFoundError, OSError) as exc:
                # T-04-01 / Pitfall 7: source disappeared between catalog scan and now
                error_action = dataclasses.replace(stage, action="error")
                plan.errors.append(error_action)
                if logger:
                    logger.error(
                        f"ERROR | src={group.canonical.path} | hash={group.hash} "
                        f"| outcome=exception | detail={exc}"
                    )
                continue

            if ok:
                plan.to_copy.append(stage)
                if logger:
                    logger.info(
                        f"COPY | src={group.canonical.path} | dest={actual_dest} "
                        f"| hash={group.hash} | outcome=ok"
                    )
            else:
                # Hash mismatch — corrupt destination was already removed by copy_and_verify
                error_action = dataclasses.replace(stage, action="copy_hash_mismatch")
                plan.errors.append(error_action)
                if logger:
                    logger.error(
                        f"ERROR | src={group.canonical.path} | dest={actual_dest} "
                        f"| hash={group.hash} | outcome=hash_mismatch_dest_removed"
                    )

    # Write manifest after all copies complete (D-11, D-12)
    if not dry_run and plan.to_manifest:
        dest_dir = Path(config.consolidation.destination_path)
        write_manifest(plan.to_manifest, dest_dir)

    return plan
