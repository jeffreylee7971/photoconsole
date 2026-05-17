# Phase 3: Visual Clustering & AI Integration - Pattern Map

**Mapped:** 2026-05-17
**Files analyzed:** 12 new/modified files
**Analogs found:** 12 / 12

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `photoconsole/clustering.py` | service | batch + transform | `photoconsole/dedup.py` + `photoconsole/hasher.py` | role-match |
| `photoconsole/quality.py` | service | batch + transform | `photoconsole/hasher.py` | exact |
| `photoconsole/catalog/models.py` | model | CRUD | self (extend) | self |
| `photoconsole/catalog/db.py` | utility | CRUD | self (extend) | self |
| `photoconsole/config.py` | config | transform | self (extend) | self |
| `photoconsole/cli.py` | controller | request-response | self (extend) | self |
| `tests/test_clustering.py` | test | batch | `tests/test_dedup.py` | exact |
| `tests/test_quality.py` | test | batch | `tests/test_hasher.py` | exact |
| `tests/test_config_phase3.py` | test | transform | `tests/test_config.py` | exact |
| `tests/test_catalog_phase3.py` | test | CRUD | `tests/test_catalog.py` | exact |
| `tests/test_cli_phase3.py` | test | request-response | `tests/test_cli_phase2.py` | exact |
| `tests/test_eval_clustering.py` | test | batch | `tests/test_dedup.py` (structure) | role-match |

---

## Pattern Assignments

---

### `photoconsole/clustering.py` (service, batch + transform)

**Analogs:** `photoconsole/dedup.py` (dataclass pattern) + `photoconsole/hasher.py` (ThreadPoolExecutor pattern) + `photoconsole/consolidator.py` (manifest pattern)

**Imports pattern** — copy from `dedup.py` lines 1-40 and `consolidator.py` lines 42-53:
```python
"""Visual similarity clustering for PhotoConsole.

Public API
----------
load_clip_model()              -- load ViT-B-32 once; returns (model, preprocess, tokenizer)
embed_images(paths, model, ...) -- batch CLIP embeddings; returns np.ndarray (N, 512)
compute_phash(path)             -- imagehash.phash for one file; returns str hex
build_phash_groups(session)     -- group files by pHash Hamming <= threshold
cluster_embeddings(embeddings)  -- DBSCAN on cosine distance matrix; returns labels array
cluster_embeddings_sparse(embeddings, eps) -- NearestNeighbors radius graph for N > 50K
write_cluster_manifest(rows, dest_dir)     -- CSV + .bat deletion manifest
"""
from __future__ import annotations

import csv
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import imagehash
import numpy as np
from PIL import Image
from sklearn.cluster import DBSCAN
from sklearn.metrics import pairwise

from photoconsole.catalog.models import MediaFile

logger = logging.getLogger(__name__)
```

**ClusterGroup dataclass** — copy structure from `dedup.py` lines 42-62:
```python
@dataclass
class ClusterGroup:
    """A set of catalog entries assigned the same cluster_id by DBSCAN.

    Follows the DuplicateGroup pattern from dedup.py.
    """
    cluster_id: int
    members: list[MediaFile]        # ALL members; sorted by quality_score desc
    keeper: MediaFile               # auto-pick: highest quality_score
    redundants: list[MediaFile]     # all others
    component_scores: dict[str, dict]
    # Format: {path_str: {sharpness, resolution, faces, exif, combined}}
```

**Core parallel pattern** — copy from `hasher.py` lines 154-212 (`process_files`):
```python
def embed_images(
    paths: list[str],
    model,
    preprocess,
    device: str,
    batch_size: int = 32,
) -> np.ndarray:
    """Compute CLIP embeddings in batches. Model loaded ONCE by caller."""
    # No ThreadPoolExecutor here — GPU/CPU inference is single-threaded.
    # Use plain loop with rich.progress.track() for progress.
    all_embeddings = []
    for i in range(0, len(paths), batch_size):
        batch_paths = paths[i : i + batch_size]
        images = []
        for p in batch_paths:
            try:
                img = preprocess(Image.open(p).convert("RGB"))
                images.append(img)
            except (OSError, Exception):
                # Corrupt/missing: append zero vector (AI-SPEC Section 6 guardrail)
                images.append(preprocess(Image.new("RGB", (224, 224))))
        import torch
        tensor = torch.stack(images).to(device)
        with torch.no_grad():
            embs = model.encode_image(tensor)
            embs = embs / embs.norm(dim=-1, keepdim=True)  # L2 normalize
        all_embeddings.append(embs.cpu().numpy())
    return np.vstack(all_embeddings)
```

**pHash worker** — follows `hasher.py` `process_file` pattern of returning a dict from worker:
```python
def _compute_phash_worker(path: str) -> dict:
    """Called from ThreadPoolExecutor. Returns dict only — no DB writes."""
    try:
        img = Image.open(path)
        h = imagehash.phash(img, hash_size=8)
        return {"path": path, "phash": str(h), "error": None}
    except Exception as exc:
        return {"path": path, "phash": None, "error": str(exc)}
```

**Manifest pattern** — copy from `consolidator.py` lines 335-392 (`write_manifest`), adapting columns:
```python
# Phase 3 CSV columns differ from Phase 2 — no destination_path
_CLUSTER_MANIFEST_FIELDS = [
    "original_path",
    "hash",
    "source_name",
    "cluster_id",
    "quality_score",
]

def write_cluster_manifest(rows: list[dict], dest_dir: Path) -> tuple[Path, Path]:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = dest_dir / f"cluster_deletion_manifest_{ts}.csv"
    bat_path = dest_dir / f"cluster_delete_redundants_{ts}.bat"

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_CLUSTER_MANIFEST_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    # BAT format: identical to consolidator.write_manifest (lines 374-391)
    with open(bat_path, "w", encoding="utf-8-sig", newline="") as f:
        f.write("@echo off\r\n")
        f.write("chcp 65001 >nul\r\n")
        f.write(f":: PhotoConsole cluster deletion manifest — generated {ts}\r\n")
        f.write(f":: Total redundant files: {len(rows)}\r\n")
        f.write(":: Review carefully before running. Deletions are permanent.\r\n")
        f.write("\r\n")
        for row in rows:
            orig = row["original_path"]
            if row.get("source_type", "local") == "rclone":
                f.write(f":: rclone deletefile {orig}\r\n")
            else:
                f.write(f'del /f "{orig}"\r\n')

    return (csv_path, bat_path)
```

---

### `photoconsole/quality.py` (service, batch + transform)

**Analog:** `photoconsole/hasher.py` — exact role match (parallel per-file CPU processing, returns result dicts to main thread)

**Imports pattern** — copy from `hasher.py` lines 1-19:
```python
"""Per-image quality score computation for PhotoConsole.

Public API
----------
compute_quality_scores(paths, max_workers) -- parallel quality pass; yields result dicts
_compute_quality(path)                     -- worker: blur + dims + faces; returns dict
normalize_scores(results)                  -- min-max normalize each signal to [0,1]
compute_combined_score(normalized, weights) -- weighted sum * 100
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Iterator, Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# Haar cascade shipped with opencv-python-headless — no extra download
_FACE_CASCADE = cv2.CascadeClassifier(
    cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
)
```

**Worker pattern** — copy from `hasher.py` lines 44-151 (`process_file`):
```python
def _compute_quality(path: str) -> dict:
    """Compute quality signals for one image. Called from ThreadPoolExecutor.

    Returns result dict only — never writes to DB (T-02-02).
    """
    result: dict = {
        "path": path,
        "blur_score": None,
        "pixel_width": None,
        "pixel_height": None,
        "face_count": None,
        "error": None,
    }
    try:
        img_bgr = cv2.imread(path)
        if img_bgr is None:
            result["error"] = "cv2.imread returned None"
            return result
        gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
        result["blur_score"] = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        h, w = img_bgr.shape[:2]
        result["pixel_width"] = w
        result["pixel_height"] = h
        faces = _FACE_CASCADE.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5)
        result["face_count"] = len(faces)
    except Exception as exc:
        result["error"] = str(exc)
    return result
```

**Parallel orchestration** — copy from `hasher.py` lines 154-212 (`process_files`):
```python
def compute_quality_scores(
    paths: list[str],
    max_workers: int,
    progress_cb: Callable[[int, int], None] | None = None,
) -> Iterator[dict]:
    """Parallel quality computation. Yields result dicts to main thread for DB writes."""
    total = len(paths)
    completed = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_path = {executor.submit(_compute_quality, p): p for p in paths}
        for future in as_completed(future_to_path):
            path = future_to_path[future]
            try:
                result = future.result()
            except Exception as exc:
                result = {"path": path, "blur_score": None, "pixel_width": None,
                          "pixel_height": None, "face_count": None, "error": str(exc)}
            completed += 1
            yield result
            if progress_cb is not None:
                progress_cb(completed, total)
```

---

### `photoconsole/catalog/models.py` (model, CRUD — EXTEND)

**Analog:** self — extend following existing `mapped_column` pattern

**New columns to add** — follow the style of existing nullable columns (lines 59-88):
```python
# --- Phase 3: Quality signals (D-06, D-07) ---
from sqlalchemy import Boolean, LargeBinary  # add to existing import line

blur_score: Mapped[Optional[float]] = mapped_column(Float)
pixel_width: Mapped[Optional[int]] = mapped_column(Integer)
pixel_height: Mapped[Optional[int]] = mapped_column(Integer)
face_count: Mapped[Optional[int]] = mapped_column(Integer)

# --- Phase 3: Cluster assignments (D-06) ---
cluster_id: Mapped[Optional[int]] = mapped_column(Integer)
cluster_keeper: Mapped[Optional[bool]] = mapped_column(Boolean)
cluster_redundant: Mapped[Optional[bool]] = mapped_column(Boolean)

# --- Phase 3: Embedding storage (D-02) ---
embedding_blob: Mapped[Optional[bytes]] = mapped_column(LargeBinary)
phash: Mapped[Optional[str]] = mapped_column(String(16))  # imagehash hashsize=8 hex
```

**Import additions** — extend line 18 of `models.py`:
```python
# Before (line 18):
from sqlalchemy import BigInteger, DateTime, Float, Integer, String
# After:
from sqlalchemy import BigInteger, Boolean, DateTime, Float, Integer, LargeBinary, String
```

**Critical:** `LargeBinary` must be declared in the ORM model or `embedding_blob.isnot(None)` queries behave unexpectedly in SQLAlchemy 2.0. Use `.is_(None)` and `.isnot(None)` — not `== None`.

---

### `photoconsole/catalog/db.py` (utility, CRUD — EXTEND)

**Analog:** self — extend following the existing engine factory structure

**Migration helper** — add after line 89 (`Base.metadata.create_all(engine)`):
```python
from sqlalchemy import text  # add to existing sqlalchemy import

_PHASE3_COLUMNS: list[tuple[str, str]] = [
    ("cluster_id",        "INTEGER"),
    ("cluster_keeper",    "BOOLEAN"),
    ("cluster_redundant", "BOOLEAN"),
    ("blur_score",        "REAL"),
    ("pixel_width",       "INTEGER"),
    ("pixel_height",      "INTEGER"),
    ("face_count",        "INTEGER"),
    ("embedding_blob",    "BLOB"),
    ("phash",             "TEXT"),
]

def _ensure_phase3_columns(engine: "Engine") -> None:
    """Idempotent: add Phase 3 columns to media_files if absent.

    SQLAlchemy create_all() does NOT add missing columns to existing tables
    (verified empirically). This function checks PRAGMA table_info and issues
    ALTER TABLE only for absent columns.
    """
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
```

**Call site** — in `create_catalog_engine()`, after `Base.metadata.create_all(engine)` (line 89):
```python
    Base.metadata.create_all(engine)
    _ensure_phase3_columns(engine)   # <-- ADD THIS LINE
    return engine
```

**Partial upsert pattern** — `upsert_media_file()` already supports this (lines 113-163). No modifications needed. Pass only the columns to update:
```python
# Quality score update (partial — only these 5 columns touched)
upsert_media_file(session, {
    "path": str(file_path),
    "blur_score": result["blur_score"],
    "pixel_width": result["pixel_width"],
    "pixel_height": result["pixel_height"],
    "face_count": result["face_count"],
})
```

**`_VALID_COLUMNS` note:** Built at import time from `MediaFile.__table__.columns` (line 45-47). Once new columns are added to `models.py`, `_VALID_COLUMNS` automatically includes them. Always update `models.py` first, then `db.py`, then business logic.

---

### `photoconsole/config.py` (config — EXTEND)

**Analog:** self — extend following existing `@dataclass` + `ConsolidationConfig` pattern

**New Pydantic models** — add after `ConsolidationConfig` dataclass (after line 59):
```python
from pydantic import BaseModel, Field, model_validator  # new import

class QualityWeightsConfig(BaseModel):
    """Quality signal weights — must sum to 1.0 (D-08, D-09).

    Follows pydantic v2 BaseModel pattern. Coexists with stdlib @dataclass Config.
    """
    sharpness: float = Field(default=0.45, ge=0.0, le=1.0)
    resolution: float = Field(default=0.30, ge=0.0, le=1.0)
    faces: float = Field(default=0.15, ge=0.0, le=1.0)
    exif_completeness: float = Field(default=0.10, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _weights_sum_to_one(self) -> "QualityWeightsConfig":
        total = self.sharpness + self.resolution + self.faces + self.exif_completeness
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"quality_weights must sum to 1.0, got {total:.6f}")
        return self


class ClusterConfig(BaseModel):
    """Clustering algorithm parameters (D-04).

    Follows pydantic v2 BaseModel pattern.
    """
    eps: float = Field(default=0.25, gt=0.0, lt=2.0)          # DBSCAN epsilon (cosine distance)
    min_samples: int = Field(default=2, ge=2, le=100)          # DBSCAN min_samples
    phash_threshold: int = Field(default=10, ge=0, le=64)      # Hamming distance for pHash pre-filter
    batch_size: int = Field(default=32, ge=1, le=512)          # CLIP embedding batch size
    max_workers: int = Field(default=4, ge=1, le=64)           # ThreadPoolExecutor for quality pass
    model_name: str = Field(default="ViT-B-32")
    model_pretrained: str = Field(default="laion2b_s34b_b79k")
    sparse_threshold: int = Field(default=50_000, ge=1000)     # switch to sparse DBSCAN above this
```

**Extend Config dataclass** — add two fields to `Config` (after line 83):
```python
@dataclass
class Config:
    # ... existing fields unchanged ...
    consolidation: ConsolidationConfig = field(default_factory=ConsolidationConfig)
    cluster: ClusterConfig = field(default_factory=ClusterConfig)             # NEW
    quality_weights: QualityWeightsConfig = field(default_factory=QualityWeightsConfig)  # NEW
```

**Extend `load_config()`** — add after the consolidation section (after line 205), before the final `return Config(...)`:
```python
    from pydantic import ValidationError  # local import — keeps top-level clean

    # --- Optional: cluster section ---
    cluster_section = raw.get("cluster", {}) or {}
    quality_weights_section = raw.get("quality_weights", {}) or {}
    try:
        cluster = ClusterConfig(**cluster_section)
        quality_weights = QualityWeightsConfig(**quality_weights_section)
    except ValidationError as exc:
        raise ValueError(f"Invalid cluster/quality_weights config:\n{exc}") from exc
```

**And pass to Config constructor** — extend the final `return Config(...)` to include `cluster=cluster, quality_weights=quality_weights`.

**Pattern note:** stdlib `@dataclass` holding a pydantic `BaseModel` field is verified working (RESEARCH.md Pattern 8).

---

### `photoconsole/cli.py` (controller, request-response — EXTEND)

**Analog:** self — extend following `_run_scan` / `_run_report` pure-helper pattern exactly

**New imports to add** (after line 58, `logger = logging.getLogger(__name__)`):
```python
# Phase 3 additions
from photoconsole.clustering import (
    load_clip_model, embed_images, compute_phash, build_phash_groups,
    cluster_embeddings, cluster_embeddings_sparse, write_cluster_manifest,
    ClusterGroup,
)
from photoconsole.quality import compute_quality_scores, normalize_scores, compute_combined_score
```

**`_run_cluster()` pure helper** — copy structure from `_run_scan()` (lines 143-297):
```python
def _run_cluster(config_path: str, threshold: float | None = None,
                 verbose: bool = False, quiet: bool = False) -> dict:
    """Execute the full cluster pipeline. Pure — no click API calls.

    Pattern: identical to _run_scan() structure.
    Steps: load config -> engine -> quality pass -> pHash pass ->
           embedding pass -> DBSCAN -> write cluster_id -> summary.
    """
    import time
    start = time.monotonic()
    cfg = load_config(config_path)

    # Preflight: opencv importable (gate — same pattern as ffprobe gate lines 177-184)
    try:
        import cv2  # noqa: F401
    except ImportError:
        raise RuntimeError(
            "opencv-python-headless is required for 'cluster'. "
            "Install: pip install opencv-python-headless"
        )

    engine = create_catalog_engine(cfg.catalog_path)  # runs _ensure_phase3_columns()
    SessionLocal = session_factory(engine)

    # --- Pass 0: quality scores (parallel, same pattern as _run_scan Step 6) ---
    # Query files with NULL blur_score (D-07 incremental)
    # ThreadPoolExecutor via compute_quality_scores()
    # Main thread writes via upsert_media_file() in batches of _BATCH_SIZE
    buffer: list[dict] = []
    # ... (follow _flush_buffer pattern from _run_scan lines 230-243)

    # --- Pass 1: pHash (parallel workers, main thread writes) ---
    # --- Pass 2: CLIP embeddings (single-threaded batch, main thread writes blobs) ---
    # --- Pass 3: DBSCAN clustering (main thread, in-memory) ---
    #     If len(files) > cfg.cluster.sparse_threshold: use cluster_embeddings_sparse()
    # --- Write cluster_id to catalog ---
    # --- Rich end-of-run summary table ---

    elapsed = time.monotonic() - start
    return {
        "files_quality_computed": ...,
        "files_embedded": ...,
        "clusters_found": ...,
        "elapsed_seconds": elapsed,
    }
```

**`_run_review()` pure helper** — copy structure from `_run_report()` (lines 325-353):
```python
def _run_review(config_path: str, verbose: bool = False, quiet: bool = False) -> list[ClusterGroup]:
    """Load pending clusters for review. Pure — no click API calls."""
    cfg = load_config(config_path)
    engine = create_catalog_engine(cfg.catalog_path)
    SessionLocal = session_factory(engine)
    with SessionLocal() as session:
        # Query WHERE cluster_id IS NOT NULL AND cluster_keeper IS NULL
        # Build ClusterGroup list from results
        ...
    return groups
```

**Click command wrapper** — copy from `report` command (lines 439-473), thin wrapper:
```python
@main.command()
@click.option("--config", "config_path", required=True,
              type=click.Path(exists=True, dir_okay=False, readable=True),
              help="Path to the YAML configuration file.")
@click.option("--threshold", default=None, type=float,
              help="DBSCAN epsilon (cosine distance). Overrides config.")
@click.pass_context
def cluster(ctx: click.Context, config_path: str, threshold: float | None) -> None:
    """Compute quality scores and cluster visually similar photos."""
    verbose: bool = ctx.obj["verbose"]
    quiet: bool = ctx.obj["quiet"]
    summary = _run_cluster(config_path, threshold=threshold, verbose=verbose, quiet=quiet)
    if not quiet:
        _print_cluster_summary(summary)
```

**Rich progress pattern** — use `rich.progress.track()` NOT tqdm (RESEARCH.md Q8). Both coexist:
```python
from rich.progress import track
for result in track(compute_quality_scores(paths, max_workers=cfg.cluster.max_workers),
                    total=len(paths), description="Computing quality scores"):
    buffer.append(result)
    if len(buffer) >= _BATCH_SIZE:
        _flush_buffer()
```

**os.startfile pattern** — for review-clusters (D-13):
```python
import os
for path in top_candidates[:3]:
    try:
        os.startfile(str(Path(path).resolve()))
    except OSError:
        from rich.console import Console
        Console().print(f"[yellow]Could not open {path}: no default viewer registered[/]")
```

**Batch flush pattern** — copy from `_run_scan` lines 230-243 exactly:
```python
def _flush_buffer() -> None:
    nonlocal cataloged, errored
    if not buffer:
        return
    with SessionLocal() as session:
        for r in buffer:
            upsert_media_file(session, r)  # partial dict — only cols in r are updated
        session.commit()
    buffer.clear()
```

---

### `tests/test_clustering.py` (test, batch)

**Analog:** `tests/test_dedup.py` — exact structure match (in-memory engine, `_make_engine()` helper, attribute-assignment MediaFile construction)

**Imports and engine helper** — copy from `test_dedup.py` lines 1-28:
```python
"""Unit tests for photoconsole.clustering."""
from __future__ import annotations
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from photoconsole.catalog.models import Base, MediaFile
from photoconsole.clustering import (
    ClusterGroup, compute_phash, embed_images, write_cluster_manifest,
)

def _make_engine():
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    return engine
```

**Fixture generation** — use `tmp_path` + numpy/PIL synthesis (RESEARCH.md Q7):
```python
import numpy as np
from PIL import Image

def _make_sharp_jpg(path, size=(200, 200)):
    arr = np.zeros((*size, 3), dtype=np.uint8)
    arr[::2, ::2] = 255  # checkerboard -> high Laplacian variance (~388183)
    Image.fromarray(arr).save(str(path), "JPEG", quality=95)

def _make_blurry_jpg(path, size=(200, 200)):
    arr = np.full((*size, 3), 128, dtype=np.uint8)
    Image.fromarray(arr).save(str(path), "JPEG", quality=95)

def _make_near_duplicate(source_path, dest_path):
    from PIL import ImageFilter
    img = Image.open(source_path).filter(ImageFilter.GaussianBlur(radius=1))
    img.save(str(dest_path), "JPEG", quality=85)
    # Hamming distance from original: ~2 (well within threshold of 10)
```

**Test structure** — one class per public function, follow `TestUpsert` pattern from `test_catalog.py`:
```python
class TestPHash:
    def test_phash_near_duplicate(self, tmp_path): ...
    def test_phash_different_images(self, tmp_path): ...

class TestEmbedImages:
    def test_embed_determinism(self, tmp_path): ...
    def test_embed_shape(self, tmp_path): ...
    def test_embed_corrupt_file_returns_zero_vector(self, tmp_path): ...

class TestClusterEmbeddings:
    def test_dbscan_labels(self, tmp_path): ...
    def test_dbscan_noise_label_minus_one(self, tmp_path): ...

class TestWriteClusterManifest:
    def test_write_cluster_manifest(self, tmp_path): ...
    def test_bat_del_format(self, tmp_path): ...
    def test_bat_rclone_format(self, tmp_path): ...
```

---

### `tests/test_quality.py` (test, batch)

**Analog:** `tests/test_hasher.py` — exact structure match

**Imports** — copy from `test_hasher.py` + add cv2:
```python
"""Unit tests for photoconsole.quality."""
from __future__ import annotations
import pytest
from photoconsole.quality import _compute_quality, normalize_scores, compute_combined_score
```

**Fixture pattern** — use `conftest.py` `sample_jpg` fixture shape; generate sharp/blurry programmatically:
```python
# Use tmp_path fixture (not committed fixtures) for unit test images
class TestBlurScore:
    def test_blur_score_ordering(self, tmp_path):
        """Sharp image must score higher than blurry image."""
        sharp = tmp_path / "sharp.jpg"
        blurry = tmp_path / "blurry.jpg"
        _make_sharp_jpg(sharp)   # same helper as test_clustering.py
        _make_blurry_jpg(blurry)
        r_sharp = _compute_quality(str(sharp))
        r_blurry = _compute_quality(str(blurry))
        assert r_sharp["blur_score"] > r_blurry["blur_score"]

class TestNormalization:
    def test_quality_score_range(self, tmp_path): ...  # combined in [0, 100]
    def test_weights_applied(self): ...

class TestExifBonus:
    def test_exif_completeness_from_catalog_record(self): ...
    # EXIF bonus is computed from catalog row (date_taken + gps_lat/lon IS NOT NULL)
    # not from the file directly — test with a mock MediaFile dict
```

---

### `tests/test_config_phase3.py` (test, transform)

**Analog:** `tests/test_config.py` — exact structure match (write YAML via helper, assert on exceptions)

**Imports and helper** — copy from `test_config.py` lines 1-18:
```python
"""Tests for Phase 3 config: ClusterConfig and QualityWeightsConfig."""
import textwrap
import pytest
from photoconsole.config import ClusterConfig, QualityWeightsConfig, load_config

def write_yaml(tmp_path, content: str, filename: str = "test_config.yaml"):
    path = tmp_path / filename
    path.write_text(textwrap.dedent(content), encoding="utf-8")
    return str(path)
```

**Validation tests** — follow `TestMissingRequiredKeys` pattern from `test_config.py`:
```python
class TestClusterConfig:
    def test_default_values_are_valid(self): ...
    def test_cluster_config_invalid_eps(self):
        with pytest.raises(ValueError):
            ClusterConfig(eps=5.0)      # gt=0.0, lt=2.0 — 5.0 violates lt=2.0
    def test_cluster_config_invalid_min_samples(self): ...

class TestQualityWeightsConfig:
    def test_weights_sum_validation(self):
        with pytest.raises(ValueError, match="sum to 1.0"):
            QualityWeightsConfig(sharpness=0.5, resolution=0.5, faces=0.5, exif_completeness=0.5)
    def test_valid_weights_load(self): ...

class TestLoadConfigPhase3:
    def test_cluster_section_parsed(self, tmp_path): ...
    def test_quality_weights_section_parsed(self, tmp_path): ...
    def test_missing_cluster_section_uses_defaults(self, tmp_path): ...
```

---

### `tests/test_catalog_phase3.py` (test, CRUD)

**Analog:** `tests/test_catalog.py` — exact structure match (in-memory engine, class-per-feature)

**Migration test** — key test verifying `_ensure_phase3_columns`:
```python
"""Tests for Phase 3 schema migration and partial upsert."""
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session
from photoconsole.catalog.models import Base

def _make_pre_phase3_engine():
    """Engine with only Phase 1/2 columns — simulates upgrade scenario."""
    engine = create_engine("sqlite://", future=True)
    # Create tables WITHOUT the Phase 3 columns by creating the schema
    # before Phase 3 columns are added. Use raw SQL to insert only Phase 1/2 cols.
    Base.metadata.create_all(engine)
    # Drop Phase 3 columns by recreating table with only Phase 1/2 cols
    # OR: just test that _ensure_phase3_columns adds them when absent.
    return engine

class TestPhase3Migration:
    def test_phase3_migration_adds_columns(self, tmp_path):
        """_ensure_phase3_columns() must add all 9 Phase 3 columns."""
        from photoconsole.catalog.db import create_catalog_engine, _ensure_phase3_columns
        db_path = str(tmp_path / "cat.db")
        engine = create_catalog_engine(db_path)  # includes migration call
        with engine.connect() as conn:
            cols = {row[1] for row in conn.execute(text("PRAGMA table_info(media_files)")).fetchall()}
        required = {"cluster_id", "cluster_keeper", "cluster_redundant",
                    "blur_score", "pixel_width", "pixel_height", "face_count",
                    "embedding_blob", "phash"}
        assert required.issubset(cols), f"Missing: {required - cols}"

    def test_migration_is_idempotent(self, tmp_path): ...  # call _ensure_phase3_columns twice

class TestPartialUpsert:
    def test_partial_upsert_quality_cols_only(self): ...
    def test_partial_upsert_embedding_blob(self): ...
    def test_partial_upsert_cluster_assignment(self): ...
```

---

### `tests/test_cli_phase3.py` (test, request-response)

**Analog:** `tests/test_cli_phase2.py` — exact structure match (CliRunner, `_write_config` helper, `_seed_*` DB helper)

**Imports and helpers** — copy from `test_cli_phase2.py` lines 1-79:
```python
"""CLI integration tests for Phase 3: cluster + review-clusters commands."""
from __future__ import annotations
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
from click.testing import CliRunner
from photoconsole.cli import main
from photoconsole.catalog import create_catalog_engine, session_factory, upsert_many

def _write_config(config_path, catalog_path, source_path, **cluster_kwargs):
    """Write a minimal config.yaml with cluster section."""
    # Follow _write_config pattern from test_cli_phase2.py exactly

def _seed_catalog_with_quality(catalog_path, source_path):
    """Insert catalog rows with quality scores and cluster_id assigned."""
    engine = create_catalog_engine(str(catalog_path))
    SessionLocal = session_factory(engine)
    # upsert records with blur_score, pixel_width, cluster_id set
    ...
```

**Integration test pattern** — follow `test_cli_phase2.py` CliRunner invocation:
```python
class TestClusterCommand:
    def test_cluster_skips_cached(self, tmp_path):
        """Files with embedding_blob already set must not be re-embedded."""
        runner = CliRunner()
        # seed catalog with embedding_blob NOT NULL
        # mock embed_images() to track call count
        with patch("photoconsole.clustering.embed_images") as mock_embed:
            result = runner.invoke(main, ["cluster", "--config", str(config_path)])
        assert result.exit_code == 0
        mock_embed.assert_not_called()

    def test_cluster_exit_code_zero_on_success(self, tmp_path): ...

class TestReviewClustersCommand:
    def test_review_keeper_persisted(self, tmp_path):
        """Confirming a keeper must set cluster_keeper=True in catalog."""
        runner = CliRunner()
        with runner.isolated_filesystem():
            # seed cluster with 2 members
            # invoke with input="1\n" (confirm auto-pick)
            result = runner.invoke(main, ["review-clusters", "--config", str(config_path)],
                                   input="1\n")
        assert result.exit_code == 0
        # verify cluster_keeper=True in catalog
```

---

### `tests/test_eval_clustering.py` (test, batch — eval dimensions)

**Analog:** `tests/test_dedup.py` structure + pytest marks pattern (new — no existing eval test)

**Marks registration** — requires addition to `pyproject.toml` `[tool.pytest.ini_options]`:
```toml
markers = [
    "critical: critical eval dimensions -- must pass before any merge",
    "slow: throughput benchmarks -- run manually, not in CI",
]
```

**Test structure**:
```python
"""Eval dimensions for Phase 3 clustering quality.

@pytest.mark.critical -- must pass before any merge (run: pytest -m critical)
@pytest.mark.slow     -- throughput benchmarks (run: pytest -m slow --benchmark-only)
"""
from __future__ import annotations
import pytest

# Programmatic fixture generation (no committed binary fixtures needed for unit tier)

@pytest.mark.critical
class TestClusterPurity:
    def test_cluster_purity(self, tmp_path):
        """Cluster purity >= 0.90 on synthesized ground truth."""
        # Generate 3 burst groups of 5 images each (near-duplicate via GaussianBlur)
        # Run cluster_embeddings() on them
        # Assert: purity = (correctly grouped) / (total) >= 0.90
        ...

@pytest.mark.critical
class TestBurstSequenceRecall:
    def test_burst_sequence_recall(self, tmp_path):
        """Burst capture groups identified at rate >= 90%."""
        ...

@pytest.mark.critical
class TestKeeperPickAccuracy:
    def test_keeper_pick_accuracy(self, tmp_path):
        """Auto-pick (highest quality_score) selects the sharpest image >= 80% of the time."""
        ...

@pytest.mark.critical
def test_exif_absent_quality_ranking(tmp_path):
    """Sharp photo without EXIF must still rank in top 2 vs soft photo with EXIF."""
    # Verify EXIF-absent sharp photo still outranks soft photo with full EXIF
    # (sharpness 45% weight dominates exif 10% weight)
    ...

@pytest.mark.slow
def test_throughput_benchmark(tmp_path, benchmark):
    """10K synthetic files clustered in < 30 minutes."""
    # pytest-benchmark fixture; run with --benchmark-only
    ...
```

---

## Shared Patterns

### Batch Commit (50-record flush) — apply to all DB write loops

**Source:** `photoconsole/cli.py` lines 229-243 (`_flush_buffer`)
**Apply to:** `_run_cluster()` quality pass, embedding pass, cluster assignment pass

```python
_BATCH_SIZE = 50  # already defined at module level in cli.py

buffer: list[dict] = []

def _flush_buffer() -> None:
    if not buffer:
        return
    with SessionLocal() as session:
        for r in buffer:
            upsert_media_file(session, r)
        session.commit()
    buffer.clear()

# In the result loop:
for result in compute_quality_scores(...):
    buffer.append(result)
    if len(buffer) >= _BATCH_SIZE:
        _flush_buffer()
_flush_buffer()  # flush remainder
```

### Single-Writer Thread Assertion — apply to all CLI commands

**Source:** `photoconsole/cli.py` lines 246-249
**Apply to:** `_run_cluster()`, `_run_review()`

```python
import threading
assert threading.current_thread() is threading.main_thread(), (
    "CLI cluster must run on the main thread"
)
```

### Rich Table Pattern — apply to all Phase 3 terminal output

**Source:** `photoconsole/cli.py` lines 382-409 (`_print_report`, text branch)
**Apply to:** `_print_cluster_summary()`, review table in `_run_review()`

```python
from rich.console import Console
from rich.table import Table

table = Table(title="Cluster Review")
table.add_column("Cluster ID", justify="right")
table.add_column("Path", no_wrap=False)
table.add_column("Sharpness", justify="right")
table.add_column("Resolution", justify="right")
table.add_column("Faces", justify="right")
table.add_column("EXIF", justify="right")
table.add_column("Score", justify="right")
table.add_column("", style="green")  # [AUTO-PICK] marker

# For test output capture (Pitfall 7, RESEARCH.md):
# buf = io.StringIO()
# Console(file=buf, force_terminal=True).print(table)
# assert "AUTO-PICK" in buf.getvalue()
Console().print(table)
```

### Click Preflight Gate — apply to `cluster` command

**Source:** `photoconsole/cli.py` lines 173-184 (ffprobe gate)
**Apply to:** `_run_cluster()` — gate on opencv importable, gate on CLIP model reachable

```python
# Same pattern as lines 173-184:
try:
    import cv2  # noqa: F401
except ImportError:
    raise RuntimeError(
        "opencv-python-headless is required for 'cluster'. "
        "Install: pip install opencv-python-headless>=4.9"
    )
```

### In-Memory Engine Helper — apply to all Phase 3 test files

**Source:** `tests/test_catalog.py` lines 173-178 (`_make_in_memory_engine`)
**Apply to:** `test_clustering.py`, `test_quality.py`, `test_catalog_phase3.py`

```python
def _make_in_memory_engine():
    from photoconsole.catalog.models import Base
    from sqlalchemy import create_engine
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    return engine
```

### CliRunner + Config Writer — apply to `test_cli_phase3.py`

**Source:** `tests/test_cli_phase2.py` lines 24-79
**Apply to:** `test_cli_phase3.py` — copy `_write_config()` and `_seed_*` helper pattern verbatim, extend for cluster section

---

## No Analog Found

All 12 files have analogs in the codebase. No files fall into this category.

---

## Critical Implementation Order

The following dependency chain MUST be respected (from RESEARCH.md Pitfall 2):

1. **`photoconsole/catalog/models.py`** — add all 9 new columns first
2. **`photoconsole/catalog/db.py`** — add `_ensure_phase3_columns()` and call from `create_catalog_engine()` (after models.py update, `_VALID_COLUMNS` auto-includes new cols)
3. **`photoconsole/config.py`** — add `ClusterConfig` + `QualityWeightsConfig` + extend `Config` dataclass
4. **`photoconsole/quality.py`** — new module; depends on models.py column names for result dict keys
5. **`photoconsole/clustering.py`** — new module; depends on models.py + consolidator.py manifest pattern
6. **`photoconsole/cli.py`** — extend with `cluster` + `review-clusters` subcommands
7. **Tests** — all test files can be written in any order after steps 1–6

---

## Metadata

**Analog search scope:** `photoconsole/`, `tests/`
**Files scanned:** 13 source files read in full
**Pattern extraction date:** 2026-05-17
