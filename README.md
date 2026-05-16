# PhotoConsole

Local-first CLI tool for scanning, cataloging, and deduplicating personal photo and video libraries across local drives and network storage.

## Features

- Recursive scanning of local folders and rclone/NAS sources
- SHA-256 hashing for exact duplicate detection
- EXIF metadata extraction (date taken, GPS, camera model, orientation)
- Video metadata extraction via ffprobe
- SQLite catalog with incremental re-scan (unchanged files skipped automatically)
- Files with errors are retried on every scan
- Configurable file extension filtering
- Parallel hashing with configurable worker count

## Requirements

- Python 3.12+
- [ffmpeg/ffprobe](https://ffmpeg.org/download.html) — for video metadata extraction
- [rclone](https://rclone.org/install/) — only if scanning rclone remotes

## Installation

```bash
git clone https://github.com/jeffreylee7971/photoconsole.git
cd photoconsole
pip install -e .
```

## Quick Start

1. Copy the example config and edit it to match your setup:

```bash
copy config.example.yaml config.yaml
```

2. Edit `config.yaml` — set `catalog_path` and add your photo sources:

```yaml
catalog_path: ~/.photoconsole/catalog.db

sources:
  - name: "My Photos"
    type: local
    path: C:\Users\you\Pictures

  - name: "NAS Photos"
    type: local
    path: "J:\\Photos"

hashing:
  max_workers: 8
```

3. Run a scan:

```bash
photoconsole scan --config config.yaml
```

4. Re-run any time — unchanged files are skipped automatically:

```
photoconsole v0.1.0  |  2026-05-16 12:00:00
Scan complete in 87.0s
  Total candidates : 163241
  Cataloged        : 1842
  Skipped          : 161399
  Errored          : 0
```

## Supported File Types

**Photos:** `.jpg` `.jpeg` `.png` `.gif` `.heic` `.heif` `.raw` `.cr2` `.cr3` `.nef` `.arw` `.dng` `.tiff` `.tif` `.bmp` `.webp`

**Videos:** `.mp4` `.mov` `.avi` `.mkv` `.wmv` `.flv` `.m4v` `.3gp`

## Catalog Report

Run at any time (safe during an active scan):

```bash
python catalog-report.py
```

Shows status breakdown, file counts by extension, counts by source, and duplicate groups.

## Roadmap

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Scanning & cataloging foundation | ✅ Complete |
| 2 | Deduplication & consolidation | 🔜 Next |
| 3 | Visual clustering & AI integration (local LLaVA) | ⏳ Planned |
| 4 | Immich & PhotoPrism integration | ⏳ Planned |
| 5 | Web UI | ⏳ Planned |

## License

MIT
