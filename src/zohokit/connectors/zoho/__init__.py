"""Zoho product connectors: CRM, Books, Projects, Forms (v0.2.0+)."""

from __future__ import annotations

from zohokit.connectors.zoho.auth import (
    CLIENT_ID_ENV,
    CLIENT_SECRET_ENV,
    KEYRING_SERVICE,
    REFRESH_TOKEN_ENV,
    AuthTransport,
    TokenManager,
    TokenResponse,
    exchange_grant_code,
    read_client_secret,
    read_refresh_token,
    refresh_access_token,
    store_client_secret,
    store_refresh_token,
)
from zohokit.connectors.zoho.budget import DEFAULT_MAX_API_CALLS, CallBudget
from zohokit.connectors.zoho.cache import DEFAULT_TTL_SECONDS, ResponseCache, cache_dir
from zohokit.connectors.zoho.client import ENDPOINT_STATUS, ZohoClient
from zohokit.connectors.zoho.dc import DC_TABLE, TOKEN_PATH, DataCentre, data_centre, token_url
from zohokit.connectors.zoho.doctor import (
    CheckResult,
    CheckStatus,
    doctor_exit_code,
    org_fingerprint,
    run_doctor,
)
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
from zohokit.connectors.zoho.profiles import (
    PRODUCTION_ALLOW_ENV,
    EnvironmentType,
    Profile,
    check_production,
    load_profile,
    production_allowed,
    profile_path,
    profiles_dir,
    save_profile,
)
from zohokit.connectors.zoho.retry import (
    CONNECT_TIMEOUT,
    READ_TIMEOUT,
    RetryPolicy,
    default_timeouts,
)
from zohokit.connectors.zoho.scopes import (
    OVER_PRIVILEGED_MARKERS,
    READ_SCOPES,
    find_over_privileged,
    sufficient_for,
)

__all__: list[str] = [
    "CLIENT_ID_ENV",
    "CLIENT_SECRET_ENV",
    "CONNECT_TIMEOUT",
    "DC_TABLE",
    "DEFAULT_MAX_API_CALLS",
    "DEFAULT_TTL_SECONDS",
    "ENDPOINT_STATUS",
    "KEYRING_SERVICE",
    "OVER_PRIVILEGED_MARKERS",
    "PRODUCTION_ALLOW_ENV",
    "READ_SCOPES",
    "READ_TIMEOUT",
    "REFRESH_TOKEN_ENV",
    "TOKEN_PATH",
    "AsyncGetOnlyTransport",
    "AuthTransport",
    "CallBudget",
    "CheckResult",
    "CheckStatus",
    "ConnectorError",
    "ContractDriftError",
    "DataCentre",
    "EnvironmentType",
    "GetOnlyTransport",
    "OrgInfo",
    "PaginationOutcome",
    "Profile",
    "RecordPage",
    "ResponseCache",
    "RetryPolicy",
    "SafetyGuardError",
    "TokenManager",
    "TokenPage",
    "TokenResponse",
    "ZohoClient",
    "ZohoResponse",
    "cache_dir",
    "check_production",
    "data_centre",
    "default_timeouts",
    "doctor_exit_code",
    "exchange_grant_code",
    "find_over_privileged",
    "iter_page_number_pages",
    "iter_page_token_pages",
    "load_profile",
    "org_fingerprint",
    "production_allowed",
    "profile_path",
    "profiles_dir",
    "read_client_secret",
    "read_refresh_token",
    "refresh_access_token",
    "run_doctor",
    "save_profile",
    "store_client_secret",
    "store_refresh_token",
    "sufficient_for",
    "token_url",
    "validate_response",
]
