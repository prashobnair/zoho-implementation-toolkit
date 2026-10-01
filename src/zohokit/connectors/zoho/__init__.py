"""Zoho product connectors: CRM, Books, Projects, Forms (v0.2.0+)."""

from __future__ import annotations

from zohokit.connectors.zoho.budget import DEFAULT_MAX_API_CALLS, CallBudget
from zohokit.connectors.zoho.client import ENDPOINT_STATUS, ZohoClient
from zohokit.connectors.zoho.errors import (
    ConnectorError,
    ContractDriftError,
    SafetyGuardError,
)
from zohokit.connectors.zoho.guard import AsyncGetOnlyTransport, GetOnlyTransport
from zohokit.connectors.zoho.models import (
    OrgInfo,
    RecordPage,
    TokenPage,
    ZohoResponse,
    validate_response,
)
from zohokit.connectors.zoho.pagination import (
    PaginationOutcome,
    iter_page_number_pages,
    iter_page_token_pages,
)
from zohokit.connectors.zoho.retry import (
    CONNECT_TIMEOUT,
    READ_TIMEOUT,
    RetryPolicy,
    default_timeouts,
)

__all__: list[str] = [
    "CONNECT_TIMEOUT",
    "DEFAULT_MAX_API_CALLS",
    "ENDPOINT_STATUS",
    "READ_TIMEOUT",
    "AsyncGetOnlyTransport",
    "CallBudget",
    "ConnectorError",
    "ContractDriftError",
    "GetOnlyTransport",
    "OrgInfo",
    "PaginationOutcome",
    "RecordPage",
    "RetryPolicy",
    "SafetyGuardError",
    "TokenPage",
    "ZohoClient",
    "ZohoResponse",
    "default_timeouts",
    "iter_page_number_pages",
    "iter_page_token_pages",
    "validate_response",
]
