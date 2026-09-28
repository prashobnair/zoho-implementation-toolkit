# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### 0.1.0 in short (first release)

- One CLI, `zohokit`, over 8 ported Zoho helpers: migration audit, release
  diff, workflow simulation, forms parity, books reconciliation, metrics
  checks, timeline composition and lead routing — all offline, all byte-equal
  to the original tools on 37 captured outputs except documented fixes.
- One report envelope (JSON/table/Markdown/HTML) with stable finding IDs,
  a readiness flag and strict exit codes; every input/output model ships a
  versioned JSON Schema under `schemas/`.
- Docs site with a page per module and a full finding-code index; unavailable
  flags (`--live`, `--profile`, `--ai`, `--baseline`, `--max-api-calls`) fail
  loudly with the release that unlocks them. No live mode, no writes, no
  sends.
- Fixed during the port, each with a regression test: order-free release
  fingerprints; books row-level amount errors; metrics duplicate IDs and
  staff-hours validation; forms hidden-parent visibility and output-difference
  (`parity_mismatch`) findings; timeline claim normalization.

### Added

- WP-05 scaffold: `zohokit` package skeleton, shared-core modules, minimal CLI.
- Legacy history for all 8 `zoho-*` repos under `legacy/<name>/` (TK-MIG-1).
- Import-linter contracts enforcing TK-ARCH-3 (modules independent, core pure).
- CI pipeline per `specs/01` §3.3 (lint, test, contract, ai-evals, demo, security, docker, pages).
- Legacy golden outputs for all 8 modules under `tests/golden/legacy/` (TK-MIG-2).
- Shared core v1: full finding/report envelope, stable identities, money/time/graph/plan utilities, JSON/table/Markdown/HTML renderers, exit codes (TK-CORE-1, 2, 4, 5, 6, 7, TK-CORE-8 partial).
- Ported release, migration, workflow and forms with WP-06 golden parity (TK-MIG-3, TK-MIG-4; TK-FIX-1, TK-FIX-5, TK-FIX-7).
- Intentional parity differences (TK-FIX-1): release `target_manifest_sha256` is now order-free, e.g. `01_examples.json` changed `0e1aabe6…` → `ca3d3e6e…`; all other release goldens likewise. No forms golden changed (TK-FIX-5 only affects chained visibility, absent from fixtures).
- Ported books, metrics, timeline and lead_routing with WP-06 golden parity (TK-MIG-3, TK-MIG-4; TK-FIX-2, TK-FIX-3, TK-FIX-4, TK-FIX-6).
- Intentional parity differences: `metrics/05_invalid_utilization.json` gains `invalid_staff_row` for s-1 and drops `invalid_utilization` (valid rows now aggregate to 50.00%) via TK-FIX-4; all other books/metrics/timeline/lead_routing goldens byte-equal.
- Stable finding identities: discriminators now come from identifying input data (row IDs, field/case names, components), never positions; forms surfaces legacy case issues as findings (TK-CORE-2).
- Forms parity semantics: case issues identical on source and target are info (not blocking); only a source/target difference blocks; ready follows legacy all_pass. CLI exit codes match legacy on all 37 golden inputs (CLI parity test).
- Forms output differences now surface as `parity_mismatch` (error) findings, one per differing case/field with both values as evidence; new invariant: a not-ready report always carries an error/review finding.
- Unified CLI (TK-X-1): global `--live/--profile/--format/--out/--strict/--ai/--baseline/--max-api-calls` on every command; future features fail loudly with their release version; shell completion via `--show-completion`; `--help` snapshots for the root and all 8 modules.
- Plugin registry (TK-ARCH-4): third-party modules register via the `zohokit.modules` entry-point group and appear in `zohokit modules list`.
- JSON Schemas (TK-ARCH-5): `schemas/<module>/input.v1.json` and `report.v1.json` via `make schemas`; CI fails when stale.
- Docs (TK-MIG-7): one page per module plus a full finding-code index; `mkdocs build --strict` green (Pages deploy stays off).
