"""Plugin registry tests: third-party modules via entry points (TK-ARCH-4)."""

from __future__ import annotations

import tomllib
from importlib import metadata as importlib_metadata
from importlib.metadata import EntryPoint
from pathlib import Path

import pytest
from typer.testing import CliRunner

import zohokit.modules.plugins as plugins
from zohokit.cli import create_app
from zohokit.modules import MODULES

PLUGINS_DIR = Path(__file__).resolve().parent / "plugins"

runner = CliRunner()


def _demo_entry() -> EntryPoint:
    return EntryPoint(name="demo", value="zohokit_demo:app", group=plugins.GROUP)


def _stub_demo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.syspath_prepend(str(PLUGINS_DIR))
    monkeypatch.setattr(plugins, "_entry_points", lambda: (_demo_entry(),))


def test_demo_plugin_declares_registry_group() -> None:
    """The fixture plugin really registers via the zohokit.modules group."""
    with (PLUGINS_DIR / "demo" / "pyproject.toml").open("rb") as handle:
        declared = tomllib.load(handle)
    assert declared["project"]["entry-points"]["zohokit.modules"] == {"demo": "zohokit_demo:app"}


def test_installed_dist_declares_builtin_modules() -> None:
    """The installed package exposes all 8 built-ins in the registry group."""
    try:
        dist = importlib_metadata.distribution("zohokit")
    except importlib_metadata.PackageNotFoundError:
        pytest.skip("zohokit is not installed in this environment")
    declared = {point.name for point in dist.entry_points if point.group == plugins.GROUP}
    assert declared == {
        "migration",
        "release",
        "workflow",
        "forms",
        "books",
        "metrics",
        "timeline",
        "lead-routing",
    }


def test_plugin_discovered_by_modules_list(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_demo(monkeypatch)
    result = runner.invoke(create_app(), ["modules", "list"])
    assert result.exit_code == 0
    assert result.output.splitlines() == [*MODULES, "demo"]


def test_plugin_commands_mount(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_demo(monkeypatch)
    result = runner.invoke(create_app(), ["demo", "hello"])
    assert result.exit_code == 0
    assert result.output == "hello from zohokit-demo\n"


def test_builtin_name_entry_point_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """An entry point colliding with a built-in never duplicates it."""
    monkeypatch.syspath_prepend(str(PLUGINS_DIR))
    monkeypatch.setattr(
        plugins,
        "_entry_points",
        lambda: (
            EntryPoint(name="forms", value="zohokit_demo:app", group=plugins.GROUP),
            _demo_entry(),
        ),
    )
    result = runner.invoke(create_app(), ["modules", "list"])
    assert result.exit_code == 0
    assert result.output.splitlines() == [*MODULES, "demo"]


def test_broken_plugin_skipped_with_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        plugins,
        "_entry_points",
        lambda: (
            EntryPoint(name="broken", value="no_such_module:app", group=plugins.GROUP),
            _demo_entry(),
        ),
    )
    monkeypatch.syspath_prepend(str(PLUGINS_DIR))
    result = runner.invoke(create_app(), ["modules", "list"])
    assert result.exit_code == 0
    assert result.stdout.splitlines() == [*MODULES, "demo"]
    assert "warning: skipping plugin 'broken'" in result.output


def test_non_typer_plugin_skipped_with_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.syspath_prepend(str(PLUGINS_DIR))
    monkeypatch.setattr(
        plugins,
        "_entry_points",
        lambda: (EntryPoint(name="odd", value="zohokit_demo:__name__", group=plugins.GROUP),),
    )
    result = runner.invoke(create_app(), ["modules", "list"])
    assert result.exit_code == 0
    assert result.stdout.splitlines() == [*MODULES]
    assert "warning: skipping plugin 'odd'" in result.output
