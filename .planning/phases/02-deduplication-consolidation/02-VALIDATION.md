---
phase: 2
slug: 02-deduplication-consolidation
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-16
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.3 |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` |
| **Quick run command** | `pytest tests/test_dedup.py tests/test_consolidator.py -x -q` |
| **Full suite command** | `pytest tests/ -q` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/test_dedup.py tests/test_consolidator.py -x -q`
- **After every plan wave:** Run `pytest tests/ -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** ~15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|----------|-----------|-------------------|-------------|--------|
| 02-01-01 | 01 | 1 | FR5 | ConsolidationConfig dataclass parses YAML consolidation section | unit | `python -c "from photoconsole.config import ConsolidationConfig; print('OK')"` | ❌ W0 | ⬜ pending |
| 02-01-02 | 01 | 1 | FR5 | load_config returns Config with consolidation.destination_path and source_priority | unit | `pytest tests/test_config.py -x -q` | ❌ W0 | ⬜ pending |
| 02-02-01 | 02 | 2 | FR3 | find_duplicate_groups returns correct DuplicateGroup list | unit | `pytest tests/test_dedup.py::test_find_duplicates -x` | ❌ W0 | ⬜ pending |
| 02-02-02 | 02 | 2 | FR3 | classify_group elects D: source as canonical (D-01) and sets needs_copy correctly | unit | `pytest tests/test_dedup.py::test_classify_group_d_wins -x` | ❌ W0 | ⬜ pending |
| 02-03-01 | 03 | 3 | FR4 | compute_dest_path returns YYYY/MM/filename from date_taken; falls back to unknown/YYYY/MM from mtime | unit | `pytest tests/test_consolidator.py::test_dest_path_with_date tests/test_consolidator.py::test_dest_path_mtime_fallback -x` | ❌ W0 | ⬜ pending |
| 02-03-02 | 03 | 3 | FR4 | resolve_conflict renames on hash collision; returns None for same-hash (idempotent) | unit | `pytest tests/test_consolidator.py::test_conflict_rename tests/test_consolidator.py::test_conflict_idempotent -x` | ❌ W0 | ⬜ pending |
| 02-03-02b | 03 | 3 | FR4, NFR1 | copy_and_verify copies file and verifies hash; removes corrupt copy on mismatch | unit | `pytest tests/test_consolidator.py::test_copy_and_verify tests/test_consolidator.py::test_copy_hash_mismatch -x` | ❌ W0 | ⬜ pending |
| 02-04-01 | 04 | 4 | FR4, NFR1 | write_manifest produces CSV (D-11) and .bat (D-12) with rclone routing (Pitfall 6) | unit | `pytest tests/test_consolidator.py::test_write_manifest tests/test_consolidator.py::test_bat_quoted_paths -x` | ❌ W0 | ⬜ pending |
| 02-04-02 | 04 | 4 | FR4, NFR1 | run_consolidation dry_run=True returns plan without I/O; live run copies file and logs | unit | `pytest tests/test_consolidator.py::test_dry_run_no_io tests/test_consolidator.py::test_log_append -x` | ❌ W0 | ⬜ pending |
| 02-05-01 | 05 | 5 | FR3, FR5 | `photoconsole report` outputs hash/count/total_size/sources/date_range in text and JSON | integration | `pytest tests/test_cli_phase2.py::test_report_text tests/test_cli_phase2.py::test_report_json -x` | ❌ W0 | ⬜ pending |
| 02-05-02 | 05 | 5 | FR4, FR5 | `plan-consolidation` exits 0 and prints plan; `consolidate --dry-run` writes no files | integration | `pytest tests/test_cli_phase2.py::test_plan_consolidation tests/test_cli_phase2.py::test_consolidate_dry_run -x` | ❌ W0 | ⬜ pending |
| 02-06-01 | 06 | 5 | NFR4 | Unit tests for dedup.py cover all FR3 acceptance criteria without real filesystem | unit | `pytest tests/test_dedup.py -q` | ❌ W0 | ⬜ pending |
| 02-06-02 | 06 | 5 | NFR4 | Unit tests for consolidator.py cover all FR4 acceptance criteria using tmp_path fixtures | unit | `pytest tests/test_consolidator.py -q` | ❌ W0 | ⬜ pending |
| 02-07-01 | 07 | 6 | FR3, FR4, FR5 | CLI integration: report, plan-consolidation, consolidate, idempotent re-run all pass | integration | `pytest tests/test_cli_phase2.py -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_dedup.py` — stubs/tests for FR3: find_duplicate_groups, classify_group
- [ ] `tests/test_consolidator.py` — stubs/tests for FR4: compute_dest_path, resolve_conflict, copy_and_verify, write_manifest, run_consolidation
- [ ] `tests/test_cli_phase2.py` — integration tests for FR5 new CLI commands
- [ ] In-memory SQLite fixtures (extend existing conftest.py patterns from test_catalog.py)

*All test files are Wave 0 gaps — no existing tests cover Phase 2 behaviors.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Windows .bat runs correctly on cmd.exe with accented filenames | D-12, Pitfall 2 | Requires real Windows cmd.exe execution | Generate manifest via test, open cmd.exe, run the .bat, verify files deleted |
| rclone source paths produce correct `:: rclone deletefile` comments | Pitfall 6 | Requires rclone remote configured | Seed a rclone source in catalog, run consolidate, inspect generated .bat |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
