# Phase 1: Scanning & Cataloging Foundation - Context

**Gathered:** 2026-05-16
**Status:** Ready for planning

<domain>
## Phase Boundary

Deliver a scanning engine that discovers media files from local filesystem paths and rclone mounts, computes SHA256 hashes, extracts key metadata (EXIF for photos, embedded timestamps + GPS for videos), and persists everything to a SQLite catalog. Accessed via `photoconsole scan --config config.yaml`.

Phase 1 ends when: files can be discovered, hashed, cataloged, and failures are tracked. Deduplication and consolidation are Phase 2.

</domain>

<decisions>
## Implementation Decisions

### Error Handling
- **D-01:** Files that fail to read or hash are stored in the catalog with `status='error'` and an `error_type` field (e.g., `'permission_denied'`, `'read_error'`). They are NOT skipped or discarded.
- **D-02:** All failure types are treated uniformly — no distinction between "couldn't open" vs "hash computation failed". One error_type field covers all cases.
- **D-03:** On incremental re-scan, always retry files with `status='error'`. If the retry succeeds, update to `status='ok'`. This handles transient failures (locked files, temporary permission issues) automatically.

### Symlink Policy
- **D-04:** Do not follow symbolic links. Skip them entirely during directory traversal.
- **D-05:** Skipped symlinks are silent by default. Log them only when `--verbose` flag is active. They are never stored in the catalog.

### Config File Structure
- **D-06:** Sources are a named list with `type` and path fields:
  ```yaml
  sources:
    - name: "NAS Photos"
      type: local
      path: /mnt/nas/photos
    - name: "Google Drive"
      type: rclone
      remote: gdrive:
  ```
  `type: local` uses pathlib; `type: rclone` uses the rclone integration.
- **D-07:** File filtering (include/exclude by extension or pattern) is global — one set of rules applied to all sources. No per-source overrides in Phase 1.
- **D-08:** `catalog_path` is defined in config.yaml (e.g., `catalog_path: ~/.photoconsole/catalog.db`). Not a CLI flag; the config file is the single source of truth for the DB path.
- **D-09:** `hashing.max_workers` is configurable in config.yaml. Default = `os.cpu_count()`. Allows power users to tune for their hardware.

### Metadata — Photos (JPG, PNG, GIF)
- **D-10:** Extract and store: `path`, `hash` (SHA256), `size` (bytes), `mtime`, `ctime`, plus EXIF fields: `date_taken`, `camera_model`, `orientation`, `gps_lat`, `gps_lon`. GPS coordinates stored as decimal degrees.
- **D-11:** Use **Pillow + piexif** for EXIF extraction. If EXIF is absent or malformed, those fields are NULL — not an error.

### Metadata — Videos (MP4, MOV, AVI)
- **D-12:** Extract and store: `path`, `hash` (SHA256), `size` (bytes), `mtime`, `ctime`, plus: `date_taken` (from embedded `creation_time`), `gps_lat` / `gps_lon` if present in container metadata.
- **D-13:** Use **ffprobe** (part of ffmpeg) as a required system dependency for video metadata extraction. If ffprobe is not installed, the scan command should error clearly with install instructions. Video resolution and duration are deferred to Phase 3.

### Claude's Discretion
- CLI framework (click vs argparse) — planner's choice
- Progress reporting style (tqdm, custom spinner, plain prints) — planner's choice
- SQLite schema design and indexing details — planner's choice
- Incremental scan marker mechanism (track by mtime, inode, or DB timestamp) — planner's choice
- Exact rclone integration approach (mount vs subprocess vs rclone.py) — planner's choice

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project Scope & Requirements
- `.planning/PROJECT.md` — Vision, problem statement, scope, success criteria, key constraints
- `.planning/REQUIREMENTS.md` — FR1–FR6 (functional), NFR1–NFR4 (non-functional), technical notes, out-of-scope items
- `.planning/ROADMAP.md` — Phase 1 features, deliverables, success criteria, decision log

No external specs or ADRs exist yet — requirements are fully captured in the documents above and decisions above.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- None — this is a greenfield project. No existing code to reference.

### Established Patterns
- None yet — Phase 1 establishes the patterns that subsequent phases will follow.

### Integration Points
- Phase 2 (deduplication) will query the catalog built here — schema design must account for hash-based grouping queries.
- Phase 4 (Immich/PhotoPrism) will ingest from this catalog — `source` and `source_name` columns will be important.

</code_context>

<specifics>
## Specific Ideas

- Config example file should be included in the repo as `config.example.yaml` — users need a reference to get started.
- `photoconsole scan` should show a final summary: total files scanned, files cataloged, files skipped (non-media), files errored, time elapsed.
- The `error_type` values should be a defined set (enum or constants), not free-form strings, so they can be filtered and retried reliably.

</specifics>

<deferred>
## Deferred Ideas

- **Per-source include/exclude overrides** — raised during config design discussion. Useful but adds complexity; defer to a later iteration.
- **Video resolution + duration metadata** — skipped for Phase 1; this data is useful for quality ranking in Phase 3 clustering.
- **Full EXIF extraction** (ISO, focal length, aperture, white balance) — basics + GPS captured now; extended EXIF can be added if needed for ranking in Phase 3.
- **RAW format support** (CR2, NEF, ARW) — not in Phase 1 scope; would require additional libraries (rawpy).

</deferred>

---

*Phase: 1-Scanning & Cataloging Foundation*
*Context gathered: 2026-05-16*
