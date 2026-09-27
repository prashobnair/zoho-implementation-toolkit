# Schemas

Every input and output model exports JSON Schema to `schemas/<module>/<name>.v<N>.json`
(TK-ARCH-5, lands WP-07 with the shared core). CI fails if the export is stale
(`make schemas && git diff --exit-code`).
