# Phase 2: Deduplication & Consolidation - Context

**Gathered:** 2026-05-16
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 2 delivers exact duplicate detection from the catalog (by SHA-256 hash), and safe consolidation of all media into a single date-organized master library on D:. 

The two core operations are:
1. **Pull**: Copy cloud-only files (not yet on D:) to the D: organized library
2. **Deduplicate**: For files that exist on multiple sources, D: copy is canonical; cloud copies are flagged as redundant backups

PhotoConsole never deletes. It copies verified files to the destination, then produces a deletion manifest (CSV + Windows `.bat`) that the user reviews and runs manually.

</domain>

<decisions>
## Implementation Decisions

### Primary Copy Selection
- **D-01:** D: source = highest priority. When the same hash exists on D: and cloud sources, the D: copy is the definitive keeper. No copy operation needed for these.
- **D-02:** Cloud-only files (hash not found on any D: source) are "missing from master" — consolidation copies one instance to D: organized by date.
- **D-03:** When multiple cloud copies of the same hash exist (e.g., OneDrive AND Amazon Photos both have it), pick any one (they are identical by hash). Source selection order for tie-breaking: Claude's discretion (e.g., first source in config order).
- **D-04:** Source priority is configured as an ordered list of source names in config (e.g., `["D: SSD", "OneDrive", "Amazon Photos", "iCloud"]`). The highest-ranked source with a copy wins.

### Destination Folder Structure
- **D-05:** Primary folder structure: `YYYY/MM/filename.ext` (month-level). Example: `D:\PhotoLibrary\2023\06\IMG_1234.jpg`.
- **D-06:** Files with no `date_taken` (NULL EXIF) fall back to `unknown/YYYY/MM/filename.ext`, using file `mtime` for the YYYY/MM portion.
- **D-07:** Destination root is a user-configured path (e.g., `D:\PhotoLibrary\`) added to config as `consolidation.destination_path`. Existing D: folder structure is untouched.

### Conflict Resolution at Destination
- **D-08:** If two different files (different hashes) want the same destination path, auto-rename the second with a numeric suffix: `IMG_1234_2.jpg`, `IMG_1234_3.jpg`, etc.
- **D-09:** If the same file (same hash) already exists at the destination (idempotent re-run), skip the copy. Log it as "already present."

### Redundant Copy Lifecycle (Post-Consolidation)
- **D-10:** After copying each file to the destination, re-hash the destination file and compare to the catalog hash. Only if hashes match is the file considered successfully consolidated.
- **D-11:** Successful copies are added to a **deletion manifest CSV**: columns `original_path`, `hash`, `destination_path`, `source_name`.
- **D-12:** A **Windows `.bat` file** is generated alongside the CSV with `del /f "original_path"` commands for each verified original. User reviews and runs manually.
- **D-13:** The tool never executes deletions itself. All destructive operations are the user's responsibility via the generated manifest/script.

### Report & Audit
- **D-14:** `photoconsole report` shows duplicate groups (same hash, multiple paths), grouped by hash. Columns: hash (short), count, total_size, sources, date_taken range.
- **D-15:** All consolidation operations are logged to `consolidation.log` (append-mode): timestamp, operation (copy/skip/error), source_path, destination_path, hash, outcome.
- **D-16:** Dry-run mode (`--dry-run`) shows the full plan (what would be copied, what would be in the manifest) without writing any files or generating the `.bat`. This is the "verify visually" step.

### Config Extensions
- **D-17:** New `consolidation` section in YAML config:
  ```yaml
  consolidation:
    destination_path: D:\PhotoLibrary
    source_priority:
      - "D: SSD"
      - OneDrive
      - Amazon Photos
      - iCloud
  ```

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project Requirements
- `.planning/REQUIREMENTS.md` — FR3 (exact duplicate detection), FR4 (safe consolidation), FR5 (CLI commands: report, plan-consolidation, consolidate), NFR1 (safety/data integrity)
- `.planning/ROADMAP.md` — Phase 2 deliverables, success criteria, and deferred items

### Existing Codebase (Phase 1)
- `photoconsole/catalog/models.py` — MediaFile ORM model; `hash` column (line 68) is already SHA-256 indexed for Phase 2 dedup; `source_name`, `source_type`, `date_taken`, `mtime` all available
- `photoconsole/catalog/db.py` — existing DB session factory, `upsert_many`, `should_skip`; Phase 2 adds dedup queries on top of this
- `photoconsole/config.py` — existing `Config` and `Source` dataclasses; Phase 2 extends `Config` with `consolidation` section
- `photoconsole/cli.py` — existing `main` click group; Phase 2 adds `report`, `plan-consolidation`, `consolidate` subcommands following same pattern as `scan`
- `photoconsole/hasher.py` — `process_files` and SHA-256 logic; Phase 2 reuses hashing for post-copy verification

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `photoconsole/catalog/models.py:MediaFile.hash` — already indexed (`index=True`), ready for `GROUP BY hash HAVING COUNT(*) > 1` dedup queries
- `photoconsole/hasher.py:process_files` — parallel SHA-256 hashing; reuse for post-copy hash verification (single file, not batch)
- `photoconsole/config.py:load_config` — extend to parse `consolidation:` YAML section; follow existing pattern of `hashing_section = raw.get('hashing', {}) or {}`
- `photoconsole/cli.py:main` click group — add `report`, `plan-consolidation`, `consolidate` subcommands; follow `_run_scan` pattern (pure helper + click wrapper)

### Established Patterns
- **Single writer thread**: all DB writes happen on the main thread (T-02-02); dedup queries are read-only, so no change needed; any new catalog writes (e.g., marking files as consolidated) follow same pattern
- **Batch size 50**: `_BATCH_SIZE = 50` in cli.py; apply same batching to copy + verify operations
- **Preflight gates**: check ffprobe/rclone before scan; Phase 2 should check that `consolidation.destination_path` is writable before starting
- **Pure helper + click wrapper**: `_run_scan` is decoupled from click for testability; apply same pattern to `_run_report`, `_run_consolidate`

### Integration Points
- `dedup.py` queries `media_files` table by hash → groups → reports duplicate sets
- `consolidator.py` reads dedup groups + config → produces copy plan → executes copies → writes manifest CSV + `.bat` + `consolidation.log`
- New `consolidation` config section parsed in `config.py`; `consolidation_destination_path`, `source_priority` list added to `Config` dataclass
- `photoconsole report` → calls `dedup.py`
- `photoconsole plan-consolidation` → calls `consolidator.py` in dry-run mode
- `photoconsole consolidate [--dry-run]` → calls `consolidator.py`

</code_context>

<specifics>
## Specific Ideas

- **Windows `.bat` format**: `del /f "C:\path\to\original.jpg"` — one line per file, with a header comment showing generation timestamp and total count
- **Manifest CSV columns**: `original_path`, `hash`, `destination_path`, `source_name` (matches what the user said verbatim)
- **Cloud strategy context**: Amazon Photos = free for photos (keep); Google Drive = videos; iCloud = phone live saves (must pull to D:). The source_priority list in config captures this preference ordering.
- **Verification step**: "verify visibly" = dry-run first (`plan-consolidation`), user reviews output, then runs `consolidate`. No interactive prompts mid-consolidation except the final "Proceed? Y/N" confirmation.

</specifics>

<deferred>
## Deferred Ideas

- **Cloud-specific organization rules**: organizing cloud copies into the same YYYY/MM structure as D: (syncing back to cloud) — deferred to Phase 4 (Immich/PhotoPrism integration or cloud sync phase)
- **rclone mtime for incremental skip**: noted in Phase 1 as deferred; Phase 2 should implement mtime fetching for rclone sources to enable proper incremental skip for cloud-only files
- **Amazon Photos / Google Drive quota management**: routing photos vs videos to specific cloud services — deferred (out of CLI scope, handled externally)
- **Visual verification UI**: Phase 5 web UI for browsing organized library before approving deletions

None — discussion stayed within phase scope for core dedup and consolidation.

</deferred>

---

*Phase: 2 — Deduplication & Consolidation*
*Context gathered: 2026-05-16*
