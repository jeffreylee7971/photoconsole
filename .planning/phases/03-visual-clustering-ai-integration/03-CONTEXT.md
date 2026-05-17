# Phase 3: Visual Clustering & AI Integration - Context

**Gathered:** 2026-05-16
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 3 delivers visual similarity clustering and quality-based ranking for photos in the catalog — helping users identify and rank similar shots beyond exact duplicates (which Phase 2 handles).

The two core operations are:
1. **Cluster**: Detect visually similar photos using a two-pass approach (pHash pre-filter → CLIP semantic grouping). Assign `cluster_id` to grouped photos in the catalog.
2. **Review**: Walk through clusters via terminal UI, auto-open top candidates in Windows Photos for visual comparison, flag a keeper and redundants per cluster, generate a deletion manifest.

Phase 3 ends when: similar (non-exact) photos are clustered, quality-ranked, and the user can confirm keepers via terminal review. No LLaVA, no captioning, no semantic search — those belong in a future phase.

</domain>

<decisions>
## Implementation Decisions

### Similarity Method
- **D-01:** Two-pass approach: pHash (perceptual hashing via `imagehash` library) runs first as a fast pre-filter to catch near-identical/resized duplicates. CLIP embeddings run second for semantic grouping (catches same-scene photos with different framing).
- **D-02:** CLIP embeddings stored as SQLite BLOB in a new column (or separate `embeddings` table linked by `media_file_id`). Follows the existing catalog-first pattern. Enables incremental updates.
- **D-03:** Embedding is incremental: `photoconsole cluster` skips files that already have a cached embedding. Only new or changed files are re-embedded.
- **D-04:** Separate CLI command: `photoconsole cluster [--threshold FLOAT]`. Does not run automatically during scan. User-configurable similarity threshold (default: Claude's discretion).
- **D-05:** Only clusters with 2+ similar photos are reported. Unique photos (no similar neighbors above threshold) are excluded from cluster output — focused, actionable results.

### Catalog Schema Extensions
- **D-06:** New columns on `MediaFile`:
  - `cluster_id` (Integer, nullable) — assigned cluster group; NULL = no similar neighbors or not yet clustered
  - `cluster_keeper` (Boolean, nullable) — True = user confirmed this is the keeper for its cluster
  - `cluster_redundant` (Boolean, nullable) — True = user marked this as redundant within the cluster
  - `blur_score` (Float, nullable) — OpenCV Laplacian variance (sharpness metric); incremental
  - `pixel_width` (Integer, nullable) — image width in pixels; incremental
  - `pixel_height` (Integer, nullable) — image height in pixels; incremental
  - `face_count` (Integer, nullable) — number of faces detected (OpenCV Haar cascades); incremental
- **D-07:** All quality scores computed incrementally — only files with NULL values are processed on each run.

### Quality Ranking
- **D-08:** Four quality signals combined into a normalized 0–100 score:
  - Sharpness (Laplacian variance): **45%**
  - Resolution (pixel_width × pixel_height): **30%**
  - Face count: **15%**
  - EXIF completeness (has `date_taken` + `gps_lat/lon` in catalog): **10%**
- **D-09:** Weights are configurable in `config.yaml` under a new `quality_weights:` section:
  ```yaml
  quality_weights:
    sharpness: 0.45
    resolution: 0.30
    faces: 0.15
    exif_completeness: 0.10
  ```
- **D-10:** Each signal normalized to [0, 1] before weighting, then multiplied by 100 for the final score. Highest score = auto-suggested best photo in the cluster.
- **D-11:** Individual component scores are shown in the review table (not just the combined score) so the user can understand why one photo ranked higher.

### Review Interface
- **D-12:** Terminal review command: `photoconsole review-clusters`. Uses Rich tables to display each cluster: cluster ID, photo count, file paths, individual quality scores, combined score, auto-pick suggestion.
- **D-13:** For each cluster, automatically opens the top 2–3 ranked candidates in the Windows default photo viewer (`os.startfile()` or `subprocess` with the file path) for visual comparison. User reviews photos, returns to terminal.
- **D-14:** Terminal prompt per cluster: confirm the auto-pick, override with a different file, or skip the cluster. Photo-opening is done before the prompt so the user can compare visually first.
- **D-15:** On confirmation: sets `cluster_keeper = True` on the chosen file, `cluster_redundant = True` on the rest. These flags persist in the catalog.
- **D-16:** After review, generates a deletion manifest (CSV + Windows `.bat`) listing redundant cluster photos — same pattern as Phase 2 consolidation manifest (`D-11`/`D-12` from Phase 2 context). User reviews and runs manually. PhotoConsole never deletes.

### LLaVA / AI Scope
- **D-17:** LLaVA is NOT included in Phase 3. Phase 3 uses only local libraries (imagehash, OpenCLIP/CLIP, OpenCV). No Ollama dependency in this phase.

### Claude's Discretion
- CLIP model size/variant — pick a model that fits comfortably in 12GB VRAM (RX 6750 XT, ROCm). Suggested: `ViT-B/32` (OpenCLIP) as a good balance of speed and quality. Avoid CUDA-only builds.
- Clustering algorithm — DBSCAN recommended (no need to pre-specify N clusters, handles noise well). Threshold = epsilon parameter.
- pHash threshold for near-identical detection — common default is Hamming distance ≤ 10.
- Normalization formula for quality signals (min-max or percentile-based) — Claude's choice.
- SQLite schema migration approach — add new columns via ALTER TABLE or schema version bump, following existing patterns.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project Requirements
- `.planning/REQUIREMENTS.md` — FR6 (performance/scalability: 100K items in reasonable time), NFR1 (safety/data integrity: no deletions), NFR2 (privacy: local-first, no cloud APIs)
- `.planning/ROADMAP.md` — Phase 3 features, deliverables, success criteria ("cluster 100K items in reasonable time", "> 90% precision")

### Existing Codebase (Phases 1–2)
- `photoconsole/catalog/models.py` — MediaFile ORM model; new columns (`cluster_id`, `blur_score`, `pixel_width`, `pixel_height`, `face_count`, `cluster_keeper`, `cluster_redundant`) extend this model
- `photoconsole/catalog/db.py` — existing DB session factory, `upsert_many` pattern; Phase 3 adds new upsert for quality scores and cluster assignments
- `photoconsole/config.py` — existing `Config` + `ConsolidationConfig` dataclasses; Phase 3 extends `Config` with `quality_weights` and `cluster` config sections
- `photoconsole/cli.py` — existing `main` click group; add `cluster` and `review-clusters` subcommands following the `_run_scan` / `_run_report` pure-helper pattern
- `photoconsole/consolidator.py` — `write_manifest` function; reuse or follow the same pattern for the cluster redundancy deletion manifest (CSV + .bat)
- `photoconsole/dedup.py` — existing `DuplicateGroup` dataclass pattern; Phase 3's `ClusterGroup` dataclass follows the same structure

### Phase 2 Context (Decisions carried forward)
- `.planning/phases/02-deduplication-consolidation/02-CONTEXT.md` — D-11/D-12 (manifest format: CSV columns + .bat format), D-13 (never delete), D-15 (audit log pattern)

### Hardware Constraints
- User machine: AMD RX 6750 XT (12GB VRAM, RDNA 2, ROCm — NOT CUDA). All GPU-accelerated code must use ROCm-compatible builds. See memory file: `~/.claude/projects/.../memory/project_ai_phase3.md`

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `photoconsole/catalog/models.py:MediaFile` — extend with new quality + cluster columns; follow existing `mapped_column` pattern
- `photoconsole/catalog/db.py:upsert_many` — adapt for incremental quality score updates (UPDATE where blur_score IS NULL)
- `photoconsole/consolidator.py:write_manifest` — reuse or follow for cluster redundancy deletion manifest (same CSV + .bat format)
- `photoconsole/cli.py:_run_scan` pattern — `_run_cluster` and `_run_review` should be pure helpers (no click dependency) for testability
- `photoconsole/hasher.py:process_files` — ThreadPoolExecutor pattern; follow same for parallel quality score computation

### Established Patterns
- **Pure helper + click wrapper**: all business logic in `_run_*` functions; click commands are thin wrappers. Critical for testing.
- **Incremental skip**: `should_skip()` in `db.py` pattern — Phase 3 adds equivalent "skip if embedding/score already computed"
- **Preflight gates**: check dependencies before running (ffprobe gate in cli.py). Phase 3 should gate on: OpenCV importable, CLIP model downloaded, Ollama running (if ever needed)
- **Single writer thread**: all DB writes on main thread; worker threads return result dicts. Apply to quality score batch writes.
- **Batch size 50**: `_BATCH_SIZE = 50` in cli.py; apply to quality score computation batches

### Integration Points
- `clustering.py` (new) → queries `media_files` by embedding BLOB → computes similarity matrix → assigns `cluster_id`
- `quality.py` (new) → decodes image headers + OpenCV analysis → writes `blur_score`, `pixel_width`, `pixel_height`, `face_count` to catalog
- `photoconsole cluster` → calls `quality.py` then `clustering.py` then writes results
- `photoconsole review-clusters` → reads clusters from catalog → Rich terminal UI → updates `cluster_keeper`/`cluster_redundant` → writes manifest

</code_context>

<specifics>
## Specific Ideas

- **Quality weight config section**:
  ```yaml
  quality_weights:
    sharpness: 0.45
    resolution: 0.30
    faces: 0.15
    exif_completeness: 0.10
  ```
  Make weights configurable so the user can tune them without code changes.

- **Review table columns**: show cluster_id, file path (truncated), sharpness score, resolution, face_count, EXIF bonus, combined_score (0–100), and a `[AUTO-PICK]` marker on the top-ranked photo.

- **Windows Photos auto-open**: use `os.startfile(path)` for each of the top 2–3 candidates. Opens in default photo viewer. Non-blocking — user reviews in Photos, returns to terminal, types their decision.

- **Deletion manifest continuity**: same CSV column names as Phase 2 (`original_path`, `hash`, `source_name`) plus `cluster_id` and `quality_score`. `.bat` format: `del /f "path"` per redundant file with header comment.

- **ROCm note for CLIP**: use `open_clip` (OpenCLIP) package rather than `openai/clip`. OpenCLIP supports ROCm via standard PyTorch AMD builds. Model: `ViT-B-32` with `laion2b_s34b_b79k` weights as starting point.

</specifics>

<deferred>
## Deferred Ideas

- **LLaVA integration (future phase — Phase 4 or 5)**: local vision model via Ollama for:
  - Generating text captions/descriptions per photo (stored in catalog for search)
  - Semantic natural language search ("show me fishing photos", "sunset beach trips", "photos with grandma")
  - AI-assisted event grouping (group photos by scene/event beyond visual similarity)
  - Auto-picking best photo in a cluster using vision reasoning
  - AMD ROCm setup notes: Ollama supports AMD GPU on Windows via ROCm (experimental). LLaVA 7B (4-bit quantized ~4–5GB) fits in 12GB VRAM comfortably.
  **This is a high-priority future feature — should be a named phase in the roadmap (Phase 4 or between Phase 3 and Immich integration).**

- **Video quality ranking**: Phase 3 quality signals are photo-focused (Laplacian blur, pixel dimensions). Video sharpness/quality ranking (bitrate, resolution, stabilization) requires different signals. Defer to the LLaVA phase or a dedicated video QC phase.

- **Web UI for cluster review**: Phase 5 web dashboard will be a much better surface for reviewing visual clusters (thumbnails, side-by-side comparison, batch approval). Terminal review in Phase 3 is the pragmatic MVP.

- **User-adjustable weights at review time**: interactive weight tuning during review session (e.g., "I care more about sharpness for this batch"). Defer — configurable weights in config.yaml is sufficient for now.

</deferred>

---

*Phase: 3-Visual Clustering & AI Integration*
*Context gathered: 2026-05-16*
