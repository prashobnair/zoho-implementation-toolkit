"""The gitleaks config allowlists exact fake strings in exact files only.

The global ``[allowlist]`` table combines ``paths`` OR ``regexes``, which
would allowlist both scanner-fixture test files entirely. The config must
instead use per-entry ``[[allowlists]]`` with ``condition = "AND"`` so
only the exact fake string inside that exact file is skipped. This test
parses ``.gitleaks.toml`` and asserts that structure.

The expected fake strings are assembled from fragments (never a single
literal) so this file itself cannot read as a leaked credential.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG = ROOT / ".gitleaks.toml"

SCAN_TEST = "tests/unit/test_cassette_scan.py"
QUALITY_TEST = "tests/unit/test_cassette_quality.py"


def _expected_oauth_regex() -> str:
    return "1000" + "\\." + "abcdef12" + "\\." + "34567890"


def _expected_token_regex() -> str:
    return "90c6" + "abcdef0123456789fc09f0" + "abcdef"


def _load() -> dict:
    with CONFIG.open("rb") as handle:
        return tomllib.load(handle)


def test_no_global_or_allowlist() -> None:
    """No top-level ``[allowlist]``: it would OR paths with regexes."""
    assert "allowlist" not in _load()


def test_allowlists_combine_path_and_regex_with_and() -> None:
    config = _load()
    assert config["extend"]["useDefault"] is True
    entries = config["allowlists"]
    assert isinstance(entries, list) and len(entries) == 2
    for entry in entries:
        assert entry["condition"] == "AND"
        assert isinstance(entry["paths"], list) and entry["paths"]
        assert isinstance(entry["regexes"], list) and entry["regexes"]


def test_each_fake_string_scoped_to_its_exact_file() -> None:
    entries = _load()["allowlists"]
    by_path = {tuple(entry["paths"]): list(entry["regexes"]) for entry in entries}
    assert by_path == {
        (SCAN_TEST.replace(".", "\\."),): [_expected_oauth_regex()],
        (QUALITY_TEST.replace(".", "\\."),): [_expected_token_regex()],
    }
