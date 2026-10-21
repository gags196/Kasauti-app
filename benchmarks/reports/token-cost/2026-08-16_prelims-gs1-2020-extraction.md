# API cost estimate — Prelims GS1 Paper 1, 2020 (2026-08-16)

Measured across **the complete 100-question paper** (5 extraction calls, one per page-range slice). Output figures are totals, not extrapolations.

> **These are estimates, not measurements.** Anthropic's tokenizer is not public and its PDF render DPI is not documented. Every figure below is a band with its assumptions stated. One real API call collapses the band to a measurement — see *Recalibration*.

## What was actually measured

| Quantity | Value |
|---|---|
| Source paper | var\papers\prelims_p1_2020.pdf |
| Pages | 48 |
| File size | 12.8 MB |
| Text layer | 0 chars (pure scan — vision required) |
| Over 32 MB API request limit | no |
| Extraction tier used | `light` -> claude-haiku-4-5 |
| System prompt | 4550 chars |
| Output JSON, 100 questions | 107833 chars |
| — of which Devanagari | 25925 (24%) |
| — of which Latin | 46100 (43%) |

Measured from these extraction requests in `var/llm_queue/` (pass them back to `--request-id` to reproduce this report):

- `4dbe8f906947f5a2`
- `4ac714a89d1098d5`
- `245b5d8b8f51a018`
- `414048b43c470bd9`
- `515b03e7d035511d`

## Estimated tokens for one full paper

| | low | expected | high |
|---|---:|---:|---:|
| Input (pages as images + prompt) | 33,301 | 112,832 | 129,561 |
| Output (bilingual JSON) | 37,807 | 49,248 | 64,561 |

**Devanagari is 24% of output characters but ~50% of output tokens.** Hindi, not page count, is the dominant cost driver in a bilingual corpus.

## Cost per paper

| Tier | Model | Input | Output | **Total** |
|---|---|---:|---:|---:|
| `light` | claude-haiku-4-5 | $0.113 | $0.246 | **$0.359** |
| `standard` | claude-sonnet-5 | $0.338 | $0.739 | **$1.077** |

Sticker rates from `PRICING_PER_MTOK` in `domain/llm/cost_ledger.py`; discounts are deliberately ignored so cost is never understated.

## Extrapolation

| Scope | Papers | Haiku | Sonnet |
|---|---:|---:|---:|
| This paper | 1 | $0.36 | $1.08 |
| Prelims Paper 1, all years | 14 | $5.03 | $15.08 |
| Whole bucket (Prelims P1+P2, GS1-4, Essay) | 89 | $31.96 | $95.87 |

Paper counts are from the R2 bucket listing. Mains papers are free-text rather than MCQ, so their output is smaller per question — these figures are an upper bound for those.

## Findings that change the engineering, not just the budget

1. **Output would truncate.** `extract_scan` sets `max_tokens=32000`. A full 100-question paper needs ~49,248 output tokens, so extraction would silently stop around question 65. Papers must be split by page range regardless of the 32 MB limit.

2. **The 32 MB request limit does not bind here.** This paper is 12.8 MB, under the limit — but finding 1 already makes splitting mandatory, so nothing changes. The limit bites on other papers in this bucket (the 2026 booklet is 34 MB), so the split step stays unconditional.

3. **Output dominates input** at these ratios, and output is where Devanagari lands. Any cost work should target output size — for instance, not re-emitting option text that is identical across languages.

4. **Tagging is the sleeper cost.** `tag_question` (`domain/ingestion/tag.py`) resends the entire candidate topic list on every question. At today's 18 GS2 topics that is negligible; against a full ~300-topic taxonomy it is roughly 400k input tokens per paper — comparable to or larger than extraction. Prompt caching or batching questions per call fixes it.

5. **Batch API halves it.** Roughly 50% off for asynchronous processing, and a multi-year backfill is exactly that workload.

## Assumptions

| Bucket | chars/token (low / expected / high) |
|---|---|
| latin | 4.2 / 3.7 / 3.1 |
| devanagari | 1.6 / 1.05 / 0.75 |
| digit | 3.0 / 2.5 / 2.0 |
| other | 3.4 / 3.0 / 2.4 |

- Image tokens use Anthropic's ~`width x height / 750` rule. The *low* figure treats pages at their native 72 DPI point size; *expected* assumes rendering at print resolution then downscaling to the ~1568px long-edge cap, which is where a normal A4 page lands.
- This run does **not** validate tier quality. Extraction was done by Claude Code, a far larger model than Haiku. A paper transcribed cleanly here may still fail on the `light` tier — see `benchmarks/reports/extraction-accuracy/`.

## Recalibration

Make one real API call, then set `CALIBRATION` in this script from its reported `usage` and re-run. The bands collapse to measurements.

**Not yet calibrated** — no real API call has been made.
