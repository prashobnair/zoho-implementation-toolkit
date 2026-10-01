"""Validated response models: unknown fields kept, missing fields drift (STD-H3)."""

from __future__ import annotations

from typing import Any, TypeVar

from pydantic import BaseModel, ConfigDict, ValidationError

from zohokit.connectors.zoho.errors import ContractDriftError

ModelT = TypeVar("ModelT", bound="ZohoResponse")


class ZohoResponse(BaseModel):
    """Base model for Zoho payloads: ``extra="allow"``, unknowns in ``raw_extra``."""

    model_config = ConfigDict(extra="allow")

    @property
    def raw_extra(self) -> dict[str, Any]:
        """Fields the contract does not name yet, kept verbatim."""
        return dict(self.model_extra or {})


def validate_response(model: type[ModelT], *, endpoint: str, payload: Any) -> ModelT:
    """Validate *payload*; a missing required field raises contract drift (exit 3)."""
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise ContractDriftError(endpoint, str(exc) or "invalid payload") from exc


class OrgInfo(ZohoResponse):
    """Minimal org identity: ``/crm/v8/org`` (synthetic shape, unverified)."""

    id: str
    company_name: str


class RecordPage(ZohoResponse):
    """One page of CRM records with the ``info.more_records`` style flag."""

    data: list[dict[str, Any]]
    more_records: bool = False


class TokenPage(ZohoResponse):
    """One page of CRM records with the ``page_token`` style cursor."""

    data: list[dict[str, Any]]
    next_page_token: str | None = None


__all__: list[str] = ["OrgInfo", "RecordPage", "TokenPage", "ZohoResponse", "validate_response"]
