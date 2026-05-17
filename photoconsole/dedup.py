"""Exact duplicate detection for PhotoConsole.

This module queries the SQLite catalog for hashes appearing more than once and
classifies each group into a canonical copy and a list of redundant copies using
source-priority ordering.

Design decisions implemented here
-----------------------------------
D-01 — D: wins:
    When the same hash exists on a local D: source (source_type='local') AND on
    one or more cloud sources, the local copy is always the canonical keeper.
    No copy operation is needed for these groups.

D-02 — cloud-only → needs_copy:
    When a hash is present only in cloud sources (all source_type='rclone'),
    the file is absent from the local master library.  DuplicateGroup.needs_copy
    is set to True so the consolidator knows to copy one instance to D:.

D-03 / D-04 — source_priority ordering:
    source_priority is a caller-supplied ordered list of source names
    (e.g. ['D: SSD', 'OneDrive', 'Amazon Photos']).  Within a group the file
    whose source_name appears earliest in that list becomes canonical; ties are
    broken by stable sort (insertion order preserved).  An unknown source_name
    receives a sentinel priority of len(source_priority), placing it last.

Note: this module does NOT import from photoconsole.config.  source_priority is
always passed by the caller as a plain list[str], keeping dedup.py decoupled
from configuration concerns.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from photoconsole.catalog.models import MediaFile


@dataclass
class DuplicateGroup:
    """A set of catalog entries that share the same SHA-256 hash.

    Attributes
    ----------
    hash:       The shared SHA-256 hex digest for this group.
    canonical:  The preferred keeper — the file that should be retained.
                Chosen by source_priority ranking (D-01/D-04).
    redundants: All other files in the group (same hash, not canonical).
                len(redundants) == len(all files in group) - 1.
    needs_copy: True when no file in the group has source_type='local'
                (i.e. the hash is absent from every D: drive).  The
                consolidator must copy one instance to the destination (D-02).
                False when at least one local copy exists (D-01).
    """

    hash: str
    canonical: MediaFile
    redundants: List[MediaFile] = field(default_factory=list)
    needs_copy: bool = False


def classify_group(
    files: List[MediaFile],
    source_priority: List[str],
) -> DuplicateGroup:
    """Classify a list of MediaFile objects sharing the same hash.

    Selects the canonical copy using *source_priority* ordering and determines
    whether the hash needs to be copied to the local D: library (needs_copy).

    Algorithm
    ---------
    1. Build a priority map: ``{source_name: index}`` from source_priority.
    2. Use ``sentinel = len(source_priority)`` for any source_name not in the
       map (unknown sources sort last — lowest priority).
    3. Stable-sort files by their priority index so the best source floats to
       the front.  Stable sort preserves original order for ties.
    4. canonical = sorted_files[0]; redundants = sorted_files[1:].
    5. needs_copy = True iff *none* of the files has source_type='local'.
       A local file means the hash already lives on a D: drive (D-01);
       cloud-only groups must be pulled to D: (D-02).

    Args:
        files:           Non-empty list of MediaFile rows sharing the same hash.
        source_priority: Ordered list of source names from config
                         (e.g. ['D: SSD', 'OneDrive', 'iCloud']).

    Returns:
        A DuplicateGroup with canonical, redundants, and needs_copy set.
    """
    priority_map = {name: idx for idx, name in enumerate(source_priority)}
    sentinel = len(source_priority)

    sorted_files = sorted(
        files,
        key=lambda f: priority_map.get(f.source_name, sentinel),
    )

    canonical = sorted_files[0]
    redundants = sorted_files[1:]

    needs_copy = not any(f.source_type == "local" for f in files)

    return DuplicateGroup(
        hash=canonical.hash,
        canonical=canonical,
        redundants=redundants,
        needs_copy=needs_copy,
    )


def find_duplicate_groups(
    session: Session,
    source_priority: List[str],
) -> List[DuplicateGroup]:
    """Query the catalog and return one DuplicateGroup per duplicated hash.

    A hash is considered duplicated when two or more catalog rows share the
    same SHA-256 hash and both have status='ok'.  Rows with status='error' or
    a NULL hash are excluded from consideration (T-02-01).

    Algorithm
    ---------
    Step 1 — find duplicate hashes:
        SELECT hash FROM media_files
        WHERE hash IS NOT NULL AND status = 'ok'
        GROUP BY hash
        HAVING COUNT(id) > 1

    Step 2 — for each duplicate hash, fetch all ok rows:
        SELECT * FROM media_files
        WHERE hash = :hash_val AND status = 'ok'

    Step 3 — classify each group via classify_group().

    All queries use parameterized SQLAlchemy expressions.  No string
    interpolation is used in SQL construction (T-02-01).

    Args:
        session:         An active SQLAlchemy Session (read-only usage).
        source_priority: Ordered source names for canonical selection
                         (passed through to classify_group).

    Returns:
        List of DuplicateGroup instances, one per duplicated hash.
        Returns an empty list when the catalog has no duplicates.
    """
    # Step 1: find all hashes with more than one ok row
    dup_hash_stmt = (
        select(MediaFile.hash)
        .where(MediaFile.hash.isnot(None))
        .where(MediaFile.status == "ok")
        .group_by(MediaFile.hash)
        .having(func.count(MediaFile.id) > 1)
    )
    dup_hashes: List[str] = [
        row.hash for row in session.execute(dup_hash_stmt)
    ]

    # Step 2 & 3: fetch rows per hash and classify
    groups: List[DuplicateGroup] = []
    for hash_val in dup_hashes:
        files_stmt = (
            select(MediaFile)
            .where(MediaFile.hash == hash_val)
            .where(MediaFile.status == "ok")
        )
        files: List[MediaFile] = list(
            session.execute(files_stmt).scalars().all()
        )
        groups.append(classify_group(files, source_priority))

    return groups
