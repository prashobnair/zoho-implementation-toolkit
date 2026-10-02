"""Validated response models: unknown fields kept, missing fields drift (STD-H3).

Envelope shapes follow the official Zoho CRM v8 docs (all ``unverified``;
see ``docs/API_CONTRACTS.md`` for the per-endpoint doc URL):

- ``GET /crm/v8/org`` → ``{"org": [...]}``
- ``GET /crm/v8/settings/modules`` → ``{"modules": [...]}``
- ``GET /crm/v8/settings/fields?module=X`` → ``{"fields": [...]}``
- ``GET /crm/v8/users`` → ``{"users": [...], "info": {...}}``

An empty or missing envelope list raises :class:`ContractDriftError`
naming the endpoint. Error messages are value-free (field location +
error type only, never API values) so they are safe for public logs.
"""

from __future__ import annotations

from typing import Any, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from zohokit.connectors.zoho.errors import ContractDriftError

ModelT = TypeVar("ModelT", bound="ZohoResponse")


class ZohoResponse(BaseModel):
    """Base model for Zoho payloads: ``extra="allow"``, unknowns in ``raw_extra``."""

    model_config = ConfigDict(extra="allow")

    @property
    def raw_extra(self) -> dict[str, Any]:
        """Fields the contract does not name yet, kept verbatim."""
        return dict(self.model_extra or {})


def _safe_detail(exc: ValidationError) -> str:
    """Value-free summary of *exc*: endpoint-safe ``loc: type`` fragments.

    Built from ``exc.errors(include_input=False, include_url=False)`` so
    no API value (email, phone, name, token, ``input_value=`` snippet) can
    reach the message — and therefore the public Actions logs.
    """
    parts: list[str] = []
    for err in exc.errors(include_input=False, include_url=False):
        loc = ".".join(str(step) for step in err.get("loc", ()))
        kind = str(err.get("type", "invalid"))
        parts.append(f"{loc}: {kind}" if loc else kind)
    return "; ".join(parts) or "invalid payload"


def validate_response(model: type[ModelT], *, endpoint: str, payload: Any) -> ModelT:
    """Validate *payload*; a missing required field raises contract drift (exit 3).

    The drift message names the endpoint plus the failing field location
    and error type only — never values.
    """
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise ContractDriftError(endpoint, _safe_detail(exc)) from exc


class OrgInfo(ZohoResponse):
    """One org entry inside the ``{"org": [...]}`` envelope."""

    id: str
    company_name: str


class OrgResponse(ZohoResponse):
    """CRM ``/crm/v8/org`` reply: the ``{"org": [...]}`` envelope (synthetic shape)."""

    org: list[OrgInfo] = Field(min_length=1)


class RecordPage(ZohoResponse):
    """One page of CRM records with the ``info.more_records`` style flag."""

    data: list[dict[str, Any]]
    more_records: bool = False


class TokenPage(ZohoResponse):
    """One page of CRM records with the ``page_token`` style cursor."""

    data: list[dict[str, Any]]
    next_page_token: str | None = None


class ModulesResponse(ZohoResponse):
    """CRM ``/settings/modules`` reply: the ``{"modules": [...]}`` envelope (synthetic shape)."""

    modules: list[dict[str, Any]] = Field(min_length=1)


class FieldsResponse(ZohoResponse):
    """CRM ``/settings/fields`` reply: the ``{"fields": [...]}`` envelope (synthetic shape)."""

    fields: list[dict[str, Any]] = Field(min_length=1)


class UsersResponse(ZohoResponse):
    """CRM ``/users`` reply: the ``{"users": [...], "info": {...}}`` envelope (synthetic shape)."""

    users: list[dict[str, Any]] = Field(min_length=1)
    info: dict[str, Any] | None = None


def unwrap_org(payload: Any, *, endpoint: str) -> OrgInfo:
    """Validate the ``{"org": [...]}`` envelope and return ``org[0]``.

    An empty or missing ``org`` list raises contract drift naming *endpoint*.
    """
    envelope = validate_response(OrgResponse, endpoint=endpoint, payload=payload)
    if not envelope.org:
        raise ContractDriftError(endpoint, "org: empty list")
    return envelope.org[0]


def unwrap_modules(payload: Any, *, endpoint: str) -> list[dict[str, Any]]:
    """Validate the ``{"modules": [...]}`` envelope and return the list."""
    envelope = validate_response(ModulesResponse, endpoint=endpoint, payload=payload)
    if not envelope.modules:
        raise ContractDriftError(endpoint, "modules: empty list")
    return envelope.modules


def unwrap_fields(payload: Any, *, endpoint: str) -> list[dict[str, Any]]:
    """Validate the ``{"fields": [...]}`` envelope and return the list."""
    envelope = validate_response(FieldsResponse, endpoint=endpoint, payload=payload)
    if not envelope.fields:
        raise ContractDriftError(endpoint, "fields: empty list")
    return envelope.fields


def unwrap_users(payload: Any, *, endpoint: str) -> list[dict[str, Any]]:
    """Validate the ``{"users": [...], "info": {...}}`` envelope and return the list."""
    envelope = validate_response(UsersResponse, endpoint=endpoint, payload=payload)
    if not envelope.users:
        raise ContractDriftError(endpoint, "users: empty list")
    return envelope.users


__all__: list[str] = [
    "FieldsResponse",
    "ModulesResponse",
    "OrgInfo",
    "OrgResponse",
    "RecordPage",
    "TokenPage",
    "UsersResponse",
    "ZohoResponse",
    "unwrap_fields",
    "unwrap_modules",
    "unwrap_org",
    "unwrap_users",
    "validate_response",
]
