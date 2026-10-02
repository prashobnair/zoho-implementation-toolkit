"""`zohokit doctor`: read-only checklist for a profile (TK-CONN-2, STD-L2/L4).

Checklist: DC reachability, token refresh, org identity (fingerprint
only), scope sufficiency per module, call budget, clock skew and
environment type. Each check reports pass/warn/fail; any fail exits 3.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from zohokit.connectors.zoho.budget import CallBudget
from zohokit.connectors.zoho.client import ZohoClient
from zohokit.connectors.zoho.dc import DC_TABLE
from zohokit.connectors.zoho.profiles import Profile, check_production
from zohokit.connectors.zoho.readers import read_org
from zohokit.connectors.zoho.scopes import READ_SCOPES, find_over_privileged, sufficient_for

#: Scope prefix per module: a profile is "configured for" a module when it
#: carries at least one scope with that prefix. Unconfigured modules are
#: never required (dev-in ships CRM scopes only, so Books absence is not a
#: failure and not even a warning).
MODULE_SCOPE_PREFIX = {"crm": "ZohoCRM.", "books": "ZohoBooks."}


def configured_modules(scopes: list[str]) -> list[str]:
    """Modules the profile is configured for (prefix match, READ_SCOPES order)."""
    configured: list[str] = []
    for module in READ_SCOPES:
        prefix = MODULE_SCOPE_PREFIX.get(module, "")
        if prefix and any(scope.startswith(prefix) for scope in scopes):
            configured.append(module)
    return configured


CheckStatus = Literal["pass", "warn", "fail"]


@dataclass(frozen=True)
class CheckResult:
    """One doctor line: stable name, outcome and a human detail."""

    name: str
    status: CheckStatus
    detail: str


def org_fingerprint(org_id: str) -> str:
    """Short hash identifying the org without ever printing its raw id."""
    return "sha256:" + hashlib.sha256(org_id.encode()).hexdigest()[:16]


def run_doctor(
    profile: Profile,
    *,
    client_factory: Callable[[], ZohoClient],
    token_refresher: Callable[[], bool],
    budget: CallBudget,
    confirmed_org_name: str | None = None,
    experimental: bool = False,
    now: datetime | None = None,
) -> list[CheckResult]:
    """Run every check offline-testable: network enters only via *client_factory*."""
    moment = now or datetime.now(UTC)
    checks: list[CheckResult] = []

    if profile.dc not in DC_TABLE:
        checks.append(CheckResult("dc_reachability", "fail", f"unknown DC {profile.dc!r}"))
        return checks
    checks.append(
        CheckResult("dc_reachability", "pass", f"DC {profile.dc!r} maps to a known accounts host")
    )

    try:
        refreshed = token_refresher()
    except Exception as exc:
        refreshed = False
        checks.append(CheckResult("token_refresh", "fail", f"refresh failed: {exc}"))
    else:
        checks.append(
            CheckResult(
                "token_refresh",
                "pass" if refreshed else "fail",
                "refresh token exchanged" if refreshed else "no stored credentials",
            )
        )

    try:
        client = client_factory()
        # The single shared org read (also used by smoke): identical payloads
        # can never disagree again. Zoho error bodies arrive here as
        # ConnectorError (carrying the Zoho code only), not contract drift.
        read = read_org(client, experimental=experimental)
        org_id = read.org.id
        checks.append(
            CheckResult(
                "org_identity",
                "pass" if org_id else "fail",
                f"org {org_fingerprint(org_id)}" if org_id else "org response has no id",
            )
        )
        date_header = read.date_header
        if date_header:
            checks.append(
                CheckResult("clock_skew", "pass", f"server date header seen ({date_header})")
            )
        else:
            checks.append(CheckResult("clock_skew", "warn", "no date header to compare the clock"))
    except Exception as exc:
        checks.append(CheckResult("org_identity", "fail", f"org read failed: {exc}"))
        checks.append(CheckResult("clock_skew", "warn", "skipped: org read failed"))

    offenders = find_over_privileged(profile.scopes)
    if offenders:
        checks.append(
            CheckResult(
                "scope_sufficiency",
                "fail",
                f"over_privileged_scope: {sorted(offenders)} requests more than read access",
            )
        )
    else:
        modules = configured_modules(profile.scopes)
        if not modules:
            checks.append(
                CheckResult(
                    "scope_sufficiency",
                    "warn",
                    "no module scopes configured (expected one of: crm, books)",
                )
            )
        else:
            missing_parts: list[str] = []
            for module in modules:
                missing = sufficient_for(profile.scopes, READ_SCOPES[module])
                for scope in sorted(missing):
                    missing_parts.append(f"missing {scope} for {module}")
            if missing_parts:
                checks.append(CheckResult("scope_sufficiency", "warn", "; ".join(missing_parts)))
            elif modules == ["crm"]:
                checks.append(
                    CheckResult("scope_sufficiency", "pass", "read scopes cover CRM checks")
                )
            else:
                checks.append(
                    CheckResult(
                        "scope_sufficiency",
                        "pass",
                        f"read scopes cover {', '.join(modules)} checks",
                    )
                )

    if budget.exhausted:
        checks.append(CheckResult("budget", "fail", "call budget already exhausted"))
    else:
        checks.append(
            CheckResult("budget", "pass", f"{budget.remaining} of {budget.max_calls} calls remain")
        )

    try:
        check_production(profile, confirmed_org_name=confirmed_org_name)
        checks.append(
            CheckResult(
                "environment_type",
                "pass" if profile.environment != "production" else "warn",
                f"environment is {profile.environment}"
                + (" (confirmed for this run)" if profile.environment == "production" else ""),
            )
        )
    except PermissionError as exc:
        checks.append(CheckResult("environment_type", "fail", str(exc)))

    _ = moment
    return checks


def doctor_exit_code(checks: list[CheckResult]) -> int:
    """Exit 3 on any fail (STD §3.5 connector error), else 0."""
    return 3 if any(check.status == "fail" for check in checks) else 0


__all__: list[str] = [
    "CheckResult",
    "CheckStatus",
    "configured_modules",
    "doctor_exit_code",
    "org_fingerprint",
    "run_doctor",
]
