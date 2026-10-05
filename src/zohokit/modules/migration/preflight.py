"""Migration preflight orchestration (TK-MIG-F1..F3).

Streams each mapped source file, converts row-level problems to
``row_parse_error`` findings (the run never aborts on a bad row), and
validates the mapping plus a head sample against the target metadata.
Pure apart from file reads; the frozen clock keeps reports identical.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from zohokit.connectors.sources import csv_reader, hubspot, pipedrive
from zohokit.connectors.sources.csv_reader import CsvReadError, CsvStream
from zohokit.core.context import RunContext
from zohokit.core.findings import Finding, Report, Severity
from zohokit.core.ids import canonical_json
from zohokit.modules import Analysis
from zohokit.modules.migration.mapping import MappingDoc
from zohokit.modules.migration.metadata import SAMPLE_ROWS, TargetMetadata, validate_mapping
from zohokit.modules.migration.report import build_report

#: Source formats the preflight accepts (mirrors mapping ``source``).
SOURCE_FORMATS = ("generic", "pipedrive", "hubspot")

#: Pipedrive file kind per mapping entity name (override via SourceSpec.kinds).
PIPEDRIVE_KINDS = ("persons", "organizations", "deals", "activities")

#: HubSpot file kind per mapping entity name (override via SourceSpec.kinds).
HUBSPOT_KINDS = ("contacts", "companies", "deals")


@dataclass(frozen=True)
class SourceSpec:
    """Where one entity's rows stream from."""

    path: str
    kind: str = ""


def _open_entity(source_format: str, spec: SourceSpec, entity_name: str) -> CsvStream:
    """Open one entity file; layout errors propagate as config errors."""
    if source_format == "pipedrive":
        return pipedrive.open_kind(spec.path, kind=spec.kind or entity_name)
    if source_format == "hubspot":
        return hubspot.open_kind(spec.path, kind=spec.kind or entity_name)
    try:
        return csv_reader.open_csv(spec.path)
    except CsvReadError as exc:
        raise ValueError(str(exc)) from exc


def run_preflight(
    doc: MappingDoc,
    sources: dict[str, SourceSpec],
    metadata: TargetMetadata,
    *,
    ctx: RunContext,
) -> Report:
    """Stream sources, validate, and build the versioned report envelope.

    Per-record findings use stable source record keys (never row
    positions) with the physical file line in evidence; only
    ``row_parse_error`` is positional (a parse fault has no record to
    key on) and is documented as such.
    """
    findings: list[Finding] = []
    headers: dict[str, list[str]] = {}
    samples: dict[str, list[tuple[int, dict[str, str]]]] = {}
    counts: dict[str, int] = {}
    source_format = doc.source if doc.source in SOURCE_FORMATS else "generic"
    for entity in doc.entities:
        spec = sources.get(entity.name)
        if spec is None:
            findings.append(
                Finding.create(
                    module="migration",
                    code="missing_source_column",
                    severity=Severity.ERROR,
                    entity=entity.name,
                    entity_id=entity.source_kind,
                    message="No source file was provided for the mapped entity.",
                    evidence={"source_kind": entity.source_kind},
                    remediation="Pass a source file for every mapped entity.",
                    discriminator=f"source\0{entity.source_kind}",
                )
            )
            continue
        try:
            stream = _open_entity(source_format, spec, entity.source_kind)
        except (pipedrive.PipedriveLayoutError, hubspot.HubSpotLayoutError, ValueError) as exc:
            findings.append(
                Finding.create(
                    module="migration",
                    code="row_parse_error",
                    severity=Severity.ERROR,
                    entity=entity.name,
                    entity_id=entity.source_kind,
                    message="Source file cannot be opened.",
                    evidence={"source_kind": entity.source_kind},
                    remediation="Fix the source file layout and re-run.",
                    discriminator=f"source\0{entity.source_kind}",
                )
            )
            _ = exc
            continue
        try:
            header = list(stream.dialect.header)
            headers[entity.name] = header
            rows: list[tuple[int, dict[str, str]]] = []
            total = 0
            for line_number, row, issue in stream.rows():
                if issue is not None:
                    findings.append(
                        Finding.create(
                            module="migration",
                            code="row_parse_error",
                            severity=Severity.ERROR
                            if issue.reason == "wrong_column_count"
                            else Severity.WARNING,
                            entity=entity.name,
                            entity_id=f"line-{line_number}",
                            message="Source row cannot be parsed; it is excluded from checks.",
                            evidence={"reason": issue.reason, "line": line_number},
                            remediation="Fix or remove the row and re-run.",
                            discriminator=f"row\0{issue.reason}\0line-{line_number}",
                        )
                    )
                    continue
                if row is None:  # Unreachable: issues always pair with a null row.
                    continue
                total += 1
                if len(rows) < SAMPLE_ROWS:
                    rows.append((line_number, row))
            counts[entity.name] = total
            samples[entity.name] = rows
        finally:
            stream.close()
    findings.extend(validate_mapping(doc, metadata, headers, samples))
    ready = not any(item.severity is Severity.ERROR for item in findings)
    digest = hashlib.sha256(
        canonical_json(
            {
                "mapping": doc.model_dump(mode="json"),
                "sources": sorted(counts.items()),
            }
        ).encode("utf-8")
    ).hexdigest()
    analysis = Analysis(findings=tuple(findings), legacy=_legacy_summary(counts), ready=ready)
    return build_report(analysis, ctx=ctx, inputs_sha256=digest)


def _legacy_summary(counts: dict[str, int]) -> dict[str, object]:
    """Minimal legacy-shaped payload for the shared report builder."""
    return {
        "mode": "dry_run_only",
        "ready_for_import": not counts,
        "source_counts": dict(counts),
        "target_preview_counts": None,
        "issues": [],
        "import_order": ["organizations", "people", "deals", "activities"],
        "rollback_manifest": {
            "precondition": "Keep original export and a dated target backup before any real import",
            "source_ids": {},
            "action": "No rollback executed; capture target IDs at import time",
        },
    }


__all__: list[str] = [
    "HUBSPOT_KINDS",
    "PIPEDRIVE_KINDS",
    "SOURCE_FORMATS",
    "SourceSpec",
    "run_preflight",
]
