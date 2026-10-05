"""Offline source readers for non-Zoho exports (TK-CONN-8, TK-MIG-F2).

Generic CSV plus the Pipedrive and HubSpot export layouts. Each reader
documents its assumed layout, streams rows (no full-file load), and
reports row-level problems to the caller instead of aborting the run.
"""

from __future__ import annotations

__all__: list[str] = []
