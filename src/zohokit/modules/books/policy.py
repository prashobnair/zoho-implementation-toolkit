"""Books match policy (TK-BK-F1): key strategy, tolerance, billing plans.

The policy is a YAML file validated by :class:`MatchPolicy` (schema
``schemas/books/policy.v1.json``)::

    key_strategy: crm_deal_id_in_invoice_custom_field  # or reference_number, sales_order_link
    custom_field_label: "CRM Deal ID"                  # only for the custom-field strategy
    tolerance: {abs: "1.00", pct: "0.5"}
    allow_multiple_invoices_when: {billing_plan_field: "Billing_Plan"}
    credit_notes: net_off
    tax: compare_net_only                            # or compare_gross_with_tax_table
    tax_table: {GST18: "18.00"}                      # rates as percent strings, gross mode only
    include_draft: false                             # drafts excluded by default
    include_void: false                              # voids excluded by default
    period: {by: deal_closing_date, start: 2026-09-01, end: 2026-09-30}

Key strategies (one test per strategy):

- ``crm_deal_id_in_invoice_custom_field``: the invoice's custom field
  labelled ``custom_field_label`` must equal the deal id.
- ``reference_number``: ``invoice.reference_number`` must equal
  ``deal.reference_number``.
- ``sales_order_link``: ``invoice.salesorder_id`` (or
  ``salesorder_number``) must equal the deal's ``salesorder_id`` (or
  ``salesorder_number``).

Tolerance passes when ``|diff|`` fits every bound the policy states:
both ``abs`` and ``pct`` when both are given, only the stated one when a
single bound is given, and exact match (``diff == 0``) when neither bound
is given. A policy that sets only ``pct`` never inherits the ``abs``
default — ``0.5%`` means ``0.5%`` alone. Credit notes linked to a matched
invoice are netted off the invoiced total (``net_off`` is the only
supported mode). ``tax: compare_net_only`` compares deal net against
the invoice net; ``compare_gross_with_tax_table`` grosses the deal net
up by the deal's tax rate from ``tax_table`` and compares against the
invoice gross (unknown tax names fall back to net-only for that deal,
noted in evidence — never a guessed rate).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

KeyStrategy = Literal[
    "crm_deal_id_in_invoice_custom_field",
    "reference_number",
    "sales_order_link",
]

TaxMode = Literal["compare_net_only", "compare_gross_with_tax_table"]

PeriodBasis = Literal["deal_closing_date", "invoice_date"]


class Tolerance(BaseModel):
    """Absolute + percentage tolerance bounds (only stated bounds apply)."""

    model_config = ConfigDict(frozen=True)

    abs: Decimal | None = Field(default=None)
    pct: Decimal | None = Field(default=None)

    @field_validator("abs", "pct")
    @classmethod
    def _non_negative(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and value < 0:
            raise ValueError("tolerance bounds must be >= 0")
        return value


class CrmDealFields(BaseModel):
    """CRM field names mapped to offline deal attributes (live Deals read).

    The live recon reads Deals through the GET-only CRM v8 reader with
    these fields (plus ``id``) in the explicit ``fields=`` list the API
    requires. ``entity`` names the CRM field holding the entity
    discriminator matched against each entity map entry's
    ``crm_criteria`` (default ``Entity``, as in the Marigold fixture).
    """

    model_config = ConfigDict(frozen=True)

    amount: str = "Amount"
    closing_date: str = "Closing_Date"
    currency: str = "Currency"
    customer: str = "Account_Name"
    billing_plan: str = "Billing_Plan"
    entity: str = "Entity"


class AllowMultiple(BaseModel):
    """When several invoices may sum to one deal net (UC-BK-2 staged billing)."""

    model_config = ConfigDict(frozen=True)

    billing_plan_field: str = "Billing_Plan"


class PeriodWindow(BaseModel):
    """Month window; both bounds inclusive (see :mod:`period`)."""

    model_config = ConfigDict(frozen=True)

    by: PeriodBasis = "deal_closing_date"
    start: date = date(2026, 9, 1)
    end: date = date(2026, 9, 30)


class MatchPolicy(BaseModel):
    """Validated Books reconciliation policy (TK-BK-F1)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key_strategy: KeyStrategy = "crm_deal_id_in_invoice_custom_field"
    custom_field_label: str = "CRM Deal ID"
    tolerance: Tolerance = Field(default_factory=Tolerance)
    allow_multiple_invoices_when: AllowMultiple | None = None
    credit_notes: Literal["net_off"] = "net_off"
    tax: TaxMode = "compare_net_only"
    tax_table: dict[str, Decimal] = Field(default_factory=dict)
    include_draft: bool = False
    include_void: bool = False
    period: PeriodWindow | None = None
    crm_fields: CrmDealFields = Field(default_factory=CrmDealFields)


def default_policy() -> MatchPolicy:
    """The default policy (custom-field keys, drafts/voids excluded)."""
    return MatchPolicy()


class PolicyConfigError(ValueError):
    """A policy file problem as ``path:line: detail`` (exit 1 at the CLI)."""

    def __init__(self, path: str | Path, line: int, detail: str) -> None:
        super().__init__(f"{path}:{line}: {detail}")
        self.path = str(path)
        self.line = line
        self.detail = detail


def load_policy(path: Path) -> MatchPolicy:
    """Load and validate a policy YAML file.

    YAML syntax problems and schema violations raise
    :class:`PolicyConfigError` as ``path:line: detail`` (exit 1 at the
    CLI). Messages name field locations only, never values.
    """
    text_path = Path(path)
    try:
        text = text_path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise PolicyConfigError(str(path), 1, f"cannot read policy file: {exc}") from exc
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        line = getattr(getattr(exc, "problem_mark", None), "line", None)
        raise PolicyConfigError(
            str(path), (line + 1) if isinstance(line, int) else 1, "invalid YAML"
        ) from exc
    if not isinstance(raw, dict):
        raise PolicyConfigError(str(path), 1, "policy must be a YAML mapping")
    try:
        return MatchPolicy.model_validate(raw)
    except ValidationError as exc:
        first = exc.errors(include_input=False, include_url=False)[0]
        loc = ".".join(str(step) for step in first.get("loc", ()))
        detail = (
            f"invalid match policy at {loc}: {first.get('msg')}" if loc else "invalid match policy"
        )
        raise PolicyConfigError(str(path), 1, detail) from exc


def policy_to_json(policy: MatchPolicy) -> dict[str, Any]:
    """Render *policy* as JSON-safe data (Decimal as strings)."""
    return policy.model_dump(mode="json")


__all__: list[str] = [
    "AllowMultiple",
    "CrmDealFields",
    "MatchPolicy",
    "PeriodWindow",
    "PolicyConfigError",
    "Tolerance",
    "default_policy",
    "load_policy",
    "policy_to_json",
]
