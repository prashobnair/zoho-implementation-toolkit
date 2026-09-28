"""Ready/findings invariant over every golden input (forms parity follow-up).

For ALL 8 modules and all 37 golden manifest entries:
- ``ready is False`` implies at least one error or review finding, and
- ``ready is True`` implies zero error findings.

This guards the ``zohokit forms parity`` defect where a case whose source
and target outputs differ (``delivery_calculation``: multiply vs add) made
``ready=false`` with zero error/review findings, because the difference was
never surfaced as a Finding. Output differences now emit ``parity_mismatch``
(error) findings.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from zohokit.core.findings import Severity
from zohokit.modules import Analysis
from zohokit.modules.books.engine import analyze as analyze_books
from zohokit.modules.books.models import BooksInput
from zohokit.modules.forms.engine import analyze as analyze_forms
from zohokit.modules.forms.models import FormsInput
from zohokit.modules.lead_routing.engine import analyze as analyze_routing
from zohokit.modules.lead_routing.models import LeadRoutingInput
from zohokit.modules.metrics.engine import analyze as analyze_metrics
from zohokit.modules.metrics.models import MetricsInput
from zohokit.modules.migration.engine import analyze as analyze_migration
from zohokit.modules.migration.models import MigrationInput
from zohokit.modules.release.engine import analyze as analyze_release
from zohokit.modules.release.models import ReleaseInput
from zohokit.modules.timeline.engine import analyze as analyze_timeline
from zohokit.modules.timeline.models import TimelineInput
from zohokit.modules.workflow.engine import analyze as analyze_workflow
from zohokit.modules.workflow.models import WorkflowInput

ROOT = Path(__file__).resolve().parent.parent.parent

PORTS: dict[str, dict[str, Any]] = {
    "migration": {"model": MigrationInput, "analyze": analyze_migration},
    "release": {"model": ReleaseInput, "analyze": analyze_release},
    "workflow": {"model": WorkflowInput, "analyze": analyze_workflow},
    "forms": {"model": FormsInput, "analyze": analyze_forms},
    "books": {"model": BooksInput, "analyze": analyze_books},
    "metrics": {"model": MetricsInput, "analyze": analyze_metrics},
    "timeline": {"model": TimelineInput, "analyze": analyze_timeline},
    "lead_routing": {"model": LeadRoutingInput, "analyze": analyze_routing},
}


def _cases() -> list[tuple[str, dict[str, Any]]]:
    cases: list[tuple[str, dict[str, Any]]] = []
    for module in sorted(PORTS):
        manifest_path = ROOT / "tests" / "golden" / "legacy" / module / "_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for entry in manifest:
            cases.append((module, entry))
    return cases


CASES = _cases()
assert len(CASES) == 37, f"expected 37 golden entries, got {len(CASES)}"


def _argv_audience(argv: list[str]) -> str | None:
    if "--audience" in argv:
        return argv[argv.index("--audience") + 1]
    return None


@pytest.mark.parametrize(("module", "entry"), CASES)
def test_ready_implies_findings(module: str, entry: dict[str, Any]) -> None:
    """ready=False needs an error/review finding; ready=True needs no errors."""
    port = PORTS[module]
    inputs = json.loads((ROOT / entry["input"]).read_text(encoding="utf-8"))
    audience = _argv_audience(entry["argv"])
    if audience is None:
        analysis: Analysis = port["analyze"](port["model"].model_validate(inputs))
    else:
        analysis = port["analyze"](port["model"].model_validate(inputs), audience=audience)
    blocking = [
        finding
        for finding in analysis.findings
        if finding.severity in (Severity.ERROR, Severity.REVIEW)
    ]
    errors = [finding for finding in analysis.findings if finding.severity is Severity.ERROR]
    if analysis.ready is False:
        assert blocking != [], (
            f"{module} {entry['golden']}: ready is False "
            f"with zero error/review findings "
            f"({len(analysis.findings)} info/warning findings)"
        )
    else:
        assert errors == [], (
            f"{module} {entry['golden']}: ready is True "
            f"with error findings {[finding.code for finding in errors]}"
        )
