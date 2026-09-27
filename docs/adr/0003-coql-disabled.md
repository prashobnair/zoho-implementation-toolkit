# ADR-0003: COQL disabled

- Status: accepted
- Date: 2026-09-27

## Context

Zoho's COQL `SELECT` endpoint requires POST, which conflicts with the
GET-only guard (program decision D1; WP-01 decision 1).

## Decision

COQL is disabled. Record reads use GET search endpoints only.

## Consequences

Recorded in `docs/API_CONTRACTS.md` when the connector foundation lands
(WP-12). Revisit only via an owner-approved ADR with a
parser-validated `SELECT`-only allowlist.
