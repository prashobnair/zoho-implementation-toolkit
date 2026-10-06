# Known issues

Deferred defects with a planned home. Nothing here blocks the current
release; each entry names the release that will fix it.

| ID | Modules | Issue | Impact | Planned fix |
|---|---|---|---|---|
| KI-001 | migration audit (legacy-v1 parity path), lead_routing | Duplicate findings land on whichever record appears second (first-seen survivor selection is input-order dependent): `migration audit` `possible_duplicate` (legacy-v1 parity, golden-locked) and lead-routing duplicates. Finding IDs themselves are stable for a fixed input order. | Baseline suppression and diff-reports key on stable IDs, so a reordered input can shift which record carries the duplicate finding. | lead-routing backtest (planned); the legacy audit path stays parity-locked. Note: the new `migration preflight` duplicate clusters (`fuzzy_duplicate_cluster`) are deterministic — content-keyed rows, earliest-created-time survivor, order-independent IDs (shuffle property-tested). |
