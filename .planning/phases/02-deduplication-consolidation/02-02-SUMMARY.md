---
phase: 02-deduplication-consolidation
plan: "02"
subsystem: dedup
tags: [deduplication, SQLAlchemy, dataclass, source-priority, D-01, D-02]
dependency_graph:
  requires: [02-01]
  provides: [DuplicateGroup, classify_group, find_duplicate_groups]
  affects: [photoconsole/consolidator.py, photoconsole/cli.py]
tech_stack:
  added: []
  patterns: [SQLAlchemy-2.0-select-group-by-having, dataclass-with-field, stable-sort-priority-map]
key_files:
  created:
    - photoconsole/dedup.py
  modified: []
decisions:
  - "find_duplicate_groups written alongside classify_group in a single cohesive file; both tasks committed together since the module was written atomically"
  - "DuplicateGroup.hash set to canonical.hash (not independently passed) — hash is already on the MediaFile ORM object"
  - "No import from config.py; source_priority accepted as list[str] to keep dedup.py decoupled from config concerns"
  - "Stable sort (Python's built-in sorted) preserves insertion order for equal priorities — deterministic tie-breaking"
metrics:
  duration_seconds: 134
  completed_date: "2026-05-17T00:12:41Z"
  tasks_completed: 2
  files_modified: 1
---

# Phase 02 Plan 02: Duplicate Detection Module — Summary

DuplicateGroup dataclass and find_duplicate_groups() implemented in photoconsole/dedup.py; classify_group() ranks files by source_priority, enforces D: source wins (D-01), flags cloud-only groups as needs_copy (D-02), and find_duplicate_groups() queries the catalog with parameterized SQLAlchemy GROUP BY hash HAVING COUNT > 1.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | DuplicateGroup dataclass and classify_group() | 0cdf74f | photoconsole/dedup.py |
| 2 | find_duplicate_groups() — catalog query and group assembly | 0cdf74f | photoconsole/dedup.py |

Note: Both tasks were committed together in 0cdf74f because the complete module was written atomically. Task 2's implementation was included in the initial write of Task 1's file since find_duplicate_groups() directly depends on classify_group() and DuplicateGroup from the same module.

## What Was Built

### DuplicateGroup dataclass (Task 1)

```python
@dataclass
class DuplicateGroup:
    hash: str
    canonical: MediaFile
    redundants: List[MediaFile] = field(default_factory=list)
    needs_copy: bool = False
```

Fields align exactly with the plan spec. `hash` is taken from `canonical.hash` (already present on the ORM object).

### classify_group() (Task 1)

Accepts `files: List[MediaFile]` and `source_priority: List[str]`. Algorithm:
- Builds `priority_map = {name: idx}` from source_priority
- `sentinel = len(source_priority)` for unknown source names (lowest priority)
- Stable-sorts files by priority index (preserves insertion order for ties)
- `canonical = sorted_files[0]`, `redundants = sorted_files[1:]`
- `needs_copy = not any(f.source_type == 'local' for f in files)` (D-01/D-02)

### find_duplicate_groups() (Task 2)

Accepts `session: Session` and `source_priority: List[str]`. Two-step query:

Step 1 — parameterized GROUP BY query:
```python
select(MediaFile.hash)
    .where(MediaFile.hash.isnot(None))
    .where(MediaFile.status == "ok")
    .group_by(MediaFile.hash)
    .having(func.count(MediaFile.id) > 1)
```

Step 2 — per-hash row fetch:
```python
select(MediaFile)
    .where(MediaFile.hash == hash_val)
    .where(MediaFile.status == "ok")
```

Both queries use parameterized SQLAlchemy expressions — no string interpolation (T-02-01).

## Verification Results

Task 1 verify command (from plan):
```
OK
```

Additional acceptance criteria (Task 1):
- Cloud-only group (all rclone) → needs_copy=True: PASSED
- Unknown source_name gets sentinel priority: PASSED
- redundants count == len(files) - 1: PASSED

Task 2 verify command (from plan):
```
OK
```

Additional acceptance criteria (Task 2):
- Empty catalog returns []: PASSED
- status='error' rows excluded from groups: PASSED
- NULL hash rows excluded from groups: PASSED

Final import check:
```
imports OK
```

## Deviations from Plan

None — plan executed exactly as written. Both tasks were implemented in a single atomic write of photoconsole/dedup.py since they are tightly coupled (Task 2 builds directly on Task 1 within the same module). The TDD RED phase was confirmed by the ModuleNotFoundError before implementation.

## Known Stubs

None — DuplicateGroup fields are all populated from real MediaFile ORM objects and logic. No placeholder values.

## Threat Flags

None — no new network endpoints, auth paths, or file access patterns introduced. The module is read-only against the catalog (T-02-02 accepted per plan). All SQL uses parameterized SQLAlchemy expressions (T-02-01 mitigated).

## Self-Check: PASSED

| Check | Result |
|-------|--------|
| photoconsole/dedup.py exists | FOUND |
| `class DuplicateGroup` in dedup.py | FOUND (line 42) |
| `def classify_group` in dedup.py | FOUND (line 64) |
| `def find_duplicate_groups` in dedup.py | FOUND (line 114) |
| No f-string SQL in dedup.py | CONFIRMED |
| Commit 0cdf74f exists | FOUND |
| Task 1 verify command exits 0 with "OK" | PASSED |
| Task 2 verify command exits 0 with "OK" | PASSED |
| Final import check exits 0 with "imports OK" | PASSED |
