---
phase: 02-deduplication-consolidation
plan: "03"
subsystem: consolidator
tags: [consolidation, copy-pipeline, pathlib, shutil, sha256, D-05, D-06, D-08, D-09, D-10]
dependency_graph:
  requires: [02-01, 02-02]
  provides: [compute_dest_path, resolve_conflict, copy_and_verify, CopyAction, ConsolidationPlan]
  affects: [photoconsole/consolidator.py, photoconsole/cli.py]
tech_stack:
  added: []
  patterns: [tdd-red-green, pathlib-arithmetic, shutil-copy2-verify, multi-format-strptime, idempotent-conflict-resolution]
key_files:
  created:
    - photoconsole/consolidator.py
    - tests/test_consolidator.py
  modified: []
decisions:
  - "Both tasks (Task 1 + Task 2) implemented in a single atomic write of consolidator.py since all five exports are in one cohesive module"
  - "_DATE_FORMATS module-level constant tries formats in order: colon-EXIF, dash-ISO, T-ISO"
  - "resolve_conflict short-circuits at each conflict slot (stem_N) if sha256 matches src_hash — prevents accumulation on idempotent re-runs (Pitfall 3)"
  - "copy_and_verify wraps FileNotFoundError+OSError rather than just FileNotFoundError for full Pitfall 7 coverage"
  - "CopyAction uses str fields for src_path/dest_path (not Path) per plan spec — callers pass strings from catalog rows"
metrics:
  duration_seconds: 173
  completed_date: "2026-05-17T00:15:46Z"
  tasks_completed: 2
  files_modified: 2
---

# Phase 02 Plan 03: Copy Pipeline Building Blocks — Summary

photoconsole/consolidator.py created with three pure functions (compute_dest_path, resolve_conflict, copy_and_verify) and two dataclasses (CopyAction, ConsolidationPlan) implementing the D-05/D-06 date-organized path structure, D-08/D-09 idempotent conflict resolution, and D-10 post-copy SHA-256 verification; all five exports fully covered by 23 pytest tests.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| RED  | Failing tests for compute_dest_path, resolve_conflict, copy_and_verify (23 tests) | d677432 | tests/test_consolidator.py |
| GREEN | consolidator.py with compute_dest_path, CopyAction, ConsolidationPlan, resolve_conflict, copy_and_verify | 7681824 | photoconsole/consolidator.py |

## What Was Built

### CopyAction dataclass (Task 1)

```python
@dataclass
class CopyAction:
    src_path: str
    dest_path: str
    hash: str
    source_name: str
    action: str  # 'copy' | 'skip_idempotent' | 'error'
```

### ConsolidationPlan dataclass (Task 1)

```python
@dataclass
class ConsolidationPlan:
    to_copy: list[CopyAction] = field(default_factory=list)
    to_manifest: list[dict] = field(default_factory=list)
    skipped: list[CopyAction] = field(default_factory=list)
    errors: list[CopyAction] = field(default_factory=list)
```

### compute_dest_path() (Task 1)

Implements D-05 and D-06:
- date_taken parseable (3 formats tried in order) → `root/YYYY/MM/name`
- date_taken None/unparseable, mtime available → `root/unknown/YYYY/MM/name`
- both None → `root/unknown/name`

Uses `Path(filename).name` — only basename is used regardless of input path.

### resolve_conflict() (Task 2)

Implements D-08 and D-09 with Pitfall 3 protection:
- Non-existent dest → return dest as-is
- Existing dest, same hash → return None (D-09 idempotent skip)
- Existing dest, different hash → try `stem_2.ext`, `stem_3.ext`…; at each slot, check hash before incrementing (prevents accumulation on re-run)

All paths built with pathlib arithmetic inside `desired_dest.parent` (T-03-01).

### copy_and_verify() (Task 2)

Implements D-10 and T-03-02:
1. `dest_path.parent.mkdir(parents=True, exist_ok=True)`
2. `shutil.copy2(src_path, str(dest_path))`
3. `sha256_file(dest_path)` post-copy verification
4. Hash mismatch → `dest_path.unlink(missing_ok=True)`, return False
5. `FileNotFoundError`/`OSError` on copy → return False (Pitfall 7)
6. Source file never modified or removed (D-13)

Reuses `sha256_file` from `photoconsole.hasher` — not re-implemented.

## Verification Results

Task 1 verify command:
```
OK
```

Task 2 verify command:
```
OK
```

Final import check:
```
imports OK
```

Full test suite: 179 passed, 4 skipped (symlink tests — pre-existing Windows-only skip).

## Deviations from Plan

None — plan executed exactly as written. Tasks 1 and 2 were written in a single file since they are tightly coupled within the same module. RED committed before GREEN; both GREEN tasks committed together since the full module was implemented atomically.

## Known Stubs

None — all three functions are fully operational with real filesystem I/O.

## Threat Flags

None — no new network endpoints or auth paths. File access patterns are explicitly filesystem-local (shutil.copy2 to user-configured destination_root). All threat model mitigations applied:
- T-03-01: pathlib arithmetic only in resolve_conflict (no string interpolation)
- T-03-02: corrupt dest removed on hash mismatch; source never touched

## Self-Check: PASSED

| Check | Result |
|-------|--------|
| photoconsole/consolidator.py exists | FOUND |
| tests/test_consolidator.py exists | FOUND |
| `def compute_dest_path` in consolidator.py | FOUND |
| `def resolve_conflict` in consolidator.py | FOUND |
| `def copy_and_verify` in consolidator.py | FOUND |
| `class CopyAction` in consolidator.py | FOUND |
| `class ConsolidationPlan` in consolidator.py | FOUND |
| Commit d677432 (RED) exists | FOUND |
| Commit 7681824 (GREEN) exists | FOUND |
| Task 1 verify command exits 0 with "OK" | PASSED |
| Task 2 verify command exits 0 with "OK" | PASSED |
| Final import check exits 0 with "imports OK" | PASSED |
| pytest tests/test_consolidator.py — 23 tests | PASSED |
| pytest tests/ — full suite | 179 passed, 4 skipped |
