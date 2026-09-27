# ADR-0002: GET-only guard

- Status: accepted
- Date: 2026-09-27

## Context

Live Zoho access is read-only by program decision (D1).

## Decision

All Zoho traffic goes through one `ZohoClient` whose transport rejects any
method other than GET (and HEAD) before the request leaves the process,
raising `SafetyGuardError` (exit 4). Disguised writes
(`X-HTTP-Method-Override`, `_method` params) are rejected too (STD-L1).

## Consequences

Anything that would write becomes a dry-run plan artifact (STD-W1/W2).
