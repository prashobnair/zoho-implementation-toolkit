"""Versioned prompt files with front-matter (STD-AI2).

Files live at ``src/zohokit/ai/prompts/<feature>/v1.md``::

    ---
    feature: explain
    version: v1
    schema: ExplainDraft
    owner: toolkit
    eval_suite: evals/explain
    ---
    <user template with {{ variables }}>

The prompt hash of the rendered prompt goes into every AI output for
traceability.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from zohokit.ai.providers import AiError

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

REQUIRED_FRONT_MATTER = ("feature", "version", "schema", "owner", "eval_suite")


class PromptFileError(AiError):
    """A prompt file is missing or malformed (file + key only, no content)."""


@dataclass(frozen=True)
class PromptTemplate:
    """A loaded prompt file: metadata plus the user template body."""

    feature: str
    version: str
    schema_name: str
    owner: str
    eval_suite: str
    body: str


def prompt_path(feature: str, version: str = "v1") -> Path:
    """Filesystem path of a versioned prompt file."""
    return PROMPTS_DIR / feature / f"{version}.md"


def load_template(feature: str, version: str = "v1") -> PromptTemplate:
    """Load and validate a prompt file; errors name the file and key."""
    path = prompt_path(feature, version)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        raise PromptFileError(f"prompt file missing: prompts/{feature}/{version}.md") from None
    if not text.startswith("---\n"):
        raise PromptFileError(f"prompt file prompts/{feature}/{version}.md lacks front-matter")
    try:
        _, header, body = text.split("---\n", 2)
    except ValueError:
        raise PromptFileError(
            f"prompt file prompts/{feature}/{version}.md has unclosed front-matter"
        ) from None
    try:
        meta = yaml.safe_load(header)
    except yaml.YAMLError:
        raise PromptFileError(
            f"prompt file prompts/{feature}/{version}.md has invalid front-matter"
        ) from None
    if not isinstance(meta, dict):
        raise PromptFileError(
            f"prompt file prompts/{feature}/{version}.md front-matter is not a mapping"
        ) from None
    for key in REQUIRED_FRONT_MATTER:
        if not meta.get(key):
            raise PromptFileError(
                f"prompt file prompts/{feature}/{version}.md misses front-matter key {key}"
            )
    if str(meta["feature"]) != feature or str(meta["version"]) != version:
        raise PromptFileError(
            f"prompt file prompts/{feature}/{version}.md front-matter names a "
            "different feature or version"
        )
    if not body.strip():
        raise PromptFileError(f"prompt file prompts/{feature}/{version}.md has an empty body")
    return PromptTemplate(
        feature=str(meta["feature"]),
        version=str(meta["version"]),
        schema_name=str(meta["schema"]),
        owner=str(meta["owner"]),
        eval_suite=str(meta["eval_suite"]),
        body=body.strip() + "\n",
    )


def render_template(body: str, variables: dict[str, str]) -> str:
    """Substitute ``{{ name }}`` placeholders; missing names fail loudly.

    Error messages name the variable only, never surrounding content.
    """
    rendered = body
    for name, value in variables.items():
        rendered = rendered.replace("{{ " + name + " }}", value)
    first_open = rendered.find("{{")
    if first_open != -1:
        close = rendered.find("}}", first_open)
        missing = rendered[first_open + 2 : close].strip() if close != -1 else "unknown"
        raise PromptFileError(f"prompt template misses variable {missing or 'unknown'}")
    return rendered


__all__: list[str] = [
    "PROMPTS_DIR",
    "PromptFileError",
    "PromptTemplate",
    "load_template",
    "prompt_path",
    "render_template",
]
