# Architecture and design decisions

## Layout

- `apps/api` — FastAPI, SQLAdmin (`/admin`), arq workers. Most of the code.
  - `domain/` is split by trust level: `ingestion` (LLM-touching), `retrieval`, `intelligence`
    (statistics, mostly no LLM), `practice` (scoring, no model at all), `extraction` (handwriting),
    `rubric` (the evaluator).
- `apps/web` — Next.js learner app, bilingual.
- `content/` — versioned prompts, rubrics (YAML, JSON-Schema validated) and taxonomies, loaded at call
  time. A prompt is never edited in place once used; it is versioned by filename.
- `scripts/` — operational CLIs. `scripts/one_off_parsers/` holds per-year/per-paper transcript
  parsers that were needed once; they are kept for provenance, not as a framework.
- `benchmarks/reports/` — generated, committed reports.

## Decisions worth discussing

1. **Deterministic trust boundary.** User-visible facts are computed in Python from checks, not
   copied from model output. MCQ correctness comes only from official keys; the evaluator's
   "hit" claims are verified by string search against the transcript.
2. **Structured outputs everywhere.** Each LLM call goes through a provider protocol with a Pydantic
   schema; tiers ("light"/"standard") map to models in one place.
3. **Unsupported ≠ miss.** A claimed hit whose quote is not in the transcript is `unsupported`
   (a defect in the system), distinct from a point the learner did not make (`miss`) and from a
   point nobody judged (`not_judged`).
4. **Read, then judge.** Handwriting transcription and rubric judging are separate calls with the
   transcript as an inspectable artifact, because transcription errors dominate grading errors and a
   single call hides them. Uncertain spans flow from the reader to the judge.
5. **Right null for the right claim.** Option-level patterns use a within-archetype permutation
   null; statement-level patterns use a per-question hypergeometric null; letter position uses
   chi-square. Each family carries a Bonferroni threshold, and a "finding" needs a minimum sample.
6. **Paper scoping.** Analyses never pool different papers; scope is pinned positively rather than via
   exclusion lists after an earlier bug silently pooled two exams.
7. **One retrieval function.** All semantic search goes through one place so relevance work lands
   everywhere.
8. **Frozen verdicts.** A learner's score is written once at submission and never re-derived when keys
   are corrected later.
9. **Bilingual by paired columns** (`_en`/`_hi`), one shared multilingual embedding space.

## Testing

Provider fakes dispatch on the Pydantic schema type and run against a real local Postgres. Statistical
helpers are hand-rolled and pinned by tests against hand-computed values.
