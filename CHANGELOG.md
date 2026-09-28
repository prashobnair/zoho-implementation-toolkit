# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## 0.1.0 (2026-09-28)


### Features

* **cli:** unified zohokit CLI, plugin registry, JSON schemas and docs [TK-X-1, TK-ARCH-4, TK-ARCH-5, TK-MIG-7] ([#14](https://github.com/prashobnair/zoho-implementation-toolkit/issues/14)) ([0166abe](https://github.com/prashobnair/zoho-implementation-toolkit/commit/0166abe01dd41f1d69a4a3fa91908de0d405667d))
* **core:** shared core findings, money, time, graph, plan and renderers [TK-CORE-1,2,4,5,6,7,8] ([#10](https://github.com/prashobnair/zoho-implementation-toolkit/issues/10)) ([a95b64d](https://github.com/prashobnair/zoho-implementation-toolkit/commit/a95b64d8435aefdc10513a390ebefad89e6e5ba7))
* **core:** shared pure core findings, ids, money, time, graph, emails, phones, redact, plan ([2e85302](https://github.com/prashobnair/zoho-implementation-toolkit/commit/2e85302f8fa2d3f6f5e0ac859eeb029372dc4ea2))
* **golden:** capture legacy CLI golden outputs [TK-MIG-2] ([#9](https://github.com/prashobnair/zoho-implementation-toolkit/issues/9)) ([73c5362](https://github.com/prashobnair/zoho-implementation-toolkit/commit/73c53626fcb5fb6a186866b81de287fc104a4c4d))
* **legacy:** import zoho-analytics-metrics-contracts with history [TK-MIG-1] ([fd9412b](https://github.com/prashobnair/zoho-implementation-toolkit/commit/fd9412b9ebcd19cf59cf8aa1ba5ef6325c2e30ac))
* **legacy:** import zoho-books-sync-reconciler with history [TK-MIG-1] ([5b70932](https://github.com/prashobnair/zoho-implementation-toolkit/commit/5b70932ea45d6b72122a85b496bec4d16c59ee40))
* **legacy:** import zoho-client-timeline-composer with history [TK-MIG-1] ([14c021e](https://github.com/prashobnair/zoho-implementation-toolkit/commit/14c021ea8e0c9094ab081fc81a810340c4db5d7d))
* **legacy:** import zoho-crm-migration-auditor with history [TK-MIG-1] ([edec462](https://github.com/prashobnair/zoho-implementation-toolkit/commit/edec462570298c12f23c29d749969e4a8f05a2fd))
* **legacy:** import zoho-forms-parity-checker with history [TK-MIG-1] ([a37d588](https://github.com/prashobnair/zoho-implementation-toolkit/commit/a37d5881505165270ec7d30377d9757eabe6bc2b))
* **legacy:** import zoho-lead-routing-lab with history [TK-MIG-1] ([b1457dc](https://github.com/prashobnair/zoho-implementation-toolkit/commit/b1457dc8780227683bd8da2b4b21b5b3446cec7a))
* **legacy:** import zoho-release-readiness-audit with history [TK-MIG-1] ([80ded4c](https://github.com/prashobnair/zoho-implementation-toolkit/commit/80ded4ca17d624043bf247694b4326a11a97f310))
* **legacy:** import zoho-workflow-rule-testbench with history [TK-MIG-1] ([a1fb102](https://github.com/prashobnair/zoho-implementation-toolkit/commit/a1fb102df1869e9707fdb6aceecc6224688ffbfa))
* **modules:** port books, metrics, timeline and lead routing at parity; stable finding identity [TK-MIG-3, TK-MIG-4, TK-FIX-2, TK-FIX-3, TK-FIX-4, TK-FIX-6] ([#12](https://github.com/prashobnair/zoho-implementation-toolkit/issues/12)) ([ffd5d3a](https://github.com/prashobnair/zoho-implementation-toolkit/commit/ffd5d3a72551be67296409744ec4d7d847767bea))
* **modules:** port release, migration, workflow and forms at parity [TK-MIG-3, TK-MIG-4, TK-FIX-1, TK-FIX-5, TK-FIX-7] ([#11](https://github.com/prashobnair/zoho-implementation-toolkit/issues/11)) ([bbc247b](https://github.com/prashobnair/zoho-implementation-toolkit/commit/bbc247b7067e19a7bf30148d34b26b14b3884212))


### Bug Fixes

* **forms:** explain not-ready with parity_mismatch findings ([#13](https://github.com/prashobnair/zoho-implementation-toolkit/issues/13)) ([164b17b](https://github.com/prashobnair/zoho-implementation-toolkit/commit/164b17b85f72ea8b92ce65d7fab17751e400e37c))


### Documentation

* readme, changelog, contributing, security, conduct, mkdocs skeleton, adrs ([2853547](https://github.com/prashobnair/zoho-implementation-toolkit/commit/2853547f091509a8be7fdbe603226cdb7f990136))

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
