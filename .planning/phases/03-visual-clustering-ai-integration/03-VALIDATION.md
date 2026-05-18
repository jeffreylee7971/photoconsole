---
phase: 3
slug: visual-clustering-ai-integration
status: ready
nyquist_compliant: true
wave_0_complete: true
created: 2026-05-17
---

# Phase 3 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.3 |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` |
| **Quick run command** | `pytest tests/test_quality.py tests/test_config_phase3.py -v --timeout=30` |
| **Full suite command** | `pytest tests/ -v -m "not slow"` |
| **Eval dimensions command** | `pytest tests/test_eval_clustering.py -m critical -v` |
| **Estimated runtime (quick)** | ~30 seconds |
| **Estimated runtime (full)** | ~2–5 minutes |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/test_quality.py tests/test_config_phase3.py -v --timeout=30`
- **After every plan wave:** Run `pytest tests/ -v -m "not slow"`
- **Before `/gsd:verify-work`:** Full suite (`pytest tests/ -v`) must be green
- **Max feedback latency:** 30 seconds (quick run)

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 03-01-01 | 01 | 1 | NFR2/FR6 | T-03-SC | all 6 Phase 3 runtime packages + rich in pyproject.toml deps; `critical`/`slow` markers registered; conftest helpers produce blur_score >10k (sharp) <50 (blurry) Hamming≤10 (near-dup) | unit | `python -c "import tomllib; d=tomllib.loads(open('pyproject.toml','rb').read().decode()); deps=d['project']['dependencies']; assert any('open-clip-torch' in x for x in deps); marks=d['tool']['pytest']['ini_options']['markers']; assert any('critical' in m for m in marks); print('OK')"` | modifies existing files | ⬜ pending |
| 03-02-01 | 02 | 2 | NFR1 | T-03-02 | schema migration adds all 9 columns idempotently; upsert partial update works | unit | `pytest tests/test_catalog_phase3.py -v` | ❌ W0 | ⬜ pending |
| 03-03-01 | 03 | 2 | NFR1/NFR2 | T-03-01 | ClusterConfig rejects eps=5.0; QualityWeightsConfig rejects sum≠1.0; load_config parses cluster:/quality_weights: YAML | unit | `pytest tests/test_config_phase3.py -v` | ❌ W0 | ⬜ pending |
| 03-04-01 | 04 | 3 | NFR2 | — | blur_score ordering sharp>blurry; quality_score 0–100; EXIF bonus applied | unit | `pytest tests/test_quality.py -v` | ❌ W0 | ⬜ pending |
| 03-05-01 | 05 | 3 | NFR2/FR6 | — | pHash Hamming≤10 for near-dups; embed_images() deterministic; DBSCAN groups known-similar; BLOB round-trip intact | unit | `pytest tests/test_clustering.py -v` | ❌ W0 | ⬜ pending |
| 03-06-01 | 06 | 4 | FR5/NFR1 | — | cluster command incremental skip; review-clusters keeper persisted; redundant flagged; manifest CSV columns correct; os.startfile fallback | integration | `pytest tests/test_cli_phase3.py::test_cluster_skips_cached tests/test_cli_phase3.py::test_review_keeper_persisted -v` | ❌ W0 | ⬜ pending |
| 03-07-01 | 07 | 5 | FR6 | — | burst recall≥90%; cluster purity≥90%; keeper accuracy≥80%; cluster size≤50 | critical | `pytest tests/test_eval_clustering.py -m critical -v` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

> **Note — Inline-TDD structure:** This phase uses an inline-TDD pattern where each plan
> creates both implementation and tests together in the same wave. There is no separate
> Wave 0 stub step. Tests are written alongside (or immediately after) their implementation
> within each plan's tasks, so every task's `<verify>` block has a concrete automated
> command from the moment the plan executes. The `nyquist_compliant: true` and
> `wave_0_complete: true` flags reflect this — test files are created as part of their
> respective plans (Plans 01–07), not as a pre-execution stub wave.
>
> Plans that create test files: 01 (conftest + pyproject markers), 02 (test_catalog_phase3),
> 03 (test_quality), 04 (test_config_phase3), 05 (test_clustering), 06 (test_cli_phase3),
> 07 (test_eval_clustering).

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Windows Photos opens for top 2–3 cluster candidates | D-13 | os.startfile() is non-blocking; cannot assert viewer opened in automated test | Run `photoconsole review-clusters` on a real catalog with clustered images; verify Windows Photos opens |
| Rich review table is visually readable | D-12 | Terminal rendering not assertable in CI | Run `photoconsole review-clusters` on a 5-cluster catalog; verify table columns visible and truncated paths readable |
| Deletion .bat file runs correctly on Windows | D-16 | BAT execution requires interactive confirmation | Open cluster_manifest.bat in notepad; verify `del /f` lines are correct; run on a test file |
| CLIP model downloads on first run | AI-SPEC §6 | Requires network; cannot run in offline CI | Run `photoconsole cluster` with empty cache; verify ~350 MB download completes and model loads |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify — inline-TDD pattern; tests created in same plan as implementation
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 coverage: handled via inline-TDD (see Wave 0 Requirements note above)
- [x] No watch-mode flags
- [x] Feedback latency < 30s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved (inline-TDD structure confirmed)

## Validation Audit 2026-05-17
| Metric | Count |
|--------|-------|
| Documentation gaps found | 4 |
| Resolved | 4 |
| Escalated to manual-only | 0 |

Fixes applied: wave numbers corrected (Plans 02→wave 2, 04→wave 3, 06→wave 4, 07→wave 5); Plan 01 row updated to describe actual behavior (deps + conftest infra) with correct verify command; status updated to `ready`; test descriptions realigned to their correct plans.
