"""Database engine factory and catalog query helpers.

Public functions
----------------
create_catalog_engine(db_path)      -- Open/create a WAL-enabled SQLite engine.
session_factory(engine)             -- Return a sessionmaker bound to *engine*.
upsert_media_file(session, record)  -- UPSERT one record by path; caller commits.
upsert_many(session, records)       -- UPSERT many records; caller commits.
should_skip(session, path, mtime)   -- True iff file is unchanged and status='ok'.
get_known_record(session, path)     -- Return the MediaFile row or None.

Design notes
------------
* All DB writes go through ``upsert_media_file`` which uses SQLite's
  ``INSERT ... ON CONFLICT(path) DO UPDATE SET ...`` to guarantee at-most-one
  row per path.

* ``should_skip`` returns False for status='error' rows so that transient
  failures are always retried on the next incremental scan (decision D-03).

* Unknown record keys are explicitly rejected (ValueError) to catch typos
  early rather than silently dropping data (threat T-02-01).

* The engine uses WAL journal mode + busy_timeout=5000 ms to tolerate the
  single-writer / multi-reader pattern described in the architecture
  (threat T-02-02).

* All queries use parameterized SQLAlchemy statements — no string interpolation
  in SQL (threat T-02-04).
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Iterable, Optional

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from photoconsole.catalog.models import Base, MediaFile

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

# Set of valid column names built once at module load time.
_VALID_COLUMNS: frozenset[str] = frozenset(
    c.name for c in MediaFile.__table__.columns
)


# ---------------------------------------------------------------------------
# Engine / session factory
# ---------------------------------------------------------------------------


def create_catalog_engine(db_path: "str | Path") -> "Engine":
    """Create (or open) a WAL-enabled SQLite catalog at *db_path*.

    Steps
    -----
    1. Resolve the path and create the parent directory if it doesn't exist.
    2. Open a SQLAlchemy engine with ``future=True`` (2.0 API).
    3. Register a ``connect`` event listener that sets WAL journal mode,
       synchronous=NORMAL, busy_timeout=5000 ms, and foreign_keys=ON via raw
       DBAPI cursor calls (pragmas must be set per-connection).
    4. Run ``Base.metadata.create_all`` to create the ``media_files`` table.
    5. Return the engine.

    Args:
        db_path: Filesystem path to the SQLite database file.  Tilde expansion
                 and symlink resolution are applied.

    Returns:
        A configured SQLAlchemy ``Engine`` instance.
    """
    resolved = Path(db_path).expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(f"sqlite:///{resolved}", future=True)

    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    return engine


def session_factory(engine: "Engine") -> sessionmaker:
    """Return a ``sessionmaker`` bound to *engine*.

    ``expire_on_commit=False`` keeps ORM objects accessible after commit
    without triggering implicit lazy-loads.

    Args:
        engine: A SQLAlchemy engine (typically from ``create_catalog_engine``).

    Returns:
        A ``sessionmaker`` callable that produces ``Session`` instances.
    """
    return sessionmaker(bind=engine, expire_on_commit=False)


# ---------------------------------------------------------------------------
# Upsert helpers
# ---------------------------------------------------------------------------


def upsert_media_file(session: Session, record: dict) -> None:
    """UPSERT a single media file record by ``path``.

    The record is inserted if no row exists for ``path``; otherwise the
    existing row is updated in-place.  The caller is responsible for
    committing the session (to support batching).

    Validation
    ----------
    * ``record`` must contain the ``'path'`` key (ValueError if missing).
    * Every key in ``record`` must match a ``MediaFile`` column name.
      Unknown keys raise ``ValueError`` listing the offending key(s) so
      callers catch typos early rather than silently losing data (T-02-01).

    Args:
        session: An active SQLAlchemy ``Session``.
        record:  Mapping of column-name → value.  At minimum must include
                 ``'path'``.

    Raises:
        ValueError: If ``'path'`` is absent or if any key is not a valid
                    ``MediaFile`` column name.
    """
    if "path" not in record:
        raise ValueError(
            "upsert_media_file: record must include 'path' key. "
            f"Got keys: {sorted(record.keys())}"
        )

    unknown = sorted(k for k in record if k not in _VALID_COLUMNS)
    if unknown:
        raise ValueError(
            f"upsert_media_file: unknown column(s) {unknown!r}. "
            f"Valid columns: {sorted(_VALID_COLUMNS)}"
        )

    # Import here to keep the top-level import surface clean; this is a
    # dialect-specific import that only matters at call time.
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert  # noqa: PLC0415

    stmt = sqlite_insert(MediaFile).values(**record)

    # Build the SET clause from all keys except 'path' (conflict target) and
    # 'id' (auto-increment PK that must never be overwritten).
    update_keys = [k for k in record if k not in ("path", "id")]
    stmt = stmt.on_conflict_do_update(
        index_elements=["path"],
        set_={k: getattr(stmt.excluded, k) for k in update_keys},
    )

    session.execute(stmt)


def upsert_many(session: Session, records: Iterable[dict]) -> int:
    """UPSERT multiple records; returns the count of records processed.

    The caller is responsible for committing the session.

    Args:
        session: An active SQLAlchemy ``Session``.
        records: Iterable of record dicts (each must satisfy
                 ``upsert_media_file`` validation rules).

    Returns:
        Number of records processed.
    """
    count = 0
    for record in records:
        upsert_media_file(session, record)
        count += 1
    return count


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------


def build_skip_index(session: Session) -> dict[str, tuple[float | None, str | None]]:
    """Load path/mtime/status for all catalog rows into a dict (one query).

    Used by the fast incremental skip-check path to avoid N individual
    SELECT queries during a scan (533K rows → 533K queries → very slow).

    Returns:
        Dict mapping path → (mtime, status).
    """
    rows = session.execute(
        select(MediaFile.path, MediaFile.mtime, MediaFile.status)
    ).all()
    return {row.path: (row.mtime, row.status) for row in rows}


def should_skip(session: Session, path: str, mtime: float) -> bool:
    """Return True iff the file at *path* is unchanged and previously succeeded.

    Skipping rules
    --------------
    * No existing row → False (must be scanned for the first time).
    * Existing row with ``status='error'`` → False (D-03: always retry errors).
    * Existing row with ``status='ok'`` and ``mtime == mtime`` → True.
    * Existing row with ``status='ok'`` but different ``mtime`` → False.

    Args:
        session: An active SQLAlchemy ``Session``.
        path:    Absolute path (or rclone path) to look up.
        mtime:   Current modification time of the file.

    Returns:
        ``True`` if the file should be skipped; ``False`` otherwise.
    """
    existing: Optional[MediaFile] = session.execute(
        select(MediaFile).where(MediaFile.path == path)
    ).scalar_one_or_none()

    if existing is None:
        return False
    if existing.status == "error":
        return False  # D-03: always retry error rows
    return existing.mtime == mtime


def get_known_record(session: Session, path: str) -> Optional[MediaFile]:
    """Return the ``MediaFile`` row for *path*, or ``None`` if not found.

    Primarily used in tests and debugging.

    Args:
        session: An active SQLAlchemy ``Session``.
        path:    Absolute path (or rclone path) to look up.

    Returns:
        The ``MediaFile`` instance, or ``None``.
    """
    return session.execute(
        select(MediaFile).where(MediaFile.path == path)
    ).scalar_one_or_none()
