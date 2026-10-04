# Changelog

## [0.2.1](https://github.com/prashobnair/zoho-implementation-toolkit/compare/v0.2.0...v0.2.1) (2026-10-04)


### Bug Fixes

* **cli:** UTF-8-safe output on every platform; Windows CI ([#37](https://github.com/prashobnair/zoho-implementation-toolkit/issues/37)) ([e3d6c31](https://github.com/prashobnair/zoho-implementation-toolkit/commit/e3d6c317b9648bb6a2fbf6413c5c1c109d30fd28))

## [0.2.0](https://github.com/prashobnair/zoho-implementation-toolkit/compare/v0.1.0...v0.2.0) (2026-10-04)


### Features

* **connectors:** read-only Zoho connector foundation [STD-L1..L6, STD-A1..A4, STD-H1..H3, STD-X1..X2, STD-W1..W3, TK-CONN-1, TK-CONN-2, TK-CONN-9] ([#23](https://github.com/prashobnair/zoho-implementation-toolkit/issues/23)) ([12fba75](https://github.com/prashobnair/zoho-implementation-toolkit/commit/12fba7582ef8386b180be25ef970c84cb9d98136))
* **live:** verified CRM read contracts from the developer org ([#32](https://github.com/prashobnair/zoho-implementation-toolkit/issues/32)) ([8e6cec6](https://github.com/prashobnair/zoho-implementation-toolkit/commit/8e6cec631f378ba5f0637b07eeecc1187ad3c3a8))
* **release:** release module v2 and release-gate GitHub Action; baseline, report diff, SARIF and JUnit ([#35](https://github.com/prashobnair/zoho-implementation-toolkit/issues/35)) ([9c1716f](https://github.com/prashobnair/zoho-implementation-toolkit/commit/9c1716f3fc8f47a47d54ee60797f4923b5f03563))


### Bug Fixes

* **connectors:** doctor org parsing, empty and parameterised record reads ([#28](https://github.com/prashobnair/zoho-implementation-toolkit/issues/28)) ([d5bcd03](https://github.com/prashobnair/zoho-implementation-toolkit/commit/d5bcd034f1a1a902670ed12e3562bb6a6ab4cb5f))
* **connectors:** real Zoho CRM v8 response envelopes; value-free contract errors ([#27](https://github.com/prashobnair/zoho-implementation-toolkit/issues/27)) ([e737dbf](https://github.com/prashobnair/zoho-implementation-toolkit/commit/e737dbfc270ea0dbbf08b3076aef02c38257bd8b))
* **recording:** timestamp-safe redaction, stable IDs, slim cassettes; weekly live schedule ([#31](https://github.com/prashobnair/zoho-implementation-toolkit/issues/31)) ([0e23cfd](https://github.com/prashobnair/zoho-implementation-toolkit/commit/0e23cfd9e733e24f8eda0c6ed14bbd8326e33355))
* **redaction:** key-based PII masking; value-free scanner output ([#29](https://github.com/prashobnair/zoho-implementation-toolkit/issues/29)) ([2fae25b](https://github.com/prashobnair/zoho-implementation-toolkit/commit/2fae25bae6b2642deff1a1ffeaad41b64921afd2))
* **scan:** treat numeric time-zone offsets as structural ([#30](https://github.com/prashobnair/zoho-implementation-toolkit/issues/30)) ([145ae2d](https://github.com/prashobnair/zoho-implementation-toolkit/commit/145ae2d0c6003ed85bf8a4342a6df4fa8b3dfe1a))

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
