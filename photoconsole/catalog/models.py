"""SQLAlchemy 2.0 ORM model for the PhotoConsole media catalog.

Defines the declarative ``Base`` and ``MediaFile`` model whose columns
cover every field required by decisions D-10 (photos) and D-12 (videos).

Column design notes:
- ``path`` is the primary natural key used for UPSERT deduplication.
- ``hash`` (SHA-256 hex) is indexed to support Phase-2 duplicate queries.
- ``status`` is indexed to support filtering for error-retry logic (D-03).
- ``scanned_at`` defaults to a timezone-aware UTC datetime (avoids the
  deprecated ``datetime.utcnow`` that returns a naive datetime).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import BigInteger, DateTime, Float, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base shared by all ORM models in this package."""
    pass


class MediaFile(Base):
    """A single cataloged media file (photo or video).

    One row per unique ``path``. Re-scanning the same path UPSERTs the row
    (see ``db.upsert_media_file``).

    Columns
    -------
    id           : Auto-increment primary key.
    path         : Absolute filesystem path or ``remote:path/to/file`` for rclone
                   sources.  Unique constraint enforces the one-row-per-path
                   invariant that the UPSERT relies on.
    hash         : SHA-256 hex digest (64 chars).  Indexed for Phase-2 dedup.
    size         : File size in bytes.
    mtime        : File modification time (Unix timestamp, float).
    ctime        : File creation/metadata-change time (Unix timestamp, float).
    source_name  : Human-readable source label from config (e.g. "NAS Photos").
    source_type  : ``'local'`` or ``'rclone'``.
    media_type   : ``'photo'`` or ``'video'``.
    status       : ``'ok'`` or ``'error'``.  Indexed for retry filtering (D-03).
    error_type   : One of the ``ErrorType`` string values; NULL when status='ok'.
    date_taken   : ISO-ish timestamp string extracted from EXIF or container
                   metadata.  NULL when metadata is absent or malformed.
    camera_model : Camera model string from EXIF (D-10).
    orientation  : EXIF orientation tag value (D-10).
    gps_lat      : GPS latitude in decimal degrees (D-10, D-12).
    gps_lon      : GPS longitude in decimal degrees (D-10, D-12).
    scanned_at   : UTC datetime when this row was last written.
    """

    __tablename__ = "media_files"

    id: Mapped[int] = mapped_column(primary_key=True)

    # --- Identification / source ---
    path: Mapped[str] = mapped_column(String, unique=True, index=True)
    source_name: Mapped[Optional[str]] = mapped_column(String)
    source_type: Mapped[Optional[str]] = mapped_column(String)   # 'local' | 'rclone'
    media_type: Mapped[Optional[str]] = mapped_column(String)    # 'photo' | 'video'

    # --- File system attributes ---
    hash: Mapped[Optional[str]] = mapped_column(String(64), index=True)   # SHA-256 hex
    size: Mapped[Optional[int]] = mapped_column(BigInteger)
    mtime: Mapped[Optional[float]] = mapped_column(Float)
    ctime: Mapped[Optional[float]] = mapped_column(Float)

    # --- Catalog status ---
    status: Mapped[str] = mapped_column(String, default="ok", index=True)  # 'ok' | 'error'
    error_type: Mapped[Optional[str]] = mapped_column(String)               # ErrorType value

    # --- EXIF / container metadata ---
    date_taken: Mapped[Optional[str]] = mapped_column(String)   # ISO-ish from EXIF/ffprobe
    camera_model: Mapped[Optional[str]] = mapped_column(String)
    orientation: Mapped[Optional[int]] = mapped_column(Integer)
    gps_lat: Mapped[Optional[float]] = mapped_column(Float)
    gps_lon: Mapped[Optional[float]] = mapped_column(Float)

    # --- Audit ---
    scanned_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
    )
