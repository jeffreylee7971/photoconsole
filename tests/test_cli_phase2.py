"""CLI integration tests for Phase 2 commands: report, plan-consolidation, consolidate.

Tests exercise the full CLI pipeline using click.testing.CliRunner.
Database state is seeded directly via SQLAlchemy to avoid running a full scan.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from photoconsole.cli import main
from photoconsole.catalog import create_catalog_engine, session_factory, upsert_many


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _write_config(
    config_path: Path,
    catalog_path: Path,
    source_path: Path,
    destination_path: str = "",
    source_priority: list[str] | None = None,
) -> None:
    """Write a minimal config.yaml for Phase 2 testing."""
    lines = [
        f"catalog_path: '{catalog_path}'",
        "sources:",
        "  - name: 'D: SSD'",
        "    type: local",
        f"    path: '{source_path}'",
        "include_extensions:",
        "  - '.jpg'",
    ]
    priority = source_priority or ["D: SSD", "OneDrive"]
    priority_lines = "\n".join(f"  - '{s}'" for s in priority)
    lines.append("consolidation:")
    if destination_path:
        lines.append(f"  destination_path: '{destination_path}'")
    lines.append(f"  source_priority:\n{priority_lines}")
    config_path.write_text("\n".join(lines), encoding="utf-8")


def _seed_duplicates(catalog_path: Path, source_path: Path) -> None:
    """Insert two catalog rows that share a hash to create a duplicate group."""
    engine = create_catalog_engine(str(catalog_path))
    SessionLocal = session_factory(engine)
    records = [
        {
            "path": str(source_path / "a.jpg"),
            "hash": "abc123" * 10 + "ab12",  # 64-char hex
            "source_name": "D: SSD",
            "source_type": "local",
            "status": "ok",
            "size": 1024,
            "date_taken": "2023:06:15 10:30:00",
            "mtime": 1700000000.0,
        },
        {
            "path": str(source_path / "b.jpg"),
            "hash": "abc123" * 10 + "ab12",  # same hash — duplicate!
            "source_name": "OneDrive",
            "source_type": "rclone",
            "status": "ok",
            "size": 1024,
            "date_taken": "2023:06:15 10:30:00",
            "mtime": 1700000001.0,
        },
    ]
    with SessionLocal() as session:
        upsert_many(session, records)
        session.commit()


# ---------------------------------------------------------------------------
# Task 1: report command — text / csv / json output modes
# ---------------------------------------------------------------------------

class TestReportText:
    """report command with default text output (rich table)."""

    def test_report_text_exit_code_zero_with_duplicates(self, tmp_path):
        source_path = tmp_path / "media"
        source_path.mkdir()
        catalog_path = tmp_path / "catalog.db"
        config_path = tmp_path / "config.yaml"
        _write_config(config_path, catalog_path, source_path)
        _seed_duplicates(catalog_path, source_path)

        runner = CliRunner()
        result = runner.invoke(main, ["report", "--config", str(config_path)])
        assert result.exit_code == 0, result.output

    def test_report_text_shows_duplicate_groups_header(self, tmp_path):
        source_path = tmp_path / "media"
        source_path.mkdir()
        catalog_path = tmp_path / "catalog.db"
        config_path = tmp_path / "config.yaml"
        _write_config(config_path, catalog_path, source_path)
        _seed_duplicates(catalog_path, source_path)

        runner = CliRunner()
        result = runner.invoke(main, ["report", "--config", str(config_path)])
        assert result.exit_code == 0, result.output
        assert "Duplicate Groups" in result.output or "duplicate" in result.output.lower()

    def test_report_text_shows_12char_hash_prefix(self, tmp_path):
        source_path = tmp_path / "media"
        source_path.mkdir()
        catalog_path = tmp_path / "catalog.db"
        config_path = tmp_path / "config.yaml"
        _write_config(config_path, catalog_path, source_path)
        _seed_duplicates(catalog_path, source_path)

        runner = CliRunner()
        result = runner.invoke(main, ["report", "--config", str(config_path)])
        assert result.exit_code == 0, result.output
        # The 12-char prefix of "abc123" * 10 + "ab12" is "abc123abc123"
        assert "abc123abc123" in result.output

    def test_report_text_zero_rows_when_no_duplicates(self, tmp_path):
        source_path = tmp_path / "media"
        source_path.mkdir()
        catalog_path = tmp_path / "catalog.db"
        config_path = tmp_path / "config.yaml"
        _write_config(config_path, catalog_path, source_path)
        # No seed — empty catalog

        runner = CliRunner()
        result = runner.invoke(main, ["report", "--config", str(config_path)])
        assert result.exit_code == 0, result.output


class TestReportCsv:
    """report command with --output-format csv."""

    def test_report_csv_exit_code_zero(self, tmp_path):
        source_path = tmp_path / "media"
        source_path.mkdir()
        catalog_path = tmp_path / "catalog.db"
        config_path = tmp_path / "config.yaml"
        _write_config(config_path, catalog_path, source_path)
        _seed_duplicates(catalog_path, source_path)

        runner = CliRunner()
        result = runner.invoke(
            main, ["report", "--config", str(config_path), "--output-format", "csv"]
        )
        assert result.exit_code == 0, result.output

    def test_report_csv_header_present(self, tmp_path):
        source_path = tmp_path / "media"
        source_path.mkdir()
        catalog_path = tmp_path / "catalog.db"
        config_path = tmp_path / "config.yaml"
        _write_config(config_path, catalog_path, source_path)
        _seed_duplicates(catalog_path, source_path)

        runner = CliRunner()
        result = runner.invoke(
            main, ["report", "--config", str(config_path), "--output-format", "csv"]
        )
        assert "hash,count,total_size,sources,date_range" in result.output

    def test_report_csv_data_row_present(self, tmp_path):
        source_path = tmp_path / "media"
        source_path.mkdir()
        catalog_path = tmp_path / "catalog.db"
        config_path = tmp_path / "config.yaml"
        _write_config(config_path, catalog_path, source_path)
        _seed_duplicates(catalog_path, source_path)

        runner = CliRunner()
        result = runner.invoke(
            main, ["report", "--config", str(config_path), "--output-format", "csv"]
        )
        lines = result.output.strip().splitlines()
        # Header + at least 1 data row
        assert len(lines) >= 2

    def test_report_csv_12char_hash_in_data(self, tmp_path):
        source_path = tmp_path / "media"
        source_path.mkdir()
        catalog_path = tmp_path / "catalog.db"
        config_path = tmp_path / "config.yaml"
        _write_config(config_path, catalog_path, source_path)
        _seed_duplicates(catalog_path, source_path)

        runner = CliRunner()
        result = runner.invoke(
            main, ["report", "--config", str(config_path), "--output-format", "csv"]
        )
        assert "abc123abc123" in result.output


class TestReportJson:
    """report command with --output-format json."""

    def test_report_json_exit_code_zero(self, tmp_path):
        source_path = tmp_path / "media"
        source_path.mkdir()
        catalog_path = tmp_path / "catalog.db"
        config_path = tmp_path / "config.yaml"
        _write_config(config_path, catalog_path, source_path)
        _seed_duplicates(catalog_path, source_path)

        runner = CliRunner()
        result = runner.invoke(
            main, ["report", "--config", str(config_path), "--output-format", "json"]
        )
        assert result.exit_code == 0, result.output

    def test_report_json_is_valid_json(self, tmp_path):
        source_path = tmp_path / "media"
        source_path.mkdir()
        catalog_path = tmp_path / "catalog.db"
        config_path = tmp_path / "config.yaml"
        _write_config(config_path, catalog_path, source_path)
        _seed_duplicates(catalog_path, source_path)

        runner = CliRunner()
        result = runner.invoke(
            main, ["report", "--config", str(config_path), "--output-format", "json"]
        )
        parsed = json.loads(result.output)
        assert isinstance(parsed, list)

    def test_report_json_has_required_keys(self, tmp_path):
        source_path = tmp_path / "media"
        source_path.mkdir()
        catalog_path = tmp_path / "catalog.db"
        config_path = tmp_path / "config.yaml"
        _write_config(config_path, catalog_path, source_path)
        _seed_duplicates(catalog_path, source_path)

        runner = CliRunner()
        result = runner.invoke(
            main, ["report", "--config", str(config_path), "--output-format", "json"]
        )
        parsed = json.loads(result.output)
        assert len(parsed) == 1
        item = parsed[0]
        assert "hash" in item
        assert "count" in item
        assert "total_size_bytes" in item
        assert "sources" in item
        assert "date_range" in item

    def test_report_json_12char_hash(self, tmp_path):
        source_path = tmp_path / "media"
        source_path.mkdir()
        catalog_path = tmp_path / "catalog.db"
        config_path = tmp_path / "config.yaml"
        _write_config(config_path, catalog_path, source_path)
        _seed_duplicates(catalog_path, source_path)

        runner = CliRunner()
        result = runner.invoke(
            main, ["report", "--config", str(config_path), "--output-format", "json"]
        )
        parsed = json.loads(result.output)
        assert parsed[0]["hash"] == "abc123abc123"

    def test_report_json_total_size_bytes_is_int(self, tmp_path):
        source_path = tmp_path / "media"
        source_path.mkdir()
        catalog_path = tmp_path / "catalog.db"
        config_path = tmp_path / "config.yaml"
        _write_config(config_path, catalog_path, source_path)
        _seed_duplicates(catalog_path, source_path)

        runner = CliRunner()
        result = runner.invoke(
            main, ["report", "--config", str(config_path), "--output-format", "json"]
        )
        parsed = json.loads(result.output)
        assert isinstance(parsed[0]["total_size_bytes"], int)
        assert parsed[0]["total_size_bytes"] == 2048  # 1024 + 1024

    def test_report_json_empty_when_no_duplicates(self, tmp_path):
        source_path = tmp_path / "media"
        source_path.mkdir()
        catalog_path = tmp_path / "catalog.db"
        config_path = tmp_path / "config.yaml"
        _write_config(config_path, catalog_path, source_path)

        runner = CliRunner()
        result = runner.invoke(
            main, ["report", "--config", str(config_path), "--output-format", "json"]
        )
        parsed = json.loads(result.output)
        assert parsed == []


class TestReportImport:
    """Verify _run_report is importable and pure."""

    def test_run_report_importable(self):
        from photoconsole.cli import _run_report  # noqa: F401
        assert callable(_run_report)

    def test_report_command_registered(self):
        """report command must appear in main's commands."""
        assert "report" in main.commands

    def test_report_accepts_output_format_choices(self):
        runner = CliRunner()
        # Passing an invalid choice should exit non-zero
        result = runner.invoke(
            main, ["report", "--config", "config.yaml", "--output-format", "xml"]
        )
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Task 2: plan-consolidation and consolidate commands
# ---------------------------------------------------------------------------

class TestPlanConsolidation:
    """plan-consolidation command — always dry_run=True."""

    def test_plan_consolidation_exits_zero(self, tmp_path):
        source_path = tmp_path / "media"
        source_path.mkdir()
        dest_path = tmp_path / "dest"
        dest_path.mkdir()
        catalog_path = tmp_path / "catalog.db"
        config_path = tmp_path / "config.yaml"
        _write_config(config_path, catalog_path, source_path,
                      destination_path=str(dest_path))
        _seed_duplicates(catalog_path, source_path)

        runner = CliRunner()
        result = runner.invoke(
            main, ["plan-consolidation", "--config", str(config_path)]
        )
        assert result.exit_code == 0, result.output

    def test_plan_consolidation_prints_dry_run_message(self, tmp_path):
        source_path = tmp_path / "media"
        source_path.mkdir()
        dest_path = tmp_path / "dest"
        dest_path.mkdir()
        catalog_path = tmp_path / "catalog.db"
        config_path = tmp_path / "config.yaml"
        _write_config(config_path, catalog_path, source_path,
                      destination_path=str(dest_path))
        _seed_duplicates(catalog_path, source_path)

        runner = CliRunner()
        result = runner.invoke(
            main, ["plan-consolidation", "--config", str(config_path)]
        )
        assert "dry run" in result.output.lower() or "no files written" in result.output.lower()

    def test_plan_consolidation_prints_plan_summary(self, tmp_path):
        source_path = tmp_path / "media"
        source_path.mkdir()
        dest_path = tmp_path / "dest"
        dest_path.mkdir()
        catalog_path = tmp_path / "catalog.db"
        config_path = tmp_path / "config.yaml"
        _write_config(config_path, catalog_path, source_path,
                      destination_path=str(dest_path))
        _seed_duplicates(catalog_path, source_path)

        runner = CliRunner()
        result = runner.invoke(
            main, ["plan-consolidation", "--config", str(config_path)]
        )
        assert "consolidation plan" in result.output.lower()

    def test_plan_consolidation_writes_no_files(self, tmp_path):
        source_path = tmp_path / "media"
        source_path.mkdir()
        dest_path = tmp_path / "dest"
        dest_path.mkdir()
        catalog_path = tmp_path / "catalog.db"
        config_path = tmp_path / "config.yaml"
        _write_config(config_path, catalog_path, source_path,
                      destination_path=str(dest_path))
        _seed_duplicates(catalog_path, source_path)

        runner = CliRunner()
        result = runner.invoke(
            main, ["plan-consolidation", "--config", str(config_path)]
        )
        assert result.exit_code == 0, result.output
        # dest_path should contain no files (dry run)
        assert list(dest_path.iterdir()) == []

    def test_plan_consolidation_command_registered(self):
        assert "plan-consolidation" in main.commands


class TestConsolidateDryRun:
    """consolidate --dry-run flag."""

    def test_consolidate_dry_run_exits_zero(self, tmp_path):
        source_path = tmp_path / "media"
        source_path.mkdir()
        dest_path = tmp_path / "dest"
        dest_path.mkdir()
        catalog_path = tmp_path / "catalog.db"
        config_path = tmp_path / "config.yaml"
        _write_config(config_path, catalog_path, source_path,
                      destination_path=str(dest_path))
        _seed_duplicates(catalog_path, source_path)

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["consolidate", "--config", str(config_path), "--dry-run"],
        )
        assert result.exit_code == 0, result.output

    def test_consolidate_dry_run_prints_dry_run_message(self, tmp_path):
        source_path = tmp_path / "media"
        source_path.mkdir()
        dest_path = tmp_path / "dest"
        dest_path.mkdir()
        catalog_path = tmp_path / "catalog.db"
        config_path = tmp_path / "config.yaml"
        _write_config(config_path, catalog_path, source_path,
                      destination_path=str(dest_path))
        _seed_duplicates(catalog_path, source_path)

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["consolidate", "--config", str(config_path), "--dry-run"],
        )
        assert "dry run" in result.output.lower() or "no files written" in result.output.lower()

    def test_consolidate_dry_run_writes_no_files(self, tmp_path):
        source_path = tmp_path / "media"
        source_path.mkdir()
        dest_path = tmp_path / "dest"
        dest_path.mkdir()
        catalog_path = tmp_path / "catalog.db"
        config_path = tmp_path / "config.yaml"
        _write_config(config_path, catalog_path, source_path,
                      destination_path=str(dest_path))
        _seed_duplicates(catalog_path, source_path)

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["consolidate", "--config", str(config_path), "--dry-run"],
        )
        assert result.exit_code == 0, result.output
        # No files copied
        assert list(dest_path.iterdir()) == []


class TestConsolidateLiveRun:
    """consolidate command without --dry-run — requires confirmation prompt."""

    def test_consolidate_prompts_for_confirmation(self, tmp_path):
        source_path = tmp_path / "media"
        source_path.mkdir()
        dest_path = tmp_path / "dest"
        dest_path.mkdir()
        catalog_path = tmp_path / "catalog.db"
        config_path = tmp_path / "config.yaml"
        _write_config(config_path, catalog_path, source_path,
                      destination_path=str(dest_path))
        _seed_duplicates(catalog_path, source_path)

        runner = CliRunner()
        # Send 'n' to abort — if no prompt exists the output won't show it
        result = runner.invoke(
            main,
            ["consolidate", "--config", str(config_path)],
            input="n\n",
        )
        # abort=True on click.confirm means Ctrl+C / 'n' exits non-zero
        assert result.exit_code != 0 or "abort" in result.output.lower()

    def test_consolidate_with_confirm_yes_exits_zero(self, tmp_path):
        source_path = tmp_path / "media"
        source_path.mkdir()
        dest_path = tmp_path / "dest"
        dest_path.mkdir()
        catalog_path = tmp_path / "catalog.db"
        config_path = tmp_path / "config.yaml"
        _write_config(config_path, catalog_path, source_path,
                      destination_path=str(dest_path))
        # No duplicates so consolidation plan is trivially a no-op
        # (avoids actual file I/O while testing the confirmation gate)

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["consolidate", "--config", str(config_path)],
            input="y\n",
        )
        assert result.exit_code == 0, result.output


class TestConsolidateImport:
    """Verify _run_consolidate is importable and commands are registered."""

    def test_run_consolidate_importable(self):
        from photoconsole.cli import _run_consolidate  # noqa: F401
        assert callable(_run_consolidate)

    def test_consolidate_command_registered(self):
        assert "consolidate" in main.commands

    def test_consolidate_has_dry_run_flag(self):
        runner = CliRunner()
        result = runner.invoke(main, ["consolidate", "--help"])
        assert "--dry-run" in result.output
