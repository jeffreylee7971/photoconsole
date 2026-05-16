"""Catalog persistence layer for PhotoConsole.

Public surface re-exported here so callers can import directly from
``photoconsole.catalog`` without digging into sub-modules.

Example::

    from photoconsole.catalog import (
        Base,
        MediaFile,
        create_catalog_engine,
        session_factory,
        upsert_media_file,
        upsert_many,
        should_skip,
        get_known_record,
    )
"""
from photoconsole.catalog.models import Base, MediaFile
from photoconsole.catalog.db import (
    create_catalog_engine,
    session_factory,
    upsert_media_file,
    upsert_many,
    should_skip,
    get_known_record,
)

__all__ = [
    "Base",
    "MediaFile",
    "create_catalog_engine",
    "session_factory",
    "upsert_media_file",
    "upsert_many",
    "should_skip",
    "get_known_record",
]
