# Phase 3: Visual Clustering & AI Integration - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-16
**Phase:** 3-Visual Clustering & AI Integration
**Areas discussed:** Similarity method, LLaVA scope, Review interface, Quality ranking signals

---

## Similarity Method

| Option | Description | Selected |
|--------|-------------|----------|
| Perceptual hashing only | pHash/dHash via imagehash. Fast, no GPU, pixel-level. | |
| CLIP embeddings only | Semantic similarity, uses RX 6750 XT via ROCm. | |
| Both — pHash pre-filter + CLIP semantic | pHash for near-identical first, CLIP for same-scene grouping. | ✓ |

**User's choice:** Both — pHash pre-filter + CLIP semantic grouping

---

**Q: Where to cache CLIP embeddings?**

| Option | Description | Selected |
|--------|-------------|----------|
| SQLite BLOB column | Single source of truth, incremental, fits existing pattern. | ✓ |
| Separate .npy file | Fast batch math but brittle sync with catalog. | |
| You decide | Claude picks. | |

**User's choice:** SQLite BLOB column

---

**Q: Clustering trigger — flag on scan or separate command?**

| Option | Description | Selected |
|--------|-------------|----------|
| Separate `photoconsole cluster` command | Independent, follows existing pattern. | ✓ |
| Flag on scan (`--cluster`) | One step but mixes concerns. | |
| You decide | Claude picks. | |

**User's choice:** Separate `photoconsole cluster` command

---

**Q: Incremental re-embedding on re-run?**

| Option | Description | Selected |
|--------|-------------|----------|
| Incremental — skip files with cached embeddings | Fast for ongoing use. | ✓ |
| Full re-run always | Simple but impractical for 100K files. | |
| You decide | Claude picks. | |

**User's choice:** Incremental — only embed files without a cached embedding

---

## LLaVA Scope

| Option | Description | Selected |
|--------|-------------|----------|
| Phase 3: clustering + quality ranking only (no LLaVA) | Ship focused, LLaVA in a future phase. | ✓ |
| Phase 3: LLaVA for auto-picking best shot | Ollama dependency, ROCm setup in this phase. | |
| Phase 3: LLaVA for captioning + indexing | Semantic catalog building now. | |

**User's choice:** No LLaVA in Phase 3.
**Notes:** User explicitly requested that LLaVA (or equivalent local vision model) be noted for a future phase covering: (1) text captions/descriptions per photo, (2) semantic search ("show me fishing photos"), (3) event grouping by scene. Flagged as high-priority future feature.

---

**Q: Cluster output — all photos or only groups with 2+?**

| Option | Description | Selected |
|--------|-------------|----------|
| Only groups with 2+ similar photos | Focused output, no singletons. | ✓ |
| All photos including singletons | Complete but noisier. | |

**User's choice:** Only groups with 2+ similar photos

---

**Q: Cluster results — catalog or report file?**

| Option | Description | Selected |
|--------|-------------|----------|
| Persisted in catalog — cluster_id column | Queryable, persistent, incremental. | ✓ |
| Report file only — CSV/JSON per run | Simpler schema, loses queryability. | |

**User's choice:** Persisted in catalog via cluster_id column on MediaFile

---

## Review Interface

| Option | Description | Selected |
|--------|-------------|----------|
| Terminal review — Rich table + prompt per cluster | Interactive, CLI-native. | ✓ |
| Report only — no interactive prompts | Scriptable, simpler. | |
| Defer interactive review to Phase 5 web UI | Phase 3 = auto-rank only. | |

**User's choice:** Terminal review (Rich table)
**Notes:** User immediately asked "how will I review the actual photos easily?" — can't see images in terminal. Follow-up question added about photo viewing.

---

**Q: How to view actual photos during terminal review?**

| Option | Description | Selected |
|--------|-------------|----------|
| Auto-open top 2-3 candidates in Windows Photos app | User reviews in Photos, returns to terminal. | ✓ |
| Generate HTML report with embedded images | Visual in browser, mark keepers in HTML. | |
| Show file paths only — trust quality scores | No photo opening, fastest. | |

**User's choice:** Auto-open top 2–3 candidates in Windows Photos (os.startfile)

---

**Q: What happens when keeper is confirmed?**

| Option | Description | Selected |
|--------|-------------|----------|
| Flag keeper in catalog (cluster_keeper = True, redundants flagged, deletion manifest) | Catalog-integrated, follows Phase 2 pattern. | ✓ |
| Copy keeper to 'reviewed' folder | External output, no catalog update. | |
| You decide | Claude picks. | |

**User's choice:** Flag in catalog + deletion manifest (CSV + .bat), same pattern as Phase 2

---

## Quality Ranking Signals

| Option | Description | Selected |
|--------|-------------|----------|
| Blur/sharpness (OpenCV Laplacian) | Fast, reliable, no GPU. | ✓ |
| Resolution (pixel dimensions) | Image header decode, already useful. | ✓ |
| EXIF completeness | Already in catalog, zero extra compute. | ✓ |
| Face detection (OpenCV Haar cascades) | Heavier, but important for family photos. | ✓ |

**User's choice:** All four signals

---

**Q: How to combine signals into a ranking score?**

| Option | Description | Selected |
|--------|-------------|----------|
| Weighted score — blur > resolution > faces > EXIF | One float, configurable weights. | ✓ |
| Tiered elimination — eliminate blurry first, then resolution | Deterministic, no floating point. | |
| You decide | Claude picks. | |

**User's choice:** Weighted score with configurable weights
**Notes:** User provided exact weights:
- Sharpness: 45%
- Resolution: 30%
- Faces: 15%
- EXIF completeness: 10%
Normalize to 0–100. Weights configurable in config.yaml. Individual component scores shown in review table.

---

**Q: Store quality scores in catalog or compute on-demand?**

| Option | Description | Selected |
|--------|-------------|----------|
| Stored in catalog columns — incremental | Persistent, queryable, consistent with embedding storage. | ✓ |
| Computed on-demand each run | Simple schema, impractical for large libraries. | |

**User's choice:** Stored in catalog (blur_score, pixel_width, pixel_height, face_count columns) — incremental

---

## Claude's Discretion

- CLIP model variant — ViT-B/32 (OpenCLIP) recommended; must be ROCm-compatible
- Clustering algorithm — DBSCAN recommended
- pHash Hamming distance threshold for near-identical — default ≤ 10
- Signal normalization formula — min-max or percentile-based
- SQLite migration approach for new columns

## Deferred Ideas

- **LLaVA integration (high-priority future phase)**: captioning, semantic search, event grouping, AI picking. User explicitly wants this — should be a named phase in the roadmap.
- **Video quality ranking**: different signals needed (bitrate, stabilization). Defer.
- **Web UI for cluster review**: Phase 5 will be a much better surface for visual review (thumbnails, side-by-side).
- **User-adjustable weights at review time**: configurable in config.yaml is sufficient for now.
