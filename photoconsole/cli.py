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

Phase 2 additions (Plan 02-05):
- D-14: report command outputs a rich.table.Table (text), CSV, or JSON list of
  duplicate groups found in the catalog.
- D-16: plan-consolidation always runs dry_run=True; writes no files.
- FR4/FR5: consolidate command prompts for confirmation before live run; dry-run
  flag available for safe preview.
"""
from __future__ import annotations

import csv
import json
import logging
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import click

from photoconsole.catalog import (
    build_skip_index,
    create_catalog_engine,
    session_factory,
    should_skip,
    upsert_many,
)
from photoconsole.config import load_config
from photoconsole.constants import VIDEO_EXTENSIONS
from photoconsole.dedup import find_duplicate_groups
from photoconsole.consolidator import run_consolidation, ConsolidationPlan, CopyAction
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
    if not quiet:
        click.echo(f"[1/3] Discovering files from {len(cfg.sources)} source(s)...")

    def _on_source_start(name: str, source_type: str) -> None:
        click.echo(f"  Scanning {name} ({source_type})...")

    def _on_source_done(name: str, source_type: str, count: int) -> None:
        click.echo(f"    {count:,} files found")

    candidates = list(scan_all(
        cfg,
        verbose=verbose,
        on_source_start=_on_source_start if not quiet else None,
        on_source_done=_on_source_done if not quiet else None,
    ))

    if not quiet:
        click.echo(f"  Total: {len(candidates):,} candidates")

    if verbose:
        logger.info("Total candidates discovered: %d", len(candidates))

    # --- Step 5: Filter candidates via incremental skip predicate ---
    # Fast path: one bulk SELECT loads all catalog rows into memory, then
    # stat() calls run in parallel (same worker count as hashing).  This
    # replaces the old approach of N sequential stat() + N individual DB
    # queries, which was extremely slow over SMB-mounted NAS shares.
    if not quiet:
        click.echo(f"[2/3] Checking {len(candidates):,} candidates against catalog...")

    with SessionLocal() as session:
        skip_index = build_skip_index(session)

    def _get_mtime(item: tuple[str, str, str]) -> tuple[str, str, str, float | None]:
        path, source_name, source_type = item
        if source_type == "local":
            try:
                return path, source_name, source_type, Path(path).stat().st_mtime
            except OSError:
                return path, source_name, source_type, None
        return path, source_name, source_type, None

    survivors: list[tuple[str, str, str]] = []
    skipped = 0

    with ThreadPoolExecutor(max_workers=cfg.hashing_max_workers) as pool:
        for path, source_name, source_type, mtime in pool.map(_get_mtime, candidates):
            if mtime is not None:
                cat_mtime, cat_status = skip_index.get(path, (None, None))
                if cat_status == "ok" and cat_mtime == mtime:
                    skipped += 1
                    if verbose:
                        logger.info("Skipping unchanged file: %s", path)
                    continue
            survivors.append((path, source_name, source_type))

    if verbose:
        logger.info(
            "Skip check: %d skipped, %d survivors to process",
            skipped, len(survivors),
        )

    if not quiet:
        click.echo(
            f"  {len(survivors):,} to process, {skipped:,} unchanged (skipping)"
        )

    # --- Step 6: Parallel hash + metadata (worker threads, results yielded to main thread) ---
    if not quiet and survivors:
        click.echo(f"[3/3] Processing {len(survivors):,} files...")
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
    from datetime import datetime
    import photoconsole
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    click.echo(
        f"\nphotoconsole v{photoconsole.__version__}  |  {timestamp}\n"
        f"Scan complete in {summary['elapsed_seconds']:.1f}s\n"
        f"  Total candidates : {summary['total_candidates']}\n"
        f"  Cataloged        : {summary['cataloged']}\n"
        f"  Skipped          : {summary['skipped']}\n"
        f"  Errored          : {summary['errored']}"
    )


# ---------------------------------------------------------------------------
# report subcommand
# ---------------------------------------------------------------------------


def _run_report(
    config_path: str,
    output_format: str = "text",
    verbose: bool = False,
    quiet: bool = False,
):
    """Query catalog for duplicate groups and return them.

    Pure helper — no click API calls. Directly testable without CliRunner.

    Args:
        config_path:   Path to the YAML config file.
        output_format: One of 'text', 'csv', 'json' (unused here; passed for
                       symmetry with other _run_* helpers).
        verbose:       Reserved for future per-group debug output.
        quiet:         Reserved for future suppression behaviour.

    Returns:
        list[DuplicateGroup] — one entry per hash that appears more than once
        in the catalog with status='ok'.
    """
    cfg = load_config(config_path)
    engine = create_catalog_engine(cfg.catalog_path)
    SessionLocal = session_factory(engine)
    with SessionLocal() as session:
        groups = find_duplicate_groups(
            session, cfg.consolidation.source_priority
        )
    return groups


def _print_report(
    groups, output_format: str, quiet: bool, output_path: str | None = None
) -> None:
    """Render duplicate groups in the requested format to stdout or a file.

    Args:
        groups:        list[DuplicateGroup] from _run_report.
        output_format: 'text' | 'csv' | 'json'
        quiet:         When True this function should not be called (the caller
                       guards it), but we accept it here for interface symmetry.
        output_path:   If set, write output to this file path instead of stdout.
                       A one-line summary is always printed to the terminal.
    """
    import io

    def _build_rows():
        for group in groups:
            all_files = [group.canonical] + group.redundants
            total_size = sum(f.size or 0 for f in all_files)
            sources = ", ".join(
                sorted({f.source_name for f in all_files if f.source_name})
            )
            dates = [f.date_taken for f in all_files if f.date_taken]
            date_range = f"{min(dates)} .. {max(dates)}" if dates else "unknown"
            yield (group.hash or "")[:12], len(all_files), total_size, sources, date_range

    if output_format == "text":
        from rich.console import Console
        from rich.table import Table

        table = Table(title="Duplicate Groups")
        table.add_column("Hash", style="cyan", no_wrap=True)
        table.add_column("Count", justify="right")
        table.add_column("Total Size", justify="right")
        table.add_column("Sources")
        table.add_column("Date Range")

        for hash_, count, total_size, sources, date_range in _build_rows():
            table.add_row(
                hash_,
                str(count),
                f"{total_size / 1_048_576:.1f} MB",
                sources,
                date_range,
            )

        if output_path:
            buf = io.StringIO()
            Console(file=buf, no_color=True, width=200).print(table)
            with open(output_path, "w", encoding="utf-8") as fh:
                fh.write(buf.getvalue())
            click.echo(f"{len(groups):,} groups written to {output_path}")
        else:
            Console().print(table)

    elif output_format == "csv":
        rows = list(_build_rows())
        if output_path:
            with open(output_path, "w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerow(["hash", "count", "total_size", "sources", "date_range"])
                writer.writerows(
                    [h, c, ts, src, dr] for h, c, ts, src, dr in rows
                )
            click.echo(f"{len(groups):,} groups written to {output_path}")
        else:
            writer = csv.writer(sys.stdout)
            writer.writerow(["hash", "count", "total_size", "sources", "date_range"])
            writer.writerows([h, c, ts, src, dr] for h, c, ts, src, dr in rows)

    elif output_format == "json":
        json_rows = [
            {"hash": h, "count": c, "total_size_bytes": ts, "sources": src, "date_range": dr}
            for h, c, ts, src, dr in _build_rows()
        ]
        if output_path:
            with open(output_path, "w", encoding="utf-8") as fh:
                json.dump(json_rows, fh, indent=2)
            click.echo(f"{len(groups):,} groups written to {output_path}")
        else:
            print(json.dumps(json_rows, indent=2))


@main.command()
@click.option(
    "--config", "config_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, readable=True),
    help="Path to the YAML configuration file.",
)
@click.option(
    "--output-format",
    default="text",
    type=click.Choice(["text", "csv", "json"]),
    show_default=True,
    help="Output format for the report.",
)
@click.option(
    "--output", "output_path",
    default=None,
    type=click.Path(dir_okay=False, writable=True),
    help="Write report to this file instead of stdout.",
)
@click.pass_context
def report(ctx: click.Context, config_path: str, output_format: str, output_path: str | None) -> None:
    """Report duplicate media groups found in the catalog.

    Queries the catalog for files sharing the same SHA-256 hash and displays
    a summary table (text), CSV rows, or a JSON array.  Use --output FILE to
    write the full report to a file instead of the terminal.
    """
    verbose: bool = ctx.obj["verbose"]
    quiet: bool = ctx.obj["quiet"]

    groups = _run_report(config_path, output_format, verbose, quiet)

    if not quiet:
        _print_report(groups, output_format, quiet, output_path)


# ---------------------------------------------------------------------------
# plan-consolidation and consolidate subcommands
# ---------------------------------------------------------------------------


def _run_consolidate(
    config_path: str,
    dry_run: bool = True,
    verbose: bool = False,
) -> ConsolidationPlan:
    """Run the consolidation pipeline and return the plan.

    Pure helper — no click API calls. Directly testable without CliRunner.

    Args:
        config_path: Path to the YAML config file.
        dry_run:     When True, no files are written (D-16).
        verbose:     Reserved for per-file progress output in future.

    Returns:
        ConsolidationPlan with to_copy, to_manifest, skipped, and errors.
    """
    cfg = load_config(config_path)
    engine = create_catalog_engine(cfg.catalog_path)
    SessionLocal = session_factory(engine)
    with SessionLocal() as session:
        groups = find_duplicate_groups(
            session, cfg.consolidation.source_priority
        )
    plan = run_consolidation(groups, cfg, dry_run=dry_run)
    return plan


def _print_plan(plan: ConsolidationPlan, verbose: bool = False) -> None:
    """Print a human-readable summary of the consolidation plan.

    Args:
        plan:    ConsolidationPlan returned by _run_consolidate.
        verbose: When True, print each CopyAction src → dest.
    """
    click.echo("Consolidation plan:")
    click.echo(f"  Files to copy  : {len(plan.to_copy)}")
    click.echo(f"  Already present: {len(plan.skipped)}")
    click.echo(f"  Manifest entries: {len(plan.to_manifest)}")
    click.echo(f"  Errors         : {len(plan.errors)}")

    if verbose and plan.to_copy:
        for action in plan.to_copy:
            click.echo(f"    {action.src_path} -> {action.dest_path}")


@main.command(name="plan-consolidation")
@click.option(
    "--config", "config_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, readable=True),
    help="Path to the YAML configuration file.",
)
@click.pass_context
def plan_consolidation(ctx: click.Context, config_path: str) -> None:
    """Preview the consolidation plan without writing any files.

    Always runs in dry-run mode (D-16). Use `consolidate` to execute the plan.
    """
    verbose: bool = ctx.obj["verbose"]

    plan = _run_consolidate(config_path, dry_run=True, verbose=verbose)
    _print_plan(plan, verbose=verbose)
    click.echo("Dry run complete — no files written.")


@main.command()
@click.option(
    "--config", "config_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, readable=True),
    help="Path to the YAML configuration file.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Preview the consolidation plan without writing any files.",
)
@click.pass_context
def consolidate(ctx: click.Context, config_path: str, dry_run: bool) -> None:
    """Consolidate duplicate media files according to source priority.

    Shows the consolidation plan first. Without --dry-run, prompts for
    confirmation before executing the live copy pipeline (FR4 safety gate,
    T-05-01).
    """
    verbose: bool = ctx.obj["verbose"]

    # Always show the dry-run plan first so the user can review before committing
    plan = _run_consolidate(config_path, dry_run=True, verbose=verbose)
    _print_plan(plan, verbose=verbose)

    if dry_run:
        click.echo("Dry run complete — no files written.")
        return

    # Confirmation gate (T-05-01): abort=True causes click.Abort on 'N' / Ctrl-C
    click.confirm("Proceed with consolidation?", abort=True)

    # Live run
    plan = _run_consolidate(config_path, dry_run=False, verbose=verbose)
    _print_plan(plan, verbose=verbose)
    click.echo(
        f"Consolidation complete. {len(plan.to_copy)} file(s) copied, "
        f"{len(plan.errors)} error(s)."
    )
