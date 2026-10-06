"""CLI tests for explain, suggest-mapping and suggest-transform (TK-CORE-9, AI-MIG-1/2).

Template and disabled paths run through the CLI; AI paths are covered at
the feature level and in the recorded eval suites, all via FakeProvider.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from zohokit.cli import app
from zohokit.cli.common import AI_DISABLED_NOTE

ROOT = Path(__file__).resolve().parent
MIGRATION_FIXTURE = str(ROOT / "golden" / "legacy" / "migration" / "inputs" / "examples.json")
PERSONS_CSV = str(ROOT.parent / "fixtures" / "migration" / "marigold" / "source" / "persons.csv")
FIELDS_DIR = str(ROOT.parent / "fixtures" / "migration" / "fields")

runner = CliRunner()


def _clear_ai_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "ZOHOKIT_AI_PROVIDER",
        "ZOHOKIT_AI_MODEL",
        "ZOHOKIT_AI_API_KEY",
        "ZOHOKIT_AI_BASE_URL",
        "ANTHROPIC_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


def _report_path(tmp_path: Path) -> str:
    out = tmp_path / "report.json"
    result = runner.invoke(app, ["migration", "audit", MIGRATION_FIXTURE, "--out", str(out)])
    assert result.exit_code == 0, result.output
    return str(out)


def test_explain_json_template_internal(tmp_path: Path) -> None:
    report = _report_path(tmp_path)
    result = runner.invoke(app, ["explain", report])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["audience"] == "internal"
    assert payload["source"] == "ai"
    assert payload["ai_status"] == "disabled"
    assert payload["sentences"], "template explains every finding"
    assert payload["sentences"][0]["finding_ids"] == []
    cited = [fid for item in payload["sentences"][1:] for fid in item["finding_ids"]]
    assert len(cited) == len(payload["sentences"]) - 1
    usage = payload["usage"]
    assert set(usage) >= {"input_tokens", "output_tokens", "estimated_cost_usd", "latency_ms"}


def test_explain_client_hides_internal_fields(tmp_path: Path) -> None:
    report = _report_path(tmp_path)
    result = runner.invoke(app, ["explain", report, "--audience", "client"])
    assert result.exit_code == 0, result.output
    assert "run_id" not in result.output
    assert "inputs_sha256" not in result.output
    assert "artifacts" not in result.output


def test_explain_table_markdown_html(tmp_path: Path) -> None:
    report = _report_path(tmp_path)
    table = runner.invoke(app, ["explain", report, "--format", "table"])
    assert table.exit_code == 0 and table.output.startswith("audience: internal")
    markdown = runner.invoke(app, ["explain", report, "--format", "markdown"])
    assert markdown.exit_code == 0 and "Template summary" in markdown.output
    html = runner.invoke(app, ["explain", report, "--format", "html"])
    assert html.exit_code == 0 and "<li>" in html.output
    assert "AI suggestion" not in html.output


def test_explain_ai_disabled_note(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_ai_env(monkeypatch)
    report = _report_path(tmp_path)
    result = runner.invoke(app, ["explain", report, "--ai"])
    assert result.exit_code == 0
    assert AI_DISABLED_NOTE in result.output


def test_explain_rejects_bad_inputs(tmp_path: Path) -> None:
    report = _report_path(tmp_path)
    bad_audience = runner.invoke(app, ["explain", report, "--audience", "partner"])
    assert bad_audience.exit_code == 1
    bad_format = runner.invoke(app, ["explain", report, "--format", "yaml"])
    assert bad_format.exit_code == 1
    live = runner.invoke(app, ["explain", report, "--live", "--profile", "dev-in"])
    assert live.exit_code == 1 and "touched no network" in live.output
    missing = runner.invoke(app, ["explain", str(tmp_path / "nope.json")])
    assert missing.exit_code == 1


def test_suggest_mapping_writes_draft(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_ai_env(monkeypatch)
    out = tmp_path / "mapping.draft.yaml"
    result = runner.invoke(
        app,
        [
            "migration",
            "suggest-mapping",
            "--csv",
            PERSONS_CSV,
            "--target-module",
            "Contacts",
            "--fields-dir",
            FIELDS_DIR,
            "--out",
            str(out),
            "--ai",
        ],
    )
    assert result.exit_code == 0, result.output
    assert AI_DISABLED_NOTE in result.output
    assert "Wrote" in result.output
    text = out.read_text(encoding="utf-8")
    assert text.startswith("# Mapping draft")
    entries = yaml.safe_load(text)
    assert isinstance(entries, list) and entries
    assert entries[0]["source_column"] == "ID"


def test_suggest_mapping_refuses_existing_out(tmp_path: Path) -> None:
    out = tmp_path / "draft.yaml"
    out.write_text("existing: true\n", encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "migration",
            "suggest-mapping",
            "--csv",
            PERSONS_CSV,
            "--target-module",
            "Contacts",
            "--fields-dir",
            FIELDS_DIR,
            "--out",
            str(out),
        ],
    )
    assert result.exit_code == 1
    assert "never overwrite" in result.output


def test_suggest_mapping_rejects_bad_inputs(tmp_path: Path) -> None:
    out = tmp_path / "draft.yaml"
    missing_csv = runner.invoke(
        app,
        [
            "migration",
            "suggest-mapping",
            "--csv",
            str(tmp_path / "nope.csv"),
            "--target-module",
            "Contacts",
            "--fields-dir",
            FIELDS_DIR,
            "--out",
            str(out),
        ],
    )
    assert missing_csv.exit_code == 1
    unknown_module = runner.invoke(
        app,
        [
            "migration",
            "suggest-mapping",
            "--csv",
            PERSONS_CSV,
            "--target-module",
            "Nope",
            "--fields-dir",
            FIELDS_DIR,
            "--out",
            str(out),
        ],
    )
    assert unknown_module.exit_code == 1


def test_suggest_transform_json_table_html() -> None:
    as_json = runner.invoke(
        app,
        [
            "migration",
            "suggest-transform",
            "--csv",
            PERSONS_CSV,
            "--column",
            "Email",
            "--target-type",
            "email",
        ],
    )
    assert as_json.exit_code == 0, as_json.output
    payload = json.loads(as_json.output)
    assert payload["column"] == "Email"
    assert payload["suggestion"]["transform"] == "trim"
    assert payload["ai_status"] == "disabled"
    table = runner.invoke(
        app,
        [
            "migration",
            "suggest-transform",
            "--csv",
            PERSONS_CSV,
            "--column",
            "Email",
            "--target-type",
            "email",
            "--format",
            "table",
        ],
    )
    assert table.exit_code == 0 and "proposed: trim" in table.output
    html = runner.invoke(
        app,
        [
            "migration",
            "suggest-transform",
            "--csv",
            PERSONS_CSV,
            "--column",
            "Email",
            "--target-type",
            "email",
            "--format",
            "html",
        ],
    )
    assert html.exit_code == 0 and "Transform draft" in html.output


def test_suggest_transform_rejects_bad_inputs() -> None:
    bad_column = runner.invoke(
        app,
        [
            "migration",
            "suggest-transform",
            "--csv",
            PERSONS_CSV,
            "--column",
            "Ghost",
            "--target-type",
            "email",
        ],
    )
    assert bad_column.exit_code == 1
    bad_type = runner.invoke(
        app,
        [
            "migration",
            "suggest-transform",
            "--csv",
            PERSONS_CSV,
            "--column",
            "Email",
            "--target-type",
            "number",
        ],
    )
    assert bad_type.exit_code == 1
    needs_sibling = runner.invoke(
        app,
        [
            "migration",
            "suggest-transform",
            "--csv",
            PERSONS_CSV,
            "--column",
            "Email",
            "--target-type",
            "currency",
        ],
    )
    assert needs_sibling.exit_code == 1
