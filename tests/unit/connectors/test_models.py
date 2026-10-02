"""STD-H3: validated responses keep unknowns, missing fields raise contract drift."""

from __future__ import annotations

import pytest

from zohokit.connectors.zoho.errors import ContractDriftError
from zohokit.connectors.zoho.models import (
    OrgInfo,
    OrgResponse,
    ZohoResponse,
    unwrap_org,
    validate_response,
)


def test_unknown_fields_kept_in_raw_extra() -> None:
    org = unwrap_org(
        {"org": [{"id": "555000111", "company_name": "Marigold Labs", "future_field": "kept"}]},
        endpoint="/crm/v8/org",
    )
    assert org.company_name == "Marigold Labs"
    assert org.raw_extra == {"future_field": "kept"}


def test_missing_required_field_raises_contract_drift_naming_endpoint() -> None:
    with pytest.raises(ContractDriftError, match=r"(?s).*/crm/v8/org.*company_name.*"):
        validate_response(OrgInfo, endpoint="/crm/v8/org", payload={"id": "555000111"})


def test_flat_org_payload_is_contract_drift() -> None:
    """The real ``/crm/v8/org`` reply is the ``{"org": [...]}`` envelope."""
    with pytest.raises(ContractDriftError, match="/crm/v8/org"):
        unwrap_org({"id": "555000111", "company_name": "Marigold Labs"}, endpoint="/crm/v8/org")


def test_empty_org_envelope_is_contract_drift() -> None:
    with pytest.raises(ContractDriftError, match="/crm/v8/org"):
        unwrap_org({"org": []}, endpoint="/crm/v8/org")


def test_contract_drift_message_carries_no_api_values() -> None:
    """A failing payload with email/phone/name leaks none of them in the error."""
    email = "amara.okafor@example.com"
    phone = "+1 415-860-1234"
    name = "Amara Okafor"
    with pytest.raises(ContractDriftError) as exc_info:
        validate_response(
            OrgResponse,
            endpoint="/crm/v8/org",
            payload={
                "org": [{"id": 123, "company_name": {"email": email, "phone": phone, "name": name}}]
            },
        )
    message = str(exc_info.value)
    assert "/crm/v8/org" in message
    assert email not in message
    assert phone not in message
    assert name not in message
    assert "input_value" not in message


def test_extra_allow_on_base_model() -> None:
    class Sample(ZohoResponse):
        name: str

    sample = Sample.model_validate({"name": "n", "anything": 1})
    assert sample.raw_extra == {"anything": 1}
