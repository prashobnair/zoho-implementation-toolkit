"""Connector error types with stable CLI exit codes (STD §3.5)."""

from __future__ import annotations


class SafetyGuardError(RuntimeError):
    """A blocked write attempt: exit 4 (STD-L1)."""

    exit_code = 4


class ContractDriftError(RuntimeError):
    """A response that no longer matches its contract: exit 3 (STD-H3)."""

    exit_code = 3

    def __init__(self, endpoint: str, message: str) -> None:
        super().__init__(f"contract_drift at {endpoint}: {message}")
        self.endpoint = endpoint


class ConnectorError(RuntimeError):
    """Auth, network or budget failure reaching Zoho: exit 3."""

    exit_code = 3


__all__: list[str] = ["ConnectorError", "ContractDriftError", "SafetyGuardError"]
