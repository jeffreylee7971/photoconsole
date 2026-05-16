# PhotoConsole Requirements

**Scope**: MVP (Phase 1–2) covering catalog, deduplication, and consolidation.

## Functional Requirements

### FR1: Multi-Source Scanning

**As a** user  
**I want** to scan multiple photo/video sources (local disks, rclone mounts)  
**So that** I can discover all my media in one place  

**Acceptance Criteria:**
- [ ] Scan local filesystem paths recursively
- [ ] Mount and scan rclone remote paths (Google Drive, OneDrive, Amazon Drive, iCloud)
- [ ] Support configurable source list (file-based config or CLI args)
- [ ] Skip non-image/video files (based on extension or MIME type)
- [ ] Report progress and stats (items scanned, skipped, errors)

**Technical Notes:**
- Use `pathlib` for local paths, `rclone.py` or subprocess for rclone mounts
- Supported formats: JPG, PNG, GIF, MP4, MOV, AVI (configurable)

---

### FR2: Photo/Video Cataloging

**As a** user  
**I want** to catalog all discovered media with metadata  
**So that** I can track and identify each file  

**Acceptance Criteria:**
- [ ] Store for each file: path, hash (SHA256), size, created/modified dates, format
- [ ] Persist catalog to local SQLite or JSON (configurable)
- [ ] Support incremental updates (rescan only changed files)
- [ ] Track source and mount point for each file

**Technical Notes:**
- Hash computation: SHA256 for all files
- Metadata extraction: `Pillow`, `piexif`, or `exifread` for photos; `ffprobe` for videos
- Database: SQLite with indexed hash column for fast lookup

---

### FR3: Exact Duplicate Detection

**As a** user  
**I want** to identify exact duplicates across all sources  
**So that** I know which files are redundant  

**Acceptance Criteria:**
- [ ] Compare file hashes to detect duplicates
- [ ] Group duplicates by unique hash
- [ ] Report duplicate groups with file count and total redundant size
- [ ] Mark "primary" copy (keep) vs. "redundant" copies (candidate for deletion)
- [ ] Provide human-readable duplicate report

**Technical Notes:**
- Primary copy selection: oldest file, highest quality (by resolution/bitrate), or user preference
- Output: CSV or JSON report grouped by hash

---

### FR4: Safe Consolidation

**As a** user  
**I want** to consolidate media into a single master library with safety  
**So that** I can manage and prune from one place  

**Acceptance Criteria:**
- [ ] Plan consolidation: show source → destination mapping, verify no overwrites
- [ ] Dry-run mode: preview all changes without modifying files
- [ ] Organize by date (YYYY/MM/DD or YYYY-MM structure)
- [ ] Handle naming conflicts (timestamp, sequence number, or user choice)
- [ ] Copy (never move) primary files to backup library
- [ ] Require explicit confirmation before any write operation
- [ ] Log all operations for audit trail

**Technical Notes:**
- Consolidation target: single backup drive path (configured at startup)
- Conflict resolution: `{filename}_{timestamp}.{ext}` or user-configurable pattern
- Safety: all operations logged to `consolidation.log` with rollback info

---

### FR5: CLI Interface

**As a** user  
**I want** a clean, intuitive command-line interface  
**So that** I can automate and repeat workflows  

**Acceptance Criteria:**
- [ ] `photoconsole scan --config <config.yaml>` — scan all sources
- [ ] `photoconsole report` — show duplicate report
- [ ] `photoconsole plan-consolidation` — preview consolidation plan
- [ ] `photoconsole consolidate --dry-run` — test without writing
- [ ] `photoconsole consolidate` — execute consolidation with confirmation
- [ ] Global flags: `--verbose`, `--quiet`, `--output-format` (json/csv/text)

**Technical Notes:**
- Framework: `click` or `argparse`
- Config format: YAML (easy to edit and version-control)
- Status output: progress bars, summaries, error messages

---

### FR6: Performance & Scalability

**As a** user  
**I want** fast scanning and hashing of 10K–100K items  
**So that** workflows remain interactive  

**Acceptance Criteria:**
- [ ] Scan 100K items in < 30 minutes (depends on hardware and network)
- [ ] Parallel hashing to use multi-core efficiently
- [ ] Incremental scanning (skip unchanged files)
- [ ] Memory-efficient: handle large file lists without OOM

**Technical Notes:**
- Parallel hashing: `concurrent.futures.ThreadPoolExecutor` or `multiprocessing`
- Incremental: track file modification times and skip if unchanged
- Batch operations: process in chunks for efficiency

---

## Non-Functional Requirements

### NFR1: Safety & Data Integrity
- No data loss: all files are copied, never deleted by PhotoConsole
- Atomic operations: consolidation confirms before any writes
- Audit trail: log all operations with timestamps and hashes

### NFR2: Privacy & Security
- No uploads to cloud services (local-first)
- No external API calls for core functionality
- Credentials: rclone handles auth (existing infrastructure)

### NFR3: Usability
- Clear error messages and recovery steps
- Dry-run mode for confidence before execution
- Config file example included in docs

### NFR4: Maintainability
- Modular design: separate scanning, hashing, reporting, consolidation
- Testable: unit tests for core logic
- Documented: README with setup, usage, and troubleshooting

---

## Out of Scope (Deferred)

- ❌ Visual similarity clustering (Phase 3)
- ❌ Immich/PhotoPrism integration (Phase 4)
- ❌ Web UI or mobile app (Phase 4+)
- ❌ Automated deletion (user must delete manually from consolidated library)
- ❌ Advanced ranking (e.g., by image quality, people detected, etc.)

---

## Assumptions

- User has `rclone` installed and configured for cloud mounts
- Backup drive has sufficient free space for consolidated library
- Medium library size (10K–100K items)
- User is comfortable with CLI tools

---

**Created**: 2026-05-16
