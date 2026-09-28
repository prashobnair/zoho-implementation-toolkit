# ADR-0003: COQL disabled

- Status: accepted
- Date: 2026-09-27

## Context

Zoho's COQL `SELECT` endpoint requires POST, which conflicts with the
GET-only guard (maintainer decision: all Zoho traffic stays GET-only).

## Decision

COQL is disabled. Record reads use GET search endpoints only.

## Consequences

Recorded in `docs/API_CONTRACTS.md` when the connector foundation lands
(planned for v0.2.0). Revisit only via an owner-approved ADR with a
parser-validated `SELECT`-only allowlist.
