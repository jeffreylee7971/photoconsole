"""PhotoConsole CLI — click group + scan command.

Entry point:
    photoconsole --help
    photoconsole scan --config <config.yaml>

Architecture notes (Phase 1 decisions):
- D-03: Files with status='error' are always retried on next scan (should_skip
  returns False for error rows regardless of mtime).
- D-09: hashing.max_workers is read from config; thread pool size is configurable.
- D-13: ffprobe gate fires at scan startup when include_extensions overlaps with
  VIDEO_EXTENSIONS. Photo-only users bypass the gate entirely.
- T-02-02: All DB writes happen in the main thread (single writer). Worker
  threads return result dicts; upsert_many is called from the main thread loop.
- T-05-01: click.Path(exists=True, dir_okay=False, readable=True) validates the
  config path before load_config is called.
- T-05-04: scan_all candidates are fully listed (not streamed) — acceptable up
  to ~100K items per FR6.

Pitfall 6 (RESEARCH.md): rclone candidates have remote-prefixed paths (e.g.
'gdrive:photos/a.jpg'). Path.stat() cannot be called on them, so should_skip
always receives mtime=None for rclone candidates, which means should_skip
returns False and they are always re-processed in Phase 1. A streaming mtime
approach for rclone is deferred to a later phase.
"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

import click

from photoconsole.catalog import (
    create_catalog_engine,
    session_factory,
    should_skip,
    upsert_many,
)
from photoconsole.config import load_config
from photoconsole.constants import VIDEO_EXTENSIONS
from photoconsole.hasher import process_files
from photoconsole.metadata.video import check_ffprobe_available
from photoconsole.scanner import check_rclone_available, scan_all

logger = logging.getLogger(__name__)

_BATCH_SIZE = 50


# ---------------------------------------------------------------------------
# Click group
# ---------------------------------------------------------------------------


@click.group()
@click.option("-v", "--verbose", is_flag=True, default=False,
              help="Enable INFO-level logging and per-file progress output.")
@click.option("-q", "--quiet", is_flag=True, default=False,
              help="Suppress all non-error output including the final summary.")
@click.pass_context
def main(ctx: click.Context, verbose: bool, quiet: bool) -> None:
    """PhotoConsole — local-first media cataloging tool.

    Run `photoconsole scan --config config.yaml` to discover and catalog
    media files from your configured sources.
    """
    if verbose and quiet:
        raise click.UsageError(
            "--verbose and --quiet are mutually exclusive. Use one or neither."
        )

    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    ctx.obj["quiet"] = quiet

    # Configure root logger based on verbosity flags.
    if verbose:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
    elif quiet:
        logging.basicConfig(level=logging.ERROR)
    else:
        logging.basicConfig(level=logging.WARNING)


# ---------------------------------------------------------------------------
# scan subcommand
# ---------------------------------------------------------------------------


@main.command()
@click.option(
    "--config", "config_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, readable=True),
    help="Path to the YAML configuration file.",
)
@click.pass_context
def scan(ctx: click.Context, config_path: str) -> None:
    """Scan configured sources and populate the media catalog.

    Discovers media files from all configured sources, computes SHA-256
    hashes, extracts metadata, and UPSERTs results into the SQLite catalog.
    Files that have not changed since the last scan are skipped (incremental
    mode). Files previously stored with status='error' are always retried.
    """
    verbose: bool = ctx.obj["verbose"]
    quiet: bool = ctx.obj["quiet"]

    summary = _run_scan(config_path, verbose, quiet)

    if not quiet:
        _print_summary(summary)

    if summary["errored"] > 0:
        click.echo(
            f"Warning: {summary['errored']} file(s) encountered errors during scan.",
            err=True,
        )


# ---------------------------------------------------------------------------
# Internal: _run_scan (pure — no click dependencies; directly testable)
# ---------------------------------------------------------------------------


def _run_scan(config_path: str, verbose: bool = False, quiet: bool = False) -> dict:
    """Execute the full scan pipeline and return a summary dict.

    This function is intentionally free of click API calls so it can be
    invoked directly in unit tests without a CliRunner.

    Args:
        config_path: Path to the YAML config file.
        verbose:     When True, log per-source counts and per-file events.
        quiet:       When True, suppress tqdm progress bar output.

    Returns:
        Dict with keys:
            total_candidates (int)  — total files found by all scanners
            cataloged (int)         — files successfully processed (status='ok')
            errored (int)           — files that resulted in status='error'
            skipped (int)           — files skipped (unchanged, incremental)
            elapsed_seconds (float) — wall-clock time for the scan

    Raises:
        RuntimeError: If a required dependency (rclone, ffprobe) is missing.
    """
    start = time.monotonic()

    # --- Step 1: load config ---
    cfg = load_config(config_path)

    # --- Step 2: Dependency gates (fire BEFORE any scanning) ---

    # rclone gate: check once if any source is rclone-type
    has_rclone_source = any(s.type == "rclone" for s in cfg.sources)
    if has_rclone_source:
        # Raises RuntimeError with 'rclone' and 'install' if binary is missing
        check_rclone_available()

    # ffprobe gate: check if any video extension is in include_extensions (D-13)
    # Photo-only users bypass this gate entirely (no ffmpeg requirement).
    needs_ffprobe = bool(cfg.include_extensions & VIDEO_EXTENSIONS)
    if needs_ffprobe:
        # Raises RuntimeError with 'ffprobe' and 'install' if binary is missing
        check_ffprobe_available()

    # --- Step 3: Create catalog engine + session factory ---
    engine = create_catalog_engine(cfg.catalog_path)
    SessionLocal = session_factory(engine)

    # --- Step 4: Discover all candidates (full list — T-05-04 accepted for ≤100K) ---
    candidates = list(scan_all(cfg, verbose=verbose))

    if verbose:
        logger.info("Total candidates discovered: %d", len(candidates))

    # --- Step 5: Filter candidates via incremental skip predicate ---
    survivors: list[tuple[str, str, str]] = []
    skipped = 0

    with SessionLocal() as session:
        for path, source_name, source_type in candidates:
            # Get mtime for local files; rclone files always get None (Pitfall 6
            # in RESEARCH.md — rclone remote mtime integration deferred to Phase 2).
            if source_type == "local":
                try:
                    mtime: float | None = Path(path).stat().st_mtime
                except OSError:
                    mtime = None
            else:
                # rclone candidates: never skip in Phase 1
                mtime = None

            if mtime is not None and should_skip(session, path, mtime):
                skipped += 1
                if verbose:
                    logger.info("Skipping unchanged file: %s", path)
            else:
                survivors.append((path, source_name, source_type))

    if verbose:
        logger.info(
            "Skip check: %d skipped, %d survivors to process",
            skipped, len(survivors),
        )

    # --- Step 6: Parallel hash + metadata (worker threads, results yielded to main thread) ---
    cataloged = 0
    errored = 0
    buffer: list[dict] = []

    def _flush_buffer() -> None:
        nonlocal cataloged, errored
        if not buffer:
            return
        with SessionLocal() as session:
            upsert_many(session, buffer)
            session.commit()
        # Count outcomes from the flushed batch
        for record in buffer:
            if record.get("status") == "ok":
                cataloged += 1
            else:
                errored += 1
        buffer.clear()

    # Verify writer runs in main thread (T-02-02 / T-05-02):
    # process_files yields from worker threads; upsert_many is called here
    # on the main thread from the for-loop below.
    assert threading.current_thread() is threading.main_thread(), (
        "CLI scan must run on the main thread"
    )

    try:
        # Use tqdm for progress when not quiet
        if not quiet and survivors:
            try:
                from tqdm import tqdm
                progress_bar = tqdm(
                    total=len(survivors),
                    unit="file",
                    desc="Scanning",
                    leave=False,
                    disable=quiet,
                )
            except ImportError:
                progress_bar = None
        else:
            progress_bar = None

        def _progress_cb(completed: int, total: int) -> None:
            if progress_bar is not None:
                progress_bar.update(1)

        for result in process_files(
            survivors,
            max_workers=cfg.hashing_max_workers,
            progress_cb=_progress_cb if survivors else None,
        ):
            buffer.append(result)
            if len(buffer) >= _BATCH_SIZE:
                _flush_buffer()

        # Flush remaining records
        _flush_buffer()

    finally:
        if progress_bar is not None:
            progress_bar.close()

    elapsed = time.monotonic() - start

    return {
        "total_candidates": len(candidates),
        "cataloged": cataloged,
        "errored": errored,
        "skipped": skipped,
        "elapsed_seconds": elapsed,
    }


# ---------------------------------------------------------------------------
# Summary printer
# ---------------------------------------------------------------------------


def _print_summary(summary: dict) -> None:
    """Print the final scan summary table to stdout."""
    click.echo(
        f"\nScan complete in {summary['elapsed_seconds']:.1f}s\n"
        f"  Total candidates : {summary['total_candidates']}\n"
        f"  Cataloged        : {summary['cataloged']}\n"
        f"  Skipped          : {summary['skipped']}\n"
        f"  Errored          : {summary['errored']}"
    )
