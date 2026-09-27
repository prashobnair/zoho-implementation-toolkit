"""Architecture contract tests: TK-ARCH-3 via import-linter, TK-ARCH-1 purity."""

from __future__ import annotations

from pathlib import Path

from importlinter import cli

SRC = Path(__file__).resolve().parent.parent / "src" / "zohokit" / "modules"


def test_import_contracts() -> None:
    assert (
        cli.lint_imports(config_filename=".importlinter", no_cache=True, no_logo=True)
        == cli.EXIT_STATUS_SUCCESS
    )


def test_engines_read_no_wall_clock() -> None:
    """TK-ARCH-1: engines take a RunContext; no datetime.now() in engine.py."""
    engines = sorted(SRC.glob("*/engine.py"))
    assert len(engines) == 4
    for engine in engines:
        source = engine.read_text(encoding="utf-8")
        assert "datetime.now" not in source, engine
        assert "time.time" not in source, engine
        assert "RunContext" in source, engine


def test_findings_use_create_only() -> None:
    """Ported findings are built with Finding.create, never Finding(...)."""
    checked = 0
    for path in sorted(SRC.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        assert "Finding(" not in source, path
        checked += 1
    assert checked > 0
