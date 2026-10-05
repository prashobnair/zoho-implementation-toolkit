"""Export every input and output model to schemas/<module>/<name>.v<N>.json (TK-ARCH-5).

Usage: ``make schemas`` (repo root). Output is deterministic
(``sort_keys=True`` + trailing newline); CI fails when it is stale via
``make schemas && git diff --exit-code``.
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
from zohokit.modules.migration.mapping import MappingDoc
from zohokit.modules.migration.models import MigrationInput
from zohokit.modules.release.manifest import Manifest
from zohokit.modules.release.models import ReleaseInput
from zohokit.modules.timeline.models import TimelineInput
from zohokit.modules.workflow.models import WorkflowInput

ROOT = Path(__file__).resolve().parent.parent

SCHEMA_VERSION = 1

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


def _write(path: Path, schema: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Fixed LF: Path.write_text translates newlines on Windows checkouts,
    # which would dirty every schema file there (CI runs the LF diff).
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(schema, indent=2, sort_keys=True) + "\n")


def main() -> None:
    report_schema = Report.model_json_schema()
    for module, model in sorted(INPUTS.items()):
        _write(
            ROOT / "schemas" / module / f"input.v{SCHEMA_VERSION}.json", model.model_json_schema()
        )
        # The report envelope is shared; each module dir carries its own
        # copy so every output model resolves under schemas/<module>/.
        _write(ROOT / "schemas" / module / f"report.v{SCHEMA_VERSION}.json", report_schema)
    _write(ROOT / "schemas" / "release" / "manifest.v2.json", Manifest.model_json_schema())
    _write(ROOT / "schemas" / "migration" / "mapping.v1.json", MappingDoc.model_json_schema())
    print(f"wrote {2 * len(INPUTS) + 2} schemas (v{SCHEMA_VERSION})")


if __name__ == "__main__":
    main()
