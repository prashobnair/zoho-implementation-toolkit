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
  person-name columns are replaced by shape hints
  (`<name: 2 words>`, header kept) before the prompt is built.
  Matching is per header word (spaces, underscores, hyphens and
  camelCase): person-role words (`Owner`, `Manager`, `Contact`,
  `Customer`, `Rep`, `Assignee`, ...) and `First/Last/Full/Given/`
  `Family/Sur` + `Name` mask — so `Account Manager` and
  `Deal Owner Name` mask — while `Account/Company/Deal/Product Name`
  stay visible, plus any column the mapping marks `pii: true`.
  `--ai-allow-pii` skips redaction for synthetic-only local runs and is
  refused with `--live`.
- **Grounding.** Every AI sentence cites finding IDs, and every number
  or date is checked against the report. Spelled-out counts are
  converted to digits first ("six errors" is accepted against 6;
  "seven errors" is rejected there), so wording a hallucinated count
  out in words cannot bypass the check. Finance narratives may restate
  amounts in Indian notation (`₹4.2L`/`4.2 lakh` = 420000,
  `1.5 Cr`/`crore` = 15000000, `$1.2k`, `1.2M`); a figure is accepted
  only when it matches a report amount at its own stated precision AND
  within 2% with a matching currency (`₹4L` never passes for 420000;
  `$4.2L` never grounds a 420000 INR report; a stated zero only matches
  a report zero). A mismatch falls back to the
  deterministic template.
- **Draft action targets (STD-AI10).** A drafted workflow rule acts
  only on literals the description mentions: every webhook `url` must
  appear in full or as a same-scheme dotted host (`http://` never
  grounds on an `https://` mention; a dotless host like `billing` never
  grounds on a bare word), and every email `template` / `assign_owner`
  `owner` must match whole whitespace tokens (`own` is not `owner`;
  `won` is not `closed-won`), or match a
  caller-supplied allowlist entry (`--allow-targets FILE`, a JSON
  list of exact strings). Anything else is a prompt-injection
  attempt: the draft is rejected with
  `grounding: action target not in description` and the run falls
  back to an abstention.
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

## Features

All three read local files only and never touch the network except an
explicitly configured provider call.

- `zohokit explain <report.json> [--audience internal|client] [--ai]`
  summarizes a report. Without `--ai` a deterministic template lists
  severity counts plus one cited line per finding. With `--ai` every
  sentence cites finding IDs with verbatim quotes and every number/date
  is verified against the report, otherwise the template runs instead.
  The client audience drops run IDs, hashes, artifact paths and raw
  evidence values (finding IDs stay as citable references).
- `zohokit migration suggest-mapping --csv FILE --target-module MOD
  --fields-dir DIR --out mapping.draft.yaml [--ai]` proposes mapping
  entries from headers plus 5 sample values per column. Columns below
  0.6 confidence are abstained (`null`). The draft is written to a
  separate file and never overwrites an existing one; invalid proposals
  are dropped and reported.
- `zohokit migration suggest-transform --csv FILE --column NAME
  --target-type text|email|phone|date|currency [--ai]` proposes one
  value transform. It is applied to the samples first: anything below
  100% parse success is dropped and reported, with the deterministic
  guess as fallback.
- `zohokit workflow draft --description TEXT [--metadata FILE]
  [--module Deals] [--record FILE] [--allow-targets FILE] [--ai]`
  drafts one rule and simulates it immediately against the record
  (default: a small synthetic Marigold deal), printing the full
  trace. Draft only, not deployed: nothing is written anywhere
  except `--out`. Without `--ai` (or with no provider) it prints
  `AI disabled` and abstains. Every webhook url, email template
  and owner must be mentioned in the description (STD-AI10, above)
  or pre-approved via `--allow-targets`, otherwise the draft falls
  back to an abstention.
- `zohokit workflow lint --rules FILE [--ai]` attaches a cited loop
  explanation to each `potential_loop` finding (an `ai` block on
  the finding, "AI suggestion" badge in HTML). Without a provider
  the deterministic report is unchanged.

AI items render with an "AI suggestion" badge plus confidence in HTML
output (`--format html`). JSON output carries the `ai_usage` block
(tokens, cost estimate, latency) alongside `ai_status`, `model` and
the prompt version.
