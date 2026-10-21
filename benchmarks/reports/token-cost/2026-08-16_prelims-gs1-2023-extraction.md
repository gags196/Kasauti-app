# API cost estimate — Prelims GS1 Paper 1, 2023 (2026-08-16)

Measured across **the complete 100-question paper** (5 extraction calls, one per page-range slice). Output figures are totals, not extrapolations.

> **These are estimates, not measurements.** Anthropic's tokenizer is not public and its PDF render DPI is not documented. Every figure below is a band with its assumptions stated. One real API call collapses the band to a measurement — see *Recalibration*.

## What was actually measured

| Quantity | Value |
|---|---|
| Source paper | var\papers\prelims_p1_2023.pdf |
| Pages | 48 |
| File size | 6.63 MB |
| Text layer | 79334 chars (has text) |
| Over 32 MB API request limit | no |
| Extraction tier used | `light` -> claude-haiku-4-5 |
| System prompt | 4550 chars |
| Output JSON, 100 questions | 116309 chars |
| — of which Devanagari | 29202 (25%) |
| — of which Latin | 51418 (44%) |

## Estimated tokens for one full paper

| | low | expected | high |
|---|---:|---:|---:|
| Input (pages as images + prompt) | 31,044 | 127,192 | 146,075 |
| Output (bilingual JSON) | 41,040 | 53,688 | 70,498 |

**Devanagari is 25% of output characters but ~52% of output tokens.** Hindi, not page count, is the dominant cost driver in a bilingual corpus.

## Cost per paper

| Tier | Model | Input | Output | **Total** |
|---|---|---:|---:|---:|
| `light` | claude-haiku-4-5 | $0.127 | $0.268 | **$0.396** |
| `standard` | claude-sonnet-5 | $0.382 | $0.805 | **$1.187** |

Sticker rates from `PRICING_PER_MTOK` in `domain/llm/cost_ledger.py`; discounts are deliberately ignored so cost is never understated.

## Extrapolation

| Scope | Papers | Haiku | Sonnet |
|---|---:|---:|---:|
| This paper | 1 | $0.40 | $1.19 |
| Prelims Paper 1, all years | 14 | $5.54 | $16.62 |
| Whole bucket (Prelims P1+P2, GS1-4, Essay) | 89 | $35.21 | $105.63 |

Paper counts are from the R2 bucket listing. Mains papers are free-text rather than MCQ, so their output is smaller per question — these figures are an upper bound for those.

## Findings that change the engineering, not just the budget

1. **Output would truncate.** `extract_scan` sets `max_tokens=32000`. A full 100-question paper needs ~53,688 output tokens, so extraction would silently stop around question 60. Papers must be split by page range regardless of the 32 MB limit.

2. **The 32 MB request limit does not bind here.** This paper is 6.63 MB, under the limit — but finding 1 already makes splitting mandatory, so nothing changes. The limit bites on other papers in this bucket (the 2026 booklet is 34 MB), so the split step stays unconditional.

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
