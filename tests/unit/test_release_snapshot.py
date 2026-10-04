"""Snapshot and drift tests: byte-identical files, redaction, live replay.

The live path replays synthetic cassettes shaped like the real v8
``settings/fields`` envelopes (see ``tests/contract/cassettes/release/``)
through the GET-only client. No request ever leaves the process.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

from zohokit.cli import app
from zohokit.connectors.zoho.client import ZohoClient
from zohokit.modules.release.manifest import coerce_manifest
from zohokit.modules.release.snapshot import (
    read_snapshot,
    snapshot_files,
    snapshot_from_client,
    write_snapshot,
)

ROOT = Path(__file__).resolve().parent.parent.parent
CASSETTES = ROOT / "tests" / "contract" / "cassettes" / "release"
runner = CliRunner()


def _body(name: str) -> dict[str, Any]:
    envelope = json.loads((CASSETTES / name).read_text(encoding="utf-8"))
    body = envelope["response"]["body"]
    assert isinstance(body, dict)
    return body


def _client() -> ZohoClient:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        module = request.url.params.get("module", "")
        return httpx.Response(200, json=_body(f"fields_{module}.json"))

    return ZohoClient(
        "https://www.zohoapis.in",
        transport=httpx.MockTransport(handler),
        token_provider=lambda: "test-token",
    )


def test_snapshot_builds_field_components() -> None:
    manifest = snapshot_from_client(_client(), source_env="test")
    ids = sorted(item.component_id() for item in manifest.components)
    assert ids == [
        "field:Contacts.Last_Name",
        "field:Contacts.Mobile",
        "field:Deals.Amount",
        "field:Deals.Contact_Email",
        "field:Deals.Deal_Name",
        "field:Leads.Last_Name",
        "field:Leads.Phone",
    ]
    amount = next(item for item in manifest.components if item.name == "Deals.Amount")
    assert amount.attributes["data_type"] == "currency"
    assert amount.source_env == "test"


def test_two_snapshots_are_byte_identical(tmp_path: Path) -> None:
    first = snapshot_from_client(_client(), source_env="test")
    second = snapshot_from_client(_client(), source_env="test")
    assert snapshot_files(first) == snapshot_files(second)
    write_snapshot(first, tmp_path / "one")
    write_snapshot(second, tmp_path / "two")
    one = sorted(path.read_bytes() for path in (tmp_path / "one").glob("*.json"))
    two = sorted(path.read_bytes() for path in (tmp_path / "two").glob("*.json"))
    assert one == two
    assert [path.name for path in sorted((tmp_path / "one").glob("*.json"))] == ["field.json"]
    reread = read_snapshot(tmp_path / "one")
    assert [item.component_id() for item in reread.components] == [
        item.component_id() for item in first.components
    ]


def test_snapshot_redacts_contact_details() -> None:
    manifest = snapshot_from_client(
        _client(),
        source_env="test",
        extra=list(
            coerce_manifest(
                [
                    {
                        "kind": "webhook",
                        "name": "Notify",
                        "attributes": {
                            "url": "https://hooks.example.invalid/x?to=someone@example.com",
                            "owner_email": "owner@example.com",
                        },
                    }
                ]
            ).components
        ),
    )
    notify = next(item for item in manifest.components if item.name == "Notify")
    assert notify.attributes["owner_email"] == "o***@example.invalid"
    assert "someone@example.com" not in notify.attributes["url"]
    assert "example.invalid" in notify.attributes["url"]


def test_drift_offline_reports_unapproved(tmp_path: Path) -> None:
    manifest = snapshot_from_client(_client(), source_env="test")
    write_snapshot(manifest, tmp_path / "approved")
    live_file = tmp_path / "live.json"
    live_file.write_text(
        json.dumps(
            {
                "components": [
                    item.model_dump(mode="json")
                    for item in manifest.components
                    if item.name != "Deals.Amount"
                ]
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    result = runner.invoke(
        app,
        ["release", "drift", "--approved", str(tmp_path / "approved"), "--after", str(live_file)],
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ready"] is False
    assert [item["code"] for item in payload["findings"]] == ["unapproved_drift"]
    assert payload["findings"][0]["entity_id"] == "field:Deals.Amount"
    strict = runner.invoke(
        app,
        [
            "release",
            "drift",
            "--approved",
            str(tmp_path / "approved"),
            "--after",
            str(live_file),
            "--strict",
        ],
    )
    assert strict.exit_code == 2
    clean = runner.invoke(
        app,
        [
            "release",
            "drift",
            "--approved",
            str(tmp_path / "approved"),
            "--after",
            str(tmp_path / "approved" / "field.json"),
        ],
    )
    assert clean.exit_code == 0
    assert json.loads(clean.output)["ready"] is True


@pytest.mark.contract
def test_synthetic_cassette_shapes_match_v8_envelopes() -> None:
    """Every synthetic cassette keeps the real v8 envelope (fields list)."""
    for name in ("fields_Deals.json", "fields_Leads.json", "fields_Contacts.json"):
        body = _body(name)
        assert isinstance(body["fields"], list) and body["fields"]
        assert all("api_name" in entry and "data_type" in entry for entry in body["fields"])
