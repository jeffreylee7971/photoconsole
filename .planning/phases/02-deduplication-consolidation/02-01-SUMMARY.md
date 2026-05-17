---
phase: 02-deduplication-consolidation
plan: "01"
subsystem: config
tags: [config, dataclass, consolidation, yaml-parsing]
dependency_graph:
  requires: []
  provides: [ConsolidationConfig, Config.consolidation, load_config-consolidation]
  affects: [photoconsole/consolidator.py, photoconsole/dedup.py, photoconsole/cli.py]
tech_stack:
  added: []
  patterns: [dataclass-default-factory, abspath-expanduser-normalization, hashing-section-pattern]
key_files:
  created: []
  modified:
    - photoconsole/config.py
    - tests/test_config.py
decisions:
  - "ConsolidationConfig placed immediately before Config dataclass in config.py for locality"
  - "Empty destination_path stays '' — abspath('') resolves to cwd which would be wrong"
  - "source_priority coerced to list() at parse time so callers always get a mutable list"
metrics:
  duration_seconds: 148
  completed_date: "2026-05-17T00:05:15Z"
  tasks_completed: 2
  files_modified: 2
---

# Phase 02 Plan 01: Config Extension for Consolidation — Summary

ConsolidationConfig dataclass added to photoconsole/config.py with typed fields for destination_path and source_priority; load_config() extended to parse the `consolidation:` YAML section with abspath+expanduser normalization, providing a validated ConsolidationConfig on every Config instance.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| RED  | Failing tests for ConsolidationConfig + load_config consolidation parsing | 59a3c49 | tests/test_config.py |
| GREEN | ConsolidationConfig dataclass + Config.consolidation field + load_config extension | e47dbab | photoconsole/config.py, tests/test_config.py |

## What Was Built

### ConsolidationConfig dataclass (Task 1)

Added `ConsolidationConfig` immediately before `Config` in `photoconsole/config.py`:

- `destination_path: str = ''` — target directory for consolidated library; empty string means not configured
- `source_priority: list[str] = field(default_factory=list)` — ordered source names for tie-breaking

Added `consolidation: ConsolidationConfig = field(default_factory=ConsolidationConfig)` to `Config`, with no changes to existing fields or function signatures.

### load_config() extension (Task 2)

After the `hashing_section` block, added a `consolidation_section` block following the identical pattern:

```python
consolidation_section = raw.get('consolidation', {}) or {}
destination_path_raw = consolidation_section.get('destination_path', '')
if destination_path_raw:
    destination_path = os.path.abspath(os.path.expanduser(str(destination_path_raw)))
else:
    destination_path = ''
source_priority: list[str] = list(consolidation_section.get('source_priority', []))
```

The `Config(...)` constructor call was updated to pass `consolidation=consolidation`.

## Verification Results

- `pytest tests/test_config.py -x -q` — 40 tests pass (24 original + 16 new)
- Manual verification: `python -c "from photoconsole.config import Config, ConsolidationConfig, load_config; ..."` — OK
- Threat model T-02-01: `destination_path` path traversal mitigated via `abspath+expanduser` (same pattern as `catalog_path`)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed YAML test helper using f-string interpolation with textwrap.dedent**

- **Found during:** GREEN phase test run
- **Issue:** The `_minimal_yaml(extra)` test helper used `textwrap.dedent(f"... {extra}")` where `extra` contained multiline strings. `textwrap.dedent` strips the consistent indentation from the template but the embedded `extra` lines lost their indentation, producing invalid YAML (ParserError).
- **Fix:** Rewrote `TestLoadConfigConsolidation` tests to use explicit `yaml_text = """..."""` blocks instead of a shared helper with f-string interpolation. Each test has its own complete YAML string.
- **Files modified:** `tests/test_config.py`
- **Commit:** e47dbab (included with GREEN phase as part of the same logical fix)

## Known Stubs

None — all fields wire directly to the Config object returned to callers.

## Threat Flags

None — no new network endpoints, auth paths, file access patterns, or schema changes. The `destination_path` path normalization follows the existing `catalog_path` pattern (T-01-02/T-02-01).

## Self-Check: PASSED

| Check | Result |
|-------|--------|
| photoconsole/config.py exists | FOUND |
| tests/test_config.py exists | FOUND |
| 02-01-SUMMARY.md exists | FOUND |
| Commit 59a3c49 (RED) exists | FOUND |
| Commit e47dbab (GREEN) exists | FOUND |
| `class ConsolidationConfig` in config.py | FOUND |
| `consolidation_section = raw.get(...)` in config.py | FOUND |
| `consolidation: ConsolidationConfig` field in Config | FOUND |
| pytest tests/test_config.py -x -q | 40 passed |
