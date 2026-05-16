# Phase 1: Scanning & Cataloging Foundation - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-16
**Phase:** 1-Scanning & Cataloging Foundation
**Areas discussed:** Error handling, Symlink policy, Config file design, Metadata depth

---

## Error Handling

### Q1: What happens when a file can't be read?

| Option | Description | Selected |
|--------|-------------|----------|
| Skip and log to console | Print a warning, continue scanning | |
| Mark in DB with error status | Record path + error reason in catalog | ✓ |
| Abort on first error | Stop entire scan if any file fails | |

**User's choice:** Mark in DB with error status

---

### Q2: What error information to store?

| Option | Description | Selected |
|--------|-------------|----------|
| Path + error type | status='error', error_type='permission_denied' | ✓ |
| Path + full error message | Raw Python exception message | |
| Path only | Just mark failed, no reason | |

**User's choice:** Path + error type

---

### Q3: Distinguish hash errors from read errors?

| Option | Description | Selected |
|--------|-------------|----------|
| Same treatment for all failures | All go to error status | ✓ |
| Distinguish in error_type field | 'read_error' vs 'hash_error' | |
| You decide | Leave to planner | |

**User's choice:** Same treatment

---

### Q4: Retry behavior on incremental re-scan?

| Option | Description | Selected |
|--------|-------------|----------|
| Always retry error files | Re-attempt every scan; update to 'ok' on success | ✓ |
| Skip unless --retry flag | Only retry if user explicitly requests | |
| You decide | Leave to planner | |

**User's choice:** Always retry error files

---

## Symlink Policy

### Q1: Follow symbolic links?

| Option | Description | Selected |
|--------|-------------|----------|
| Skip symlinks entirely | Safest, avoids cycles and double-counting | ✓ |
| Follow with cycle detection | Track visited inodes to prevent loops | |
| Follow without cycle detection | Simple follow, risky | |

**User's choice:** Skip symlinks entirely

---

### Q2: Log skipped symlinks?

| Option | Description | Selected |
|--------|-------------|----------|
| Silent skip | Don't log | |
| Log with --verbose only | Show when user requests verbose output | ✓ |
| Log all skipped symlinks always | Always report | |

**User's choice:** Log to console with --verbose only

---

## Config File Design

### Q1: How should sources be listed?

| Option | Description | Selected |
|--------|-------------|----------|
| Named list with type + path | `[{name, type, path/remote}]` | ✓ |
| Separate local_paths and rclone_remotes lists | Two distinct top-level keys | |
| Single flat list of paths | Minimal config | |

**User's choice:** Named list with type + path

---

### Q2: Per-source include/exclude overrides?

| Option | Description | Selected |
|--------|-------------|----------|
| Global include/exclude only | One rule set for all sources | ✓ |
| Per-source overrides | Each source can override global filters | |
| No filtering in Phase 1 | Scan everything | |

**User's choice:** Global include/exclude only

---

### Q3: Where is catalog_path configured?

| Option | Description | Selected |
|--------|-------------|----------|
| In config.yaml | `catalog_path: ~/.photoconsole/catalog.db` | ✓ |
| CLI flag only | --catalog passed each run | |
| Fixed default, overridable by flag | Default path, CLI flag overrides | |

**User's choice:** In config.yaml

---

### Q4: Expose max_workers in config?

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, expose max_workers | `hashing.max_workers: 4`, default = CPU count | ✓ |
| Hard-coded defaults only | os.cpu_count() automatically | |
| You decide | Leave to planner | |

**User's choice:** Yes, expose max_workers in config

---

## Metadata Depth

### Q1: Photo metadata to store?

| Option | Description | Selected |
|--------|-------------|----------|
| Basics only | path, hash, size, file dates | |
| Basics + EXIF essentials | + date_taken, camera_model, orientation | |
| Basics + EXIF + GPS | + date_taken, camera_model, orientation, GPS coordinates | ✓ |

**User's choice:** Basics + EXIF essentials + GPS (custom: between options 2 and 3)

---

### Q2: Video metadata to store?

| Option | Description | Selected |
|--------|-------------|----------|
| Basics only | path, hash, size, file dates | |
| Basics + duration + resolution | Run ffprobe | |
| Basics + date_taken + GPS | Embedded creation_time + GPS if available | ✓ |

**User's choice:** Basics + date taken + GPS if available (custom)

---

### Q3: ffprobe as dependency?

| Option | Description | Selected |
|--------|-------------|----------|
| Yes — require ffprobe | Best source of embedded metadata | ✓ |
| Use file system dates as fallback | Graceful degradation if ffprobe missing | |
| File system dates only | Skip ffprobe entirely | |

**User's choice:** Yes — require ffprobe for video metadata

---

### Q4: EXIF library for photos?

| Option | Description | Selected |
|--------|-------------|----------|
| Pillow + piexif | Common Python image library + EXIF handling | ✓ |
| exifread | Lighter weight, read-only | |
| You decide | Leave to planner | |

**User's choice:** Pillow + piexif

---

## Claude's Discretion

- CLI framework (click vs argparse)
- Progress reporting style (tqdm, spinner, plain prints)
- SQLite schema design and indexing details
- Incremental scan marker mechanism
- Exact rclone integration approach (mount vs subprocess vs rclone.py)

## Deferred Ideas

- Per-source include/exclude overrides — raised during config design, deferred to later iteration
- Video resolution + duration metadata — deferred to Phase 3 (quality ranking)
- Full EXIF extraction (ISO, focal length, aperture) — basics + GPS captured now; extended EXIF deferred to Phase 3
- RAW format support (CR2, NEF, ARW) — out of Phase 1 scope
