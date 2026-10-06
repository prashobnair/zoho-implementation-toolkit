"""Token accounting and the ``--ai-max-tokens`` budget (STD-AI9)."""

from __future__ import annotations

import os


def estimate_tokens(text: str) -> int:
    """Heuristic token count (4 chars per token, minimum 1)."""
    return max(1, len(text) // 4)


def estimate_cost_usd(input_tokens: int, output_tokens: int) -> float:
    """Cost estimate from configured per-1k rates (0.0 when unconfigured).

    Rates come from ``ZOHOKIT_AI_PRICE_PER_1K_USD`` (``in,out`` pair) so no
    model pricing is hardcoded. Real providers overwrite usage with metered
    counts where the API returns them.
    """
    raw = os.environ.get("ZOHOKIT_AI_PRICE_PER_1K_USD", "").strip()
    try:
        in_rate, _, out_rate = raw.partition(",")
        in_price = float(in_rate) if in_rate.strip() else 0.0
        out_price = float(out_rate) if out_rate.strip() else 0.0
    except ValueError:
        in_price, out_price = 0.0, 0.0
    return round((input_tokens / 1000) * in_price + (output_tokens / 1000) * out_price, 6)


def within_budget(prompt_tokens: int, budget: int | None) -> bool:
    """True when the estimated prompt fits the ``--ai-max-tokens`` budget."""
    if budget is None:
        return True
    return prompt_tokens <= budget


__all__: list[str] = ["estimate_cost_usd", "estimate_tokens", "within_budget"]
