# API cost estimate — Prelims GS1 Paper 1 extraction (2026-08-14)

Derived from a real manual extraction of **10 questions**, scaled to a 100-question paper.

> **These are estimates, not measurements.** Anthropic's tokenizer is not public and its PDF render DPI is not documented. Every figure below is a band with its assumptions stated. One real API call collapses the band to a measurement — see *Recalibration*.

## What was actually measured

| Quantity | Value |
|---|---|
| Source paper | var\papers\prelims_p1_2026.pdf |
| Pages | 56 |
| File size | 34.19 MB |
| Text layer | 0 chars (pure scan — vision required) |
| Over 32 MB API request limit | **YES — must be split** |
| Extraction tier used | `light` -> claude-haiku-4-5 |
| System prompt | 1419 chars |
| Output JSON, 10 questions | 12879 chars |
| — of which Devanagari | 3287 (26%) |
| — of which Latin | 5766 (45%) |

## Estimated tokens for one full paper

| | low | expected | high |
|---|---:|---:|---:|
| Input (pages as images + prompt) | 31,676 | 132,768 | 152,622 |
| Output (bilingual JSON) | 45,600 | 59,770 | 78,530 |

**Devanagari is 26% of output characters but ~52% of output tokens.** Hindi, not page count, is the dominant cost driver in a bilingual corpus.

## Cost per paper

| Tier | Model | Input | Output | **Total** |
|---|---|---:|---:|---:|
| `light` | claude-haiku-4-5 | $0.133 | $0.299 | **$0.432** |
| `standard` | claude-sonnet-5 | $0.398 | $0.897 | **$1.295** |

Sticker rates from `PRICING_PER_MTOK` in `domain/llm/cost_ledger.py`; discounts are deliberately ignored so cost is never understated.

## Extrapolation

| Scope | Papers | Haiku | Sonnet |
|---|---:|---:|---:|
| This paper | 1 | $0.43 | $1.29 |
| Prelims Paper 1, all years | 14 | $6.04 | $18.13 |
| Whole bucket (Prelims P1+P2, GS1-4, Essay) | 89 | $38.41 | $115.24 |

Paper counts are from the R2 bucket listing. Mains papers are free-text rather than MCQ, so their output is smaller per question — these figures are an upper bound for those.

## Findings that change the engineering, not just the budget

1. **Output would truncate.** `extract_scan` sets `max_tokens=32000`. A full 100-question paper needs ~59,770 output tokens, so extraction would silently stop around question 54. Papers must be split by page range regardless of the 32 MB limit.

2. **The 32 MB request limit already bites.** This paper is 34.19 MB. Splitting is mandatory, not an optimisation.

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
