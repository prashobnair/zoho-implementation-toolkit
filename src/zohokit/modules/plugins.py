"""Third-party module registry (TK-ARCH-4).

Modules register via the ``zohokit.modules`` entry-point group so third
parties can add a module. Each entry point resolves to a Typer app whose
commands run under ``zohokit <name> ...``::

    [project.entry-points."zohokit.modules"]
    demo = "zohokit_demo:app"

The eight built-in modules are registered statically in ``zohokit.cli``;
entry points whose name collides with a built-in are ignored. An entry
point that fails to load (or is not a Typer app) is skipped with a
warning on stderr so one broken plugin never bricks the CLI.
"""

from __future__ import annotations

import sys
from importlib import metadata as _metadata

import typer

from zohokit.modules import MODULES

GROUP = "zohokit.modules"

# Built-in command names also declared as entry points in pyproject.toml
# (so the group lists every module); they mount statically in ``zohokit.cli``.
_BUILTIN_COMMANDS = frozenset(
    [*MODULES, "lead-routing"]  # MODULES uses lead_routing; the CLI spells it lead-routing
)


def _entry_points() -> tuple[_metadata.EntryPoint, ...]:
    """Scan the registry group. Separated for tests to stub."""
    return tuple(_metadata.entry_points(group=GROUP))


def discover_module_apps() -> dict[str, typer.Typer]:
    """Load third-party module apps, keyed by module name."""
    apps: dict[str, typer.Typer] = {}
    for entry in _entry_points():
        if entry.name in _BUILTIN_COMMANDS or entry.name in apps:
            continue
        try:
            loaded = entry.load()
        except Exception as exc:  # any plugin failure skips, with a warning
            print(f"warning: skipping plugin {entry.name!r}: {exc}", file=sys.stderr)
            continue
        if not isinstance(loaded, typer.Typer):
            print(
                f"warning: skipping plugin {entry.name!r}: entry point is not a typer.Typer app",
                file=sys.stderr,
            )
            continue
        apps[entry.name] = loaded
    return apps


__all__: list[str] = ["GROUP", "discover_module_apps"]
