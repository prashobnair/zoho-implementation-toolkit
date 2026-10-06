"""Provider tests (STD-AI1): FakeProvider replays; network adapters stay out of tests.

Only ``FakeProvider`` is exercised here. The network adapters
(``AnthropicProvider``, ``OpenAICompatibleProvider``) are never
instantiated in tests, so no test can trigger a network call. Their
construction guards are covered indirectly through ``build_provider``,
which returns ``None`` unless a key, model (and base URL) are configured.
"""

from __future__ import annotations

import os

import pytest
from pydantic import BaseModel

from zohokit.ai.models import AiConfig, Prompt
from zohokit.ai.providers import (
    FakeProvider,
    FakeProviderError,
    SchemaParseError,
    build_provider,
    parse_structured,
    read_api_key,
    repair_prompt_text,
)


class _Item(BaseModel):
    name: str


def _prompt(text: str = "hello") -> Prompt:
    return Prompt(
        feature="explain",
        version="v1",
        schema_name="_Item",
        system="system statement",
        text=text,
    )


def test_fake_provider_replays_by_prompt_hash() -> None:
    prompt = _prompt()
    provider = FakeProvider({prompt.prompt_hash: '{"name": "ok"}'}, model="fake-test")
    result = provider.complete_structured(prompt, _Item, max_tokens=50)
    assert result.data == _Item(name="ok")
    assert result.usage.prompt_hash == prompt.prompt_hash
    assert result.usage.prompt_version == "v1"
    assert result.usage.status == "ok"
    assert result.usage.model == "fake-test"


def test_fake_provider_missing_recording_is_a_clear_error() -> None:
    provider = FakeProvider({}, model="fake-test")
    prompt = _prompt("unrecorded")
    with pytest.raises(FakeProviderError) as excinfo:
        provider.complete_raw(prompt, max_tokens=50)
    assert prompt.prompt_hash in str(excinfo.value)


def test_parse_structured_error_is_value_free() -> None:
    sneaky = "secret-spill-811213@example.invalid"
    with pytest.raises(SchemaParseError) as excinfo:
        parse_structured(f'{{"name": 123, "leak": "{sneaky}"}}', _Item)
    message = str(excinfo.value)
    assert sneaky not in message
    assert "_Item" in message


def test_repair_text_names_fields_not_values() -> None:
    failure = SchemaParseError("_Item", 2, "name")
    text = repair_prompt_text(failure)
    assert "name" in text
    assert "secret-spill" not in text


def test_build_provider_returns_none_without_key_or_model() -> None:
    assert build_provider(AiConfig()) is None
    assert build_provider(AiConfig(provider="anthropic")) is None
    assert build_provider(AiConfig(provider="anthropic", model="m")) is None
    assert (
        build_provider(AiConfig(provider="openai-compatible", model="m", has_api_key=True)) is None
    )


def test_read_api_key_never_logged_only_returned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ZOHOKIT_AI_API_KEY", "test-key-value")
    assert read_api_key("anthropic") == "test-key-value"
    monkeypatch.delenv("ZOHOKIT_AI_API_KEY")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fallback-key-value")
    assert read_api_key("anthropic") == "fallback-key-value"


def test_ai_config_from_env() -> None:
    env = {
        "ZOHOKIT_AI_PROVIDER": "anthropic",
        "ZOHOKIT_AI_MODEL": "config-model",
        "ZOHOKIT_AI_API_KEY": "k",
        "ZOHOKIT_AI_MAX_TOKENS": "777",
    }
    config = AiConfig.from_env(env)
    assert config.provider == "anthropic"
    assert config.model == "config-model"
    assert config.is_configured
    assert config.max_tokens == 777
    assert AiConfig.from_env({}).is_configured is False
    assert os.environ.get("NEVER_SET_ZOHOKIT") is None


def test_network_adapters_never_instantiated_in_tests() -> None:
    """Guard: no test file may construct a network provider (no network calls)."""
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent.parent
    offenders = []
    markers = ["Anthropic" + "Provider(", "OpenAICompatible" + "Provider("]
    candidates = sorted((root / "unit").rglob("test_*.py"))
    if (root / "eval").exists():
        candidates += sorted((root / "eval").rglob("test_*.py"))
    for path in candidates:
        text = path.read_text(encoding="utf-8")
        for marker in markers:
            if marker in text:
                offenders.append(f"{path.name}: {marker}")
    assert not offenders, f"network provider constructed in tests: {offenders}"
