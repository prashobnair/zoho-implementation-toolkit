"""Structured pipeline: parse → one repair retry → deterministic fallback (STD-AI3).

Every outcome carries ``source: "ai"`` with the model and prompt version
(STD-AI5); nothing is ever auto-applied. With no provider configured the
deterministic fallback runs and the status reads ``disabled`` (STD-AI4).
All errors are value-free: hashes, counts and field paths, never prompt
or response content.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict

from zohokit.ai.models import AiStatus, AiUsage, Prompt
from zohokit.ai.prompts import PromptTemplate
from zohokit.ai.providers import (
    FakeProviderError,
    LLMProvider,
    ProviderError,
    SchemaParseError,
    parse_structured,
    repair_prompt_text,
)
from zohokit.ai.redaction import build_prompt
from zohokit.ai.usage import estimate_cost_usd, estimate_tokens, within_budget
from zohokit.core.redact import Redactor

ModelT = TypeVar("ModelT", bound=BaseModel)


class AiOutcome(BaseModel, Generic[ModelT]):
    """One AI attempt: suggestion data plus traceability (STD-AI5).

    ``data`` is always a suggestion for human review, labeled with its
    source, model and prompt version. ``ai_status`` is ``fallback`` (or
    ``disabled``) whenever the deterministic path produced ``data``.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    source: str = "ai"
    model: str = ""
    prompt_version: str = ""
    prompt_hash: str = ""
    ai_status: AiStatus = "disabled"
    data: Any = None
    usage: AiUsage = AiUsage()


@dataclass(frozen=True)
class AiRequest:
    """Everything one AI call needs beyond the provider."""

    template: PromptTemplate
    variables: dict[str, str]
    allow_pii: bool = False
    budget_tokens: int | None = None
    temperature: float = 0.0
    system_addendum: str = ""


def run_ai(
    provider: LLMProvider | None,
    request: AiRequest,
    schema: type[ModelT],
    *,
    fallback: Callable[[], ModelT],
    redactor: Redactor | None = None,
) -> AiOutcome[ModelT]:
    """Run one structured AI call with repair retry and fallback (STD-AI3).

    - ``provider`` is ``None`` → deterministic ``fallback()`` (``disabled``).
    - Prompt over the token budget → ``fallback()`` (``fallback``).
    - Parse failure → one repair retry naming field paths only, then
      ``fallback()`` (``fallback``).
    """
    active_redactor = redactor or Redactor()
    prompt = build_prompt(
        request.template,
        request.variables,
        redactor=active_redactor,
        allow_pii=request.allow_pii,
        system_addendum=request.system_addendum,
    )
    base_usage = AiUsage(
        provider=provider.name if provider is not None else "",
        model=provider.model if provider is not None else "",
        prompt_version=request.template.version,
        prompt_hash=prompt.prompt_hash,
    )
    if provider is None:
        return AiOutcome[ModelT](
            model="",
            prompt_version=request.template.version,
            prompt_hash=prompt.prompt_hash,
            ai_status="disabled",
            data=fallback(),
            usage=base_usage.model_copy(update={"status": "disabled"}),
        )
    prompt_tokens = estimate_tokens(prompt.system + prompt.text)
    if not within_budget(prompt_tokens, request.budget_tokens):
        return AiOutcome[ModelT](
            model=provider.model,
            prompt_version=request.template.version,
            prompt_hash=prompt.prompt_hash,
            ai_status="fallback",
            data=fallback(),
            usage=base_usage.model_copy(
                update={
                    "status": "fallback",
                    "input_tokens": prompt_tokens,
                    "note": "budget_exceeded",
                }
            ),
        )
    started = time.perf_counter()
    try:
        result = provider.complete_structured(
            prompt,
            schema,
            max_tokens=request.budget_tokens or 2000,
            temperature=request.temperature,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        usage = result.usage.model_copy(
            update={
                "prompt_version": request.template.version,
                "prompt_hash": prompt.prompt_hash,
                "status": "ok",
                "latency_ms": latency_ms,
            }
        )
        return AiOutcome[ModelT](
            model=provider.model,
            prompt_version=request.template.version,
            prompt_hash=prompt.prompt_hash,
            ai_status="ok",
            data=result.data,
            usage=usage,
        )
    except SchemaParseError as first_failure:
        repair_text = prompt.text + "\n\n" + repair_prompt_text(first_failure)
        repair = Prompt(
            feature=prompt.feature,
            version=prompt.version,
            schema_name=prompt.schema_name,
            system=prompt.system,
            text=repair_text,
        )
        try:
            raw_retry = provider.complete_raw(
                repair,
                max_tokens=request.budget_tokens or 2000,
                temperature=request.temperature,
            )
            data = parse_structured(raw_retry, schema)
            latency_ms = int((time.perf_counter() - started) * 1000)
            usage = AiUsage(
                provider=provider.name,
                model=provider.model,
                prompt_version=request.template.version,
                prompt_hash=prompt.prompt_hash,
                input_tokens=estimate_tokens(prompt.system + repair_text),
                output_tokens=estimate_tokens(raw_retry),
                estimated_cost_usd=estimate_cost_usd(
                    estimate_tokens(prompt.system + repair_text), estimate_tokens(raw_retry)
                ),
                latency_ms=latency_ms,
                status="repaired",
            )
            return AiOutcome[ModelT](
                model=provider.model,
                prompt_version=request.template.version,
                prompt_hash=prompt.prompt_hash,
                ai_status="repaired",
                data=data,
                usage=usage,
            )
        except (SchemaParseError, FakeProviderError, ProviderError):
            return AiOutcome[ModelT](
                model=provider.model,
                prompt_version=request.template.version,
                prompt_hash=prompt.prompt_hash,
                ai_status="fallback",
                data=fallback(),
                usage=base_usage.model_copy(
                    update={
                        "status": "fallback",
                        "input_tokens": prompt_tokens,
                        "note": "repair_failed",
                    }
                ),
            )
    except (FakeProviderError, ProviderError):
        return AiOutcome[ModelT](
            model=provider.model,
            prompt_version=request.template.version,
            prompt_hash=prompt.prompt_hash,
            ai_status="fallback",
            data=fallback(),
            usage=base_usage.model_copy(
                update={"status": "fallback", "input_tokens": prompt_tokens, "note": "call_failed"}
            ),
        )


__all__: list[str] = ["AiOutcome", "AiRequest", "run_ai"]
