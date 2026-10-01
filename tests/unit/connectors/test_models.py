"""STD-H3: validated responses keep unknowns, missing fields raise contract drift."""

from __future__ import annotations

import pytest

from zohokit.connectors.zoho.errors import ContractDriftError
from zohokit.connectors.zoho.models import OrgInfo, ZohoResponse, validate_response


def test_unknown_fields_kept_in_raw_extra() -> None:
    org = validate_response(
        OrgInfo,
        endpoint="/crm/v8/org",
        payload={"id": "555000111", "company_name": "Marigold Labs", "future_field": "kept"},
    )
    assert org.company_name == "Marigold Labs"
    assert org.raw_extra == {"future_field": "kept"}


def test_missing_required_field_raises_contract_drift_naming_endpoint() -> None:
    with pytest.raises(ContractDriftError, match=r"(?s).*/crm/v8/org.*company_name.*"):
        validate_response(OrgInfo, endpoint="/crm/v8/org", payload={"id": "555000111"})


def test_extra_allow_on_base_model() -> None:
    class Sample(ZohoResponse):
        name: str

    sample = Sample.model_validate({"name": "n", "anything": 1})
    assert sample.raw_extra == {"anything": 1}
