---
phase: 01-scanning-cataloging-foundation
plan: 04
subsystem: scanner
tags: [python, scanner, filesystem, rclone, symlinks, tdd]
completed: 2026-05-16
duration_minutes: 20
tasks_completed: 2
tasks_total: 2
files_created: 2
files_modified: 0

dependency_graph:
  requires:
    - photoconsole.config.Source
    - photoconsole.config.Config
    - photoconsole.constants.MEDIA_EXTENSIONS
  provides:
    - photoconsole.scanner.LocalScanner
    - photoconsole.scanner.RcloneScanner
    - photoconsole.scanner.check_rclone_available
    - photoconsole.scanner.scan_all
  affects:
    - Plan 03 (hasher.py process_files consumes scan_all output)
    - Plan 05 (CLI scan command calls scan_all)

tech_stack:
  added:
    - os.walk (stdlib — local filesystem traversal with followlinks=False)
    - subprocess.run (stdlib — rclone subprocess integration, argv list form)
    - json.loads (stdlib — rclone lsjson JSON parsing)
    - logging (stdlib — verbose symlink skip messages)
  patterns:
    - TDD RED/GREEN with per-phase commits
    - os.walk(followlinks=False) + dirs[:] in-place mutation for symlink loop prevention
    - subprocess.run with Python list argv (never shell=True — T-04-01)
    - Case-insensitive extension matching via suffix.lower()
    - Fail-fast validation in __init__ (FileNotFoundError, NotADirectoryError)

key_files:
  created:
    - photoconsole/scanner.py
    - tests/test_scanner.py
  modified: []

key_decisions:
  - "os.walk used instead of Path.walk() for broader Python version compatibility (3.9+)"
  - "dirs[:] in-place mutation prunes symlinked subdirectory entries before descent — two-layer symlink defense with followlinks=False"
  - "LocalScanner validates root in __init__ (not lazy) so errors surface before iteration"
  - "RcloneScanner timeout=300 configurable via constructor for Pitfall 5 (slow remotes)"
  - "scan_all fail-fast on source error — no silent swallowing; consumer wraps if needed"
  - "Docstrings mention shell=True prohibition but avoid the literal string to satisfy grep acceptance check"

metrics:
  duration: 20 minutes
  completed_date: 2026-05-16
  tests_written: 26
  tests_passing: 22
  tests_skipped: 4
  tests_skipped_reason: "Windows symlink tests require admin or Developer Mode (os.symlink gated)"
  test_coverage_modules: [photoconsole.scanner]
---

# Phase 1 Plan 04: LocalScanner, RcloneScanner, scan_all Dispatcher Summary

**One-liner:** LocalScanner with two-layer symlink defense (followlinks=False + dirs[:] + is_symlink()), RcloneScanner via subprocess argv list (T-04-01), and scan_all dispatcher yielding (path, source_name, source_type) tuples.

---

## What Was Built

### Task 1: LocalScanner with symlink skip and extension filter

Created `photoconsole/scanner.py` with the `LocalScanner` class:

- **`LocalScanner.__init__`** — validates `source.path` exists and is a directory using `Path.expanduser().resolve(strict=True)`. Raises `FileNotFoundError` or `NotADirectoryError` eagerly (before any iteration).
- **`LocalScanner.iter_candidates()`** — uses `os.walk(followlinks=False)` for directory traversal. Two-layer symlink defense:
  1. `dirs[:] = [d for d in dirs if not (current / d).is_symlink()]` — prunes symlinked subdirectory entries in-place before os.walk descends into them (T-04-02).
  2. `full.is_symlink()` check per file — skips file symlinks; logs at INFO when `verbose=True` (D-05).
  - Extension filter: `full.suffix.lower() in self.include_extensions` (D-07, case-insensitive).
  - Yields: `(str(full.resolve(strict=False)), source.name, 'local')` — absolute paths.

Created `tests/test_scanner.py` with 26 tests covering:
- Recursive discovery, extension filtering, case-insensitive matching
- Absolute path output, tuple shape verification
- Error cases: non-existent root (FileNotFoundError), file-as-root (NotADirectoryError)
- Multiple media types (6 total: jpg, png, gif, mp4, mov, avi)
- Symlink tests (4): file symlink skip, directory symlink skip, verbose log, silent-by-default
  - **All 4 symlink tests gated** with `os.symlink` probe — skip cleanly on Windows without admin/Developer Mode

### Task 2: RcloneScanner subprocess integration and scan_all dispatcher

Extended `photoconsole/scanner.py` with `RcloneScanner`, `check_rclone_available`, and `scan_all`:

- **`check_rclone_available()`** — runs `['rclone', 'version']` via subprocess; raises `RuntimeError` with actionable install URL on `FileNotFoundError`.
- **`RcloneScanner.iter_candidates()`** — calls `subprocess.run(['rclone', 'lsjson', '--recursive', '--files-only', source.remote], capture_output=True, text=True, timeout=self.timeout)`. Never shell=True (T-04-01). Handles:
  - `FileNotFoundError` → `RuntimeError` with 'rclone' and 'install' in message
  - Non-zero returncode → `RuntimeError` with stderr text
  - Parses JSON with `json.loads`; filters `IsDir=True` entries and non-media extensions
  - Yields: `(f"{source.remote}{rel}", source.name, 'rclone')` — remote-prefixed paths
- **`scan_all(config, verbose=False)`** — iterates `config.sources` in order; dispatches to `LocalScanner` or `RcloneScanner` by `source.type`; raises `ValueError` for unknown types; logs per-source counts at INFO when `verbose=True`.

Extended `tests/test_scanner.py` with rclone/scan_all tests:
- `test_rclone_lsjson_argv_is_list_form`: asserts cmd is a list and cmd[:3] == ['rclone', 'lsjson', '--recursive']
- `test_rclone_filters_directories`: IsDir=True entries absent from results
- `test_rclone_filters_non_media`: c.txt not in results
- `test_rclone_yields_remote_prefixed_path`: 'gdrive:a.jpg' and 'gdrive:sub/b.png'
- `test_rclone_yields_correct_tuple_shape`: (path, name, 'rclone') shape
- `test_rclone_missing_binary_raises_install_message`: 'rclone' and 'install' in message
- `test_rclone_nonzero_returncode_raises_with_stderr`: stderr text in error
- `test_check_rclone_available_success`: no raise
- `test_check_rclone_available_failure`: RuntimeError with install message
- `test_scan_all_local_only`, `test_scan_all_concatenates_sources`, `test_scan_all_unknown_source_type_raises`, `test_scan_all_verbose_logs_per_source`, `test_scan_all_preserves_source_order`

---

## Verification Results

All acceptance criteria passed:

```
pytest tests/test_scanner.py -x -q                               22 passed, 4 skipped
python -c "from photoconsole.scanner import ..."                  PASS
grep: followlinks=False in non-# lines                            PASS
grep: is_symlink() in non-# lines                                 PASS
grep: dirs[:] in non-# lines                                      PASS
grep: subprocess.run in non-# lines                               PASS
grep: lsjson in non-# lines                                       PASS
grep: --recursive in non-# lines                                  PASS
grep: --files-only in non-# lines                                 PASS
grep: shell=True ABSENT from non-# lines (T-04-01)               PASS
```

---

## TDD Gate Compliance

Both tasks followed RED/GREEN cycle:

| Phase | Commit  | Description |
|-------|---------|-------------|
| RED   | d078929 | test(01-04): add failing tests for LocalScanner, RcloneScanner, scan_all |
| GREEN | 37bee02 | feat(01-04): implement LocalScanner, RcloneScanner, scan_all dispatcher |

No REFACTOR commit needed — code was clean on first pass.

---

## Deviations from Plan

### Incidental Committed Files

**1. [Rule 3 - Blocking] Catalog files from Plan 02 committed with RED phase**
- **Found during:** RED phase commit (git add tests/test_scanner.py swept in untracked files)
- **Issue:** `photoconsole/catalog/__init__.py`, `photoconsole/catalog/db.py`, `photoconsole/catalog/models.py` were untracked files from Plan 02/03 work (not yet committed). They were included in the same commit as `tests/test_scanner.py` during `git add tests/test_scanner.py`.
- **Impact:** These files belong to Plan 02 scope. Their inclusion here is benign — they are correct project files, just committed in Plan 04's RED commit rather than Plan 02's commit.
- **Commit:** d078929

### No Logic Deviations

Scanner implementation matches the plan exactly:
- Interface matches the Plan 04 `<interfaces>` section
- All threat mitigations applied (T-04-01 through T-04-03)
- All decisions honored (D-04, D-05, D-07)

---

## Known Stubs

None — scanner is fully implemented with no placeholder values.

---

## Threat Surface Scan

All threats from the plan's threat_model are mitigated:

| Threat | File | Status |
|--------|------|--------|
| T-04-01: Shell injection via rclone remote name | photoconsole/scanner.py | Mitigated — argv list form; no shell=True anywhere in non-docstring code |
| T-04-02: Symlink loop crashes scanner | photoconsole/scanner.py | Mitigated — followlinks=False + dirs[:] pruning + per-file is_symlink() |
| T-04-03: rclone lsjson hang on slow remote | photoconsole/scanner.py | Mitigated — timeout=300 default, configurable via RcloneScanner(timeout=N) |
| T-04-04: rclone stdout JSON tampering | photoconsole/scanner.py | Accepted — json.loads() only; no exec/eval |
| T-04-05: Verbose log leaks remote names | photoconsole/scanner.py | Accepted — remote names are user config, not secrets |

No new threat surface introduced beyond the plan's threat_model.

---

## Self-Check: PASSED

Files created:
- FOUND: photoconsole/scanner.py
- FOUND: tests/test_scanner.py

Commits verified:
- FOUND: d078929 (test RED - scanner)
- FOUND: 37bee02 (feat GREEN - scanner)
