"""Schema freshness: schemas/<module>/*.v1.json matches the models (TK-ARCH-5).

CI also enforces this with ``make schemas && git diff --exit-code``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from zohokit.core.findings import Report
from zohokit.modules.books.models import BooksInput
from zohokit.modules.forms.models import FormsInput
from zohokit.modules.lead_routing.models import LeadRoutingInput
from zohokit.modules.metrics.models import MetricsInput
from zohokit.modules.migration.models import MigrationInput
from zohokit.modules.release.manifest import Manifest
from zohokit.modules.release.models import ReleaseInput
from zohokit.modules.timeline.models import TimelineInput
from zohokit.modules.workflow.models import WorkflowInput

ROOT = Path(__file__).resolve().parent.parent

INPUTS: dict[str, type[BaseModel]] = {
    "migration": MigrationInput,
    "release": ReleaseInput,
    "workflow": WorkflowInput,
    "forms": FormsInput,
    "books": BooksInput,
    "metrics": MetricsInput,
    "timeline": TimelineInput,
    "lead_routing": LeadRoutingInput,
}


def _dump(schema: dict[str, Any]) -> str:
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def test_every_module_has_input_and_report_schemas() -> None:
    assert sorted(path.name for path in (ROOT / "schemas").iterdir() if path.is_dir()) == sorted(
        INPUTS
    )
    for module in sorted(INPUTS):
        assert (ROOT / "schemas" / module / "input.v1.json").is_file()
        assert (ROOT / "schemas" / module / "report.v1.json").is_file()


def test_input_schemas_match_models() -> None:
    for module, model in sorted(INPUTS.items()):
        on_disk = (ROOT / "schemas" / module / "input.v1.json").read_text(encoding="utf-8")
        assert on_disk == _dump(model.model_json_schema()), f"{module} input schema is stale"


def test_report_schemas_match_envelope() -> None:
    expected = _dump(Report.model_json_schema())
    for module in sorted(INPUTS):
        on_disk = (ROOT / "schemas" / module / "report.v1.json").read_text(encoding="utf-8")
        assert on_disk == expected, f"{module} report schema is stale"


def test_release_manifest_schema_matches_model() -> None:
    on_disk = (ROOT / "schemas" / "release" / "manifest.v2.json").read_text(encoding="utf-8")
    assert on_disk == _dump(Manifest.model_json_schema()), "release manifest.v2 schema is stale"
