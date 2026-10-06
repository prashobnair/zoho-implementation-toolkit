"""Global-flag tests: shared rendering flags work; live stays loud; AI opts in (TK-X-1).

``--live``/``--profile``/``--max-api-calls`` are honored by the auth,
doctor and cache commands; module commands refuse them loudly (their live
paths are not wired yet). ``--ai`` is opt-in everywhere: with no provider
configured the tool notes "AI disabled" and runs its deterministic path
(STD-AI4). ``--baseline`` applies an accepted-findings file wherever a
report is produced.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from zohokit.cli import app
from zohokit.cli.common import AI_DISABLED_NOTE

ROOT = Path(__file__).resolve().parent.parent
GOLDEN_INPUTS = ROOT / "tests" / "golden" / "legacy"
MIGRATION_FIXTURE = str(GOLDEN_INPUTS / "migration" / "inputs" / "examples.json")
FORMS_FIXTURE = str(GOLDEN_INPUTS / "forms" / "inputs" / "examples.json")

LIVE_REFUSED = (
    "Input error: Live reads are not available for `migration` yet. "
    "This run touched no network. "
    "Use `zohokit auth login`, `zohokit doctor` and `zohokit cache` for now.\n"
)

runner = CliRunner()


def test_live_refused_on_module_before_any_input() -> None:
    """--live on a module fails before the (missing) input file is even read."""
    result = runner.invoke(app, ["--live", "migration", "audit", "no-such-file.json"])
    assert result.exit_code == 1
    assert result.output == LIVE_REFUSED


def test_profile_refused_on_module() -> None:
    result = runner.invoke(app, ["--profile", "dev-in", "version"])
    assert result.exit_code == 1
    assert "not available for `version` yet" in result.output
    assert "touched no network" in result.output


def _clear_ai_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """No provider configured: the deterministic path must run (STD-AI4)."""
    for name in (
        "ZOHOKIT_AI_PROVIDER",
        "ZOHOKIT_AI_MODEL",
        "ZOHOKIT_AI_API_KEY",
        "ZOHOKIT_AI_BASE_URL",
        "ANTHROPIC_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


def test_ai_disabled_runs_deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    """--ai with no provider configured: "AI disabled", exit 0 (STD-AI4)."""
    _clear_ai_env(monkeypatch)
    result = runner.invoke(app, ["--ai", "version"])
    assert result.exit_code == 0
    assert AI_DISABLED_NOTE in result.output


def test_baseline_ignored_by_version() -> None:
    """`version` produces no findings, so a baseline is accepted and ignored."""
    result = runner.invoke(app, ["--baseline", ".zohokit-baseline.json", "version"])
    assert result.exit_code == 0


def test_max_api_calls_refused_on_module() -> None:
    result = runner.invoke(app, ["--max-api-calls", "10", "version"])
    assert result.exit_code == 1
    assert "not available for `version` yet" in result.output


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
    # `--show-completion` is a flag: Typer detects the parent shell via
    # shellingham, so the script is bash under bash and PowerShell under
    # pwsh (notably on the Windows CI job). Accept either script.
    result = runner.invoke(app, ["--show-completion", "bash"])
    assert result.exit_code == 0
    assert result.output.strip()
    is_bash = "COMP_WORDS" in result.output and "complete -o default" in result.output
    assert is_bash or "Register-ArgumentCompleter" in result.output


def test_live_after_subcommand_refused() -> None:
    """Same refusal from the after-subcommand position."""
    result = runner.invoke(app, ["migration", "audit", MIGRATION_FIXTURE, "--live"])
    assert result.exit_code == 1
    assert result.output == LIVE_REFUSED


def test_profile_after_subcommand_refused() -> None:
    result = runner.invoke(app, ["migration", "audit", MIGRATION_FIXTURE, "--profile", "dev-in"])
    assert result.exit_code == 1
    assert "not available for `migration` yet" in result.output


def test_ai_after_subcommand_runs_deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same opt-in from the after-subcommand position: note plus report."""
    _clear_ai_env(monkeypatch)
    result = runner.invoke(app, ["migration", "audit", MIGRATION_FIXTURE, "--ai"])
    assert result.exit_code == 0
    assert AI_DISABLED_NOTE in result.output
    assert "orphan_person" in result.output


def test_ai_allow_pii_refused_with_live() -> None:
    """--ai-allow-pii with --live fails before anything runs (STD-AI8)."""
    result = runner.invoke(app, ["--live", "--ai-allow-pii", "version"])
    assert result.exit_code == 1
    assert "--ai-allow-pii is refused with --live" in result.output


def test_ai_max_tokens_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    """--ai-max-tokens parses and the command still runs (STD-AI9)."""
    _clear_ai_env(monkeypatch)
    result = runner.invoke(app, ["--ai-max-tokens", "500", "version"])
    assert result.exit_code == 0


def test_baseline_missing_file_fails_loudly() -> None:
    result = runner.invoke(
        app, ["migration", "audit", MIGRATION_FIXTURE, "--baseline", ".zohokit-baseline.json"]
    )
    assert result.exit_code == 1
    assert result.output.startswith("Input error: cannot read baseline file")


def test_max_api_calls_after_subcommand_refused() -> None:
    result = runner.invoke(app, ["migration", "audit", MIGRATION_FIXTURE, "--max-api-calls", "10"])
    assert result.exit_code == 1
    assert "not available for `migration` yet" in result.output
