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
from zohokit.modules.migration import dedupe as dedupe_mod
from zohokit.modules.migration.dedupe import RowSignals
from zohokit.modules.migration.history import check_history
from zohokit.modules.migration.mapping import EntityMapping, MappingDoc
from zohokit.modules.migration.metadata import SAMPLE_ROWS, TargetMetadata, validate_mapping
from zohokit.modules.migration.owners import check_owners
from zohokit.modules.migration.report import build_report
from zohokit.modules.migration.stages import check_stages
from zohokit.modules.migration.target_dedupe import (
    SearchFn,
    check_against_target,
    coverage_finding,
)

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


@dataclass(frozen=True)
class ExtraChecks:
    """Optional cross-row and target-backed checks (TK-MIG-F4..F8).

    ``default_region`` feeds phone normalization; ``users`` maps
    normalized owner emails to account statuses; ``search`` runs live
    target searches (unverified endpoint, ``--experimental`` only) with
    at most ``search_budget`` calls.
    """

    default_region: str | None = None
    users: dict[str, str] | None = None
    search: SearchFn | None = None
    search_budget: int | None = None


#: Mapping targets treated as email / phone / company signal carriers.
EMAIL_TARGETS = ("Email",)
PHONE_TARGETS = ("Phone", "Mobile", "Home_Phone", "Asst_Phone")
COMPANY_TARGETS = ("Account_Name", "Company")


def open_entity(source_format: str, spec: SourceSpec, entity_name: str) -> CsvStream:
    """Open one entity file; layout errors propagate as config errors."""
    if source_format == "pipedrive":
        return pipedrive.open_kind(spec.path, kind=spec.kind or entity_name)
    if source_format == "hubspot":
        return hubspot.open_kind(spec.path, kind=spec.kind or entity_name)
    try:
        return csv_reader.open_csv(spec.path)
    except CsvReadError as exc:
        raise ValueError(str(exc)) from exc


def _mapping_region(doc: MappingDoc) -> str | None:
    """First e164 region declared anywhere in the mapping, if any."""
    for entity in doc.entities:
        for field_map in entity.fields.values():
            for spec in field_map.transform:
                region = spec.args.get("region")
                if spec.name == "e164" and isinstance(region, str) and region.strip():
                    return region.strip()
    return None


def _signal_columns(
    entity: EntityMapping, header: list[str]
) -> tuple[str | None, list[str], list[str], list[str], list[str]]:
    """Derive the ID, signal and created columns for one entity."""
    if entity.external_id is not None and entity.external_id.from_col in header:
        id_col: str | None = entity.external_id.from_col
    else:
        id_col = next((col for col in dedupe_mod.ID_COLS if col in header), None)

    def mapped(targets: tuple[str, ...]) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for target, field_map in entity.fields.items():
            if target in targets and field_map.from_col in header:
                out.setdefault(target, []).append(field_map.from_col or "")
        return out

    email_cols = dedupe_mod.pick_columns(
        header, mapped(EMAIL_TARGETS), dedupe_mod.FALLBACK_EMAIL_COLS
    )
    phone_cols = dedupe_mod.pick_columns(
        header, mapped(PHONE_TARGETS), dedupe_mod.FALLBACK_PHONE_COLS
    )
    company_cols = [
        col
        for col in dedupe_mod.pick_columns(
            header, mapped(COMPANY_TARGETS), dedupe_mod.FALLBACK_COMPANY_COLS
        )
        # ID-like columns are keys, not names: fuzzy-matching them would
        # cluster every row sharing a parent (e.g. one Organization ID).
        if col not in dedupe_mod.ID_COLS and not col.casefold().endswith((" id", " ids"))
    ]
    created_cols = [col for col in dedupe_mod.CREATED_COLS if col in header]
    return id_col, email_cols, phone_cols, company_cols, created_cols


def run_preflight(
    doc: MappingDoc,
    sources: dict[str, SourceSpec],
    metadata: TargetMetadata,
    *,
    ctx: RunContext,
    extra: ExtraChecks | None = None,
) -> Report:
    """Stream sources, validate, and build the versioned report envelope.

    Beyond mapping and metadata (TK-MIG-F1..F3), every run clusters
    in-source duplicates (TK-MIG-F4), checks deal stages, owners and
    history types on the head sample (TK-MIG-F6..F8), and — only when
    *extra* carries a live search — checks rows against the target
    (TK-MIG-F5, budget-aware with coverage).
    """
    checks = extra or ExtraChecks()
    region = checks.default_region or _mapping_region(doc)
    findings: list[Finding] = []
    headers: dict[str, list[str]] = {}
    samples: dict[str, list[dict[str, str]]] = {}
    keyed: dict[str, list[tuple[str, dict[str, str]]]] = {}
    signals: dict[str, list[RowSignals]] = {}
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
            stream = open_entity(source_format, spec, entity.source_kind)
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
            id_col, email_cols, phone_cols, company_cols, created_cols = _signal_columns(
                entity, header
            )
            rows: list[dict[str, str]] = []
            keyed_rows: list[tuple[str, dict[str, str]]] = []
            entity_signals: list[RowSignals] = []
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
                            evidence={"reason": issue.reason},
                            remediation="Fix or remove the row and re-run.",
                            discriminator=f"row\0{issue.reason}\0line-{line_number}",
                        )
                    )
                    continue
                if row is None:  # Unreachable: issues always pair with a null row.
                    continue
                total += 1
                entity_signals.append(
                    dedupe_mod.signal_row(
                        row,
                        id_col=id_col,
                        email_cols=email_cols,
                        phone_cols=phone_cols,
                        company_cols=company_cols,
                        created_cols=created_cols,
                        default_region=region,
                    )
                )
                if len(rows) < SAMPLE_ROWS:
                    rows.append(row)
                    keyed_rows.append((dedupe_mod.row_key(row, id_col), row))
            counts[entity.name] = total
            samples[entity.name] = rows
            keyed[entity.name] = keyed_rows
            signals[entity.name] = entity_signals
        finally:
            stream.close()
    findings.extend(validate_mapping(doc, metadata, headers, samples))
    for entity in doc.entities:
        if entity.name not in headers:
            continue
        clusters = dedupe_mod.cluster_signals(signals[entity.name])
        findings.extend(dedupe_mod.cluster_findings(entity.name, clusters))
        entity_rows = keyed[entity.name]
        entity_header = headers[entity.name]
        fields = metadata.fields_for(entity.target_module)
        findings.extend(check_stages(entity, entity_rows, entity_header, fields.get("Stage")))
        if checks.users is not None:
            findings.extend(check_owners(entity, entity_rows, entity_header, checks.users))
        findings.extend(check_history(entity, entity_rows, entity_header))
        if checks.search is not None:
            ordered = sorted(
                signals[entity.name], key=lambda sig: (sig.email is None, sig.phone is None)
            )
            candidates = [(sig.key, sig.email, sig.phone) for sig in ordered]
            matched, checked, total_candidates, truncated = check_against_target(
                entity.name,
                entity.target_module,
                candidates,
                checks.search,
                budget=checks.search_budget,
            )
            findings.extend(matched)
            findings.append(
                coverage_finding(
                    entity.name, checked=checked, total=total_candidates, truncated=truncated
                )
            )
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
    "COMPANY_TARGETS",
    "EMAIL_TARGETS",
    "HUBSPOT_KINDS",
    "PHONE_TARGETS",
    "PIPEDRIVE_KINDS",
    "SOURCE_FORMATS",
    "ExtraChecks",
    "SourceSpec",
    "open_entity",
    "run_preflight",
]
