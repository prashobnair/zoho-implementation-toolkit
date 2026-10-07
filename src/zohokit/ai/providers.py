"""LLM providers: protocol, FakeProvider, Anthropic, OpenAI-compatible (STD-AI1).

Only :class:`FakeProvider` is ever used in tests and CI: it replays
hand-authored synthetic recordings keyed by prompt hash and raises a
clear error when a recording is missing, so a test can never trigger a
network call. The network providers are constructed only from
:class:`AiConfig` (model name from config, never hardcoded) and only on
real user invocations.
"""

from __future__ import annotations

import os
import time
from collections.abc import Mapping
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from zohokit.ai.models import AiConfig, AiUsage, Prompt, StructuredResult
from zohokit.ai.usage import estimate_cost_usd, estimate_tokens

ModelT = TypeVar("ModelT", bound=BaseModel)


class AiError(ValueError):
    """Base AI failure. Messages are value-free: hashes, counts and field
    paths only, never prompt or response content (which may carry data)."""


class AiConfigError(AiError):
    """Missing provider configuration or missing optional dependency."""


class FakeProviderError(AiError):
    """A FakeProvider recording is missing (never a network call)."""


class ProviderError(AiError):
    """A network provider call failed (endpoint + status only)."""


class SchemaParseError(AiError):
    """A provider response did not parse into its schema.

    Carries the schema name, the error count and the first field path so
    the pipeline can build one repair retry without echoing values.
    """

    def __init__(self, schema_name: str, error_count: int, first_field: str) -> None:
        super().__init__(
            f"response failed {schema_name} validation "
            f"({error_count} error(s), first at {first_field})"
        )
        self.schema_name = schema_name
        self.error_count = error_count
        self.first_field = first_field


def parse_structured(raw: str, schema: type[ModelT]) -> ModelT:
    """Parse *raw* into *schema*; raise value-free :class:`SchemaParseError`."""
    try:
        return schema.model_validate_json(raw)
    except ValidationError as exc:
        errors = exc.errors(include_input=False, include_url=False)
        first: dict[str, Any] = dict(errors[0]) if errors else {}
        loc = first.get("loc", ())
        field = ".".join(str(step) for step in loc) or "(root)"
        raise SchemaParseError(schema.__name__, len(errors), field) from None


def repair_prompt_text(failure: SchemaParseError) -> str:
    """One repair instruction naming field paths and error types only."""
    return (
        "The previous response failed validation: "
        f"{failure.error_count} error(s), first at {failure.first_field}. "
        "Return valid JSON matching the schema, and nothing else."
    )


class LLMProvider(Protocol):
    """Structured completion contract every provider honors (STD-AI1)."""

    @property
    def name(self) -> str:
        """Provider key (never a secret)."""
        ...  # pragma: no cover - protocol

    @property
    def model(self) -> str:
        """Model name from configuration, never hardcoded."""
        ...  # pragma: no cover - protocol

    def complete_raw(self, prompt: Prompt, *, max_tokens: int, temperature: float = 0.0) -> str:
        """Return the raw response text for *prompt* (parsed by the caller)."""
        ...  # pragma: no cover - protocol

    def complete_structured(
        self,
        prompt: Prompt,
        schema: type[ModelT],
        *,
        max_tokens: int,
        temperature: float = 0.0,
    ) -> StructuredResult:
        """Complete *prompt* and parse the response into *schema*."""
        ...  # pragma: no cover - protocol


class FakeProvider:
    """Deterministic replay for tests, evals and offline runs (STD-AI1).

    ``recordings`` maps prompt hash → raw recorded response. A missing
    recording raises :class:`FakeProviderError` naming the hash; it never
    touches the network. Recordings are hand-authored synthetic data,
    never model outputs.
    """

    name = "fake"

    def __init__(self, recordings: Mapping[str, str], *, model: str) -> None:
        self._recordings = dict(recordings)
        self._model = model

    @property
    def model(self) -> str:
        """The configured fake model label (from config, never hardcoded)."""
        return self._model

    def complete_raw(self, prompt: Prompt, *, max_tokens: int, temperature: float = 0.0) -> str:
        """Replay the recording for ``prompt.prompt_hash`` (or fail loudly)."""
        _ = max_tokens
        _ = temperature
        try:
            return self._recordings[prompt.prompt_hash]
        except KeyError:
            raise FakeProviderError(
                f"no recording for prompt hash {prompt.prompt_hash} "
                f"(feature {prompt.feature} {prompt.version}); "
                "author one instead of calling a network provider"
            ) from None

    def complete_structured(
        self,
        prompt: Prompt,
        schema: type[ModelT],
        *,
        max_tokens: int,
        temperature: float = 0.0,
    ) -> StructuredResult:
        """Replay the recording for ``prompt.prompt_hash`` and parse it."""
        started = time.perf_counter()
        raw = self.complete_raw(prompt, max_tokens=max_tokens, temperature=temperature)
        data = parse_structured(raw, schema)
        latency_ms = int((time.perf_counter() - started) * 1000)
        usage = AiUsage(
            provider=self.name,
            model=self._model,
            prompt_version=prompt.version,
            prompt_hash=prompt.prompt_hash,
            input_tokens=estimate_tokens(prompt.system + prompt.text),
            output_tokens=estimate_tokens(raw),
            estimated_cost_usd=0.0,
            latency_ms=latency_ms,
            status="ok",
        )
        return StructuredResult(raw=raw, data=data, usage=usage)


def read_api_key(provider: str) -> str:
    """Read the API key for *provider* (value never logged or stored)."""
    key = os.environ.get("ZOHOKIT_AI_API_KEY", "")
    if not key and provider == "anthropic":
        key = os.environ.get("ANTHROPIC_API_KEY", "")
    return key


def build_provider(config: AiConfig) -> LLMProvider | None:
    """Build the configured network provider, or None when disabled.

    Returns None when no provider is fully configured (no key, no model,
    or the ``fake`` provider, whose recordings are supplied by tests and
    evals directly). Callers run their deterministic path and report
    ``AI disabled`` in that case (STD-AI4).
    """
    provider_name = config.provider
    if provider_name == "anthropic" and config.model and config.has_api_key:
        return AnthropicProvider(api_key=read_api_key("anthropic"), model=config.model)
    if (
        provider_name == "openai-compatible"
        and config.model
        and config.base_url
        and config.has_api_key
    ):
        return OpenAICompatibleProvider(
            api_key=read_api_key("openai-compatible"),
            model=config.model,
            base_url=config.base_url,
        )
    return None


class AnthropicProvider:
    """Default network adapter, used only with explicit user configuration.

    Requires the ``[ai]`` extra (the Anthropic SDK) and an API key. Never
    instantiated in tests.
    """

    name = "anthropic"

    def __init__(self, *, api_key: str, model: str) -> None:
        if not api_key:
            raise AiConfigError("anthropic provider needs an API key (never logged)")
        if not model:
            raise AiConfigError("anthropic provider needs a model name from config")
        self._api_key = api_key
        self._model = model

    @property
    def model(self) -> str:
        """The configured model name."""
        return self._model

    def complete_raw(self, prompt: Prompt, *, max_tokens: int, temperature: float = 0.0) -> str:
        """Call the messages API and return the concatenated text.

        The locked SDK (anthropic 1.11.0) types ``messages.create``
        without a ``temperature`` field, so the caller's temperature is
        accepted for protocol compatibility but never forwarded.
        """
        try:
            import anthropic
        except ImportError:
            raise AiConfigError(
                "anthropic provider needs the [ai] extra: pip install zohokit[ai]"
            ) from None
        client = anthropic.Anthropic(api_key=self._api_key)
        try:
            response = client.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                system=prompt.system,
                messages=[{"role": "user", "content": prompt.text}],
            )
        except Exception as exc:
            raise ProviderError(f"anthropic request failed: {type(exc).__name__}") from None
        chunks: list[str] = []
        for block in response.content:
            text = getattr(block, "text", None)
            if isinstance(text, str):
                chunks.append(text)
        return "".join(chunks)

    def complete_structured(
        self,
        prompt: Prompt,
        schema: type[ModelT],
        *,
        max_tokens: int,
        temperature: float = 0.0,
    ) -> StructuredResult:
        """Call the messages API and parse the text into *schema*."""
        started = time.perf_counter()
        raw = self.complete_raw(prompt, max_tokens=max_tokens, temperature=temperature)
        data = parse_structured(raw, schema)
        latency_ms = int((time.perf_counter() - started) * 1000)
        usage = AiUsage(
            provider=self.name,
            model=self._model,
            prompt_version=prompt.version,
            prompt_hash=prompt.prompt_hash,
            input_tokens=estimate_tokens(prompt.system + prompt.text),
            output_tokens=estimate_tokens(raw),
            estimated_cost_usd=estimate_cost_usd(
                estimate_tokens(prompt.system + prompt.text), estimate_tokens(raw)
            ),
            latency_ms=latency_ms,
            status="ok",
        )
        return StructuredResult(raw=raw, data=data, usage=usage)


class OpenAICompatibleProvider:
    """Optional adapter for any OpenAI-compatible chat endpoint (STD-AI1).

    Uses httpx only (no extra dependency). Never instantiated in tests.
    """

    name = "openai-compatible"

    def __init__(self, *, api_key: str, model: str, base_url: str) -> None:
        if not api_key:
            raise AiConfigError("openai-compatible provider needs an API key (never logged)")
        if not model:
            raise AiConfigError("openai-compatible provider needs a model name from config")
        if not base_url:
            raise AiConfigError("openai-compatible provider needs a base URL from config")
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")

    @property
    def model(self) -> str:
        """The configured model name."""
        return self._model

    def complete_raw(self, prompt: Prompt, *, max_tokens: int, temperature: float = 0.0) -> str:
        """POST to ``{base_url}/chat/completions`` and return the text."""
        import httpx

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": prompt.system},
                {"role": "user", "content": prompt.text},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }
        try:
            response = httpx.post(
                f"{self._base_url}/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=60.0,
            )
        except Exception as exc:  # pragma: no cover - network edge
            raise ProviderError(f"openai-compatible request failed: {type(exc).__name__}") from None
        if response.status_code >= 400:
            raise ProviderError(
                f"openai-compatible endpoint returned status {response.status_code}"
            )
        try:
            body = response.json()
            return str(body["choices"][0]["message"]["content"])
        except (ValueError, KeyError, IndexError, TypeError):
            raise ProviderError("openai-compatible endpoint returned an unexpected shape") from None

    def complete_structured(
        self,
        prompt: Prompt,
        schema: type[ModelT],
        *,
        max_tokens: int,
        temperature: float = 0.0,
    ) -> StructuredResult:
        """POST to ``{base_url}/chat/completions`` and parse the reply."""
        started = time.perf_counter()
        raw = self.complete_raw(prompt, max_tokens=max_tokens, temperature=temperature)
        data = parse_structured(raw, schema)
        latency_ms = int((time.perf_counter() - started) * 1000)
        in_tokens = estimate_tokens(prompt.system + prompt.text)
        out_tokens = estimate_tokens(raw)
        usage = AiUsage(
            provider=self.name,
            model=self._model,
            prompt_version=prompt.version,
            prompt_hash=prompt.prompt_hash,
            input_tokens=in_tokens,
            output_tokens=out_tokens,
            estimated_cost_usd=estimate_cost_usd(in_tokens, out_tokens),
            latency_ms=latency_ms,
            status="ok",
        )
        return StructuredResult(raw=raw, data=data, usage=usage)


__all__: list[str] = [
    "AiConfigError",
    "AiError",
    "AnthropicProvider",
    "FakeProvider",
    "FakeProviderError",
    "LLMProvider",
    "OpenAICompatibleProvider",
    "ProviderError",
    "SchemaParseError",
    "build_provider",
    "parse_structured",
    "read_api_key",
    "repair_prompt_text",
]
