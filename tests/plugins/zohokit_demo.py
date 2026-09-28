"""Demo third-party plugin for the ``zohokit.modules`` registry (TK-ARCH-4).

This package is never installed; the registry test loads it from
``tests/plugins/`` through a stubbed entry point
(``demo = "zohokit_demo:app"``) and asserts ``zohokit modules list``
discovers it. The real-world declaration lives in ``demo/pyproject.toml``.
"""

from __future__ import annotations

import typer

app = typer.Typer(help="Demo plugin proving third-party module registration.")


@app.command()
def hello() -> None:
    """Greet from the demo plugin."""
    typer.echo("hello from zohokit-demo")


__all__: list[str] = ["app"]
