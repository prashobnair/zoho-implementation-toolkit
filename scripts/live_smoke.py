"""Nightly live smoke reads: GET-only, validated, redacted evidence.

Reads org, modules, fields (Leads, Contacts, Deals) and users through the
GET-only :class:`ZohoClient` (``experimental=True``: every endpoint is still
``unverified`` per STD-C2), validates each payload against its contract
model (``contract_drift`` fails loudly with exit 3), and writes a
shapes-only evidence bundle: counts, field names and the org fingerprint,
never raw IDs, values or timestamps, so the cassette scan passes over it.

With ``--record``, cassettes are additionally recorded through the existing
recorder (:func:`record_cassette.record`, redacted before write) into
``cassettes/``. Credentials always come from the environment
(``ZOHO_CLIENT_ID``/``ZOHO_CLIENT_SECRET``/``ZOHO_REFRESH_TOKEN``); the
committed ``profiles/dev-in.json`` holds no secrets.

Usage (nightly live job only; never runs on a pull request)::

    uv run python scripts/live_smoke.py --profile dev-in --evidence-dir evidence
    uv run python scripts/live_smoke.py --profile dev-in --evidence-dir evidence \\
        --record --cassettes-dir cassettes
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from scripts.record_cassette import record as record_cassette  # noqa: E402
from zohokit.connectors.zoho.auth import TokenManager  # noqa: E402
from zohokit.connectors.zoho.budget import DEFAULT_MAX_API_CALLS, CallBudget  # noqa: E402
from zohokit.connectors.zoho.client import ZohoClient  # noqa: E402
from zohokit.connectors.zoho.dc import DC_TABLE  # noqa: E402
from zohokit.connectors.zoho.doctor import org_fingerprint  # noqa: E402
from zohokit.connectors.zoho.errors import ConnectorError, ContractDriftError  # noqa: E402
from zohokit.connectors.zoho.models import (  # noqa: E402
    FieldsResponse,
    ModulesResponse,
    OrgResponse,
    RecordPage,
    UsersResponse,
    ZohoResponse,
    validate_response,
)
from zohokit.connectors.zoho.profiles import Profile, load_profile  # noqa: E402
from zohokit.core.redact import Redactor, redact_text  # noqa: E402

#: Inner transport factory for API reads (tests inject a mock).
TRANSPORT_FACTORY: Callable[[], httpx.BaseTransport] = httpx.HTTPTransport

#: (evidence name, request path, contract model, cassette file).
SMOKE_READS: tuple[tuple[str, str, type[ZohoResponse], str], ...] = (
    ("org", "/crm/v8/org", OrgResponse, "org.json"),
    ("modules", "/crm/v8/settings/modules", ModulesResponse, "modules.json"),
    ("fields_Leads", "/crm/v8/settings/fields?module=Leads", FieldsResponse, "fields_Leads.json"),
    (
        "fields_Contacts",
        "/crm/v8/settings/fields?module=Contacts",
        FieldsResponse,
        "fields_Contacts.json",
    ),
    ("fields_Deals", "/crm/v8/settings/fields?module=Deals", FieldsResponse, "fields_Deals.json"),
    ("Leads", "/crm/v8/Leads", RecordPage, "Leads.json"),
    ("Contacts", "/crm/v8/Contacts", RecordPage, "Contacts.json"),
    ("Deals", "/crm/v8/Deals", RecordPage, "Deals.json"),
    ("users", "/crm/v8/users", UsersResponse, "users.json"),
)


def summarize(name: str, model: ZohoResponse, payload: Any) -> dict[str, Any]:
    """Shapes-only summary of a validated payload (no raw IDs or values)."""
    if isinstance(model, OrgResponse):
        first = model.org[0] if model.org else None
        raw_id = first.id if first is not None else ""
        keys = sorted(first.model_dump().keys()) if first is not None else []
        return {"org_fingerprint": org_fingerprint(raw_id), "fields_seen": keys}
    if isinstance(model, ModulesResponse):
        names = sorted(str(m.get("api_name", "?")) for m in model.modules)
        return {"count": len(model.modules), "api_names": names}
    if isinstance(model, FieldsResponse):
        names = sorted(str(f.get("api_name", "?")) for f in model.fields)
        return {"count": len(model.fields), "api_names": names}
    if isinstance(model, RecordPage):
        return {"records": len(model.data), "more_records": model.more_records}
    if isinstance(model, UsersResponse):
        return {"count": len(model.users)}
    raise AssertionError(f"no summary for model {type(model).__name__} ({name})")


def build_client(
    profile: Profile,
    budget: CallBudget,
    manager: TokenManager,
    transport_factory: Callable[[], httpx.BaseTransport] | None = None,
) -> ZohoClient:
    """Authenticated GET-only client for *profile* (token from env/keyring)."""
    factory = transport_factory or TRANSPORT_FACTORY
    access_token = manager.ensure_fresh()
    client = ZohoClient(
        DC_TABLE[profile.dc].api_base,
        transport=factory(),
        token_provider=lambda: access_token,
        budget=budget,
    )
    return client


def run_smoke(
    client: ZohoClient,
    profile: Profile,
    budget: CallBudget,
    *,
    record: bool,
    cassettes_dir: Path,
    token_provider: Callable[[], str | None],
    transport_factory: Callable[[], httpx.BaseTransport] | None = None,
) -> dict[str, Any]:
    """Run every smoke read; each result is recorded, nothing stops the rest.

    A drift on one endpoint no longer hides the others: failures are kept
    as ``status: fail`` entries (redacted, value-free) and the caller exits
    non-zero at the end when any read failed.
    """
    reads: list[dict[str, Any]] = []

    def fail_read(name: str, endpoint: str, model_name: str, error: BaseException) -> None:
        detail = redact_text(f"{endpoint} failed: {error}")
        reads.append(
            {
                "name": name,
                "endpoint": endpoint,
                "model": model_name,
                "status": "fail",
                "error": detail,
            }
        )
        print(f"[FAIL] {endpoint} ({model_name}): {detail}", file=sys.stderr)

    for name, path, model, cassette_file in SMOKE_READS:
        endpoint = path.split("?")[0]
        model_name = model.__name__
        try:
            payload = client.get(path, endpoint=endpoint, experimental=True).json()
        except ValueError as exc:
            fail_read(
                name,
                endpoint,
                model_name,
                ConnectorError(f"{endpoint} returned non-JSON: {exc}"),
            )
            continue
        except Exception as exc:  # diagnostics must try every endpoint
            fail_read(name, endpoint, model_name, exc)
            continue
        try:
            validated = validate_response(model, endpoint=endpoint, payload=payload)
        except Exception as exc:  # contract drift is a recorded result here
            fail_read(name, endpoint, model_name, exc)
            continue
        reads.append(
            {
                "name": name,
                "endpoint": endpoint,
                "model": model.__name__,
                "status": "pass",
                "shape": summarize(name, validated, payload),
            }
        )
        print(f"[PASS] {endpoint} validates as {model.__name__}")
        if record:
            try:
                written = record_cassette(
                    "crm",
                    profile.name,
                    path,
                    cassettes_dir / "crm" / cassette_file,
                    allow_ci=True,
                    token_provider=token_provider,
                    budget=budget,
                    transport_factory=transport_factory,
                )
            except Exception as exc:  # a failed recording is a result, not a stop
                reads[-1] = {
                    "name": name,
                    "endpoint": endpoint,
                    "model": model.__name__,
                    "status": "fail",
                    "error": redact_text(f"{endpoint} record failed: {exc}"),
                }
                print(f"[FAIL] {endpoint} record failed: {exc}", file=sys.stderr)
                continue
            print(f"recorded {written}")
    return {
        "profile": profile.name,
        "dc": profile.dc,
        "environment": profile.environment,
        "budget": {"max_calls": budget.max_calls, "used": budget.used},
        "reads": reads,
    }


def main(argv: list[str] | None = None) -> int:
    """Entry point for the nightly live job."""
    parser = argparse.ArgumentParser(description="Read-only live smoke reads.")
    parser.add_argument("--profile", default="dev-in")
    parser.add_argument("--evidence-dir", default="evidence")
    parser.add_argument("--max-api-calls", type=int, default=DEFAULT_MAX_API_CALLS)
    parser.add_argument("--record", action="store_true")
    parser.add_argument("--cassettes-dir", default="cassettes")
    args = parser.parse_args(argv)
    try:
        profile = load_profile(args.profile)
    except ValueError as exc:
        print(f"smoke refused: {exc}", file=sys.stderr)
        return 1
    budget = CallBudget(max_calls=args.max_api_calls)
    manager = TokenManager(dc=profile.dc, profile=profile.name, transport_factory=TRANSPORT_FACTORY)
    try:
        client = build_client(profile, budget, manager)
    except (ConnectorError, ContractDriftError) as exc:
        print(f"SMOKE FAIL: {redact_text(str(exc))}", file=sys.stderr)
        return 3
    evidence = run_smoke(
        client,
        profile,
        budget,
        record=args.record,
        cassettes_dir=Path(args.cassettes_dir),
        token_provider=manager.token_provider,
        transport_factory=TRANSPORT_FACTORY,
    )
    redacted = Redactor().redact_obj(evidence)
    evidence_dir = Path(args.evidence_dir)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    out = evidence_dir / "smoke.json"
    out.write_text(json.dumps(redacted, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    passed = sum(1 for read in evidence["reads"] if read["status"] == "pass")
    total = len(SMOKE_READS)
    print(f"wrote {out} ({passed}/{total} reads pass)")
    if passed != total:
        failed = [str(read["endpoint"]) for read in evidence["reads"] if read["status"] != "pass"]
        print(
            f"SMOKE FAIL: {len(failed)} read(s) failed: {', '.join(sorted(set(failed)))}",
            file=sys.stderr,
        )
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
