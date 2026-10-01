"""STD-L6: response cache under the user cache dir, 0600, 24h TTL, purge."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from zohokit.connectors.zoho.cache import DEFAULT_TTL_SECONDS, ResponseCache


def test_ttl_is_24h() -> None:
    assert DEFAULT_TTL_SECONDS == 24 * 3600


def test_put_get_roundtrip(tmp_path: Path) -> None:
    cache = ResponseCache(base=tmp_path)
    cache.put("/crm/v8/org", None, {"id": "555000111"})
    assert cache.get("/crm/v8/org", None) == {"id": "555000111"}
    assert cache.get("/crm/v8/Leads", None) is None


def test_expiry_with_injected_clock(tmp_path: Path) -> None:
    now = [1_000_000.0]
    cache = ResponseCache(base=tmp_path, clock=lambda: now[0])
    cache.put("/crm/v8/org", None, {"id": "555000111"})
    now[0] += 24 * 3600 + 1
    assert cache.get("/crm/v8/org", None) is None
    assert list(tmp_path.glob("*.json")) == []


def test_params_are_part_of_the_key(tmp_path: Path) -> None:
    cache = ResponseCache(base=tmp_path)
    cache.put("/crm/v8/Leads", {"page": "1"}, {"page": 1})
    assert cache.get("/crm/v8/Leads", {"page": "2"}) is None
    assert cache.get("/crm/v8/Leads", {"page": "1"}) == {"page": 1}


def test_purge_removes_everything(tmp_path: Path) -> None:
    cache = ResponseCache(base=tmp_path)
    cache.put("/a", None, {"a": 1})
    cache.put("/b", None, {"b": 2})
    assert cache.purge() == 2
    assert cache.purge() == 0


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits are not enforced on Windows")
def test_cache_files_are_owner_only(tmp_path: Path) -> None:
    cache = ResponseCache(base=tmp_path)
    written = cache.put("/crm/v8/org", None, {"id": "555000111"})
    mode = stat.S_IMODE(written.stat().st_mode)
    assert mode == 0o600
