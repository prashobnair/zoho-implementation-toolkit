"""Redaction hook: the shared redactor runs on every prompt (STD-AI8)."""

from __future__ import annotations

from collections.abc import Collection, Sequence

from zohokit.ai.injection import SYSTEM_STATEMENT, wrap_data
from zohokit.ai.models import Prompt
from zohokit.ai.prompts import PromptTemplate, render_template
from zohokit.core.redact import Redactor

#: Source-column headers whose sample values are person names (STD-AI8,
#: AI-MIG-1 "redacted sample values"). Compared header-normalized
#: (case-folded, non-alphanumeric stripped), so "First Name",
#: "firstname" and "FIRST_NAME" all match — but matching is an exact
#: set hit, never a substring: "Company Name" and "Deal Name" are not
#: person columns and keep their values.
NAME_LIKE_COLUMNS = frozenset(
    {
        "name",
        "firstname",
        "lastname",
        "fullname",
        "contact",
        "contactperson",
        "owner",
        "customer",
        "person",
    }
)


def normalize_column_header(name: str) -> str:
    """Header-normalize a CSV column name for the name-like comparison."""
    return "".join(char for char in name.casefold() if char.isalnum())


def is_name_like_column(name: str, *, pii_columns: Collection[str] = ()) -> bool:
    """True when *name* is a person-name column (or mapping-marked PII).

    ``pii_columns`` carries source-column names the mapping marks
    ``pii: true``; they are matched header-normalized too, so the
    suggester never forwards a flagged column's values to the model.
    """
    normalized = normalize_column_header(name)
    if normalized in NAME_LIKE_COLUMNS:
        return True
    flagged = {normalize_column_header(item) for item in pii_columns}
    return normalized in flagged


def mask_name_sample(value: str) -> str:
    """Replace one person-name value with a shape hint for the model.

    The header is kept by the caller and the hint preserves only the
    word count ("<name: 2 words>"), which is enough to tell given names
    from full names when mapping, without sending any name to the
    model. Blank samples stay visibly blank ("<name: empty>").
    """
    words = value.split()
    if not words:
        return "<name: empty>"
    noun = "word" if len(words) == 1 else "words"
    return f"<name: {len(words)} {noun}>"


def mask_column_samples(
    name: str, samples: Sequence[str], *, pii_columns: Collection[str] = ()
) -> tuple[str, ...]:
    """Mask *samples* when *name* is a name-like (or PII-flagged) column.

    Non-name columns pass through untouched; the header itself is never
    masked, only the values.
    """
    if not is_name_like_column(name, pii_columns=pii_columns):
        return tuple(samples)
    return tuple(mask_name_sample(item) for item in samples)


def redact_variables(
    variables: dict[str, str], *, redactor: Redactor | None = None
) -> dict[str, str]:
    """Redact every prompt variable with the shared redactor (STD §4.5)."""
    active = redactor or Redactor()
    redacted: dict[str, str] = {}
    for key, value in variables.items():
        redacted[key] = active.redact_obj(value)
    return redacted


def build_prompt(
    template: PromptTemplate,
    variables: dict[str, str],
    *,
    redactor: Redactor | None = None,
    allow_pii: bool = False,
    system_addendum: str = "",
) -> Prompt:
    """Render a prompt file into a redacted, injection-hygienic prompt.

    Unless ``allow_pii`` is set (synthetic-only local runs; refused with
    ``--live``), every variable is redacted first, and every variable is
    wrapped in a delimited data block so the model treats source text as
    data, never instructions (STD-AI8/10).
    """
    raw = dict(variables) if allow_pii else redact_variables(variables, redactor=redactor)
    wrapped = {key: wrap_data(value) for key, value in raw.items()}
    text = render_template(template.body, wrapped)
    system = SYSTEM_STATEMENT
    if system_addendum:
        system = system + " " + system_addendum
    return Prompt(
        feature=template.feature,
        version=template.version,
        schema_name=template.schema_name,
        system=system,
        text=text,
    )


__all__: list[str] = [
    "NAME_LIKE_COLUMNS",
    "build_prompt",
    "is_name_like_column",
    "mask_column_samples",
    "mask_name_sample",
    "normalize_column_header",
    "redact_variables",
]
