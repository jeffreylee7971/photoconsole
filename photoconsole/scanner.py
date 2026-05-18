"""Scanner layer for PhotoConsole — discovers media file candidates from local and rclone sources.

Two scanner classes share a common iter_candidates() interface:

- LocalScanner: Walks a local filesystem directory recursively using os.scandir,
  which returns DirEntry objects with cached metadata (type, symlink status) from
  the directory listing itself — avoiding separate stat() round-trips per entry over
  SMB.  Symlinks (both file and directory) are always skipped (D-04).
  Extension filtering is case-insensitive (D-07).

- RcloneScanner: Calls `rclone lsjson --recursive --files-only <remote>` via
  subprocess.run with the argv list form (T-04-01 mitigation: list argv, no shell).
  Parses JSON output and applies the same extension filter.

scan_all() walks all configured sources in parallel using a ThreadPoolExecutor,
reducing wall-clock walk time from sum(sources) to max(sources).

Security notes:
- T-04-01: subprocess.run is always called with a Python list; the shell flag
  is never set to True, and no remote name is interpolated into a shell string.
- T-04-02: os.scandir is used with follow_symlinks=False checks; symlinked entries
  (both file and directory) are skipped before any recursion, preventing symlink loops.
- T-04-03: subprocess.run timeout defaults to 300 s (configurable per-instance).
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Iterator

from photoconsole.config import Config, Source

logger = logging.getLogger(__name__)


class LocalScanner:
    """Walk a local directory recursively and yield media file candidates.

    Uses os.scandir instead of os.walk so that DirEntry metadata (file type,
    symlink status) is returned from the directory listing itself without
    extra stat() round-trips per entry.  On SMB-mounted NAS shares this
    eliminates one network round-trip per file during the walk phase.

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
        - Uses os.scandir recursively; DirEntry.is_symlink/is_file/is_dir use
          metadata cached from the directory listing (no extra stat per entry).
        - All symlinked entries (file or directory) are skipped before recursion
          (T-04-02 / D-04).
        - Extension match is case-insensitive: suffix.lower() vs include_extensions.
        - PermissionError on a subdirectory is logged and skipped, not fatal.
        """
        def _walk(dirpath: str) -> Iterator[tuple[str, str, str]]:
            try:
                with os.scandir(dirpath) as it:
                    entries = list(it)
            except (PermissionError, OSError) as exc:
                logger.debug("Cannot scan directory %s: %s", dirpath, exc)
                return

            for entry in entries:
                # Skip ALL symlinks (file and dir) before any other check (D-04 / T-04-02).
                if entry.is_symlink():
                    if self.verbose:
                        logger.info("Skipping symlink: %s", entry.path)
                    continue

                if entry.is_dir(follow_symlinks=False):
                    yield from _walk(entry.path)
                elif entry.is_file(follow_symlinks=False):
                    if Path(entry.name).suffix.lower() in self.include_extensions:
                        yield entry.path, self.source.name, "local"

        yield from _walk(str(self._root))


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
        """Yield (remote_path, source.name, 'rclone') for each media file."""
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
            if entry.get("IsDir"):
                continue

            rel: str = entry["Path"]

            if Path(rel).suffix.lower() not in self.include_extensions:
                continue

            yield f"{self.source.remote}{rel}", self.source.name, "rclone"


def scan_all(
    config: Config,
    verbose: bool = False,
    on_source_start=None,
    on_source_done=None,
    scan_workers: int = 4,
) -> Iterator[tuple[str, str, str]]:
    """Dispatch each Source in config to the appropriate scanner and yield the
    concatenated candidate stream.

    Sources are walked in parallel using a ThreadPoolExecutor (default 4 workers),
    reducing total walk time from sum(all sources) to roughly max(slowest source).
    Results are yielded in config.sources order for deterministic output.

    Args:
        config:          Fully-loaded Config dataclass.
        verbose:         Forward to each scanner; also controls per-source count logging.
        on_source_start: Optional callable(name: str, source_type: str) fired just
                         before each source's walk begins (called from worker thread,
                         protected by an internal lock).
        on_source_done:  Optional callable(name: str, source_type: str, count: int)
                         fired after each source's walk completes.
        scan_workers:    Number of sources to walk in parallel (default 4).

    Yields:
        (path, source_name, source_type) tuples from all sources in config order.

    Raises:
        ValueError: If any source.type is not 'local' or 'rclone'.
        RuntimeError: If a scanner raises (e.g. rclone binary missing).
    """
    _lock = threading.Lock()

    def _safe_cb(cb, *args) -> None:
        if cb is not None:
            with _lock:
                cb(*args)

    def _scan_one(source: Source) -> list[tuple[str, str, str]]:
        if source.type == "local":
            try:
                scanner: LocalScanner | RcloneScanner = LocalScanner(
                    source,
                    config.include_extensions,
                    verbose=verbose,
                )
            except (PermissionError, FileNotFoundError, NotADirectoryError) as exc:
                logger.warning("Skipping source %r: %s", source.name, exc)
                return []
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

        _safe_cb(on_source_start, source.name, source.type)
        results = list(scanner.iter_candidates())
        _safe_cb(on_source_done, source.name, source.type, len(results))

        if verbose:
            logger.info("Source %r: %d candidate(s) found", source.name, len(results))

        return results

    workers = min(scan_workers, len(config.sources)) if config.sources else 1

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(_scan_one, source) for source in config.sources]
        for future in futures:
            yield from future.result()
