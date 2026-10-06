"""Redaction hook: the shared redactor runs on every prompt (STD-AI8)."""

from __future__ import annotations

from zohokit.ai.injection import SYSTEM_STATEMENT, wrap_data
from zohokit.ai.models import Prompt
from zohokit.ai.prompts import PromptTemplate, render_template
from zohokit.core.redact import Redactor


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


__all__: list[str] = ["build_prompt", "redact_variables"]
