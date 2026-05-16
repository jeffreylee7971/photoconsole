---
phase: 01-scanning-cataloging-foundation
plan: 01
subsystem: foundation
tags: [python, cli, packaging, config, scaffolding, tdd]
completed: 2026-05-16
duration_minutes: 35
tasks_completed: 2
tasks_total: 2
files_created: 10
files_modified: 0

dependency_graph:
  requires: []
  provides:
    - photoconsole.errors.ErrorType
    - photoconsole.errors.classify_error
    - photoconsole.constants.MEDIA_EXTENSIONS
    - photoconsole.constants.PHOTO_EXTENSIONS
    - photoconsole.constants.VIDEO_EXTENSIONS
    - photoconsole.constants.CHUNK_SIZE
    - photoconsole.config.Source
    - photoconsole.config.Config
    - photoconsole.config.load_config
  affects:
    - All Phase 1 plans (02–05) import from these modules

tech_stack:
  added:
    - PyYAML 6.0.3 (config parsing)
    - pytest 9.0.3 (test framework)
    - pytest-mock 3.15.1 (mocking)
    - Pillow 12.2.0, piexif 1.1.3, click 8.3.3, tqdm 4.67.3, SQLAlchemy 2.0.49 (declared in pyproject.toml)
  patterns:
    - TDD RED/GREEN with per-phase commits
    - PEP 621 pyproject.toml packaging
    - StrEnum for type-safe error constants
    - yaml.safe_load only (threat T-01-01)
    - os.path.expanduser + os.path.abspath for path normalization (threat T-01-02)

key_files:
  created:
    - pyproject.toml
    - .gitignore
    - photoconsole/__init__.py
    - photoconsole/constants.py
    - photoconsole/errors.py
    - photoconsole/config.py
    - config.example.yaml
    - tests/__init__.py
    - tests/conftest.py
    - tests/test_errors.py
    - tests/test_config.py
  modified: []

key_decisions:
  - "StrEnum for ErrorType ensures string equality and enum membership simultaneously"
  - "classify_error explicitly excludes HASH_FAILED and METADATA_FAILED — those are set by call sites"
  - "Config.include_extensions stored as frozenset for immutability and O(1) membership tests"
  - "hashing_max_workers defaults via lambda: os.cpu_count() or 1 at load time, not at class definition"
  - "config.example.yaml rclone remote values must be quoted (gdrive: contains colon)"
  - "yaml.safe_load is the only YAML loading method used — no yaml.load anywhere (T-01-01)"

metrics:
  duration: 35 minutes
  completed_date: 2026-05-16
  tests_written: 40
  tests_passing: 40
  test_coverage_modules: [photoconsole.errors, photoconsole.config]
---

# Phase 1 Plan 01: Package Skeleton, Errors, Constants, Config Loader Summary

**One-liner:** Installable Python package with ErrorType StrEnum (6 members), frozenset media extension constants, and validated YAML config loader with full threat mitigations applied.

---

## What Was Built

### Task 1: Package skeleton, errors enum, constants

Created the package foundation:

- **`pyproject.toml`** — PEP 621 build metadata with all 6 runtime dependencies, optional dev group, `photoconsole.cli:main` entry point (stub for Plan 05), `[tool.pytest.ini_options]` with testpaths and `-ra -q` addopts.
- **`photoconsole/__init__.py`** — `__version__ = "0.1.0"`.
- **`photoconsole/constants.py`** — `PHOTO_EXTENSIONS`, `VIDEO_EXTENSIONS`, `MEDIA_EXTENSIONS` as frozensets; `CHUNK_SIZE = 8192`. `MEDIA_EXTENSIONS` is defined as `PHOTO_EXTENSIONS | VIDEO_EXTENSIONS`.
- **`photoconsole/errors.py`** — `ErrorType(StrEnum)` with exactly 6 members; `classify_error()` maps PermissionError→permission_denied, FileNotFoundError→not_found, TimeoutError→timeout, default→read_error. `HASH_FAILED` and `METADATA_FAILED` are intentionally absent from `classify_error` — those are assigned by the hasher and metadata modules.
- **`tests/__init__.py`** — empty marker file.
- **`tests/conftest.py`** — `sample_jpg` fixture (pre-baked 1×1 JPEG bytes), `tmp_catalog_path` fixture (tmp_path-derived sqlite path, uninitialised), `in_memory_engine` stub (returns None; Plan 02 overrides with real ORM factory).
- **`tests/test_errors.py`** — 16 tests covering all ErrorType members, string values, StrEnum isinstance behavior, and all classify_error cases.

### Task 2: Config dataclasses, YAML loader, config.example.yaml

- **`photoconsole/config.py`** — `Source` and `Config` dataclasses with full field documentation; `load_config()` implementing all validation rules from D-06/D-07/D-08/D-09 with exact error message substrings required by tests. Threat mitigations T-01-01 (yaml.safe_load) and T-01-02 (expanduser+abspath) applied.
- **`config.example.yaml`** — Reference config with local + rclone sources, include_extensions list, and hashing.max_workers. Note: rclone remote values are quoted to prevent YAML colon parsing errors.
- **`tests/test_config.py`** — 24 tests covering all validation paths, extension normalization, defaults, and YAML safety.

### Deviation: .gitignore added

Added `.gitignore` for Python build artifacts (egg-info, pycache, dist, .db files). This was not in the plan but is required for a clean repository state (Rule 2 — missing critical tooling).

---

## Verification Results

All acceptance criteria commands passed:

```
pip install -e .                                              EXIT 0
pytest tests/test_errors.py -x -q                            16 passed
pytest tests/test_config.py -x -q                            24 passed
pytest tests/ -x -q                                          40 passed
python -c "from photoconsole.errors import ErrorType..."     PASS
python -c "from photoconsole.constants import ..."           PASS
python -c "from photoconsole.config import load_config; c = load_config('config.example.yaml')..."  PASS
```

---

## TDD Gate Compliance

Both tasks followed RED/GREEN/REFACTOR:

| Phase | Task 1 Commit | Task 2 Commit |
|-------|---------------|---------------|
| RED   | e6c1356       | 688265e       |
| GREEN | ea18a1f       | ec647f9       |

No REFACTOR commits needed — code was clean on first pass.

---

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Added .gitignore**
- **Found during:** Task 2 (post-commit cleanup)
- **Issue:** Generated files (photoconsole.egg-info/, __pycache__/) left untracked after `pip install -e .`
- **Fix:** Created comprehensive `.gitignore` covering Python build artifacts, virtual envs, SQLite catalog files, IDE files
- **Files modified:** `.gitignore` (created)
- **Commit:** f94b8d8

**2. [Rule 1 - Bug] Fixed YAML syntax error in config.example.yaml**
- **Found during:** Task 2 GREEN phase (test run)
- **Issue:** `remote: gdrive:` — YAML parser treated the trailing colon as a mapping indicator, causing `yaml.scanner.ScannerError` on line 22
- **Fix:** Quoted the value: `remote: "gdrive:"`
- **Files modified:** `config.example.yaml`
- **Commit:** Part of ec647f9

---

## Known Stubs

- **`tests/conftest.py` `in_memory_engine` fixture** — Returns `None`. Plan 02 (catalog/models) will replace the body with a real SQLAlchemy in-memory engine factory. This stub prevents `AttributeError` if any test accidentally imports it before Plan 02.
- **`photoconsole.cli:main` entry point** — Declared in pyproject.toml but the `photoconsole/cli.py` module does not exist yet. `pip install -e .` succeeds and the `photoconsole` script is registered but not callable. Plan 05 implements this.

---

## Threat Surface Scan

All threats covered per plan's threat_model:

| Threat | File | Status |
|--------|------|--------|
| T-01-01: yaml.safe_load only | photoconsole/config.py | Mitigated — only `yaml.safe_load` used; test_config.py::TestYamlSafety verifies !!python/object tags are rejected |
| T-01-02: path traversal via catalog_path | photoconsole/config.py | Mitigated — `os.path.expanduser` + `os.path.abspath` applied; test verifies no tilde remains |
| T-01-SC: pip install legitimacy | pyproject.toml | Pre-cleared — RESEARCH.md Package Legitimacy Audit verified all packages via slopcheck 0.6.1; all [OK] |

No new threat surface introduced beyond plan's threat_model.

---

## Self-Check: PASSED

Files created:
- FOUND: pyproject.toml
- FOUND: photoconsole/__init__.py
- FOUND: photoconsole/constants.py
- FOUND: photoconsole/errors.py
- FOUND: photoconsole/config.py
- FOUND: config.example.yaml
- FOUND: tests/__init__.py
- FOUND: tests/conftest.py
- FOUND: tests/test_errors.py
- FOUND: tests/test_config.py
- FOUND: .gitignore

Commits verified:
- FOUND: e6c1356 (test RED - errors)
- FOUND: ea18a1f (feat GREEN - skeleton/errors/constants)
- FOUND: 688265e (test RED - config)
- FOUND: ec647f9 (feat GREEN - config)
- FOUND: f94b8d8 (chore - .gitignore)
