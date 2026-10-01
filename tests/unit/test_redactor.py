"""STD-X1: the shared Redactor masks every PII shape, including adversarial ones."""

from __future__ import annotations

import string

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from zohokit.core.redact import REDACTED_VALUE, Redactor

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
