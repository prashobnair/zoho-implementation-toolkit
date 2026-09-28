# Modules

Eight checks, one report format. Each module reads one offline JSON input,
runs a pure engine, and emits findings with stable IDs plus a readiness flag.

| Module | Command | Answers |
|---|---|---|
| [Migration Preflight](migration.md) | `zohokit migration audit` | What breaks on import: orphans, duplicates, stage mapping. |
| [Release Readiness](release.md) | `zohokit release diff` | What a promotion changes: removals, behavior edits, missing deps. |
| [Workflow Lint & Simulator](workflow.md) | `zohokit workflow simulate` | What rules do on a record: traces, loops, duplicate follow-ups. |
| [Forms Parity](forms.md) | `zohokit forms parity` | Whether a rebuilt form matches the original on every case. |
| [Books Reconciliation](books.md) | `zohokit books reconcile` | Whether every deal has exactly one correct invoice. |
| [Metrics Contracts](metrics.md) | `zohokit metrics check` | Whether KPIs hold: joins, freshness, audience visibility. |
| [Client Timeline Composer](timeline.md) | `zohokit timeline compose` | One chronology with contradictions flagged, client-safe. |
| [Lead Routing Lab](lead_routing.md) | `zohokit lead-routing route` | Where each lead goes: consent, duplicates, queues. |

All finding codes are listed in [Finding codes](../finding-codes.md).
Third parties can add modules through the `zohokit.modules` entry-point
registry; they appear in `zohokit modules list` next to the built-ins.
