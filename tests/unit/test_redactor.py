"""STD-X1: the shared Redactor masks every PII shape, including adversarial ones."""

from __future__ import annotations

import string

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from zohokit.core.redact import REDACTED_CREDENTIAL, REDACTED_VALUE, Redactor, redact_text

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


def test_local_numbers_gain_no_country_code() -> None:
    assert redactor.redact_obj({"Phone": "9876543210"}) == {"Phone": "********10"}
    assert redactor.redact_obj({"Phone": "98765 43210"}) == {"Phone": "********10"}
    flat = str(redactor.redact_obj({"Note": "call 98765 43210"}))
    assert "98765 43210" not in flat
    assert "********10" in flat
    assert "+987" not in flat
