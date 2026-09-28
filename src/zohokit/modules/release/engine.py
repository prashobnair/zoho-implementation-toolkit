"""Release readiness engine (TK-MIG-3).

Port of ``legacy/zoho-release-readiness-audit/audit.py`` with one intentional
fix: the fingerprint sorts components by ``(kind, name)`` first (TK-FIX-1),
so list order can never change the hash. Everything else is unchanged.
"""

from __future__ import annotations

import copy
import hashlib
from typing import Any

from zohokit.core.context import RunContext
from zohokit.core.findings import Finding, Report, Severity
from zohokit.core.ids import canonical_json, fingerprint
from zohokit.modules import Analysis
from zohokit.modules.release.models import ReleaseInput
from zohokit.modules.release.report import build_report

KINDS = {"field", "layout", "workflow", "validation", "function", "webhook"}
SENSITIVE = {"workflow", "validation", "function", "webhook"}


def _index(items: Any) -> dict[tuple[str, str], dict[str, Any]]:
    if not isinstance(items, list):
        raise ValueError("components must be list")
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for item in items:
        if (
            not isinstance(item, dict)
            or item.get("kind") not in KINDS
            or not isinstance(item.get("name"), str)
            or not item["name"]
        ):
            raise ValueError("Invalid component")
        key = (item["kind"], item["name"])
        if key in result:
            raise ValueError("Duplicate component")
        deps = item.get("depends_on", [])
        if not isinstance(deps, list) or any(not isinstance(dep, str) for dep in deps):
            raise ValueError("depends_on must be a string list")
        result[key] = item
    return result


def analyze(inputs: ReleaseInput) -> Analysis:
    """Diff two manifests; return findings plus the legacy result dict."""
    before = copy.deepcopy(inputs.before)
    after = copy.deepcopy(inputs.after)
    old = _index(before)
    new = _index(after)
    findings: list[dict[str, Any]] = []
    changes: list[dict[str, Any]] = []
    keys = sorted(old.keys() | new.keys())
    for kind, name in keys:
        key = (kind, name)
        prior, later = old.get(key), new.get(key)
        if prior is None:
            change = "added"
        elif later is None:
            change = "removed"
        elif prior != later:
            change = "changed"
        else:
            continue
        changes.append({"kind": kind, "name": name, "change": change})
        if kind in SENSITIVE:
            findings.append({"code": "behavior_regression_review", "component": f"{kind}:{name}"})
        if change == "removed":
            findings.append({"code": "removal_review", "component": f"{kind}:{name}"})
    existing = {f"{kind}:{name}" for kind, name in new}
    for (kind, name), item in sorted(new.items()):
        for dep in item.get("depends_on", []):
            if dep not in existing:
                findings.append(
                    {
                        "code": "missing_dependency",
                        "component": f"{kind}:{name}",
                        "dependency": dep,
                    }
                )
    findings.sort(key=lambda item: (item["code"], item["component"], item.get("dependency", "")))
    manifest_sha256 = fingerprint(after)
    ready = not findings
    legacy = {
        "mode": "dry_run_only",
        "ready_for_release": ready,
        "changes": changes,
        "findings": findings,
        "target_manifest_sha256": manifest_sha256,
        "deployment_actions": 0,
    }
    created = tuple(
        Finding.create(
            module="release",
            code=item["code"],
            severity=Severity.ERROR,
            entity="manifest",
            entity_id=item["component"],
            message=_message(item),
            evidence={"legacy_finding": item},
            discriminator=item["component"] + "\0" + str(item.get("dependency", "")),
        )
        for item in findings
    )
    return Analysis(findings=created, legacy=legacy, ready=ready)


def _message(item: dict[str, Any]) -> str:
    text = f"{item['code']}: {item['component']}"
    if "dependency" in item:
        text += f" (missing dependency {item['dependency']})"
    return text


def run(inputs: ReleaseInput, *, ctx: RunContext) -> Report:
    """Run the diff: ``run(inputs, *, ctx) -> Report`` (TK-ARCH-1)."""
    analysis = analyze(inputs)
    digest = hashlib.sha256(
        canonical_json(inputs.model_dump(mode="json")).encode("utf-8")
    ).hexdigest()
    return build_report(analysis, ctx=ctx, inputs_sha256=digest)


__all__: list[str] = ["analyze", "run"]
