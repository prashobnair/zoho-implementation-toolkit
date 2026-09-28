# Client Timeline Composer (`timeline`)

Compose one chronological client history with contradictions flagged — and
prove the client view leaks nothing internal.

## The problem

"The client remembers go-live as Feb 1, our notes say Feb 15, and the deal
says something else. Before the QBR we need one chronology with the conflict
on the table — and nothing internal leaking into the client view." — Marigold
Labs, account manager.

## What it does

- Orders events timezone-aware and detects claim conflicts with typed
  normalization, so `Feb 1` vs `01-Feb` vs `2026-02-01` compare as dates, not
  strings (`conflicting_claims`).
- Filters by audience *before* conflict detection, so an internal claim can
  never leak into the client view through a finding.
- Keeps occurrence time distinct from record time, and provenance on every event.

## Quickstart

```sh
uv run zohokit timeline compose events.json
uv run zohokit timeline compose events.json --audience client
```

## How it works

The pure engine composes one offline event list for the chosen audience and
emits findings with stable IDs; the run is not ready while conflicts remain.
Render with `--format json|table|markdown|html` and write to a file with
`--out`.

## Finding codes

| Code | Severity | Meaning |
|---|---|---|
| `conflicting_claims` | error | Differing normalized values share a normalized claim key. |

## Scope & safety

> This module composes offline events for one audience: it never connects to
> Zoho, never sends the timeline to anyone, and never picks a winner between
> conflicting claims — a reviewer resolves those. The client view is safe to
> share only after every conflict is reviewed.
