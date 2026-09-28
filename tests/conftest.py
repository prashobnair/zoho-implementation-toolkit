"""Shared test setup."""

from __future__ import annotations

import os

# Typer sizes rich help panels from TERMINAL_WIDTH at import time; pin it so
# --help snapshots are identical on every machine and in CI.
os.environ.setdefault("TERMINAL_WIDTH", "80")
