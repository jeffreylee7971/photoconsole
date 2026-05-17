# Phase 3: Visual Clustering & AI Integration - Research

**Researched:** 2026-05-17
**Domain:** CV/ML pipeline integration into existing Python CLI (SQLAlchemy + Click + Rich)
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Similarity Method**
- D-01: Two-pass: pHash (imagehash) pre-filter -> CLIP semantic grouping
- D-02: CLIP embeddings stored as SQLite BLOB on MediaFile (catalog-first)
- D-03: Embedding is incremental (skip files with cached embedding)
- D-04: Separate CLI command `photoconsole cluster [--threshold FLOAT]`; does not auto-run during scan
- D-05: Only clusters with 2+ similar photos are reported

**Catalog Schema Extensions**
- D-06: New columns on MediaFile: cluster_id (Integer), cluster_keeper (Boolean), cluster_redundant (Boolean), blur_score (Float), pixel_width (Integer), pixel_height (Integer), face_count (Integer)
- D-07: All quality scores incremental (only files with NULL values processed per run)

**Quality Ranking**
- D-08: Four signals: sharpness 45%, resolution 30%, faces 15%, EXIF completeness 10%
- D-09: Weights configurable in config.yaml under `quality_weights:` section
- D-10: Signals normalized to [0,1] before weighting; score multiplied by 100
- D-11: Component scores shown in review table (not just combined score)

**Review Interface**
- D-12: `photoconsole review-clusters` using Rich tables
- D-13: Auto-open top 2-3 candidates in Windows default viewer (os.startfile())
- D-14: Prompt per cluster: confirm auto-pick, override, or skip
- D-15: On confirmation: cluster_keeper=True for chosen, cluster_redundant=True for rest (persisted in catalog)
- D-16: Deletion manifest (CSV + .bat) after review -- same pattern as Phase 2

**LLaVA / AI Scope**
- D-17: LLaVA NOT in Phase 3; only imagehash, OpenCLIP, OpenCV

### Claude's Discretion
- CLIP model size/variant (ViT-B/32 recommended, OpenCLIP)
- Clustering algorithm (DBSCAN recommended)
- pHash threshold (default Hamming <= 10)
- Normalization formula for quality signals (min-max or percentile)
- SQLite schema migration approach

### Deferred Ideas (OUT OF SCOPE)
- LLaVA integration (Phase 4+)
- Video quality ranking
- Web UI for cluster review
- User-adjustable weights at review time
</user_constraints>

---

> **IMPORTANT NOTE ON AI-SPEC:** The 03-AI-SPEC.md file already covers framework selection,
> CLIP/DBSCAN/OpenCV/imagehash implementation patterns, Pydantic config validation, batch
> processing, evaluation strategy, guardrails, and monitoring schema in full detail. This
> research document does NOT repeat that material. It focuses exclusively on the 10 gaps
> identified as unanswered in the brief, plus codebase integration patterns discovered by
> reading the existing source.
>
> Planner: read 03-AI-SPEC.md for implementation code examples, package install commands,
> and evaluation test structure. Read this document for schema migration, manifest format,
> session state, test fixtures, and Windows-specific behaviors.

---

## Summary

Phase 3 integrates a CV/ML pipeline (OpenCLIP + DBSCAN + OpenCV + imagehash) into the
existing Python 3.12+ CLI project. The dominant integration work is: (1) schema migration
for 8 new columns, (2) new modules `clustering.py` and `quality.py` following established
patterns, (3) two new CLI subcommands, and (4) a cluster-specific deletion manifest.

The most critical findings from codebase investigation:

**SQLAlchemy `create_all()` does NOT add missing columns.** This is verified. The existing
`create_catalog_engine()` calls `Base.metadata.create_all(engine)` which creates missing
tables but ignores missing columns on existing tables. Phase 3 must extend
`create_catalog_engine()` with an explicit idempotent migration block using `ALTER TABLE ...
ADD COLUMN` checked against `PRAGMA table_info`. This is the single most important
architectural decision for the schema extension.

**The existing `upsert_media_file()` supports partial column updates.** Its SET clause is
built dynamically from the record dict keys (excluding `path` and `id`). Passing
`{'path': p, 'blur_score': 500.0, 'pixel_width': 4032}` only updates those three columns.
This means quality score writes, embedding writes, and cluster assignment writes can all
reuse `upsert_media_file()` without a separate update path.

**The manifest format for Phase 3 differs from Phase 2.** Phase 2's `write_manifest()`
uses columns `[original_path, hash, destination_path, source_name]`. Phase 3 redundants
have no destination path (no copy is made). The manifest needs `cluster_id` and
`quality_score` instead. A new `write_cluster_manifest()` function is required.

**Primary recommendation:** Follow the `_run_scan` / `_run_report` pure-helper pattern
strictly. `_run_cluster()` and `_run_review()` are pure helpers (no click dependency),
tested directly. Click wrappers are thin. All DB writes on main thread. Worker threads
return result dicts only.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| CLIP embedding computation | CLI process (CPU batch) | -- | CPU-bound; single process; no web tier |
| pHash computation | CLI process (CPU parallel) | -- | Embarrassingly parallel; ThreadPoolExecutor |
| Quality score computation (blur/faces) | CLI process (CPU parallel) | -- | Per-file cv2 ops; follow hasher.py pattern |
| DBSCAN clustering | CLI process (in-memory) | -- | Needs full embedding matrix; main thread |
| Sparse clustering (>50K) | CLI process (in-memory) | -- | NearestNeighbors radius graph; main thread |
| Catalog reads/writes | SQLite (main thread only) | -- | Single-writer pattern; no ORM on workers |
| Embedding storage | SQLite BLOB on MediaFile | -- | D-02; catalog-first; 2KB/file at 512-dim |
| pHash storage | SQLite TEXT on MediaFile | -- | Incremental; avoids recompute on each run |
| Quality score storage | SQLite REAL/INT on MediaFile | -- | D-06/D-07; incremental; nullable |
| Cluster assignment | SQLite INTEGER on MediaFile | -- | D-06; written by cluster command only |
| Review session state | SQLite (cluster_keeper col) | -- | NULL=pending; not-NULL=reviewed |
| Terminal review UI | Rich Console/Table/Prompt | -- | D-12; CLI tier; no web |
| File opening for comparison | os.startfile() (Windows) | -- | D-13; non-blocking; graceful fallback |
| Deletion manifest | CSV + .bat on filesystem | -- | D-16; follows Phase 2 pattern |
| Run metrics | SQLite cluster_runs table | -- | AI-SPEC Section 7; no external service |

---

## Standard Stack

### Core (locked in AI-SPEC -- do not re-research)

> See AI-SPEC.md Section 2 and Section 3 for full rationale and install instructions.

| Library | Version (verified) | Purpose | Source |
|---------|-------------------|---------|--------|
| open-clip-torch | 3.3.0 [VERIFIED: npm registry] | CLIP embeddings (ViT-B-32) | PyPI registry |
| imagehash | 4.3.2 [VERIFIED: npm registry] | pHash perceptual hashing | PyPI registry |
| scikit-learn | 1.8.0 [VERIFIED: npm registry] | DBSCAN + NearestNeighbors | PyPI registry |
| opencv-python-headless | 4.13.0.92 [VERIFIED: npm registry] | Laplacian blur + Haar cascade | PyPI registry |
| scipy | 1.17.1 [VERIFIED: npm registry] | Sparse distance matrix | PyPI registry |
| pydantic | 2.13.4 [VERIFIED: npm registry] | ClusterConfig + QualityWeightsConfig | PyPI registry |

### Supporting

| Library | Version (verified) | Purpose | When to Use |
|---------|-------------------|---------|-------------|
| pytest-benchmark | 5.2.3 [VERIFIED: npm registry] | Throughput timing tests | Dev only; slow mark |
| rich | 15.0.0 (already installed) | Terminal UI, tables, progress | Phase 3 review UI |
| tqdm | 4.67.3 (already installed) | Scan progress (existing commands) | Do not use in Phase 3 commands |
| numpy | 2.4.5 (transitive) | Embedding arrays, fixture generation | Via imagehash/sklearn dep |

### Version Notes

- `open-clip-torch` 3.3.0 is the current release. AI-SPEC references 2.24.0 which was
  current at spec-writing time. Both versions support ViT-B-32 with `laion2b_s34b_b79k`
  weights. [VERIFIED: PyPI registry, confirmed `ViT-B-32` + `laion2b_s34b_b79k` in
  `open_clip.list_pretrained()` output on 3.3.0]
- All packages install and import correctly on Python 3.14 (Windows). The project targets
  Python >=3.12 per pyproject.toml; all packages provide cp314 or abi3 wheels. [VERIFIED:
  installed and imported successfully in research session]
- `torch` 2.12.0+cpu installs as a transitive dependency of open-clip-torch. Do NOT pin
  torch directly in pyproject.toml; let open-clip-torch resolve the correct version.
  `cuda_available()` returns False on this Windows machine (expected for AMD RDNA 2).
  [VERIFIED: torch.cuda.is_available() == False confirmed]

### pyproject.toml Changes Required

Add to `[project.dependencies]`:
```toml
"open-clip-torch>=3.3.0,<4",
"imagehash>=4.3.1,<5",
"scikit-learn>=1.4,<2",
"opencv-python-headless>=4.9,<5",
"pydantic>=2.0,<3",
"scipy>=1.11,<2",
```

Add to `[project.optional-dependencies]` dev section:
```toml
"pytest-benchmark>=4.0,<6",
```

Add to `[tool.pytest.ini_options]`:
```toml
markers = [
    "critical: critical eval dimensions -- must pass before any merge",
    "slow: throughput benchmarks -- run manually, not in CI",
]
```

---

## Package Legitimacy Audit

> slopcheck 0.6.1 run on all Phase 3 packages. All 7 packages returned [OK].

| Package | Registry | slopcheck | Disposition |
|---------|----------|-----------|-------------|
| open-clip-torch | PyPI | [OK] | Approved |
| imagehash | PyPI | [OK] | Approved |
| scikit-learn | PyPI | [OK] | Approved |
| opencv-python-headless | PyPI | [OK] | Approved |
| pydantic | PyPI | [OK] | Approved |
| scipy | PyPI | [OK] | Approved |
| pytest-benchmark | PyPI | [OK] (no source repo linked -- noted by slopcheck, not flagged [SUS]) | Approved |

**Packages removed due to slopcheck [SLOP] verdict:** none

**Packages flagged as suspicious [SUS]:** none

*pytest-benchmark has no source repo link on PyPI but has 5+ years of history and
millions of downloads -- slopcheck rated [OK]. The "no source repo" note is cosmetic.*

---

## Architecture Patterns

### System Architecture Diagram

```
photoconsole cluster                    photoconsole review-clusters
         |                                         |
    load_config()                            load_config()
         |                                         |
    create_catalog_engine()              create_catalog_engine()
    [ALTER TABLE migration]                         |
         |                               query clusters with
    _run_cluster()                       cluster_id IS NOT NULL
         |                               AND cluster_keeper IS NULL
    +----+----+----+                              |
    |         |    |                     FOR EACH ClusterGroup:
    |    Pass 0: quality scores               |
    | ThreadPoolExecutor                 Rich Table display
    | _compute_quality() x N             (cluster_id, path, sharpness,
    | workers return dicts               resolution, faces, exif, combined)
    | main thread writes                          |
    |         |                          os.startfile(top 2-3 paths)
    |    Pass 1: pHash pre-filter        [non-blocking, OSError fallback]
    | ThreadPoolExecutor                          |
    | compute_phash() x N               click.prompt("keeper? [1]/2/3/s")
    | main thread: build pHash groups            |
    |         |                         upsert: cluster_keeper=True
    |    Pass 2: CLIP embeddings                 cluster_redundant=True
    | embed_images() batches                      |
    | model loaded once before loop     write_cluster_manifest()
    | main thread writes blobs          CSV + .bat
    |         |
    |    Pass 3: DBSCAN clustering
    | cluster_embeddings() or
    | cluster_embeddings_sparse()
    | (sparse if N > 50K)
    |         |
    | write cluster_id to catalog
    | write cluster_runs metrics row
    | Rich end-of-run summary table
    |
    return summary dict
```

### Recommended Project Structure

```
photoconsole/
├── clustering.py        # NEW: load_clip_model(), embed_images(), cluster_embeddings(),
│                        #      cluster_embeddings_sparse(), ClusterGroup dataclass,
│                        #      compute_phash(), build_phash_groups(),
│                        #      write_cluster_manifest()
├── quality.py           # NEW: compute_quality_scores(), _compute_quality() worker,
│                        #      normalize_scores(), compute_combined_score()
├── cli.py               # ADD: cluster + review-clusters subcommands
│                        #      _run_cluster() + _run_review() pure helpers
├── config.py            # EXTEND: ClusterConfig + QualityWeightsConfig (pydantic v2)
│                        #         Config dataclass gets cluster + quality_weights fields
├── catalog/
│   ├── models.py        # EXTEND: MediaFile + 8 new columns + embedding_blob + phash
│   └── db.py            # EXTEND: create_catalog_engine gets migration block
│                        #         _ensure_phase3_columns() helper
├── consolidator.py      # REFERENCE for write_cluster_manifest() BAT format
└── dedup.py             # REFERENCE for ClusterGroup dataclass pattern

tests/
├── test_clustering.py   # Unit: embed determinism, DBSCAN labels, pHash grouping
├── test_quality.py      # Unit: blur score on fixtures, face detection, EXIF bonus
├── test_cli_phase3.py   # Integration: cluster + review-clusters CLI commands
├── test_config_phase3.py # Unit: ClusterConfig/QualityWeightsConfig validation
├── test_eval_clustering.py # Eval: critical/slow marks; reference dataset
└── fixtures/
    ├── sharp.jpg         # High Laplacian variance (synthesized -- see below)
    ├── blurry.jpg        # Low Laplacian variance (synthesized)
    ├── sharp_no_exif.jpg # High blur, no EXIF date/GPS
    ├── soft_with_exif.jpg # Lower blur, full EXIF
    ├── solid_blue_sky.jpg # Hub image: uniform background
    └── eval/
        └── ground_truth.json
```

### Pattern 1: Schema Migration in create_catalog_engine()

**What:** Idempotent `ALTER TABLE ... ADD COLUMN` block in `create_catalog_engine()`.
Runs after `Base.metadata.create_all(engine)`. Checks `PRAGMA table_info` to determine
which columns already exist before issuing ALTER statements.

**Why this approach:** SQLAlchemy's `create_all(checkfirst=True)` only detects missing
TABLES, not missing COLUMNS. Verified empirically -- adding columns to the ORM model and
re-calling `create_all()` on an existing database leaves the columns absent. [VERIFIED:
confirmed in research session]

**When to use:** Every time a new column is added to MediaFile. The check is O(1) and
idempotent -- safe to run on every startup.

```python
# photoconsole/catalog/db.py -- extend create_catalog_engine()

_PHASE3_COLUMNS: list[tuple[str, str]] = [
    ("cluster_id",       "INTEGER"),
    ("cluster_keeper",   "BOOLEAN"),
    ("cluster_redundant","BOOLEAN"),
    ("blur_score",       "REAL"),
    ("pixel_width",      "INTEGER"),
    ("pixel_height",     "INTEGER"),
    ("face_count",       "INTEGER"),
    ("embedding_blob",   "BLOB"),
    ("phash",            "TEXT"),  # hex string, 16 chars for hashsize=8
]

def _ensure_phase3_columns(engine: "Engine") -> None:
    """Idempotent: add Phase 3 columns to media_files if absent."""
    with engine.connect() as conn:
        existing = {
            row[1]
            for row in conn.execute(text("PRAGMA table_info(media_files)")).fetchall()
        }
        for col_name, col_type in _PHASE3_COLUMNS:
            if col_name not in existing:
                conn.execute(
                    text(f"ALTER TABLE media_files ADD COLUMN {col_name} {col_type}")
                )
        conn.commit()

# In create_catalog_engine(), after Base.metadata.create_all(engine):
#     Base.metadata.create_all(engine)
#     _ensure_phase3_columns(engine)   # <-- ADD THIS LINE
```

**Important:** `_VALID_COLUMNS` in `db.py` is built from `MediaFile.__table__.columns` at
import time. Once the new columns are added to `models.py`, `_VALID_COLUMNS` automatically
includes them. `upsert_media_file()` will then accept quality score and embedding updates
without modification.

### Pattern 2: Partial Column Updates via upsert_media_file()

**What:** Pass only the columns you need to update. The SET clause is built dynamically
from the record dict keys (excluding `path` and `id`). No separate update function needed.

**When to use:** Quality score writes, embedding blob writes, cluster assignment writes,
and cluster keeper/redundant writes all use this same path.

```python
# Quality score update (Pass 0)
upsert_media_file(session, {
    "path": str(file.path),
    "blur_score": scores["blur_score"],
    "pixel_width": scores["pixel_width"],
    "pixel_height": scores["pixel_height"],
    "face_count": scores["face_count"],
})

# Embedding + pHash update (Pass 1 + 2)
upsert_media_file(session, {
    "path": str(file.path),
    "embedding_blob": embedding_to_blob(emb),
    "phash": str(imagehash.phash(img)),
})

# Cluster assignment (Pass 3)
upsert_media_file(session, {
    "path": str(file.path),
    "cluster_id": int(label) if label != -1 else None,
})

# Review outcome
upsert_media_file(session, {"path": str(keeper.path), "cluster_keeper": True})
upsert_media_file(session, {"path": str(redundant.path), "cluster_redundant": True})
```

**Constraint:** Must call `session.commit()` on the main thread in batches of 50 after
accumulating results from worker threads. Never call `upsert_media_file` from a worker
thread -- the SQLAlchemy session is not thread-safe (T-02-02 pattern from Phase 1/2).

### Pattern 3: Embedding Invalidation on File Change

**What:** When a file's mtime has changed (detected by comparing `os.stat().st_mtime`
against `MediaFile.mtime` in the catalog), nullify `embedding_blob` and `phash` before
the embedding pass so they are recomputed.

**Where this belongs:** In `_run_cluster()` as a pre-pass before the embedding step. The
scan command does NOT own embedding invalidation -- keeping it in the cluster command
preserves the scan/cluster separation.

```python
# In _run_cluster(), after opening the session:
with Session() as session:
    files_with_embed = session.query(MediaFile).filter(
        MediaFile.embedding_blob.isnot(None)
    ).all()
    to_invalidate = []
    for mf in files_with_embed:
        try:
            current_mtime = Path(mf.path).stat().st_mtime
        except OSError:
            continue  # file gone; will be excluded at embedding time
        if mf.mtime is not None and abs(current_mtime - mf.mtime) > 0.01:
            to_invalidate.append(mf.path)

if to_invalidate:
    logger.info("Invalidating embeddings for %d changed files", len(to_invalidate))
    with Session() as session:
        for path in to_invalidate:
            upsert_media_file(session, {
                "path": path,
                "embedding_blob": None,
                "phash": None,
            })
        session.commit()
```

### Pattern 4: ClusterGroup Dataclass (follows DuplicateGroup)

```python
# photoconsole/clustering.py
from dataclasses import dataclass, field
from photoconsole.catalog.models import MediaFile

@dataclass
class ClusterGroup:
    """A set of catalog entries assigned the same cluster_id by DBSCAN.

    Follows the DuplicateGroup pattern from dedup.py.
    """
    cluster_id: int
    members: list[MediaFile]       # ALL members; sorted by quality_score desc
    keeper: MediaFile              # auto-pick: highest quality_score
    redundants: list[MediaFile]    # all others
    component_scores: dict[str, dict]
    # Format: {path_str: {sharpness, resolution, faces, exif, combined}}
```

### Pattern 5: Cluster Deletion Manifest (new function, not reusing write_manifest)

**What:** `write_cluster_manifest(rows, dest_dir)` in `clustering.py`. Uses the same
BAT generation logic as `consolidator.write_manifest()` but with different CSV columns.

**Why not reuse write_manifest:** Phase 2 manifest includes `destination_path` (where the
canonical copy was placed). Phase 3 redundants have no copy destination -- we are flagging
them for deletion in-place. The CONTEXT specifics list `cluster_id` and `quality_score`
as Phase 3 additions. [CITED: 03-CONTEXT.md Specific Ideas section]

```python
# CSV columns for cluster deletion manifest:
_CLUSTER_MANIFEST_FIELDS = [
    "original_path",
    "hash",
    "source_name",
    "cluster_id",
    "quality_score",
]

# BAT format: identical to write_manifest (del /f for local, :: rclone for remote)
# Header: @echo off, chcp 65001 >nul, :: comments, :: Review carefully
```

### Pattern 6: Review Session State (catalog-as-state)

**What:** No external session file needed. Session state is stored in the catalog via
`cluster_keeper` and `cluster_redundant` columns.

**Resume behavior:**
- `photoconsole review-clusters` queries `WHERE cluster_id IS NOT NULL AND cluster_keeper IS NULL`
- Returns clusters that have not been reviewed yet, ordered by `cluster_id`
- Already-reviewed clusters (cluster_keeper IS NOT NULL) are skipped automatically
- "Skip" action during review leaves cluster_keeper=NULL; cluster is shown again next run
- A `--show-reviewed` flag can optionally surface already-confirmed clusters

### Pattern 7: pHash Storage Decision

**Conclusion:** Store pHash as a TEXT column (`phash`) on MediaFile. [ASSUMED]

**Rationale:** pHash computation takes ~5ms/image. For 100K images, recomputing on every
`photoconsole cluster` invocation costs ~8 minutes even for an incremental run (which
skips embedding but currently would still recompute pHash). Storing it as a 16-char hex
string (imagehash default hashsize=8) is negligible storage overhead (1.6 MB at 100K rows).

The incremental pattern is: compute pHash for files with `phash IS NULL`, store the value,
re-use stored value for subsequent runs.

**Version pinning note from AI-SPEC Section 3 (Common Pitfalls):** imagehash 4.0 changed
the hash representation from version 3.x. Always pin `imagehash>=4.3.1`. The `phash`
column stores hashes computed by version 4.x only. If the catalog was ever populated by
a version <4.0 install, those hashes must be recomputed. [CITED: AI-SPEC.md Section 3]

### Pattern 8: Config Extension (pydantic + stdlib dataclass coexistence)

The existing `Config` dataclass uses stdlib `dataclasses`. Phase 3 adds `ClusterConfig`
and `QualityWeightsConfig` as Pydantic v2 models. A stdlib dataclass can hold a pydantic
model as a field -- verified working. [VERIFIED: confirmed in research session]

```python
# config.py -- add after existing ConsolidationConfig

class QualityWeightsConfig(BaseModel):
    # ... (full spec in AI-SPEC Section 4b.1)

class ClusterConfig(BaseModel):
    # ... (full spec in AI-SPEC Section 4b.1)

@dataclass
class Config:
    # ... existing fields ...
    cluster: ClusterConfig = field(default_factory=ClusterConfig)
    quality_weights: QualityWeightsConfig = field(default_factory=QualityWeightsConfig)
```

In `load_config()`, add after the existing consolidation section:
```python
cluster_section = raw.get("cluster", {}) or {}
quality_weights_section = raw.get("quality_weights", {}) or {}
try:
    cluster = ClusterConfig(**cluster_section)
    quality_weights = QualityWeightsConfig(**quality_weights_section)
except ValidationError as exc:
    raise ValueError(f"Invalid cluster/quality_weights config:\n{exc}") from exc
```

### Anti-Patterns to Avoid

- **Calling `session.commit()` from a worker thread.** SQLAlchemy sessions are not
  thread-safe. Workers return result dicts; main thread writes to DB (T-02-02).
- **Loading the CLIP model inside the batch loop or per-file.** Load once before the
  ThreadPoolExecutor. Model loading takes 2-5s even from cache. [CITED: AI-SPEC.md]
- **Passing cosine similarity (not distance) to DBSCAN.** Use `cosine_distances()`, not
  `cosine_similarity()`. The difference is counterintuitive and silently produces wrong
  clusters. [CITED: AI-SPEC.md Section 3 Common Pitfalls]
- **Reusing write_manifest() for cluster manifests.** The column sets differ; destination_path
  is meaningless for cluster redundants. Use a new `write_cluster_manifest()`.
- **Using tqdm in Phase 3 commands.** cli.py already uses tqdm for `scan`. Phase 3
  commands use `rich.progress.track()` for consistency with the review UI. Both libraries
  coexist (they write to terminal independently), but mixing them in a single command
  output is visually inconsistent.
- **Relying on `create_all()` to migrate schema.** Verified: adding columns to the ORM
  model and re-calling `create_all(checkfirst=True)` on an existing database does NOT add
  the columns. Must use explicit ALTER TABLE migration.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Image embeddings | Custom CNN or feature extractor | open-clip-torch ViT-B-32 | 66.6% ImageNet zero-shot; 350MB weights, proven on photo clustering |
| Density-based clustering | Custom cluster merge logic | sklearn DBSCAN | Handles noise, no pre-specified N, metric=precomputed for cosine |
| Sparse neighbor graph for 50K+ | Custom spatial index | sklearn NearestNeighbors(radius=eps, metric='cosine') | Memory-safe O(n*k) vs O(n^2); drop-in for DBSCAN precomputed |
| Blur detection | Edge filters, FFT frequency analysis | cv2.Laplacian().var() | Standard signal, zero-cost, well-calibrated for photo quality |
| Face detection | Neural face detector | cv2.CascadeClassifier (Haar cascade) | Ships with opencv-python-headless; no extra download; sufficient for "face count" signal |
| Config validation | if/else type checks | pydantic v2 BaseModel with field validators | Automatic error messages, weight sum validation, field-level bounds |
| Perceptual hash | Rolling hash, DCT from scratch | imagehash.phash() | Burst-mode calibrated; version-stable (4.x); Hamming distance via `-` operator |

**Key insight:** The CV/ML domain has deeply tested, battle-hardened implementations for
every capability in this phase. The value is in the integration and threshold calibration,
not in the algorithms themselves.

---

## Unanswered Questions -- Resolved

The following 10 questions from the brief have been researched and answered:

### Q1: Schema Migration Approach [VERIFIED]

**Answer:** ALTER TABLE with PRAGMA table_info check. SQLAlchemy `create_all()` does not
add missing columns to existing tables -- verified empirically. The correct approach is a
new `_ensure_phase3_columns(engine)` helper called from `create_catalog_engine()` after
`Base.metadata.create_all(engine)`. This is idempotent (checks existence before ALTER).

The function checks `PRAGMA table_info(media_files)` for existing column names and issues
`ALTER TABLE media_files ADD COLUMN {name} {type}` only for absent columns.

### Q2: pHash Storage [ASSUMED]

**Answer:** Yes, store pHash as a TEXT column (`phash`) on MediaFile. 16-char hex for
hashsize=8 (imagehash default). Incremental: compute only for files with `phash IS NULL`.
Invalidate alongside `embedding_blob` when mtime changes. This avoids 8-minute recompute
per 100K file run.

### Q3: Review Session State [VERIFIED]

**Answer:** Catalog IS the session state. `cluster_keeper IS NULL` = unreviewed.
`cluster_keeper IS NOT NULL` = reviewed. Resume is automatic -- `review-clusters` queries
only pending clusters. "Skip" leaves cluster_keeper=NULL; it reappears next run.
No external session file needed.

### Q4: Deletion Manifest Format [VERIFIED from codebase]

**Confirmed Phase 2 manifest columns:** `original_path`, `hash`, `destination_path`, `source_name`
(from `consolidator._MANIFEST_FIELDS`).

**Phase 3 manifest columns (different):** `original_path`, `hash`, `source_name`, `cluster_id`, `quality_score`

Phase 3 does NOT include `destination_path` (no copy is made; redundants are deleted
in-place from their original location). `cluster_id` and `quality_score` are added.

BAT format is identical to Phase 2: `del /f "path"` for local files, `:: rclone deletefile
path` for rclone sources. Same header block (`@echo off`, `chcp 65001 >nul`, etc.).

Phase 3 needs a new `write_cluster_manifest(rows, dest_dir)` function. The BAT generation
logic can be factored out from `consolidator.write_manifest()` as a shared helper, or
duplicated (simpler given the function is 30 lines).

### Q5: Windows os.startfile() Behavior [VERIFIED]

**Answer:**
- `os.startfile(path)` on Windows is **always non-blocking**. It calls `ShellExecuteW`
  and returns immediately; the photo viewer opens asynchronously.
- If Windows Photos is already open: opens the file in a new tab or window; still non-blocking.
- If the viewer crashes after `os.startfile()` returns: no exception is raised in Python;
  the call has already completed.
- If no application is registered for the file type: raises `OSError`. Wrap in
  `try/except OSError` and log a warning with an instruction to set a default viewer.
- **Implementation:** `try: os.startfile(path) except OSError: console.print(f"[yellow]Could not open {path}: no default viewer registered[/]")`
- The review UI does NOT need to track the viewer process PID or wait for it to close.
  User interaction ("did you look at the photos?") is implicit in the click.prompt.

### Q6: Database Migration -- Does db.py have versioning? [VERIFIED]

**Answer:** No. The existing `db.py` has no schema versioning mechanism. It relies on
`Base.metadata.create_all(engine)` which creates the `media_files` table if absent but
does nothing to add columns to an existing table. Phase 3 must add the migration block
directly to `create_catalog_engine()`. No Alembic, no schema version table -- just the
idempotent ALTER TABLE approach described in Q1.

### Q7: Test Fixture Creation Strategy [VERIFIED]

**Answer:** Synthesize programmatically using numpy + PIL (Pillow is already a project
dependency). Real photos are NOT needed for unit tests. The synthesis approach is verified
working:

```python
# tests/fixtures/generate_fixtures.py  (or inline in conftest.py)
import numpy as np
from PIL import Image

def make_sharp_jpg(path, size=(200, 200)):
    """High Laplacian variance: checkerboard pattern."""
    arr = np.zeros((*size, 3), dtype=np.uint8)
    arr[::2, ::2] = 255  # alternating pixels -> high frequency
    Image.fromarray(arr).save(str(path), "JPEG", quality=95)
    # Verified blur_score: ~388,183 (vs ~0.0 for solid image)

def make_blurry_jpg(path, size=(200, 200)):
    """Low Laplacian variance: solid color."""
    arr = np.full((*size, 3), 128, dtype=np.uint8)
    Image.fromarray(arr).save(str(path), "JPEG", quality=95)

def make_near_duplicate(source_path, dest_path):
    """Apply Gaussian blur to simulate JPEG recompression."""
    from PIL import ImageFilter
    img = Image.open(source_path).filter(ImageFilter.GaussianBlur(radius=1))
    img.save(str(dest_path), "JPEG", quality=85)
    # pHash Hamming distance from original: ~2 (well within threshold of 10)
```

**Verified:** Sharp checkerboard produces blur_score ~388,183; solid color produces 0.0.
Near-duplicate pair (Gaussian blur applied) produces Hamming distance ~2, within threshold
of 10. Different random images produce Hamming distance ~36, well above threshold.
[VERIFIED: confirmed in research session]

**Fixture commit strategy:** Generate fixtures at test collection time using pytest's
`tmp_path` fixture for ephemeral test images. For the eval reference dataset (ground truth
labeled clusters), generate once and commit to `tests/fixtures/eval/`. For unit test
fixtures (sharp.jpg, blurry.jpg), generate programmatically per-test using `tmp_path` --
no committed binary files needed for the unit test tier.

### Q8: Rich Progress vs. Existing tqdm [VERIFIED]

**Answer:** cli.py's `scan` command uses `tqdm` with a `try/except ImportError` fallback.
Phase 3 commands (`cluster`, `review-clusters`) use `rich.progress.track()`. Both
libraries write to the terminal independently and coexist without conflict. The AI-SPEC
directive "use Rich consistently" applies to Phase 3's own commands -- it does not require
removing tqdm from the scan command. [VERIFIED: rich.progress.track and tqdm coexist in
same Python process; confirmed in research session]

**Practical guidance:**
- `photoconsole scan` -- continues using tqdm (do not touch)
- `photoconsole cluster` -- use `rich.progress.track()` for the quality/embedding passes
- `photoconsole review-clusters` -- use `rich.console.Console().print()` and `rich.table.Table`

### Q9: Embedding Invalidation on File Change [VERIFIED]

**Answer:** The scan command's `should_skip()` / `process_files()` path already updates
`mtime` in the catalog for changed files. However, `process_files()` does NOT touch
`embedding_blob` or `phash` -- those columns are owned exclusively by the cluster command.

The cluster command must handle invalidation: before the embedding pass in `_run_cluster()`,
query files with `embedding_blob IS NOT NULL`, compare each file's current `os.stat().st_mtime`
against its stored `mtime` in the catalog, and nullify `embedding_blob` + `phash` for
files where mtime differs. See Pattern 3 above for the implementation.

This keeps the scan and cluster commands fully decoupled.

### Q10: Batch Writes for Quality Scores and Embeddings [VERIFIED]

**Answer:** Reuse `upsert_media_file()` with partial record dicts. No separate update-only
path is needed. The existing upsert builds its SET clause dynamically from the record keys,
so passing only `{path, blur_score, pixel_width, pixel_height, face_count}` updates only
those 5 columns. [VERIFIED: confirmed by reading db.py lines 156-163]

**Batch commit strategy:** Accumulate results in a buffer of 50 (matching `_BATCH_SIZE`),
then call `session.commit()` on the main thread. Same pattern as `cli._run_scan()`.

```python
buffer = []
for result in executor_results:
    buffer.append(result)
    if len(buffer) >= _BATCH_SIZE:
        with Session() as session:
            for r in buffer:
                upsert_media_file(session, r)
            session.commit()
        buffer.clear()
# flush remainder
```

---

## Common Pitfalls

### Pitfall 1: create_all() Does Not Migrate Existing Tables

**What goes wrong:** Developer adds columns to `MediaFile`, re-runs `create_catalog_engine()`,
and assumes the live database is updated. It is not. The new columns are absent, causing
`NOT NULL constraint failed` errors or silent NULL values for all existing rows.

**Root cause:** SQLAlchemy `create_all(checkfirst=True)` checks table existence, not column
completeness. This is documented behavior, not a bug.

**How to avoid:** Always use `_ensure_phase3_columns(engine)` after `create_all()` in
`create_catalog_engine()`. Test this by creating a catalog with Phase 1/2 columns and then
calling the Phase 3 `create_catalog_engine()` -- verify all 9 new columns are present.

**Warning signs:** `OperationalError: table media_files has no column named blur_score`

### Pitfall 2: upsert_media_file Rejects Unknown Column Names

**What goes wrong:** Calling `upsert_media_file(session, {"path": p, "blur_score": 500.0})`
before adding `blur_score` to the MediaFile ORM model raises `ValueError: unknown column(s)
['blur_score']`.

**Root cause:** `_VALID_COLUMNS` is built from `MediaFile.__table__.columns` at import time.
If the model definition doesn't include the new column, the upsert validator rejects it.

**How to avoid:** Always extend `models.py` first, then update `db.py`, then write the
business logic. The model definition drives both the ORM and the upsert validator.

### Pitfall 3: Dense Distance Matrix OOM at 50K+ Files

**What goes wrong:** `cosine_distances(embeddings)` for 50K embeddings allocates a
50K x 50K x 4 bytes = ~10 GB matrix. On 64 GB RAM this causes severe swapping or OOM kill.

**How to avoid:** Add a size check in `_run_cluster()`. If `len(files_with_embed) > 50_000`,
use `cluster_embeddings_sparse()` (NearestNeighbors radius graph). See AI-SPEC Section 4
for the sparse implementation. Add a startup warning for catalogs between 10K-50K files.

### Pitfall 4: CLIP Model Loaded Inside Batch Loop

**What goes wrong:** `load_clip_model()` called per-batch or per-file. First call downloads
~350 MB; subsequent calls load from disk (~2-5s). Throughput drops from ~80ms/file to
several seconds per file.

**How to avoid:** Load once before the loop. Pass the model reference to the embedding
function. The model is stateless for inference -- safe to use across batches.

### Pitfall 5: os.startfile() Path Handling on Windows

**What goes wrong:** Passing a Path object or relative path to `os.startfile()`. On some
Windows configurations this silently opens the wrong file or raises OSError.

**How to avoid:** Always pass an absolute string path: `os.startfile(str(Path(path).resolve()))`.
Wrap in `try/except OSError`.

### Pitfall 6: imagehash Version Incompatibility in Stored pHash Values

**What goes wrong:** If a user previously had imagehash 3.x installed (pre-project), any
pHash values computed then are incompatible with 4.x values. Hamming distance comparisons
produce nonsense.

**How to avoid:** The project pins `imagehash>=4.3.1`. If the `phash` column has any
values and the user upgrades from a pre-4.0 install, all pHash values must be recomputed
(set `phash = NULL` for all rows, then re-cluster). Document this in the migration notes.
In practice, this is not an issue for Phase 3 since pHash is a new column with no legacy data.

### Pitfall 7: Rich Table Console vs. pytest Output Capture

**What goes wrong:** Tests that render a Rich Table to stdout fail with pytest's output
capture because `Console()` detects non-TTY and suppresses rich formatting. Assertions
on rendered string output fail.

**How to avoid:** In tests, use `Console(force_terminal=True)` or pass `console=Console(file=buf)`
where `buf = io.StringIO()`. Assert on `buf.getvalue()` rather than captured stdout.
The existing `_print_report` in cli.py already does this pattern for the `--output` flag.

### Pitfall 8: SQLite LargeBinary Column and Null Checks

**What goes wrong:** `MediaFile.embedding_blob.isnot(None)` in a SQLAlchemy query may
not behave as expected if the column type is not declared as `LargeBinary` in the ORM.
Comparing BLOB columns with `== None` vs `.is_(None)` differs in SQLAlchemy 2.0.

**How to avoid:** Declare `embedding_blob` as `Mapped[Optional[bytes]] = mapped_column(LargeBinary)`.
Use `.is_(None)` and `.isnot(None)` for nullable column checks in SQLAlchemy 2.0 queries
(not `== None`). Import `LargeBinary` from `sqlalchemy`.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | All | Yes | 3.14.3 | -- |
| open-clip-torch | CLIP embeddings | Yes (installed) | 3.3.0 | -- |
| imagehash | pHash pre-filter | Yes (installed) | 4.3.2 | -- |
| scikit-learn | DBSCAN clustering | Yes (installed) | 1.8.0 | -- |
| opencv-python-headless | Blur + faces | Yes (installed) | 4.13.0 | -- |
| pydantic | Config validation | Yes (installed) | 2.13.4 | -- |
| scipy | Sparse distance matrix | Yes (installed) | 1.17.1 | -- |
| torch (CPU) | CLIP inference | Yes (transitive) | 2.12.0+cpu | -- |
| CUDA / ROCm | GPU acceleration | Not available (Windows AMD) | -- | CPU inference (accepted) |
| os.startfile | Windows photo viewer | Yes | Win32 API | Log warning, continue |
| Haar cascade XML | Face detection | Yes | Ships with opencv | -- |
| CLIP model weights | First cluster run | Not cached yet | -- | Download on first run (~350 MB) |

**Missing dependencies with no fallback:** None. All dependencies are available.

**Notes:**
- CLIP model weights (~350 MB) are not pre-downloaded. First `photoconsole cluster` run
  triggers a download from the OpenCLIP hub. Requires internet access once. Subsequent
  runs use the HuggingFace cache. [CITED: AI-SPEC.md Section 6 Guardrails]
- All packages installed successfully in the research session. The project may need to
  re-install them into a project-specific venv if one is created. No venv was found in
  the project directory during research.

---

## Validation Architecture

> `workflow.nyquist_validation` key is absent from `.planning/config.json` -> treated as ENABLED.

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.0.3 |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `pytest tests/test_quality.py tests/test_config_phase3.py -v --timeout=30` |
| Full suite command | `pytest tests/ -v` |
| Eval dimensions run | `pytest tests/test_eval_clustering.py -m "critical" -v` |

### Phase Requirements -> Test Map

| Behavior | Test Type | File | Command |
|----------|-----------|------|---------|
| blur_score ordering: sharp > blurry | unit | `tests/test_quality.py::test_blur_score_ordering` | `pytest tests/test_quality.py::test_blur_score_ordering -x` |
| face_count detects faces | unit | `tests/test_quality.py::test_face_count` | `pytest tests/test_quality.py::test_face_count -x` |
| quality normalization 0-100 | unit | `tests/test_quality.py::test_quality_score_range` | `pytest tests/test_quality.py::test_quality_score_range -x` |
| EXIF completeness bonus | unit | `tests/test_quality.py::test_exif_completeness` | `pytest tests/test_quality.py::test_exif_completeness -x` |
| EXIF-absent sharp photo still in top 2 | critical | `tests/test_eval_clustering.py::test_exif_absent_quality_ranking` | `pytest -m critical tests/test_eval_clustering.py -x` |
| ClusterConfig validation rejects eps=5.0 | unit | `tests/test_config_phase3.py::test_cluster_config_invalid_eps` | `pytest tests/test_config_phase3.py -x` |
| QualityWeightsConfig rejects sum != 1.0 | unit | `tests/test_config_phase3.py::test_weights_sum_validation` | `pytest tests/test_config_phase3.py -x` |
| embed_images() is deterministic | unit | `tests/test_clustering.py::test_embed_determinism` | `pytest tests/test_clustering.py::test_embed_determinism -x` |
| pHash Hamming <= 10 for near-dups | unit | `tests/test_clustering.py::test_phash_near_duplicate` | `pytest tests/test_clustering.py::test_phash_near_duplicate -x` |
| DBSCAN groups known similar images | unit | `tests/test_clustering.py::test_dbscan_labels` | `pytest tests/test_clustering.py::test_dbscan_labels -x` |
| Schema migration adds columns idempotently | unit | `tests/test_catalog_phase3.py::test_phase3_migration` | `pytest tests/test_catalog_phase3.py -x` |
| upsert partial update (quality cols only) | unit | `tests/test_catalog_phase3.py::test_partial_upsert` | `pytest tests/test_catalog_phase3.py -x` |
| cluster command: incremental skip embedded | integration | `tests/test_cli_phase3.py::test_cluster_skips_cached` | `pytest tests/test_cli_phase3.py::test_cluster_skips_cached -x` |
| review-clusters: keeper persisted | integration | `tests/test_cli_phase3.py::test_review_keeper_persisted` | `pytest tests/test_cli_phase3.py::test_review_keeper_persisted -x` |
| cluster manifest: correct CSV columns | unit | `tests/test_clustering.py::test_write_cluster_manifest` | `pytest tests/test_clustering.py::test_write_cluster_manifest -x` |
| burst sequence capture rate >= 90% | critical | `tests/test_eval_clustering.py::test_burst_sequence_recall` | `pytest -m critical -x` |
| cluster purity >= 0.90 | critical | `tests/test_eval_clustering.py::test_cluster_purity` | `pytest -m critical -x` |
| keeper pick accuracy >= 80% | critical | `tests/test_eval_clustering.py::test_keeper_pick_accuracy` | `pytest -m critical -x` |
| cluster size <= 50 (no oversized) | high | `tests/test_eval_clustering.py::test_cluster_size_distribution` | `pytest -m "critical or high" -x` |
| throughput: 10K files in < 30 min | slow | `tests/test_eval_clustering.py::test_throughput_benchmark` | `pytest -m slow --benchmark-only` |

### Sampling Rate

- **Per task commit:** `pytest tests/test_quality.py tests/test_config_phase3.py -v --timeout=30`
- **Per wave merge:** `pytest tests/ -v -m "not slow"`
- **Phase gate:** `pytest tests/ -v` (full suite, all marks) before `/gsd:verify-work`

### Wave 0 Gaps (files that do not yet exist)

- [ ] `tests/test_quality.py` -- unit tests for quality.py (blur, faces, EXIF, normalization)
- [ ] `tests/test_clustering.py` -- unit tests for clustering.py (embeds, pHash, DBSCAN, manifest)
- [ ] `tests/test_config_phase3.py` -- unit tests for ClusterConfig/QualityWeightsConfig
- [ ] `tests/test_catalog_phase3.py` -- unit tests for schema migration + partial upsert
- [ ] `tests/test_cli_phase3.py` -- integration tests for cluster + review-clusters commands
- [ ] `tests/test_eval_clustering.py` -- eval dimensions with @pytest.mark.critical/slow
- [ ] `tests/fixtures/` directory -- sharp.jpg, blurry.jpg, sharp_no_exif.jpg, soft_with_exif.jpg, solid_blue_sky.jpg
- [ ] `tests/fixtures/eval/ground_truth.json` -- user-labeled cluster memberships (Wave 2/3)
- [ ] `pyproject.toml` -- add `markers = [...]` section to pytest.ini_options
- [ ] `pyproject.toml` -- add Phase 3 packages to [project.dependencies]

---

## Security Domain

> `security_enforcement` not set -> treated as enabled (absent = enabled).

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | N/A -- local CLI, no auth |
| V3 Session Management | No | N/A -- stateless CLI |
| V4 Access Control | No | N/A -- single user, local |
| V5 Input Validation | Yes | pydantic v2 for config; path existence checks before os.startfile |
| V6 Cryptography | No | No new crypto; SHA-256 from Phase 1/2 unchanged |

### Known Threat Patterns for This Stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Path injection in manifest BAT | Tampering | Paths come from catalog rows (already-validated file paths); same approach as Phase 2 consolidator |
| os.startfile with user-controlled path | Tampering | Paths come from catalog only (never from CLI argument); wrap in try/except OSError |
| Config YAML integer overflow (eps, batch_size) | Tampering | pydantic Field(gt=0.0, lt=2.0) for eps; Field(ge=1, le=512) for batch_size |
| Large catalog OOM (>50K embeddings) | DoS (self) | Sparse fallback + startup warning; documented threshold |
| CLIP model download over network | Spoofing | HuggingFace hub with official model ID; one-time download; cached locally |

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | pHash should be stored as a TEXT column (not recomputed per cluster run) | Unanswered Q2; Pattern 7 | If wrong: extra 8-min overhead per cluster run on 100K catalog; correctness unaffected |
| A2 | Phase 3 manifest should use `original_path, hash, source_name, cluster_id, quality_score` columns | Q4; Pattern 5 | If wrong: planner needs to adjust write_cluster_manifest() column design; low risk |
| A3 | Config extension uses stdlib dataclass for Config + pydantic BaseModel for ClusterConfig/QualityWeightsConfig | Pattern 8 | If wrong: may need to convert Config to pydantic BaseModel too; medium refactor risk |

---

## Open Questions (RESOLVED)

1. **Where should write_cluster_manifest() live?** — RESOLVED
   - What we know: Phase 2's write_manifest() is in consolidator.py; Phase 3 needs a similar but distinct function
   - What's unclear: should write_cluster_manifest() go in clustering.py (co-located with the data) or consolidator.py (consolidates all manifest logic)?
   - Recommendation: put it in `clustering.py` to keep consolidator.py focused on Phase 2 copy operations. The BAT format logic can be a thin shared helper or duplicated (30 lines).
   - **Resolution:** write_cluster_manifest() lives in clustering.py — decided and implemented by Plan 05.

2. **Should `photoconsole cluster` be skippable per-source-type?** — RESOLVED
   - What we know: rclone sources may have paths that are not locally accessible at cluster time (NAS over SMB, cloud mounts)
   - What's unclear: should cluster skip rclone-sourced files if the path is inaccessible?
   - Recommendation: add a preflight check -- if a file's path cannot be opened by PIL/cv2, log a warning and assign zero-vector embedding (existing corrupt-image gate from AI-SPEC Section 6).
   - **Resolution:** Preflight check / zero-vector gate adopted in Plan 06 Task 1 Step 6. Files whose embedding L2 norm < 0.01 are excluded from clustering input.

3. **Ground truth dataset: when to build?** — RESOLVED
   - What we know: AI-SPEC requires 25-30 labeled photo sets for eval dimensions; user must manually label ground_truth.json
   - What's unclear: this requires the user to supply real family photos for the eval dataset
   - Recommendation: synthesize burst groups and sharp/blurry pairs programmatically for unit tests; defer real-photo ground truth labeling to a user review task in Wave 2 planning.
   - **Resolution:** Synthetic fixtures only for unit tests (Plan 07). User-labeled ground truth is deferred — documented as a manual user task to be completed before running eval dimensions against a real catalog.

---

## Sources

### Primary (HIGH confidence)
- Codebase direct read -- `photoconsole/catalog/db.py`, `models.py`, `config.py`, `cli.py`, `consolidator.py`, `hasher.py`, `dedup.py` -- all patterns verified by reading source
- PyPI registry -- `pip index versions` for imagehash, scikit-learn, opencv-python-headless, open-clip-torch, scipy, pydantic, pytest-benchmark -- current versions confirmed
- SQLAlchemy behavior -- `create_all() + checkfirst=True` migration behavior verified via interactive Python session
- os.startfile behavior -- Python win32 API documentation (non-blocking, OSError on no viewer)
- Package import verification -- all 6 packages imported and functionally tested on Python 3.14 Windows

### Secondary (MEDIUM confidence)
- `03-AI-SPEC.md` -- framework selection, CLIP model, DBSCAN configuration, Pydantic config patterns (generated by prior research session)
- `03-CONTEXT.md` -- locked decisions D-01 through D-17

### Tertiary (LOW confidence)
- A1 (pHash storage): based on performance calculation (5ms * 100K = 8 min) -- storage tradeoff analysis is reasoned, not benchmarked

---

## Metadata

**Confidence breakdown:**
- Codebase integration patterns: HIGH -- all patterns verified by reading source code
- Schema migration approach: HIGH -- SQLAlchemy create_all behavior verified empirically
- Package versions: HIGH -- verified via PyPI registry and import testing
- Manifest format: HIGH -- verified by reading consolidator.py write_manifest() source
- Review session state: HIGH -- straightforward DB state pattern; no external dependencies
- Test fixture strategy: HIGH -- numpy+PIL synthesis verified working on this Python/platform
- Windows os.startfile: HIGH -- Win32 API behavior is well-documented and consistent
- Throughput estimates: MEDIUM -- from AI-SPEC Section 4b.5 (based on hardware specs)

**Research date:** 2026-05-17
**Valid until:** 2026-08-17 (90 days; stable stack, no fast-moving dependencies)
