"""Copy pipeline building blocks for PhotoConsole consolidation.

Implements the stateless, independently-testable inner functions that form the
file copy pipeline:

  compute_dest_path  — builds YYYY/MM or unknown/YYYY/MM destination path
                        from date_taken (EXIF) or mtime fallback (D-05, D-06)
  resolve_conflict   — handles same-filename collisions at destination (D-08, D-09)
  copy_and_verify    — shutil.copy2 + post-copy SHA-256 verification (D-10)

All three functions are pure with respect to business logic; side effects are
limited to explicit filesystem operations documented in each function's docstring.

Design decisions
----------------
D-05  Primary structure: destination_root/YYYY/MM/filename.ext
D-06  Fallback when date_taken is None or unparseable:
        - mtime available → unknown/YYYY/MM/filename.ext
        - mtime also None → unknown/filename.ext
D-08  Conflict: same dest path, different hash → auto-rename with numeric suffix
D-09  Idempotent: same dest path, same hash → return None (caller skips copy)
D-10  Post-copy hash verification; corrupt copy removed on mismatch

Security
--------
T-03-01  resolve_conflict builds paths with pathlib arithmetic only (no string
         interpolation); all candidates remain inside desired_dest.parent.
T-03-02  copy_and_verify calls dest_path.unlink(missing_ok=True) on hash mismatch;
         source file is never touched.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from photoconsole.hasher import sha256_file

# ---------------------------------------------------------------------------
# Date format table (Pitfall 1 / RESEARCH.md)
# ---------------------------------------------------------------------------

_DATE_FORMATS = [
    "%Y:%m:%d %H:%M:%S",   # canonical EXIF: '2023:06:15 10:30:00'
    "%Y-%m-%d %H:%M:%S",   # ISO-like:       '2023-06-15 10:30:00'
    "%Y-%m-%dT%H:%M:%S",   # ISO 8601:       '2023-06-15T10:30:00'
]


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
