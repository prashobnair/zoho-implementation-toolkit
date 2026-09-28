"""Global-flag tests: every root flag works, and future flags fail loudly (TK-X-1)."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from zohokit.cli import app

ROOT = Path(__file__).resolve().parent.parent
GOLDEN_INPUTS = ROOT / "tests" / "golden" / "legacy"
MIGRATION_FIXTURE = str(GOLDEN_INPUTS / "migration" / "inputs" / "examples.json")
FORMS_FIXTURE = str(GOLDEN_INPUTS / "forms" / "inputs" / "examples.json")

runner = CliRunner()


def test_live_fails_loudly_without_touching_network() -> None:
    """--live exits 1 with a clear message, even before reading the input file."""
    result = runner.invoke(app, ["--live", "migration", "audit", "no-such-file.json"])
    assert result.exit_code == 1
    assert result.output == (
        "Input error: Live reads are not available until v0.2.0. This run touched no network.\n"
    )


def test_profile_fails_loudly() -> None:
    result = runner.invoke(app, ["--profile", "dev-in", "version"])
    assert result.exit_code == 1
    assert result.output == "Input error: Profiles are not available until v0.2.0.\n"


def test_ai_fails_loudly() -> None:
    result = runner.invoke(app, ["--ai", "version"])
    assert result.exit_code == 1
    assert result.output == "Input error: AI assistance is not available until v0.3.0.\n"


def test_baseline_fails_loudly() -> None:
    result = runner.invoke(app, ["--baseline", ".zohokit-baseline.json", "version"])
    assert result.exit_code == 1
    assert result.output == "Input error: Baseline suppression is not available until v0.2.0.\n"


def test_max_api_calls_fails_loudly() -> None:
    result = runner.invoke(app, ["--max-api-calls", "10", "version"])
    assert result.exit_code == 1
    assert result.output == "Input error: API call budgets are not available until v0.2.0.\n"


def test_global_strict_blocks_like_command_strict() -> None:
    result = runner.invoke(app, ["--strict", "forms", "parity", FORMS_FIXTURE])
    assert result.exit_code == 2


def test_global_format_selects_renderer() -> None:
    result = runner.invoke(app, ["--format", "table", "migration", "audit", MIGRATION_FIXTURE])
    assert result.exit_code == 0
    assert "orphan_person" in result.output


def test_command_format_wins_over_global_default() -> None:
    result = runner.invoke(app, ["migration", "audit", MIGRATION_FIXTURE, "--format", "markdown"])
    assert result.exit_code == 0
    assert result.output.startswith("# zohokit migration report")


def test_completion_script_available() -> None:
    result = runner.invoke(app, ["--show-completion", "bash"])
    assert result.exit_code == 0
    assert "COMP_WORDS" in result.output
    assert "complete -o default" in result.output
