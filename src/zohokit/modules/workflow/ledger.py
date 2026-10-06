"""Side-effect ledger for simulated external calls (TK-WF-F3).

Every simulated ``send_email`` / ``webhook`` / ``create_task`` /
``function`` call is recorded here. A repeat with the same
``(record, action, template/url, day)`` key is a duplicate: the second
call is dropped and reported as ``duplicate_side_effect``. The report
always carries ``external_actions: 0`` — simulation never sends.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SideEffectLedger:
    """Deduplicating record of simulated external calls."""

    entries: list[dict[str, str | int]] = field(default_factory=list)
    _seen: set[tuple[str, str, str, int]] = field(default_factory=set)

    def record(
        self,
        *,
        record_id: str,
        action: str,
        template_or_url: str,
        day: int,
        rule_id: str = "",
    ) -> bool:
        """Record one simulated call; True when it is a duplicate.

        The duplicate key is ``(record, action, template/url, day)``;
        the rule ID rides along in the entry for the causal trace but
        never affects duplicate detection.
        """
        key = (record_id, action, template_or_url, day)
        if key in self._seen:
            self.entries.append(
                {
                    "record_id": record_id,
                    "action": action,
                    "template_or_url": template_or_url,
                    "day": day,
                    "rule_id": rule_id,
                    "duplicate": 1,
                }
            )
            return True
        self._seen.add(key)
        self.entries.append(
            {
                "record_id": record_id,
                "action": action,
                "template_or_url": template_or_url,
                "day": day,
                "rule_id": rule_id,
                "duplicate": 0,
            }
        )
        return False

    def duplicates(self) -> list[dict[str, str | int]]:
        """Entries flagged as duplicates (never sent, never applied)."""
        return [entry for entry in self.entries if entry.get("duplicate") == 1]


__all__: list[str] = ["SideEffectLedger"]
