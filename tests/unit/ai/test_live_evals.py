"""Live-eval refusal tests: without a key the script exits 1, never calling out."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent.parent


def _load_script() -> Any:
    path = ROOT / "scripts" / "run_live_evals.py"
    spec = importlib.util.spec_from_file_location("run_live_evals", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_live_evals_refused_without_key(capsys: Any) -> None:
    module = _load_script()
    assert module.main([], {}) == 1
    assert "no AI API key" in capsys.readouterr().out


def test_live_evals_refused_for_fake_provider() -> None:
    module = _load_script()
    assert module.main([], {"ZOHOKIT_AI_PROVIDER": "fake", "ZOHOKIT_AI_MODEL": "x"}) == 1


def test_refusal_echoes_no_values(capsys: Any) -> None:
    """The refusal names the missing configuration, never any value."""
    module = _load_script()
    module.main([], {"ZOHOKIT_AI_PROVIDER": "anthropic", "UNRELATED": "s3cr3t-value-999"})
    out = capsys.readouterr().out
    assert "s3cr3t-value-999" not in out
    assert module.NO_KEY_MESSAGE in out
