---
phase: 3
slug: visual-clustering-ai-integration
status: draft
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
| 03-01-01 | 01 | 1 | NFR1/NFR2 | T-03-01 | ClusterConfig rejects eps=5.0; QualityWeightsConfig rejects sum≠1.0 | unit | `pytest tests/test_config_phase3.py -v` | ❌ W0 | ⬜ pending |
| 03-02-01 | 02 | 1 | NFR1 | T-03-02 | schema migration adds all 9 columns idempotently; upsert partial update works | unit | `pytest tests/test_catalog_phase3.py -v` | ❌ W0 | ⬜ pending |
| 03-03-01 | 03 | 2 | NFR2 | — | blur_score ordering sharp>blurry; quality_score 0–100; EXIF bonus applied | unit | `pytest tests/test_quality.py -v` | ❌ W0 | ⬜ pending |
| 03-04-01 | 04 | 2 | NFR2 | — | pHash Hamming≤10 for near-dups; embed_images() deterministic; DBSCAN groups known-similar | unit | `pytest tests/test_clustering.py -v` | ❌ W0 | ⬜ pending |
| 03-05-01 | 05 | 3 | FR5 | — | cluster command incremental skip; manifest CSV columns correct | integration | `pytest tests/test_cli_phase3.py::test_cluster_skips_cached tests/test_clustering.py::test_write_cluster_manifest -v` | ❌ W0 | ⬜ pending |
| 03-06-01 | 06 | 3 | FR5/NFR1 | — | review-clusters keeper persisted; redundant flagged; os.startfile fallback | integration | `pytest tests/test_cli_phase3.py::test_review_keeper_persisted -v` | ❌ W0 | ⬜ pending |
| 03-07-01 | 07 | 4 | FR6 | — | burst recall≥90%; cluster purity≥90%; keeper accuracy≥80%; cluster size≤50 | critical | `pytest tests/test_eval_clustering.py -m critical -v` | ❌ W0 | ⬜ pending |

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
