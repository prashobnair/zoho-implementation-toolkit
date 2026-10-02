"""STD-X1: the shared Redactor masks every PII shape, including adversarial ones."""

from __future__ import annotations

import string

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from zohokit.core.redact import (
    REDACTED_CREDENTIAL,
    REDACTED_VALUE,
    Redactor,
    mask_phone,
    redact_text,
)

redactor = Redactor(pii_fields=frozenset({"tax_id", "notes"}))


def test_name_fields_are_suppressed() -> None:
    record = {"First_Name": "Asha", "Last_Name": "Menon", "Stage": "Proposal"}
    assert redactor.redact_record(record) == {
        "First_Name": REDACTED_VALUE,
        "Last_Name": REDACTED_VALUE,
        "Stage": "Proposal",
    }


def test_pii_tagged_fields_are_suppressed() -> None:
    assert redactor.redact_record({"tax_id": "ABCDE1234F", "Stage": "Won"}) == {
        "tax_id": REDACTED_VALUE,
        "Stage": "Won",
    }


def test_email_and_phone_keys_use_shaped_masks() -> None:
    record = redactor.redact_record({"Email": "Asha@Example.COM", "Phone": "+919820011223"})
    assert record["Email"] == "a***@example.invalid"
    assert str(record["Phone"]).endswith("23")
    assert "98200112" not in str(record["Phone"])


def test_nested_structures_are_redacted() -> None:
    payload = {"data": [{"Email": "a@b.com", "tags": ["x", "y@z.com"]}]}
    redacted = redactor.redact_obj(payload)
    assert redacted == {
        "data": [{"Email": "a***@example.invalid", "tags": ["x", "y***@example.invalid"]}]
    }


def test_non_string_values_pass_through() -> None:
    assert redactor.redact_obj({"Amount": 42000, "Won": True, "Note": None}) == {
        "Amount": 42000,
        "Won": True,
        "Note": None,
    }


email_strategy = st.builds(
    lambda user, domain, tld: f"{user}@{domain}.{tld}",
    st.text(alphabet=string.ascii_lowercase + string.digits + "._%+-", min_size=1, max_size=12),
    st.text(alphabet=string.ascii_lowercase + string.digits + "-", min_size=1, max_size=8),
    st.sampled_from(["com", "org", "in", "io"]),
)

phone_strategy = st.builds(
    lambda cc, rest: f"+{cc} {rest[:5]} {rest[5:]}",
    st.integers(min_value=1, max_value=99),
    st.text(alphabet=string.digits, min_size=10, max_size=10),
)


@given(email=email_strategy)
@settings(suppress_health_check=[HealthCheck.too_slow], max_examples=100)
def test_property_no_input_email_survives(email: str) -> None:
    text = f"Contact {email} today about {email}"
    redacted = redactor.redact_obj({"Note": text, "Body": text})
    assert email not in str(redacted)
    assert "example.invalid" in str(redacted)


@given(phone=phone_strategy)
@settings(suppress_health_check=[HealthCheck.too_slow], max_examples=100)
def test_property_no_input_phone_survives(phone: str) -> None:
    digits = "".join(char for char in phone if char.isdigit())
    redacted = redactor.redact_obj({"Phone": phone, "Note": f"call {phone}"})
    flat = str(redacted)
    assert phone not in flat
    assert digits not in flat
    assert digits[-2:] in flat


def test_credential_keys_are_redacted_case_insensitively() -> None:
    record = redactor.redact_record(
        {
            "access_token": "tok-1",
            "REFRESH_TOKEN": "tok-2",
            "Client_Secret": "tok-3",
            "CLIENT_ID": "tok-4",
            "id_token": "tok-5",
            "Authorization": "Zoho-oauthtoken tok-6",
            "Cookie": "session=tok-7",
            "Set-Cookie": "session=tok-8",
            "X-API-Key": "tok-9",
            "Stage": "Proposal",
        }
    )
    for key, value in record.items():
        if key == "Stage":
            assert value == "Proposal"
        else:
            assert value == REDACTED_CREDENTIAL, key


def test_grant_code_redacted_only_in_token_context() -> None:
    exchange = redactor.redact_record({"grant_type": "authorization_code", "code": "grant-abc"})
    assert exchange["code"] == REDACTED_CREDENTIAL
    finding = redactor.redact_record({"code": "cycle_detected", "rule": "r-1"})
    assert finding["code"] == "cycle_detected"


def test_credential_patterns_in_free_text() -> None:
    assert "1000.abc123.def456" not in redact_text("Zoho-oauthtoken 1000.abc123.def456")
    assert REDACTED_CREDENTIAL in redact_text("Zoho-oauthtoken 1000.abc123.def456")
    assert "x.y.z" not in redact_text("Bearer x.y.z")
    assert REDACTED_CREDENTIAL in redact_text("Bearer x.y.z")
    assert "1000.aa11bb.cc22dd" not in redact_text("token 1000.aa11bb.cc22dd here")
    assert REDACTED_CREDENTIAL in redact_text("token 1000.aa11bb.cc22dd here")


token_strategy = st.builds(
    lambda a, b: f"1000.{a}.{b}",
    st.text(alphabet="0123456789abcdef", min_size=4, max_size=16),
    st.text(alphabet="0123456789abcdef", min_size=4, max_size=16),
)


@given(token=token_strategy)
@settings(suppress_health_check=[HealthCheck.too_slow], max_examples=100)
def test_property_no_generated_token_survives(token: str) -> None:
    assert token not in redact_text(f"Zoho-oauthtoken {token}")
    assert token not in redact_text(f"Bearer {token}")
    assert token not in redact_text(f"saw {token} here")
    redacted = redactor.redact_record({"access_token": token, "Note": token})
    assert token not in str(redacted)


def test_key_based_pii_masking_independent_of_value_format() -> None:
    """Any PII-named key is masked even when the value looks innocent."""
    plain = Redactor()
    payload = {
        "Phone": "23456789",
        "Mobile": "98765 43210",
        "$Phone": "+919820011223",
        "Email": "owner@example.com",
        "Mailing_Street": "12 Oracle Lane",
        "Billing_ZIP": "560001",
        "ZUID": "998877665544332211",
        "Primary_Email": "x@y.com",
        "Photo_Id": "some-photo",
        "Domain_Name": "example.com",
        "Website": "https://example.com",
        "Full_Name": "Asha Menon",
        "Fax_Number": "23456789",
        "Skype_ID": "asha.live",
        "Company_Name": "Acme Widgets",
        "DOB": "1990-01-01",
    }
    redacted = plain.redact_obj(payload)
    assert redacted["Phone"] == "******89"
    assert redacted["Mobile"] == "********10"
    assert str(redacted["$Phone"]).endswith("23")
    assert redacted["Email"] == "o***@example.invalid"
    # Phone-like keys (phone/mobile/fax) keep the shaped mask style.
    assert redacted["Fax_Number"] == "******89"
    for key in (
        "Mailing_Street",
        "Billing_ZIP",
        "ZUID",
        "Photo_Id",
        "Domain_Name",
        "Website",
        "Full_Name",
        "Skype_ID",
        "Company_Name",
        "DOB",
    ):
        assert redacted[key] == REDACTED_VALUE, key
    assert redacted["Primary_Email"] == "x***@example.invalid"


def test_structural_keys_are_never_masked() -> None:
    """Metadata keys survive even though they contain ``name``/``id``."""
    plain = Redactor()
    assert plain.redact_obj({"api_name": "Email"}) == {"api_name": "Email"}
    assert plain.redact_obj({"api_names": ["Leads"]}) == {"api_names": ["Leads"]}
    assert plain.redact_obj({"module_name": "Leads"}) == {"module_name": "Leads"}
    assert plain.redact_obj({"id": "abc123"}) == {"id": "abc123"}


def test_check_and_read_names_survive_but_record_names_do_not() -> None:
    """Bare ``name`` is structural only beside status+detail/endpoint."""
    plain = Redactor()
    check = {"name": "org_identity", "status": "pass", "detail": "org sha256:abc"}
    assert plain.redact_obj(check) == check
    read = {"name": "Leads", "endpoint": "/crm/v8/Leads", "status": "pass"}
    assert plain.redact_obj(read)["name"] == "Leads"
    user = {"name": "Asha Menon", "status": "active", "email": "a@example.com"}
    masked = plain.redact_obj(user)
    assert masked["name"] == REDACTED_VALUE
    assert masked["status"] == "active"


def test_non_string_pii_values_are_masked() -> None:
    """Numeric phones and nulls under PII keys never leak raw digits."""
    plain = Redactor()
    assert plain.redact_obj({"Phone": 98765432}) == {"Phone": "******32"}
    assert plain.redact_obj({"Phone": None}) == {"Phone": None}
    assert plain.redact_obj({"Email": None}) == {"Email": None}
    assert plain.redact_obj({"ZUID": 99887766}) == {"ZUID": REDACTED_VALUE}
    assert plain.redact_obj({"Street": None}) == {"Street": None}


def test_redaction_is_idempotent() -> None:
    """A second pass changes nothing, so scrub == record byte-for-byte."""
    plain = Redactor()
    payload = {
        "Phone": "23456789",
        "Mobile": "+919820011223",
        "Email": "owner@example.com",
        "Full_Name": "Asha Menon",
        "Mailing_Street": "12 Oracle Lane",
        "access_token": "tok-1",
    }
    once = plain.redact_obj(payload)
    assert plain.redact_obj(once) == once
    assert mask_phone(str(once["Phone"])) == once["Phone"]
    assert mask_phone(str(once["Mobile"])) == once["Mobile"]


def test_local_numbers_gain_no_country_code() -> None:
    assert redactor.redact_obj({"Phone": "9876543210"}) == {"Phone": "********10"}
    assert redactor.redact_obj({"Phone": "98765 43210"}) == {"Phone": "********10"}
    flat = str(redactor.redact_obj({"Note": "call 98765 43210"}))
    assert "98765 43210" not in flat
    assert "********10" in flat
    assert "+987" not in flat
