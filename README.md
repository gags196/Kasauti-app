# Kasauti

Bilingual (English/Hindi) exam-prep backend for Indian civil-services aspirants. This repository is
the **portfolio edition**: the engineering of the system, without the private business material,
the full question corpus or the labeled answer data.

It is built around one question: *how do you know an AI system's output is right?* Most design
decisions below follow from refusing to take an LLM's output on trust.

## What is built

| Area | What it does | Where |
|---|---|---|
| Ingestion pipeline | Scanned papers → vision-LLM extraction (structured output) → topic tagging → human review → publish gate → embeddings | `apps/api/src/kasauti_api/domain/ingestion/` |
| Retrieval | Cross-lingual semantic search (pgvector, multilingual embeddings), SQL filters, heuristic rerank | `domain/retrieval/hybrid_search.py` |
| Corpus analytics | Topic rankings, trends, recurrence, and a test of 15 folk "elimination rules" against the official answer keys, using permutation and hypergeometric nulls with Bonferroni correction | `domain/intelligence/` |
| Practice engine | Sit a past paper with the real marking scheme; scores are frozen at submission; answers are never sent to the client before submit | `domain/practice/`, `api/v1/practice.py` |
| Answer evaluator | Checks a handwritten answer against a rubric of content points. Every claimed hit must quote the learner's own words, and the quote is verified by string search | `domain/rubric/` |
| Handwriting accuracy | Character/word error rates on NFC-normalised text, plus whether the transcriber's own "uncertain" flags catch its real errors | `domain/extraction/accuracy.py` |
| Cost ledger | Every LLM/embedding call records real spend per feature | `domain/llm/cost_ledger.py` |
| Web app | Next.js, bilingual routes (`/en`, `/hi`), KaTeX for maths | `apps/web` |

## Known limits (read these before the claims above)

- **Retrieval is dense-only today.** The function is named `hybrid_search`, but it combines SQL
  filters, vector similarity and a heuristic rerank. There is no lexical (BM25/full-text) leg yet, and
  the rerank weights are untuned. Adding full-text search with rank fusion, and measuring it, is
  planned.
- **The evaluator reports content-point verdicts, not marks.** There is deliberately no score field.
  Symbolic (SymPy) verification of maths steps is **not implemented**; those points are reported as
  `not_judged`.
- **The benchmark CI gate is a stub.** It validates rubric syntax; regression gating on accuracy
  metrics is not wired up.
- **No accuracy numbers are published here yet.** The handwriting and evaluator benchmarks need a
  labeled set that is kept private.
- The full question corpus is not included. `scripts/seed_demo_questions.py` creates fabricated
  development data, clearly marked and wipeable.

## Run it

```sh
uv sync --all-packages --all-extras
docker compose -f infra/docker-compose.yml up -d postgres redis
uv run alembic -c apps/api/alembic.ini upgrade head
uv run python scripts/seed_taxonomy.py
uv run pytest                      # DB-backed tests run when Postgres is up
uv run uvicorn kasauti_api.main:app --reload
```

Copy `.env.example` to `.env` for API keys. Without keys, embedding falls back to a lexical-only dev
provider that refuses to run outside `dev`.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the design decisions and invariants.
