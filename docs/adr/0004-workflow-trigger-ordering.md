# ADR-0004: Zoho workflow trigger ordering is approximated

## Status

Accepted (2026-10-06, WP-17a).

## Context

`zohokit workflow simulate` (TK-WF-F1..F3) replays proposed CRM
automation offline against the intermediate language v2. Zoho executes
workflow rules inside its own engine: per-module trigger evaluation,
rule execution order, re-entrant firing on field updates, and scheduled
action timing are server internals. The v8 APIs expose rule
configuration (`execute_when`, `conditions`, action lists) but no
execution-order contract.

## Decision

The simulator uses a documented approximation:

1. Rules matching one event fire in `(priority, rule id)` order.
   `priority` defaults to 100; ties break on the rule ID so runs are
   byte-identical for the same input.
2. Field writes enqueue `record_edited` / `field_changed` /
   `stage_changed` follow-up events processed FIFO by `(day, seq)` on
   a virtual clock; timer rules (`scheduled`, `date_field_reached`)
   are pre-enqueued at their offset day.
3. Cycles are cut on first state-signature revisit (`cycle_detected`);
   external calls only reach the duplicate-detecting ledger
   (`external_actions: 0` always).

Real-rule import (`import_real`, TK-WF-F4/UC-WF-3) lists anything it
cannot represent as `unsupported_construct` instead of approximating
silently.

## Consequences

- Simulation traces are deterministic and safe to snapshot, but they
  are not a guarantee of Zoho's exact runtime order.
- The static linter (TK-WF-F4) reports `potential_loop` from the
  write-graph independent of ordering, so ordering drift cannot hide
  a loop.
- If Zoho documents an execution order later, this ADR is superseded
  and the simulator gains a conformance suite against it.
