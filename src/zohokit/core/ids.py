"""Stable identities and fingerprints (TK-CORE-2, TK-FIX-1).

Identities hash ``(module, code, entity, entity_id, discriminator)`` and never
include mutable values, so re-running a report keeps finding IDs stable.
Fingerprints sort components by ``(kind, name)`` first, so list order can
never change the hash.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

FINDING_ID_LENGTH = 24


def canonical_json(value: Any) -> str:
    """Render canonical JSON: sorted keys, no insignificant whitespace."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def finding_id(
    module: str,
    code: str,
    entity: str,
    entity_id: str,
    discriminator: str = "",
) -> str:
    """Return the stable 24-char finding identity."""
    payload = "\n".join([module, code, entity, entity_id, discriminator])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:FINDING_ID_LENGTH]


def fingerprint(components: list[dict[str, Any]]) -> str:
    """Hash release components independent of input order (TK-FIX-1)."""
    ordered = sorted(
        components, key=lambda item: (str(item.get("kind", "")), str(item.get("name", "")))
    )
    return hashlib.sha256(canonical_json(ordered).encode("utf-8")).hexdigest()
