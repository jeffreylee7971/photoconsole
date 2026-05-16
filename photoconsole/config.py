"""Config dataclasses and YAML loader for PhotoConsole.

The config file is the single source of truth for:
  - catalog_path: where the SQLite catalog is stored
  - sources: list of local/rclone sources to scan
  - include_extensions: file extension allow-list (global, applied to all sources)
  - exclude_patterns: glob patterns to skip (e.g. thumbs, cache dirs)
  - hashing.max_workers: thread pool size for parallel hashing

Security notes (T-01-01, T-01-02):
  - yaml.safe_load is used exclusively; !!python/object tags are rejected.
  - catalog_path is ~-expanded and converted to an absolute path.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Union

import yaml

from photoconsole.constants import MEDIA_EXTENSIONS

_VALID_SOURCE_TYPES = frozenset({"local", "rclone"})


@dataclass
class Source:
    """A single media source to scan.

    Attributes:
        name:   Human-readable label shown in progress output.
        type:   'local' for pathlib-based traversal; 'rclone' for remote mounts.
        path:   Filesystem path (required for type='local').
        remote: rclone remote specification, e.g. 'gdrive:' (required for type='rclone').
    """
    name: str
    type: str          # 'local' | 'rclone'
    path: str = ''     # local filesystem path
    remote: str = ''   # rclone remote e.g. 'gdrive:'


@dataclass
class Config:
    """Top-level configuration object returned by load_config().

    Attributes:
        sources:             List of media sources to scan.
        catalog_path:        Absolute path to the SQLite catalog file.
        include_extensions:  frozenset of lower-case extensions (each starting with '.').
        exclude_patterns:    Glob patterns to skip during traversal.
        hashing_max_workers: Thread pool size for parallel hashing; defaults to os.cpu_count().
    """
    sources: list[Source]
    catalog_path: str
    include_extensions: frozenset[str] = field(
        default_factory=lambda: MEDIA_EXTENSIONS
    )
    exclude_patterns: list[str] = field(default_factory=list)
    hashing_max_workers: int = field(
        default_factory=lambda: os.cpu_count() or 1
    )


def _normalize_extension(ext: str) -> str:
    """Normalize a file extension to lower-case with a leading dot.

    Examples:
        '.JPG' -> '.jpg'
        'jpg'  -> '.jpg'
        '.jpg' -> '.jpg'
    """
    ext = ext.strip().lower()
    if not ext.startswith('.'):
        ext = '.' + ext
    return ext


def _parse_source(raw: dict) -> Source:
    """Validate and convert a raw source dict into a Source dataclass.

    Raises:
        ValueError: On unknown type, or missing required type-specific field.
    """
    name = raw.get('name', '')
    src_type = raw.get('type', '')

    if src_type not in _VALID_SOURCE_TYPES:
        raise ValueError(
            f"unknown source type {src_type!r} in source {name!r}. "
            f"Valid types are: {sorted(_VALID_SOURCE_TYPES)}"
        )

    path = raw.get('path', '')
    remote = raw.get('remote', '')

    if src_type == 'local' and not path:
        raise ValueError(
            f"local source requires path — source {name!r} has no 'path' field"
        )
    if src_type == 'rclone' and not remote:
        raise ValueError(
            f"rclone source requires remote — source {name!r} has no 'remote' field"
        )

    return Source(name=name, type=src_type, path=path, remote=remote)


def load_config(path: Union[str, os.PathLike]) -> Config:
    """Load and validate a YAML config file, returning a Config dataclass.

    Args:
        path: Path to the YAML config file.

    Returns:
        A fully-validated Config instance with catalog_path ~-expanded to
        an absolute path and include_extensions normalized to lower-case
        frozenset with leading dots.

    Raises:
        ValueError: With a descriptive message when required fields are missing,
                    sources list is empty, source type is unknown, or a source
                    is missing its required path/remote field.
        FileNotFoundError: If the config file does not exist.
        yaml.YAMLError: If the file is not valid YAML.
    """
    with open(path, encoding='utf-8') as fh:
        raw = yaml.safe_load(fh)

    if raw is None:
        raw = {}

    # --- Required: catalog_path ---
    catalog_path_raw = raw.get('catalog_path')
    if not catalog_path_raw:
        raise ValueError(
            "config is missing required field 'catalog_path'. "
            "Example: catalog_path: ~/.photoconsole/catalog.db"
        )
    catalog_path = os.path.abspath(os.path.expanduser(str(catalog_path_raw)))

    # --- Required: sources (non-empty list) ---
    sources_raw = raw.get('sources')
    if not sources_raw:
        raise ValueError(
            "config is missing required field 'sources', or 'sources' is empty. "
            "Provide at least one source to scan."
        )

    sources = [_parse_source(s) for s in sources_raw]

    # --- Optional: include_extensions ---
    raw_exts = raw.get('include_extensions')
    if raw_exts is not None:
        include_extensions: frozenset[str] = frozenset(
            _normalize_extension(e) for e in raw_exts
        )
    else:
        include_extensions = MEDIA_EXTENSIONS

    # --- Optional: exclude_patterns ---
    exclude_patterns: list[str] = raw.get('exclude_patterns', [])

    # --- Optional: hashing.max_workers ---
    hashing_section = raw.get('hashing', {}) or {}
    raw_workers = hashing_section.get('max_workers')
    if raw_workers is not None:
        hashing_max_workers = int(raw_workers)
    else:
        hashing_max_workers = os.cpu_count() or 1

    return Config(
        sources=sources,
        catalog_path=catalog_path,
        include_extensions=include_extensions,
        exclude_patterns=exclude_patterns,
        hashing_max_workers=hashing_max_workers,
    )
