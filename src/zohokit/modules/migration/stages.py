"""Deal stage mapping against the live Stage picklist (TK-MIG-F6).

Stage values (after the mapping's own transforms) must exist in the
target ``Deals`` Stage picklist from the verified fields metadata;
anything else is ``unmapped_stage``. When the mapping declares expected
probabilities per stage and a probability column is present, a mismatch
is a ``stage_probability_mismatch`` warning.
"""

from __future__ import annotations

from zohokit.core.findings import Finding, Severity
from zohokit.modules.migration.mapping import (
    EntityMapping,
    TransformError,
    TransformSpec,
    apply_transforms,
)
from zohokit.modules.migration.metadata import FieldMeta

#: Target fields treated as the stage / probability carriers.
STAGE_TARGETS = ("Stage",)
PROBABILITY_TARGETS = ("Probability",)


def _stage_field(entity: EntityMapping) -> tuple[str, str, list[TransformSpec]] | None:
    for target in STAGE_TARGETS:
        field_map = entity.fields.get(target)
        if field_map is not None and field_map.from_col is not None:
            return target, field_map.from_col, list(field_map.transform)
    return None


def _probability_col(entity: EntityMapping, header: list[str]) -> str | None:
    for target in PROBABILITY_TARGETS:
        field_map = entity.fields.get(target)
        if field_map is not None and field_map.from_col in header:
            return field_map.from_col
    return None


def check_stages(
    entity: EntityMapping,
    rows: list[tuple[str, dict[str, str]]],
    header: list[str],
    stage_meta: FieldMeta | None,
) -> list[Finding]:
    """Validate mapped stage values (and probabilities) per row.

    *rows* are ``(content key, row)`` pairs. Without a mapped stage
    column there is nothing to check; without picklist metadata the
    membership check degrades gracefully (no false errors).
    """
    staged = _stage_field(entity)
    if staged is None:
        return []
    target, from_col, specs = staged
    prob_col = _probability_col(entity, header)
    allowed = list(stage_meta.pick_list_values) if stage_meta is not None else None
    findings: list[Finding] = []
    for key, row in rows:
        raw = row.get(from_col)
        if raw is None or raw == "":
            continue
        try:
            value = apply_transforms(raw, row, specs)
        except TransformError:
            continue  # Transform failures already surface as type_incompatible.
        if value is None or value == "":
            continue
        if allowed is not None and value not in allowed:
            findings.append(
                Finding.create(
                    module="migration",
                    code="unmapped_stage",
                    severity=Severity.ERROR,
                    entity=entity.name,
                    entity_id=key,
                    message="Deal stage has no entry in the target Stage picklist.",
                    evidence={"target_field": target, "allowed_count": len(allowed)},
                    remediation="Add the stage to the target pipeline or map it to one.",
                    discriminator=f"stage\0{value}",
                )
            )
            continue
        if prob_col is not None and value in entity.stage_probabilities:
            expected = entity.stage_probabilities[value]
            try:
                actual = float((row.get(prob_col) or "").strip().rstrip("%"))
            except ValueError:
                continue
            if abs(actual - expected) > 0.5:
                findings.append(
                    Finding.create(
                        module="migration",
                        code="stage_probability_mismatch",
                        severity=Severity.WARNING,
                        entity=entity.name,
                        entity_id=key,
                        message="Row probability differs from the expected stage probability.",
                        evidence={"stage": value, "expected": expected, "actual": actual},
                        remediation="Align the source probability with the target pipeline.",
                        discriminator=f"stage-probability\0{value}",
                    )
                )
    return findings


__all__: list[str] = [
    "PROBABILITY_TARGETS",
    "STAGE_TARGETS",
    "check_stages",
]
