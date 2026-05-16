---
phase: 01-scanning-cataloging-foundation
plan: 02
subsystem: catalog
tags: [python, sqlite, sqlalchemy, catalog, persistence, tdd]
completed: 2026-05-16
duration_minutes: 20
tasks_completed: 2
tasks_total: 2
files_created: 3
files_modified: 0

dependency_graph:
  requires:
    - photoconsole.errors.ErrorType (error_type column values)
  provides:
    - photoconsole.catalog.Base
    - photoconsole.catalog.MediaFile
    - photoconsole.catalog.create_catalog_engine
    - photoconsole.catalog.session_factory
    - photoconsole.catalog.upsert_media_file
    - photoconsole.catalog.upsert_many
    - photoconsole.catalog.should_skip
    - photoconsole.catalog.get_known_record
  affects:
    - Plan 03 (hasher produces dicts → upsert_media_file)
    - Plan 04 (metadata extractor populates EXIF columns)
    - Plan 05 (CLI wires create_catalog_engine + session_factory)

tech_stack:
  added:
    - SQLAlchemy 2.0 declarative ORM (already in pyproject.toml from Plan 01)
  patterns:
    - SQLAlchemy 2.0 Mapped[T] + mapped_column() typed column syntax
    - INSERT ... ON CONFLICT(path) DO UPDATE SET ... (sqlalchemy.dialects.sqlite.insert)
    - SQLAlchemy event listener for per-connection PRAGMA setup (WAL, synchronous, busy_timeout, foreign_keys)
    - Explicit unknown-key validation before upsert (T-02-01 mitigation)
    - TDD RED/GREEN with per-phase commits

key_files:
  created:
    - photoconsole/catalog/__init__.py
    - photoconsole/catalog/models.py
    - photoconsole/catalog/db.py
  modified: []

key_decisions:
  - "UPSERT uses sqlalchemy.dialects.sqlite.insert with on_conflict_do_update(index_elements=['path']) — one row per path, updates in-place"
  - "should_skip returns False for status='error' regardless of mtime — D-03 error retry semantics enforced at query level"
  - "Unknown record keys raise ValueError with the offending key(s) listed — catches typos early (T-02-01)"
  - "WAL mode set per-connection via SQLAlchemy event.listens_for(engine, 'connect') — pragmas survive connection pool recycling"
  - "scanned_at uses lambda: datetime.now(timezone.utc) not datetime.utcnow (deprecated)"
  - "upsert_media_file does NOT commit — caller batches commits for performance"

metrics:
  duration: 20 minutes
  completed_date: 2026-05-16
  tests_written: 26
  tests_passing: 26
  test_coverage_modules: [photoconsole.catalog.models, photoconsole.catalog.db]
---

# Phase 1 Plan 02: SQLAlchemy Catalog Models, DB Factory, Upsert/Skip Logic Summary

**One-liner:** SQLAlchemy 2.0 MediaFile ORM with 17 columns, WAL-mode SQLite engine factory, path-keyed UPSERT with unknown-key rejection, and D-03-compliant error-retry predicate.

---

## What Was Built

### Task 1: MediaFile ORM model + engine factory with WAL pragmas

- **`photoconsole/catalog/models.py`** — `Base(DeclarativeBase)` and `MediaFile(Base)` with 17 columns using SQLAlchemy 2.0 `Mapped[T]` + `mapped_column()` syntax. Columns cover all D-10 (photo) and D-12 (video) fields: `id`, `path`, `hash`, `size`, `mtime`, `ctime`, `source_name`, `source_type`, `media_type`, `status`, `error_type`, `date_taken`, `camera_model`, `orientation`, `gps_lat`, `gps_lon`, `scanned_at`. `path` has `unique=True, index=True`; `hash` and `status` are indexed. `scanned_at` defaults to a tz-aware UTC datetime via `lambda: datetime.now(timezone.utc)`.

- **`photoconsole/catalog/db.py`** (engine factory portion) — `create_catalog_engine(db_path)` resolves the path, creates parent directories, registers a `@event.listens_for(engine, 'connect')` handler that executes `PRAGMA journal_mode=WAL`, `PRAGMA synchronous=NORMAL`, `PRAGMA busy_timeout=5000`, and `PRAGMA foreign_keys=ON` via raw DBAPI cursor. Calls `Base.metadata.create_all(engine)`. `session_factory(engine)` returns `sessionmaker(bind=engine, expire_on_commit=False)`.

- **`photoconsole/catalog/__init__.py`** — Re-exports the complete public surface: `Base`, `MediaFile`, `create_catalog_engine`, `session_factory`, `upsert_media_file`, `upsert_many`, `should_skip`, `get_known_record`.

### Task 2: UPSERT + incremental skip + error retry semantics

- **`photoconsole/catalog/db.py`** (upsert/query portion) — `upsert_media_file(session, record)` validates that `'path'` is present and that every key is a valid `MediaFile` column name (raises `ValueError` for violations, implementing T-02-01). Uses `sqlalchemy.dialects.sqlite.insert` with `on_conflict_do_update(index_elements=['path'])` to UPSERT by path without duplicating rows. Does NOT commit — caller batches. `upsert_many(session, records)` iterates and returns count. `should_skip(session, path, mtime)` returns `True` only when an existing row has `status='ok'` AND `existing.mtime == mtime`; always `False` for `status='error'` (D-03). `get_known_record(session, path)` returns the `MediaFile` or `None`.

- **`tests/test_catalog.py`** — 26 tests in two classes (`TestMediaFileModel`, `TestEngineFactory`) plus `TestUpsert` and `TestShouldSkip`. Tests cover: schema column completeness, unique/index constraints, WAL journal mode, busy_timeout >= 5000, session factory, upsert insert, upsert update-by-path, error→ok promotion, upsert_many count+persist, unknown-key rejection, missing-path rejection, should_skip false-when-unknown, true-for-matching-ok-mtime, false-when-mtime-differs, false-for-status-error (D-03).

---

## Verification Results

All acceptance criteria commands passed:

```
pytest tests/test_catalog.py -x -q                       26 passed
python -c "from photoconsole.catalog import MediaFile..."  columns OK
python -c "...path UNIQUE/indexed, hash indexed"          PASS
python -c "...WAL mode, busy_timeout>=5000, media_files"  PASS
python -c "from photoconsole.catalog import should_skip"  PASS
```

---

## TDD Gate Compliance

| Phase | Task 1 | Task 2 |
|-------|--------|--------|
| RED   | 660fefc (test(01-02): MediaFile model, engine factory, upsert/skip) | (same commit — both tasks' tests shipped together) |
| GREEN | d078929 (feat(01-02): catalog models, DB factory, upsert/skip) | d078929 |

---

## Deviations from Plan

None — plan executed exactly as written.

The catalog implementation files were committed in the same commit (`d078929`) that bundled the plan 01-04 RED test file (`tests/test_scanner.py`). This is a pre-existing commit grouping from the prior session — all plan 01-02 implementation code is present and correct, all 26 tests pass, and all acceptance criteria are satisfied.

---

## Known Stubs

None — all columns are wired, all public functions are implemented and return meaningful values.

The `in_memory_engine` fixture in `tests/conftest.py` still returns `None` (stub from Plan 01). The plan 01-02 tests define their own `_make_in_memory_engine()` helper function directly in `test_catalog.py` and do not depend on the conftest fixture.

---

## Threat Surface Scan

All threats from plan's threat_model mitigated:

| Threat | File | Status |
|--------|------|--------|
| T-02-01: unknown keys in upsert_media_file | photoconsole/catalog/db.py | Mitigated — `_VALID_COLUMNS` frozenset validated at call time; ValueError raised with offending key(s) listed |
| T-02-02: concurrent writers from threaded scan | photoconsole/catalog/db.py | Mitigated — WAL mode + busy_timeout=5000 set per-connection via event listener |
| T-02-03: catalog DB readable by other local users | (OS-managed) | Accepted — local-first per NFR2; OS permissions apply |
| T-02-04: SQL injection via record values | photoconsole/catalog/db.py | Mitigated — all queries via SQLAlchemy parameterized statements; no string interpolation in SQL |
| T-02-SC: SQLAlchemy supply chain | photoconsole/catalog/db.py | Pre-cleared — slopcheck [OK] in RESEARCH.md |

No new threat surface introduced beyond plan's threat_model.

---

## Self-Check: PASSED

Files created:
- FOUND: photoconsole/catalog/__init__.py
- FOUND: photoconsole/catalog/models.py
- FOUND: photoconsole/catalog/db.py

Commits verified:
- FOUND: 660fefc (test RED — MediaFile model, engine factory, upsert/skip)
- FOUND: d078929 (feat GREEN — catalog models, DB factory, upsert/skip logic)

Test results: 26/26 passing
