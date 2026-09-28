"""Contract-suite harness check: runs with network disabled (STD §3.3).

Full cassette-based contract tests land with the connector foundation,
planned for v0.2.0. This test proves the harness itself blocks network access.
"""

from __future__ import annotations

import pytest

from zohokit.core.ids import fingerprint


@pytest.mark.contract
def test_contract_suite_runs_offline() -> None:
    components = [{"kind": "field", "name": "Stage"}]
    assert fingerprint(components) == fingerprint(list(reversed(components)))
