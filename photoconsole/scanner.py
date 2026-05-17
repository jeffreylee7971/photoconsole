"""Scanner layer for PhotoConsole — discovers media file candidates from local and rclone sources.

Two scanner classes share a common iter_candidates() interface:

- LocalScanner: Walks a local filesystem directory recursively using os.walk with
  followlinks=False.  Symlinks (both file and directory) are always skipped (D-04).
  Extension filtering is case-insensitive (D-07).

- RcloneScanner: Calls `rclone lsjson --recursive --files-only <remote>` via
  subprocess.run with the argv list form (T-04-01 mitigation: list argv, no shell).
  Parses JSON output and applies the same extension filter.

Both scanners yield (path, source_name, source_type) tuples consumed by Plan 03's
process_files() function.

Security notes:
- T-04-01: subprocess.run is always called with a Python list; the shell flag
  is never set to True, and no remote name is interpolated into a shell string.
- T-04-02: os.walk is called with followlinks=False AND symlinked subdirectory
  entries are pruned from dirs[:] before descent, preventing symlink loops.
- T-04-03: subprocess.run timeout defaults to 300 s (configurable per-instance).
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Iterator

from photoconsole.config import Config, Source

logger = logging.getLogger(__name__)


class LocalScanner:
    """Walk a local directory recursively and yield media file candidates.

    Symlinks — both file symlinks and symlinked directories — are never
    traversed or emitted (D-04).  Extensions are matched case-insensitively
    (D-07).

    Args:
        source:             Source dataclass (type='local') with a valid path.
        include_extensions: frozenset of lower-case dotted extensions e.g.
                            frozenset({'.jpg', '.png', '.mp4'}).
        verbose:            When True, log skipped symlinks at INFO level (D-05).

    Raises:
        FileNotFoundError:   If source.path does not exist at construction time.
        NotADirectoryError:  If source.path is a file, not a directory.
    """

    def __init__(
        self,
        source: Source,
        include_extensions: frozenset[str],
        verbose: bool = False,
    ) -> None:
        self.source = source
        self.include_extensions = include_extensions
        self.verbose = verbose

        # Validate and resolve the root path eagerly so that errors surface
        # before any iteration begins.
        try:
            root = Path(source.path).expanduser().resolve(strict=True)
        except PermissionError as exc:
            raise PermissionError(
                f"Permission denied accessing source {source.name!r} at {source.path!r}. "
                f"Run as administrator or remove this source from config.yaml. "
                f"Original error: {exc}"
            ) from exc
        if not root.exists():
            raise FileNotFoundError(
                f"LocalScanner root does not exist: {source.path!r}"
            )
        if not root.is_dir():
            raise NotADirectoryError(
                f"LocalScanner root is not a directory: {source.path!r}"
            )
        self._root = root

    def iter_candidates(self) -> Iterator[tuple[str, str, str]]:
        """Yield (absolute_path, source.name, 'local') for each media file.

        Traversal rules:
        - Uses os.walk(followlinks=False) to avoid following directory symlinks.
        - Prunes symlinked subdirectory entries in-place via dirs[:] mutation to
          prevent any descent into symlinked trees.
        - Checks each file candidate with Path.is_symlink(); symlinked files are
          skipped (and logged when self.verbose is True).
        - Extension match is case-insensitive: suffix.lower() vs include_extensions.
        """
        root_path = self._root

        for dirpath, dirs, files in os.walk(str(root_path), followlinks=False):
            current = Path(dirpath)

            # Prune symlinked subdirectories in-place (T-04-02 / D-04).
            # os.walk consults dirs[:] before descending, so this mutation
            # prevents traversal of any symlinked directory.
            dirs[:] = [
                d for d in dirs
                if not (current / d).is_symlink()
            ]

            for filename in files:
                full = current / filename

                # Skip symlinked files (D-04).
                if full.is_symlink():
                    if self.verbose:
                        logger.info(
                            "Skipping symlink: %s", full
                        )
                    continue

                # Extension filter — case-insensitive (D-07).
                if full.suffix.lower() not in self.include_extensions:
                    continue

                yield str(full.resolve(strict=False)), self.source.name, "local"


def check_rclone_available() -> None:
    """Verify that the rclone binary is accessible on PATH.

    Raises:
        RuntimeError: With an actionable install message when rclone is not
                      found.  The message always contains both 'rclone' and
                      'install' (case-insensitive) so callers can detect it.
    """
    try:
        subprocess.run(
            ["rclone", "version"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError:
        raise RuntimeError(
            "rclone not found on PATH. "
            "Install rclone from https://rclone.org/install/ and ensure it "
            "is available on your system PATH before running rclone sources."
        )


class RcloneScanner:
    """List files on an rclone remote and yield media file candidates.

    Calls `rclone lsjson --recursive --files-only <source.remote>` via
    subprocess.run with a Python argv list (list argv only, no shell — T-04-01).

    Args:
        source:             Source dataclass (type='rclone') with a remote field.
        include_extensions: frozenset of lower-case dotted extensions.
        verbose:            Reserved for future verbose logging (currently unused).
        timeout:            subprocess.run timeout in seconds (default 300, T-04-03).

    Raises (from iter_candidates):
        RuntimeError: When rclone binary is not found (contains 'rclone' and
                      'install' in the message).
        RuntimeError: When rclone exits non-zero (contains rclone's stderr text).
    """

    def __init__(
        self,
        source: Source,
        include_extensions: frozenset[str],
        verbose: bool = False,
        timeout: int = 300,
    ) -> None:
        self.source = source
        self.include_extensions = include_extensions
        self.verbose = verbose
        self.timeout = timeout

    def iter_candidates(self) -> Iterator[tuple[str, str, str]]:
        """Yield (remote_path, source.name, 'rclone') for each media file.

        Calls rclone lsjson with the argv list form, parses JSON, and yields
        entries that are not directories and whose extension is in
        include_extensions.

        The yielded path is the source.remote value concatenated with the
        entry's Path field (e.g. 'gdrive:photos/a.jpg').
        """
        try:
            result = subprocess.run(
                [
                    "rclone",
                    "lsjson",
                    "--recursive",
                    "--files-only",
                    self.source.remote,
                ],
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except FileNotFoundError:
            raise RuntimeError(
                "rclone not found on PATH. "
                "Install rclone from https://rclone.org/install/ and ensure it "
                "is available on your system PATH before running rclone sources."
            )

        if result.returncode != 0:
            raise RuntimeError(
                f"rclone failed (exit {result.returncode}): {result.stderr.strip()}"
            )

        entries: list[dict] = json.loads(result.stdout)

        for entry in entries:
            # Skip directory entries (--files-only should prevent these, but
            # we check defensively per T-04-04).
            if entry.get("IsDir"):
                continue

            rel: str = entry["Path"]

            # Extension filter — case-insensitive (D-07).
            if Path(rel).suffix.lower() not in self.include_extensions:
                continue

            yield f"{self.source.remote}{rel}", self.source.name, "rclone"


def scan_all(
    config: Config,
    verbose: bool = False,
) -> Iterator[tuple[str, str, str]]:
    """Dispatch each Source in config to the appropriate scanner and yield the
    concatenated candidate stream.

    Sources are processed in config.sources order (D-07).  When verbose=True,
    logs per-source file counts at INFO level after each source completes.

    Args:
        config:  Fully-loaded Config dataclass.
        verbose: Forward to each scanner; also controls per-source count logging.

    Yields:
        (path, source_name, source_type) tuples from all sources in order.

    Raises:
        ValueError: If any source.type is not 'local' or 'rclone'.
        RuntimeError: If a scanner raises (e.g. rclone binary missing).  Errors
                      are not silently swallowed — fail-fast per Phase 1 spec.
    """
    for source in config.sources:
        if source.type == "local":
            try:
                scanner: LocalScanner | RcloneScanner = LocalScanner(
                    source,
                    config.include_extensions,
                    verbose=verbose,
                )
            except (PermissionError, FileNotFoundError, NotADirectoryError) as exc:
                logger.warning("Skipping source %r: %s", source.name, exc)
                continue
        elif source.type == "rclone":
            scanner = RcloneScanner(
                source,
                config.include_extensions,
                verbose=verbose,
            )
        else:
            raise ValueError(
                f"unknown source type {source.type!r} for source {source.name!r}. "
                f"Valid types are: 'local', 'rclone'."
            )

        count = 0
        for item in scanner.iter_candidates():
            count += 1
            yield item

        if verbose:
            logger.info(
                "Source %r: %d candidate(s) found", source.name, count
            )
