"""Re-record eval responses with the real provider (manual owner step only).

Runs only via the ``evals-live`` workflow (workflow_dispatch, protected
environment). Refuses with exit 1 when no API key exists — the harness
never calls a provider without one. With a key, it replays every eval
case prompt through the configured provider and writes the fresh
responses under ``.scratch/live-recordings/`` (gitignored scratch for
local comparison only). Committed recordings stay hand-authored
synthetic; live output is never committed from CI.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from zohokit.ai.evalharness import load_dataset  # noqa: E402
from zohokit.ai.models import AiConfig  # noqa: E402
from zohokit.ai.prompts import load_template  # noqa: E402
from zohokit.ai.providers import build_provider  # noqa: E402
from zohokit.ai.redaction import build_prompt  # noqa: E402
from zohokit.core.redact import Redactor  # noqa: E402

#: Value-free refusal: names the missing configuration, never key material.
NO_KEY_MESSAGE = "live evals refused: no AI API key configured"


def _metrics_for(feature: str):  # type: ignore[no-untyped-def]
    import importlib

    return importlib.import_module(f"evals.{feature}.metrics")


def main(argv: Sequence[str] | None = None, env: dict[str, str] | None = None) -> int:
    """Entry point returning an exit code (0 recorded, 1 refused)."""
    parser = argparse.ArgumentParser(description="Re-record eval responses with a live provider.")
    parser.add_argument("--features", nargs="*", default=["explain", "mapping", "transform"])
    args = parser.parse_args(argv)
    source = env if env is not None else os.environ
    config = AiConfig.from_env(dict(source))
    provider = build_provider(config)
    if provider is None:
        print(NO_KEY_MESSAGE)
        return 1
    out_dir = ROOT / ".scratch" / "live-recordings"
    out_dir.mkdir(parents=True, exist_ok=True)
    for feature in args.features:
        metrics = _metrics_for(feature)
        template = load_template(feature)
        cases = load_dataset(ROOT / "evals" / feature / "dataset.jsonl")
        collected = {}
        for case in cases:
            prompt = build_prompt(template, metrics.case_variables(case), redactor=Redactor())
            raw = provider.complete_raw(prompt, max_tokens=config.max_tokens, temperature=0.0)
            collected[prompt.prompt_hash] = raw
        out_path = out_dir / f"{feature}.json"
        with open(out_path, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(collected, handle, indent=2, sort_keys=True)
            handle.write("\n")
        print(f"{feature}: re-recorded {len(collected)} responses to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
