# AI suggestions

`zohokit` works fully without any AI. Every AI feature is opt-in
(`--ai`) and produces **suggestions only**: a draft narrative, a draft
mapping, a draft transform. Nothing is ever auto-applied, and every
suggestion carries its source, model and prompt version for review.

## Safety rules

- **Opt-in.** Without `--ai` nothing calls a provider. With `--ai` but
  no provider configured, the tool prints `AI disabled` and runs its
  deterministic path.
- **Redact before send.** The shared redactor runs on every prompt, so
  personal data never leaves the process. Sample values from
  person-name columns (`Name`, `First/Last/Full Name`, `Contact`,
  `Contact Person`, `Owner`, `Customer`, `Person`, plus any column the
  mapping marks `pii: true`) are replaced by shape hints
  (`<name: 2 words>`, header kept) before the prompt is built.
  `--ai-allow-pii` skips redaction for synthetic-only local runs and is
  refused with `--live`.
- **Grounding.** Every AI sentence cites finding IDs, and every number
  or date is checked against the report. Spelled-out counts are
  converted to digits first ("six errors" is accepted against 6;
  "seven errors" is rejected there), so wording a hallucinated count
  out in words cannot bypass the check. A mismatch falls back to the
  deterministic template.
- **Injection hygiene.** Source text travels in delimited data blocks
  and the system prompt declares it data, never instructions.
- **Budget.** `--ai-max-tokens` caps estimated prompt tokens; every
  output carries an `ai_usage` block (tokens, cost estimate, latency).
- **No network in tests.** Tests and CI use `FakeProvider` only, which
  replays hand-authored synthetic recordings keyed by prompt hash. A
  missing recording is a clear error, never a network call.

## Providers

The provider comes from configuration only (never hardcoded):

- `ZOHOKIT_AI_PROVIDER=anthropic` with `ZOHOKIT_AI_MODEL` and
  `ZOHOKIT_AI_API_KEY` (`ANTHROPIC_API_KEY` also works). Needs the
  `ai` extra.
- `ZOHOKIT_AI_PROVIDER=openai-compatible` with `ZOHOKIT_AI_MODEL`,
  `ZOHOKIT_AI_BASE_URL` and `ZOHOKIT_AI_API_KEY`.
- `ZOHOKIT_AI_PROVIDER=fake` with `ZOHOKIT_AI_MODEL` for local
  recording replay.

## Evals

`evals/<feature>/` holds the dataset, hand-authored recordings (every
file labelled `"origin": "hand-authored synthetic"`), metrics,
thresholds and a report. CI runs them against the recordings and fails
below thresholds. The reports measure the pipeline and guardrails, not
model performance: no model is called without a key. Live re-recording
is a manual step via the `evals-live` workflow, which refuses when no
key exists and never runs on pull requests.
