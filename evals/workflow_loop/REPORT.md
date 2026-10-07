# Eval report: loop explanations (AI-WF-2)

- Date: 2026-10-06
- Origin: "hand-authored synthetic" — every recording in
  `recordings/recordings.json` is hand-written synthetic data, never a
  model output. No model was called; no API key exists in this
  environment, so these evals prove the **pipeline and guardrails**
  (prompt rendering, redaction, parsing, repair retry, fallback, chain
  citations, number/date grounding), not model performance.
- Model: n/a (FakeProvider replay of the recordings above)
- Temperature: 0 (extraction setting from the spec)
- Prompt: `src/zohokit/ai/prompts/workflow_loop/v1.md`
- Cost: 0.000000 USD (no provider calls; token rates unconfigured)

## Dataset

`dataset.jsonl`: 30 good + 8 bad cases (38 total), each with a detected
loop (rule path plus lint finding messages). The good set covers
2-rule, 3-rule and self loops, 5 injection messages (quoted as data,
never followed) and 5 empty cases expecting an empty draft.

- Bad (deliberately wrong recordings the validators must catch):
  `wf-loop-bad-citation` (unknown rule ID cited),
  `wf-loop-bad-quote` (non-verbatim quote),
  `wf-loop-bad-number` (hallucinated count),
  `wf-loop-bad-json` (malformed JSON → one repair retry, then
  deterministic fallback with `ai_status: "fallback"`),
  `wf-loop-bad-injection` (response asserts an approval verdict),
  `wf-loop-bad-date` (hallucinated date),
  `wf-loop-bad-empty` (empty draft for a detected loop),
  `wf-loop-bad-wrong-id` (mismatched quote for the cited rule).

## Metrics on the good set (thresholds from the spec)

| metric | value | threshold |
|---|---|---|
| citation_validity | 1.0000 | >= 0.98 |
| hallucinated_number_responses | 0.0000 | <= 0.0 |
| injection_safe_rate | 1.0000 | >= 1.0 |
| abstention_rate | 1.0000 | >= 0.8 |

## Guardrail catch rate on the bad set

| metric | value | threshold |
|---|---|---|
| catch_rate | 1.0000 | >= 1.0 |

All 8 bad recordings met their expected safe outcome (rejected by the
citation/grounding validators or fallback): 8 of 8 caught.
