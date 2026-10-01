"""Data-centre routing per the official multi-DC table (STD-A2).

Source: https://www.zoho.com/crm/developer/docs/api/multi-dc.html
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DataCentre:
    """Accounts host and API base for one Zoho region."""

    code: str
    accounts_host: str
    api_base: str


DC_TABLE: dict[str, DataCentre] = {
    "us": DataCentre("us", "accounts.zoho.com", "https://www.zohoapis.com"),
    "eu": DataCentre("eu", "accounts.zoho.eu", "https://www.zohoapis.eu"),
    "in": DataCentre("in", "accounts.zoho.in", "https://www.zohoapis.in"),
    "au": DataCentre("au", "accounts.zoho.com.au", "https://www.zohoapis.com.au"),
    "jp": DataCentre("jp", "accounts.zoho.jp", "https://www.zohoapis.jp"),
    "ca": DataCentre("ca", "accounts.zohocloud.ca", "https://www.zohoapis.ca"),
    "cn": DataCentre("cn", "accounts.zoho.com.cn", "https://www.zohoapis.com.cn"),
}

# Path only; the secret travels in the POST body, never in code.
TOKEN_PATH = "/oauth/v2/token"  # nosec B105


def data_centre(code: str) -> DataCentre:
    """Return the routing row for *code* or raise a usage error."""
    try:
        return DC_TABLE[code]
    except KeyError:
        raise ValueError(f"unknown DC {code!r} (choose from {sorted(DC_TABLE)})") from None


def token_url(code: str) -> str:
    """Accounts token endpoint for *code* (the only POST target anywhere)."""
    dc = data_centre(code)
    return f"https://{dc.accounts_host}{TOKEN_PATH}"


__all__: list[str] = ["DC_TABLE", "TOKEN_PATH", "DataCentre", "data_centre", "token_url"]
