# Known issues

Deferred defects with a planned home. Nothing here blocks the current
release; each entry names the release that will fix it.

| ID | Modules | Issue | Impact | Planned fix |
|---|---|---|---|---|
| KI-001 | lead_routing | Duplicate findings land on whichever record appears second (first-seen survivor selection is input-order dependent). Finding IDs themselves are stable for a fixed input order. | Baseline suppression and diff-reports key on stable IDs, so a reordered input can shift which record carries the duplicate finding. | lead-routing backtest (planned). Note: the migration preflight duplicate clusters (`fuzzy_duplicate_cluster`) are already deterministic — content-keyed rows, earliest-created-time survivor, order-independent IDs (shuffle property-tested) — so migration is out of scope for this issue. |
