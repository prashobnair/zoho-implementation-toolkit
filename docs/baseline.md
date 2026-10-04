# Accepted findings (baseline)

Some findings are known and accepted: a removal scheduled for next quarter,
a heuristic edge a reviewer has verified by hand. A **baseline file**
records those decisions so the next run stays green without hiding them.

## File format

`.zohokit-baseline.json` (version 1):

```json
{
  "version": 1,
  "suppressions": [
    {
      "id": "4de0485ea059e0d1f4d40fe0",
      "reason": "External_Ref removal approved for the October cutover.",
      "approver": "release-manager",
      "expires": "2026-10-31"
    }
  ]
}
```

Every entry needs a stable finding `id` (the `id` field in any JSON
report), a non-empty `reason`, an `approver`, and an `expires` date. A
missing reason is a hard error: silent acceptances are never allowed.

## Behavior

```sh
zohokit release diff before.json after.json --baseline .zohokit-baseline.json
```

- Suppressed findings stay visible in every format with
  `"suppressed": true`, and `summary.suppressed` counts them.
- They no longer block `ready`, and `--strict` stays exit 0 for them.
- SARIF marks them `level: none` with an `external` suppression;
  JUnit marks them `<skipped>`.
- Expired entries reactivate automatically on their `expires` date.

## Trend tracking

`zohokit diff-reports before.json after.json` compares two saved reports
by stable finding ID and prints new, resolved and changed findings
(`--format json|table|markdown`). With `--strict` it exits 2 when new
`error` findings exist, which makes it a small promotion gate in CI.
Pass `--baseline` to accept known findings on the newer report first.
