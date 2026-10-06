"""Migration scale benchmark: 100k rows offline (TK-MIG-F11).

Runs only under ``pytest -m bench`` (never in default CI): 100k source
rows must audit in under 60s with peak memory under 500 MB. Reports the
measured time and peak so the PR body can quote local numbers.
"""

from __future__ import annotations

import time
import tracemalloc
from datetime import UTC, datetime
from pathlib import Path

import pytest

from zohokit.core.context import RunContext
from zohokit.modules.migration.mapping import MappingDoc
from zohokit.modules.migration.metadata import metadata_from_dir
from zohokit.modules.migration.preflight import SourceSpec, run_preflight

pytestmark = pytest.mark.bench

ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES = ROOT / "fixtures" / "migration"

ROWS = 100_000
BUDGET_SECONDS = 60.0
BUDGET_MB = 500.0


def test_100k_rows_within_budget(tmp_path: Path) -> None:
    big = tmp_path / "persons.csv"
    with open(big, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("ID,Name,Email,Phone,Organization ID,Source,Created\n")
        for index in range(ROWS):
            handle.write(
                f"{index},Person {index},person{index}@example.invalid,"
                f"+919000{index % 1000000:06d},{index % 200},web,2026-01-05\n"
            )
    doc = MappingDoc.model_validate(
        {
            "version": 1,
            "source": "generic",
            "entities": [
                {
                    "name": "people",
                    "source_kind": "persons",
                    "target_module": "Contacts",
                    "fields": {
                        "Last_Name": {"from": "Name"},
                        "Email": {"from": "Email"},
                    },
                }
            ],
        }
    )
    metadata = metadata_from_dir(FIXTURES / "fields")
    sources = {"people": SourceSpec(path=str(big), kind="persons")}
    tracemalloc.start()
    started = time.perf_counter()
    report = run_preflight(
        doc, sources, metadata, ctx=RunContext(now=datetime(2026, 1, 5, tzinfo=UTC))
    )
    elapsed = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    peak_mb = peak / (1024 * 1024)
    print(f"\nbench: {ROWS} rows in {elapsed:.1f}s, peak {peak_mb:.1f} MB")
    assert report.ready is True
    assert elapsed < BUDGET_SECONDS, f"{elapsed:.1f}s exceeds {BUDGET_SECONDS:.0f}s"
    assert peak_mb < BUDGET_MB, f"{peak_mb:.1f} MB exceeds {BUDGET_MB:.0f} MB"
