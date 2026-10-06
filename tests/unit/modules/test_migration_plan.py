"""Import plan tests: order, keys, estimates, stable hash (TK-MIG-F9)."""

from __future__ import annotations

from typer.testing import CliRunner

from zohokit.cli import app
from zohokit.core.plan import verify_bundle
from zohokit.modules.migration.mapping import MappingDoc
from zohokit.modules.migration.plan import (
    ROLLBACK_NOTE,
    build_plan,
    estimated_api_calls,
    module_rank,
    write_plan,
)

runner = CliRunner()


def _doc():  # type: ignore[no-untyped-def]
    return MappingDoc.model_validate(
        {
            "version": 1,
            "source": "pipedrive",
            "entities": [
                {
                    "name": "deals",
                    "source_kind": "deals",
                    "target_module": "Deals",
                    "fields": {"Deal_Name": {"from": "Title"}},
                    "external_id": {"field": "External_ID__s", "from": "ID"},
                },
                {
                    "name": "people",
                    "source_kind": "persons",
                    "target_module": "Contacts",
                    "fields": {"Last_Name": {"from": "Name"}},
                    "external_id": {"field": "External_ID__s", "from": "ID"},
                },
                {
                    "name": "companies",
                    "source_kind": "organizations",
                    "target_module": "Accounts",
                    "fields": {"Account_Name": {"from": "Name"}},
                },
            ],
        }
    )


def test_dependency_order_accounts_first() -> None:
    plan = build_plan(_doc(), {"deals": 250, "people": 120, "companies": 30})
    modules = [call.path.rsplit("/", 1)[-1] for call in plan.calls]
    assert modules == ["Accounts", "Contacts", "Contacts", "Deals", "Deals", "Deals"]
    assert plan.calls[0].depends_on == []
    assert plan.calls[1].depends_on == ["pipedrive:Accounts:batch-1"]
    assert plan.calls[0].idempotency_key == "pipedrive:Accounts:batch-1"
    assert plan.calls[0].body_redacted["idempotency_key_pattern"] == "pipedrive:<source_id>"
    assert estimated_api_calls(plan) == 6


def test_plan_hash_stable_and_bundle_verifies(tmp_path) -> None:  # type: ignore[no-untyped-def]
    doc = _doc()
    counts = {"deals": 250, "people": 120, "companies": 30}
    first = build_plan(doc, counts)
    second = build_plan(doc, counts)
    assert first.canonical_hash() == second.canonical_hash()
    json_path, md_path, _ = write_plan(doc, counts, tmp_path)
    assert json_path.is_file() and md_path.is_file()
    assert verify_bundle(tmp_path).canonical_hash() == first.canonical_hash()
    assert "target-ID ledger" in md_path.read_text(encoding="utf-8")
    assert "source IDs" in ROLLBACK_NOTE or "Source IDs" in ROLLBACK_NOTE


def test_module_rank_unknown_last() -> None:
    assert module_rank("Accounts", "companies") < module_rank("Calls", "activities")
    assert module_rank("ZZZ", "mystery") == (4, "zzz")


def test_cli_plan_writes_bundle(tmp_path) -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent.parent.parent
    fixtures = root / "fixtures" / "migration"
    out = tmp_path / "plan"
    result = runner.invoke(
        app,
        [
            "migration",
            "plan",
            "--mapping",
            str(fixtures / "mapping.yaml"),
            "--source",
            str(fixtures / "source"),
            "--out",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.output
    assert (out / "plan.json").is_file()
    assert (out / "plan.md").is_file()
    assert "Estimated API calls: 3" in result.output
