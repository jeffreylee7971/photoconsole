# PhotoConsole Roadmap

## Overview

PhotoConsole is built in iterative phases, starting with a minimal MVP (Phases 1–2) and expanding to advanced features (Phases 3+).

---

## Phase 1: Scanning & Cataloging Foundation

**Goal**: Scan multiple sources and build a catalog of all media files.

**Requirements**: [FR1, FR2, FR5, FR6]

**Features**:
- Local filesystem scanning (recursive, configurable paths)
- Rclone mount integration (auto-detect configured remotes)
- File cataloging with metadata (hash, size, dates, source)
- SQLite database schema for efficient queries
- CLI: `photoconsole scan --config config.yaml`

**Deliverables**:
- Core scanning module (`scanner.py`)
- Catalog database schema and ORM layer
- Rclone wrapper module
- Config format documentation
- Basic CLI with progress reporting

**Success Criteria**:
- ✅ Scan + hash 10K local files in < 15 minutes; rclone sources dependent on network speed
- ✅ Parallel hashing uses multiple CPU cores (no single-threaded bottleneck)
- ✅ Accurately capture file metadata
- ✅ Detect and skip non-image/video files
- ✅ Handle rclone mount paths without errors

**Estimated Effort**: 2–3 weeks

**Plans**: 5 plans across 3 waves

Plans:
- [x] 01-01-PLAN.md — Package skeleton, errors enum, config dataclass + YAML loader, test fixtures (Wave 1) — DONE ec647f9
- [x] 01-02-PLAN.md — Catalog persistence: SQLAlchemy MediaFile model, WAL engine, UPSERT + incremental skip (Wave 2)
- [x] 01-03-PLAN.md — Hashing + photo EXIF + video ffprobe metadata extractors, ThreadPoolExecutor orchestration (Wave 2)
- [x] 01-04-PLAN.md — LocalScanner + RcloneScanner with symlink skip and subprocess rclone integration (Wave 2)
- [x] 01-05-PLAN.md — CLI: click group, scan command, dependency gates, end-to-end writer-thread orchestration (Wave 3) — DONE 13f9c30

---

## Phase 2: Deduplication & Consolidation

**Goal**: Identify duplicates and consolidate media into a single master library.

**Requirements**: [FR3, FR4, FR5, NFR1, NFR4]

**Features**:
- Exact duplicate detection (SHA256 hash comparison)
- Duplicate reporting (groups, size, sources)
- Safe consolidation planning with dry-run mode
- Date-based organization for consolidated library
- Confirmation workflow before destructive operations
- Audit logging for all consolidation actions

**Deliverables**:
- Deduplication module (`dedup.py`)
- Consolidation planner (`consolidator.py`)
- Report generation (CSV, JSON, text)
- Extended CLI commands (`report`, `plan-consolidation`, `consolidate`)
- Consolidation log and rollback info

**Success Criteria**:
- ✅ Accurately identify 99%+ of exact duplicates
- ✅ Consolidate 10K files without conflicts
- ✅ Dry-run produces identical results to actual run
- ✅ All operations logged and auditable
- ✅ No data loss in consolidation

**Estimated Effort**: 2–3 weeks

**Plans**: 7 plans across 6 waves

Plans:
- [x] 02-01-PLAN.md — ConsolidationConfig dataclass + load_config extension for consolidation YAML section (Wave 1) — DONE e47dbab
- [x] 02-02-PLAN.md — dedup.py: DuplicateGroup dataclass, classify_group(), find_duplicate_groups() (Wave 2) — DONE 150e604
- [x] 02-03-PLAN.md — consolidator.py part 1: compute_dest_path, resolve_conflict, copy_and_verify pure functions (Wave 3) — DONE 7681824
- [x] 02-04-PLAN.md — consolidator.py part 2: write_manifest, setup_consolidation_logger, check_destination_writable, run_consolidation orchestrator (Wave 4) — DONE 6de6003
- [x] 02-05-PLAN.md — CLI extension: _run_report, report command, _run_consolidate, plan-consolidation, consolidate commands (Wave 5) — DONE 966eede
- [x] 02-06-PLAN.md — Unit tests: test_dedup.py (8 tests) + test_consolidator.py (64 tests), 258 total pass (Wave 5) — DONE 6200141
- [x] 02-07-PLAN.md — CLI integration tests: test_cli_phase2.py — 30 CliRunner tests covering report/plan-consolidation/consolidate (Wave 6) — DONE 1ca221e

---

## Phase 3: Visual Clustering & AI Integration

**Goal**: Help users rank and identify similar photos beyond exact duplicates.

**Features**:
- Visual similarity detection (image embeddings or perceptual hashing)
- Clustering similar photos (user-configurable threshold)
- Ranking clusters by quality (resolution, blur, faces detected)
- Interactive UI for manual review of similar groups
- Integration with clustering in consolidation workflow

**Deliverables**:
- Clustering module (`clustering.py`)
- Quality ranking heuristics
- Interactive review interface
- Updated consolidation planner with clustering options

**Success Criteria**:
- ✅ Cluster visually similar photos with > 90% precision
- ✅ Rank clusters by quality heuristics
- ✅ Handle clustering for 100K items in reasonable time

**Estimated Effort**: 3–4 weeks

**Plans**: 7 plans across 5 waves

Plans:

**Wave 1** (foundation)
- [ ] 03-01-PLAN.md — pyproject.toml deps + pytest markers + conftest fixture helpers (Wave 1)

**Wave 2** *(blocked on Wave 1 completion)*
- [ ] 03-02-PLAN.md — MediaFile 9 new columns + _ensure_phase3_columns migration + test_catalog_phase3.py (Wave 2)
- [ ] 03-03-PLAN.md — ClusterConfig + QualityWeightsConfig (Pydantic v2) + load_config extension + test_config_phase3.py (Wave 2)

**Wave 3** *(blocked on Wave 2 completion)*
- [ ] 03-04-PLAN.md — quality.py (blur, faces, dimensions, normalization, EXIF bonus) + test_quality.py (Wave 3)
- [ ] 03-05-PLAN.md — clustering.py (CLIP, pHash, DBSCAN dense+sparse, ClusterGroup, write_cluster_manifest) + test_clustering.py (Wave 3)

**Wave 4** *(blocked on Wave 3 completion)*
- [ ] 03-06-PLAN.md — cli.py cluster + review-clusters commands + test_cli_phase3.py integration (Wave 4)

**Wave 5** *(blocked on Wave 4 completion)*
- [ ] 03-07-PLAN.md — test_eval_clustering.py critical eval dimensions (cluster purity, burst recall, keeper accuracy, EXIF ranking, size distribution, throughput) (Wave 5)

Cross-cutting constraints:
- Worker threads return result dicts only; main thread owns all session.commit() calls (T-02-02)
- CLIP model loaded once before batch loop — never per-batch or per-file
- All quality scores and embeddings are incremental (skip files with existing non-NULL values)

---

## Phase 4: Immich & PhotoPrism Integration

**Goal**: Read/write operations with Immich and PhotoPrism libraries.

**Features**:
- Immich API integration (catalog import, album organization)
- PhotoPrism integration (catalog import, collection sync)
- Two-way sync capabilities
- Unified asset management across multiple systems

**Deliverables**:
- Immich client module (`immich_client.py`)
- PhotoPrism client module (`photoprism_client.py`)
- Unified asset abstraction layer
- Configuration for multiple target systems

**Success Criteria**:
- ✅ Import Immich/PhotoPrism assets into PhotoConsole catalog
- ✅ Write consolidated assets back to target systems
- ✅ Sync metadata and dedup results

**Estimated Effort**: 3–4 weeks

**Status**: ⏳ Deferred

---

## Phase 5: Web UI & Advanced Features

**Goal**: Build a web interface and advanced management features.

**Features**:
- Web dashboard for browsing and managing media
- Interactive duplicate review and approval
- Detailed filtering and search
- Admin panel for configuration and monitoring
- Export and backup workflows

**Deliverables**:
- FastAPI or Flask backend
- React/Vue frontend
- Database migration support
- Docker containerization

**Success Criteria**:
- ✅ Browse catalog with filters
- ✅ Review and approve duplicates in web UI
- ✅ Manage consolidation workflows visually

**Estimated Effort**: 4–6 weeks

**Status**: ⏳ Deferred

---

## Milestones

| Milestone | Target Phase(s) | Description |
|-----------|------------------|-------------|
| **MVP Alpha** | Phase 1–2 | Functional scanning, deduplication, and safe consolidation |
| **MVP Stable** | Phase 1–2 | Performance tuning, error handling, documentation |
| **AI Ready** | Phase 3 | Visual clustering and ranking integrated |
| **Platform Ready** | Phase 4 | Immich/PhotoPrism integration validated |
| **Web UI Launch** | Phase 5 | Full-featured web dashboard |

---

## Decision Log

### Deferred Visual Clustering to Phase 3
**Rationale**: Start with exact deduplication to validate core scanning + consolidation workflow. Visual clustering adds complexity (ML model selection, performance tuning, UX design). Better to ship working MVP first, then add clustering based on user feedback.

### Local/Rclone Only for MVP
**Rationale**: Immich/PhotoPrism are valuable but optional. Core value is safe consolidation and dedup. By deferring integrations, we reduce MVP scope and can validate core tool first.

### CLI-First, Web UI in Phase 5
**Rationale**: CLI is faster to build, more testable, and sufficient for power users. Web UI adds UX/frontend complexity. Defer to Phase 5 once core tool is proven.

---

**Created**: 2026-05-16
