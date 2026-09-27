# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- WP-05 scaffold: `zohokit` package skeleton, shared-core modules, minimal CLI.
- Legacy history for all 8 `zoho-*` repos under `legacy/<name>/` (TK-MIG-1).
- Import-linter contracts enforcing TK-ARCH-3 (modules independent, core pure).
- CI pipeline per `specs/01` §3.3 (lint, test, contract, ai-evals, demo, security, docker, pages).
- Legacy golden outputs for all 8 modules under `tests/golden/legacy/` (TK-MIG-2).
- Shared core v1: full finding/report envelope, stable identities, money/time/graph/plan utilities, JSON/table/Markdown/HTML renderers, exit codes (TK-CORE-1, 2, 4, 5, 6, 7, TK-CORE-8 partial).
