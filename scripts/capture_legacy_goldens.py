"""Capture legacy CLI golden outputs (TK-MIG-2).

Runs each legacy CLI on its ``examples.json`` plus the input variations from
its tests, and stores stdout in ``tests/golden/legacy/<module>/``. Variation
inputs are committed under ``inputs/`` so the port parity tests can rerun
them; ``_manifest.json`` records the argv and exit code of every golden.

Usage: ``uv run python scripts/capture_legacy_goldens.py`` (repo root).
Every case runs twice; differing bytes fail the capture (goldens must be
deterministic).
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GOLDEN_ROOT = ROOT / "tests" / "golden" / "legacy"

Case = tuple[str, dict | None, list[str]]
# (golden_name, input_dict or None for examples.json, extra argv)


def migration_cases(examples: dict) -> list[Case]:
    clean = copy.deepcopy(examples)
    clean["people"] = clean["people"][:1]
    clean["deals"] = clean["deals"][:1]
    dup = copy.deepcopy(examples)
    dup["organizations"].append(dict(dup["organizations"][0]))
    dup["activities"][0]["deal_id"] = "missing"
    return [
        ("01_examples", None, []),
        ("02_examples_strict", None, ["--strict"]),
        ("03_clean", clean, []),
        ("04_clean_strict", clean, ["--strict"]),
        ("05_duplicate_org_orphan_activity", dup, []),
    ]


def release_cases(examples: dict) -> list[Case]:
    before = examples["before"]
    no_change = {"before": before, "after": copy.deepcopy(before)}
    added = {
        "before": before,
        "after": [
            *copy.deepcopy(before),
            {"kind": "workflow", "name": "Deal.Notify", "depends_on": []},
        ],
    }
    unknown = copy.deepcopy(examples)
    unknown["after"] = copy.deepcopy(before)
    unknown["after"][1]["depends_on"].append("field:Deal.Unknown")
    return [
        ("01_examples", None, []),
        ("02_examples_strict", None, ["--strict"]),
        ("03_no_change", no_change, []),
        ("04_added_workflow", added, []),
        ("05_unknown_dependency", unknown, []),
    ]


def workflow_cases(examples: dict) -> list[Case]:
    clean = {
        "rules": [
            {
                "id": "owner",
                "event": "deal_created",
                "action": "assign_owner",
                "value": "fictional-team",
            },
            {"id": "stage", "event": "deal_created", "action": "set_stage", "value": "qualified"},
            {
                "id": "follow",
                "event": "stage_changed",
                "action": "queue_followup",
                "value": "day-2",
            },
        ],
        "record": {"id": "x", "stage": "new"},
        "initial_event": "deal_created",
    }
    qualified = {
        "rules": examples["rules"],
        "record": {"id": "deal-demo-2", "stage": "qualified", "owner": None},
        "initial_event": "stage_changed",
    }
    subset = {
        "rules": examples["rules"][:2],
        "record": {"id": "deal-demo-3", "stage": "new", "owner": None},
        "initial_event": "deal_created",
    }
    return [
        ("01_examples", None, []),
        ("02_clean_rules", clean, []),
        ("03_qualified_record", qualified, []),
        ("04_rule_subset", subset, []),
    ]


def forms_cases(examples: dict) -> list[Case]:
    corrected = copy.deepcopy(examples)
    corrected["target_fields"][4]["operation"] = "multiply"
    return [
        ("01_examples", None, []),
        ("02_examples_strict", None, ["--strict"]),
        ("03_corrected_target", corrected, []),
        ("04_corrected_target_strict", corrected, ["--strict"]),
    ]


def books_cases(examples: dict) -> list[Case]:
    clean = copy.deepcopy(examples)
    clean["deals"] = clean["deals"][:1]
    clean["invoices"] = clean["invoices"][:1]
    cross = copy.deepcopy(clean)
    cross["invoices"][0]["entity"] = "fictional-us"
    orphan = copy.deepcopy(examples)
    orphan["invoices"].append(dict(orphan["invoices"][0], deal_ref="missing"))
    return [
        ("01_examples", None, []),
        ("02_examples_strict", None, ["--strict"]),
        ("03_clean", clean, []),
        ("04_clean_strict", clean, ["--strict"]),
        ("05_cross_entity", cross, []),
        ("06_orphan_invoice", orphan, []),
    ]


def metrics_cases(examples: dict) -> list[Case]:
    orphan = copy.deepcopy(examples)
    orphan["deals"][0]["account_id"] = "missing"
    overbooked = copy.deepcopy(examples)
    overbooked["staff"][0]["hours_booked"] = 80
    return [
        ("01_finance", None, []),
        ("02_sales", None, ["--audience", "sales"]),
        ("03_operations", None, ["--audience", "operations"]),
        ("04_orphan_deal", orphan, []),
        ("05_invalid_utilization", overbooked, ["--audience", "operations"]),
    ]


def timeline_cases(examples: dict) -> list[Case]:
    subset = {"events": examples["events"][:2]}
    return [
        ("01_internal", None, []),
        ("02_client", None, ["--audience", "client"]),
        ("03_two_events_internal", subset, []),
        ("04_two_events_client", subset, ["--audience", "client"]),
    ]


def lead_routing_cases(examples: dict) -> list[Case]:
    leads = examples["leads"]
    consent = {"leads": [dict(leads[0], id="new", phone="+919999999999", consent=False)]}
    invalid = {
        "leads": [
            dict(leads[0], id="invalid", phone="123"),
            dict(leads[0], id="unsupported", channel="email", phone="+919888888888"),
        ]
    }
    single = {"leads": [dict(leads[0], id="lead-1")]}
    return [
        ("01_examples", None, []),
        ("02_consent_blocked", consent, []),
        ("03_invalid_unsupported", invalid, []),
        ("04_single_qualified", single, []),
    ]


MODULES: dict[str, str] = {
    "migration": "zoho-crm-migration-auditor",
    "release": "zoho-release-readiness-audit",
    "workflow": "zoho-workflow-rule-testbench",
    "forms": "zoho-forms-parity-checker",
    "books": "zoho-books-sync-reconciler",
    "metrics": "zoho-analytics-metrics-contracts",
    "timeline": "zoho-client-timeline-composer",
    "lead_routing": "zoho-lead-routing-lab",
}

BUILDERS = {
    "migration": migration_cases,
    "release": release_cases,
    "workflow": workflow_cases,
    "forms": forms_cases,
    "books": books_cases,
    "metrics": metrics_cases,
    "timeline": timeline_cases,
    "lead_routing": lead_routing_cases,
}


def run_cli(legacy_dir: Path, input_path: Path, extra_args: list[str]) -> tuple[bytes, int]:
    """Run ``cli.py`` on ``input_path``; return (stdout, exit code)."""
    completed = subprocess.run(
        [sys.executable, "cli.py", str(input_path), *extra_args],
        cwd=legacy_dir,
        capture_output=True,
        check=False,
    )
    if completed.returncode not in (0, 2):
        raise RuntimeError(
            f"CLI failed (exit {completed.returncode}): {completed.stderr.decode()[:500]}"
        )
    return completed.stdout, completed.returncode


def capture_module(module: str, legacy_name: str) -> list[dict]:
    """Capture all goldens for one module; return manifest entries."""
    legacy_dir = ROOT / "legacy" / legacy_name
    out_dir = GOLDEN_ROOT / module
    inputs_dir = out_dir / "inputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    examples = json.loads((legacy_dir / "examples.json").read_text(encoding="utf-8"))
    manifest: list[dict] = []
    for golden_name, inputs, extra_args in BUILDERS[module](examples):
        if inputs is None:
            input_path = legacy_dir / "examples.json"
            input_rel = f"legacy/{legacy_name}/examples.json"
        else:
            input_path = inputs_dir / f"{golden_name}.json"
            input_path.write_text(
                json.dumps(inputs, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            input_rel = f"tests/golden/legacy/{module}/inputs/{golden_name}.json"
        first, code = run_cli(legacy_dir, input_path, extra_args)
        second, _ = run_cli(legacy_dir, input_path, extra_args)
        if first != second:
            raise RuntimeError(f"Non-deterministic output for {module}/{golden_name}")
        json.loads(first.decode("utf-8"))  # stdout must be valid JSON
        golden_path = out_dir / f"{golden_name}.json"
        golden_path.write_bytes(first)
        manifest.append(
            {
                "golden": f"tests/golden/legacy/{module}/{golden_name}.json",
                "input": input_rel,
                "argv": ["cli.py", input_rel, *extra_args],
                "exit_code": code,
            }
        )
        print(f"{module}/{golden_name}.json (exit {code})")
    (out_dir / "_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> None:
    total = 0
    for module, legacy_name in MODULES.items():
        total += len(capture_module(module, legacy_name))
    print(f"Captured {total} goldens across {len(MODULES)} modules.")


if __name__ == "__main__":
    main()
