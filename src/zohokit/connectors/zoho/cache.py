"""On-disk GET response cache: user cache dir, 0600 perms, 24h TTL (STD-L6)."""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable
from pathlib import Path

DEFAULT_TTL_SECONDS = 24 * 3600


def cache_dir(base: Path | None = None) -> Path:
    """User cache dir for responses (overridable for tests)."""
    if base is not None:
        return base
    home = Path.home()
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA", str(home / "AppData" / "Local")))
        return root / "zohokit" / "Cache"
    if sys_platform() == "darwin":
        return home / "Library" / "Caches" / "zohokit"
    return Path(os.environ.get("XDG_CACHE_HOME", str(home / ".cache"))) / "zohokit"


def sys_platform() -> str:
    """Importable platform hook so tests can pin the branch."""
    import sys

    return sys.platform


def _key(path: str, params: dict[str, str] | None) -> str:
    payload = json.dumps({"path": path, "params": params or {}}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


class ResponseCache:
    """Small file cache: one JSON file per key with an expiry timestamp."""

    def __init__(
        self,
        base: Path | None = None,
        *,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._dir = cache_dir(base)
        self._ttl = ttl_seconds
        self._clock = clock or time.time
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self._dir / f"{key}.json"

    def get(self, path: str, params: dict[str, str] | None = None) -> dict[str, object] | None:
        """Return the cached payload, or None on a miss or expiry."""
        file = self._path(_key(path, params))
        if not file.exists():
            return None
        try:
            envelope = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if self._clock() > float(envelope.get("expires_at", 0)):
            try:
                file.unlink()
            except OSError:
                pass
            return None
        payload = envelope.get("payload")
        return payload if isinstance(payload, dict) else None

    def put(self, path: str, params: dict[str, str] | None, payload: dict[str, object]) -> Path:
        """Store *payload* with 0600 permissions (owner read/write only)."""
        file = self._path(_key(path, params))
        envelope = {"expires_at": self._clock() + self._ttl, "payload": payload}
        file.write_text(json.dumps(envelope), encoding="utf-8")
        try:
            os.chmod(file, 0o600)
        except OSError:
            pass
        return file

    def purge(self) -> int:
        """Remove every cached entry; returns the number of files removed."""
        removed = 0
        for file in sorted(self._dir.glob("*.json")):
            try:
                file.unlink()
                removed += 1
            except OSError:
                continue
        return removed

    @property
    def directory(self) -> Path:
        """Where entries live (for status output)."""
        return self._dir


__all__: list[str] = ["DEFAULT_TTL_SECONDS", "ResponseCache", "cache_dir"]
