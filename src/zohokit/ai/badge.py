"""AI badge: every AI-produced item is visually distinct (STD-AI §5.4)."""

from __future__ import annotations

#: Shared badge CSS for AI suggestion markers in HTML outputs.
AI_BADGE_CSS = (
    ".ai-badge{display:inline-block;padding:0.1em 0.5em;margin-left:0.5em;"
    "border:1px solid #8a6d00;border-radius:0.75em;background:#fff3bf;color:#5c3d00;"
    "font-size:0.8em;font-weight:bold;white-space:nowrap;}"
)


def ai_badge_html(confidence: float | None) -> str:
    """An "AI suggestion" badge with confidence when the item carries one."""
    if confidence is None:
        return '<span class="ai-badge">AI suggestion</span>'
    return f'<span class="ai-badge">AI suggestion · {confidence:.2f}</span>'


__all__: list[str] = ["AI_BADGE_CSS", "ai_badge_html"]
