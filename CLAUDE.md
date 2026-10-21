# CLAUDE.md

Standing reference for Claude Code in this repo. Progress and task state live in `PROGRESS.md`; read it first.

## Project
- Name: Kasauti (portfolio edition)
- Type: bilingual (en/hi) exam-prep backend + web app
- Purpose: engineering portfolio for an AI Engineer role
- Source of truth for design: `ARCHITECTURE.md`
- Public repo: github.com/gags196/Kasauti-app (branch `main`)
- Private source repo exists separately; never copy from it without a sanitize pass

## Stack
- Python 3.12, uv workspace (`apps/api`, `ingestion`)
- FastAPI, SQLAlchemy async, Alembic, SQLAdmin, arq (Redis)
- Postgres 16 + pgvector + ltree
- Next.js + Tailwind (`apps/web`), pnpm
- LLM: Anthropic (structured outputs), Voyage (multilingual embeddings)
- Lint: ruff (line length 100). Tests: pytest, asyncio_mode=auto

## Layout
| Path | Role |
|---|---|
| `apps/api/src/kasauti_api/api/v1/` | routers: pyq, auth, users, practice |
| `.../domain/ingestion/` | LLM extraction, tagging, publish gate |
| `.../domain/retrieval/hybrid_search.py` | the only search function |
| `.../domain/intelligence/` | statistics over corpus, no LLM |
| `.../domain/practice/` | paper assembly + scoring, no model |
| `.../domain/extraction/` | handwriting transcription, CER/WER |
| `.../domain/rubric/` | evaluator: loader, evidence, engine |
| `.../domain/llm/` | provider protocol, schemas, cost ledger |
| `content/` | prompts, rubrics (YAML), taxonomies; versioned files |
| `scripts/` | operational CLIs |
| `scripts/one_off_parsers/` | per-paper transcript parsers; provenance only |
| `benchmarks/reports/` | generated, committed reports |
| `infra/` | docker-compose, Dockerfiles, Caddyfile |

## Commands
```
uv sync --all-packages --all-extras
docker compose -f infra/docker-compose.yml up -d postgres redis
uv run alembic -c apps/api/alembic.ini upgrade head
uv run python scripts/seed_taxonomy.py
uv run pytest -ra
uv run ruff check --fix .
uv run python scripts/validate_rubrics.py
uv run uvicorn kasauti_api.main:app --reload
cd apps/web && pnpm install && pnpm dev
```

## Test database
- DB-backed tests need Postgres; they skip or fail without it
- Use a throwaway DB, not a dev DB holding real data
- Throwaway: `docker run -d --name kasauti-ci-check -e POSTGRES_USER=kasauti -e POSTGRES_PASSWORD=kasauti -e POSTGRES_DB=kasauti -p 55432:5432 pgvector/pgvector:pg16`
- Point tests at it: `KASAUTI_DATABASE_URL=postgresql+asyncpg://kasauti:kasauti@localhost:55432/kasauti`
- Then: alembic upgrade head, seed_taxonomy, pytest
- Remove after: `docker rm -f kasauti-ci-check`
- Empty-DB baseline: 154 pass, 12 skip (need corpus), 0 fail

## Invariants (do not break)
- Scores/verdicts computed in Python; never taken raw from LLM output
- Evaluator has no mark/score/band field; tests assert this
- Claimed hit needs a quote found in transcript by string search, else `unsupported`
- Status taxonomy: hit, partial, miss, unsupported, not_judged; never merge
- Transcribe and judge are separate calls; `uncertain_spans` flow reader to judge
- All semantic search goes through `search_questions`
- Every LLM/embedding call records to cost ledger; real spend only
- Test fakes use `provider="fake"`; never a real model name
- Hindi/English as paired columns `_en`/`_hi`; no translation side-table
- NFC-normalise before comparing Devanagari
- Prompts/rubrics versioned by filename; never edit in place once used
- Analyses never pool different papers; scope pinned positively
- Attempt verdict frozen at submit; never re-derived
- Unsubmitted paper never exposes `is_correct`
- ltree labels use underscores; slugs use hyphens
- Demo data marked `session='demo'`, dev-only, wipeable
- No labeled/gold data, scans, `.env`, or `var/` in git

## Conventions
- Migrations: autogenerate misses pgvector/sqlalchemy_utils imports and enum ADD VALUE; fix by hand
- New arq jobs: register in `workers/queue.py`, idempotent, enqueue by name
- Provider injection via arq `ctx` for tests
- Internal tooling in SQLAdmin, not custom frontend
- Comments explain why, not what
- Commits: imperative subject; end with the Co-Authored-By trailer when Claude authored

## Known gaps (also tracked in PROGRESS.md)
- Retrieval is dense-only; named hybrid
- Rerank weights untuned
- CER counts code points, not grapheme clusters
- `unsupported` rate unmeasured
- SymPy verification not implemented (`not_judged`)
- Benchmark CI gate is a stub
- No published accuracy numbers
- No remote demo deployed
- No type checking in CI

## Working agreements
- Ask before pushing, deleting, or touching anything outside this repo
- Never run migrations/tests against a DB holding real data
- State what was run and what was not; no unverified "done"
- README claims must match code; update README with any capability change
- Push target: `origin` = github.com/gags196/Kasauti-app; `gh` active account must be `gags196`
