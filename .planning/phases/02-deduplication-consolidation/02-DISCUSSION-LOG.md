# Phase 2: Deduplication & Consolidation - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-16
**Phase:** 02-deduplication-consolidation
**Areas discussed:** Primary copy selection, Destination folder structure, Redundant copy lifecycle, Destination filename conflict handling

---

## Primary Copy Selection

| Option | Description | Selected |
|--------|-------------|----------|
| Source priority | Rank sources in config; highest-ranked wins | ✓ |
| Oldest date_taken | Keep earliest EXIF date as most original | |
| Largest file size | Biggest copy as quality proxy | |
| You decide | Claude picks source priority | |

**User's choice:** Source priority — D: SSD wins. Cloud-only files are pulled to D:.

**Notes:** User clarified the mental model: D: = master of everything. Cloud services (OneDrive, Amazon Photos, iCloud, Google Drive) are backup/sync tiers, not co-equal sources. iCloud specifically contains phone photos not yet transferred to D:. User wants to eventually be able to delete cloud copies to save subscription costs, then re-sync selectively. Amazon Photos is free for photos (keep); videos may go to Google Drive. NAS will eventually mirror D: exactly. When cloud-only files exist (e.g., phone photos only on iCloud), consolidation copies them to D:.

**Follow-up Q — cloud-only files:** Copy them to D: (pull-to-master). ✓

**Follow-up Q — destination on D::** Configured destination path (e.g., `D:\PhotoLibrary\`). D: is currently disorganized. User wants a NEW organized copy created, then to manually verify and delete old originals. ✓

---

## Destination Folder Structure

| Option | Description | Selected |
|--------|-------------|----------|
| YYYY/MM/filename | Month-level grouping | ✓ |
| YYYY/MM/DD/filename | Day-level grouping | |
| YYYY-MM/filename | Flat month dirs | |

**User's choice:** `YYYY/MM/filename`

**Notes:** Preferred for navigability in Windows Explorer without hundreds of tiny day folders.

**Follow-up Q — null date_taken fallback:**

| Option | Description | Selected |
|--------|-------------|----------|
| undated/filename | Flat undated folder | |
| YYYY/MM from mtime | Use file modification time | |
| unknown/YYYY/MM/filename from scan date | Proxy date under `unknown/` | ✓ |

**User's choice:** `unknown/YYYY/MM/filename` — uses file mtime for the YYYY/MM portion when date_taken is null.

---

## Redundant Copy Lifecycle

| Option | Description | Selected |
|--------|-------------|----------|
| Deletion manifest CSV | original_path, hash, destination_path, source | ✓ |
| Shell script to delete | Generate .sh/.bat to run | ✓ (Windows .bat) |
| Just show in report | No file generated | |

**User's choice:** Both CSV manifest AND Windows `.bat` file (user said "1 and 2, windows .bat").

**Notes:** User wants to review before deleting. The `.bat` approach gives a script they can open, inspect, and run in their own time. Critical for irreplaceable family photos.

**Follow-up Q — hash verification after copy:**

| Option | Description | Selected |
|--------|-------------|----------|
| Yes — verify hash after copy | Re-hash destination, compare to catalog | ✓ |
| No — trust the OS copy | Skip post-copy verification | |

**User's choice:** Yes — verify hash after copy before adding original to deletion manifest.

---

## Destination Filename Conflict Handling

| Option | Description | Selected |
|--------|-------------|----------|
| Auto-rename with suffix | IMG_1234_2.jpg, _3.jpg, etc. | ✓ |
| Pause and report conflicts first | Dry-run detects, refuses to proceed | |
| Rename with timestamp suffix | IMG_1234_20240615T143022.jpg | |

**User's choice:** Auto-rename with numeric suffix.

**Follow-up Q — same hash already at destination (idempotent re-run):**

| Option | Description | Selected |
|--------|-------------|----------|
| Skip — already consolidated | Hash check confirms identical, skip | ✓ |
| Overwrite anyway | Re-copy regardless | |
| Abort for that file | Stop and report | |

**User's choice:** Skip — idempotent re-runs.

---

## Claude's Discretion

- When multiple cloud copies of the same hash exist (e.g., same photo on OneDrive AND Amazon Photos), pick any one to pull — they are identical by hash. Claude picks based on config source order.
- `consolidation.log` format (append-mode text log) — Claude's discretion on exact format as long as it captures timestamp, operation, paths, hash, outcome.

## Deferred Ideas

- Cloud-specific organization (syncing organized structure back to cloud services) → Phase 4
- rclone mtime for proper incremental skip on cloud sources → Phase 2 implementation detail (should be included)
- Amazon Photos / Google Drive quota routing → handled externally
- Visual verification web UI → Phase 5
