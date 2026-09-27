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
