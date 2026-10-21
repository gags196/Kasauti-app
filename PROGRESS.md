# PROGRESS

Low-level tracker. Update on every work session. Status: `todo` | `doing` | `done` | `blocked`.

## Current state
- Date of last update: 2026-10-21
- Branch: `main`
- HEAD: `cb2c218` Portfolio edition of Kasauti (pushed)
- CI: green on GitHub (run 39657193689)
- Local empty-DB tests: 154 pass, 12 skip, 0 fail
- Next session starts at: **T-01**

## Changelog
| Date | Change | Commit |
|---|---|---|
| 2026-10-21 | Sanitized copy from private repo HEAD (248 files) | cb2c218 |
| 2026-10-21 | Removed strategy docs, moved 9 one-off scripts to `scripts/one_off_parsers/` | cb2c218 |
| 2026-10-21 | Added ARCHITECTURE.md, README (known limits), LICENSE (MIT, holder `gags196`) | cb2c218 |
| 2026-10-21 | CI: pgvector service container, alembic + seed before pytest | cb2c218 |
| 2026-10-21 | `test_topic_profile`: skip when no peers (was fail on empty DB) | cb2c218 |
| 2026-10-21 | Added CLAUDE.md, PROGRESS.md | pending |

## Code-review findings
| ID | Finding | File | Severity | Status | Task |
|---|---|---|---|---|---|
| F1 | "hybrid" search is dense-only; no lexical leg | `domain/retrieval/hybrid_search.py:54-116` | high | todo | T-03..T-06 |
| F2 | Rerank weights untuned (recency 0.15, marks 0.05, x3 candidates); recency questionable for PYQ | `hybrid_search.py:39-42` | med | todo | T-07 |
| F3 | CI skipped DB tests (no Postgres service) | `.github/workflows/ci.yml` | high | done | T-00 |
| F4 | README overclaimed SymPy / benchmark gate | `README.md` | high | done | T-00 |
| F5 | CER on code points, not grapheme clusters; inflates Devanagari | `domain/extraction/accuracy.py:67-69` | med | todo | T-08 |
| F6 | `unsupported` rate unmeasured; verbatim match may over-trigger on paraphrase/cross-lingual | `domain/rubric/evidence.py` | med | todo | T-09 |
| F7 | `illegible` spans accumulate across batches; order-dependent outcomes | `domain/rubric/engine.py:329-353` | low | todo | T-10 |
| F8 | No type checking in CI; no frontend build in CI | `ci.yml` | low | todo | T-11 |
| F9 | Actions: Node 20 deprecation; `ubuntu-latest` -> 26 on 2026-10-19 | `ci.yml` | low | todo | T-12 |

## Task backlog
### Setup (done)
| ID | Task | Status |
|---|---|---|
| T-00 | Sanitized repo, CI fix, README honesty, push | done |

### Retrieval upgrade (days 4-8)
| ID | Task | Status | Output |
|---|---|---|---|
| T-01 | Decide eval corpus source (public fixtures vs vetted slice of private DB, 100-150 q) | todo | decision in Decisions |
| T-02 | Build sample-corpus loader + seed script (no private data) | todo | `scripts/seed_sample_corpus.py` |
| T-03 | Label 60-80 queries with relevant question IDs (incl. Hindi, cross-lingual, filter cases) | todo | `benchmarks/fixtures/retrieval/queries.yaml` |
| T-04 | Eval harness: Recall@5, Recall@10, MRR, per-query-type breakdown | todo | `scripts/eval_retrieval.py` |
| T-05 | Record dense-only baseline | todo | `benchmarks/reports/retrieval/<date>_baseline.md` |
| T-06 | Add Postgres FTS (tsvector, GIN index, migration) + RRF fusion in `search_questions` | todo | migration + code |
| T-07 | Tune/validate rerank weights on eval set; drop recency if no gain | todo | report |
| T-07b | Re-measure; write before/after table into README | todo | README section |

### Evaluator quality
| ID | Task | Status |
|---|---|---|
| T-08 | Grapheme-cluster CER/WER (`regex` `\X`); keep code-point variant; unit tests with hand-computed values | todo |
| T-09 | Measure `unsupported` rate on fixtures; add fuzzy/normalised fallback only if data justifies | todo |
| T-10 | Fix cross-batch `illegible` accumulation; regression test | todo |

### CI / hygiene
| ID | Task | Status |
|---|---|---|
| T-11 | Add pyright or mypy job; add `pnpm build` + `pnpm typecheck` job | todo |
| T-12 | Bump action versions; pin runner image | todo |
| T-13 | CI status badge in README | todo |
| T-14 | GitHub repo description + topics | todo |

### Extension and delivery (days 13-30)
| ID | Task | Status |
|---|---|---|
| T-15 | MCP server over corpus: tools = search, rankings, topic profile, elimination verdicts | todo |
| T-16 | MCP tests + README section + demo transcript | todo |
| T-17 | LangGraph study-planner agent (bounded steps, validation, retry); only if target JDs require | todo |
| T-18 | Deploy read-only public demo (API + web) | todo |
| T-19 | Architecture diagram + demo GIF in README | todo |
| T-20 | Rewrite ARCHITECTURE.md in own words; self-quiz on each invariant | todo |
| T-21 | Handwriting/evaluator benchmark numbers (private labeled set; publish aggregates only) | todo |
| T-22 | Resume bullets from measured numbers only | todo |

## Decisions
| ID | Decision | Date |
|---|---|---|
| D-01 | Portfolio repo is separate, fresh history | 2026-10-21 |
| D-02 | License MIT, holder `gags196` | 2026-10-21 |
| D-03 | Real exam text kept in worked-example fixture/rubric | 2026-10-21 |
| D-04 | Uncommitted private-repo transcription work excluded | 2026-10-21 |
| D-05 | PolicyPilot dropped; Kasauti is flagship #1 | 2026-10-21 |
| D-06 | Optional second project: MCP server over Kasauti corpus | 2026-10-21 |

## Open questions
| ID | Question | Blocks |
|---|---|---|
| Q-01 | Eval corpus source: public fixtures or vetted private slice? | T-01, T-02 |
| Q-02 | Who labels relevance for queries (user approves Claude drafts)? | T-03 |
| Q-03 | Include transcription work (`pages.py`, `handwritten_answer_v2.md`) later? | none |
| Q-04 | Hosting target for demo (VPS / free tier)? | T-18 |
| Q-05 | Rotate repo description/topics wording | T-14 |

## Measurements (fill only with real runs)
| Metric | Dense-only | + FTS/RRF | Set | Date |
|---|---|---|---|---|
| Recall@5 | - | - | - | - |
| Recall@10 | - | - | - | - |
| MRR | - | - | - | - |
| Hindi->English Recall@5 | - | - | - | - |
| p95 search latency (ms) | - | - | - | - |
| `unsupported` rate | - | - | - | - |
| Hindi CER, code point | - | - | - | - |
| Hindi CER, grapheme | - | - | - | - |

## Session log
| Date | Done | Next |
|---|---|---|
| 2026-10-21 | Repo created, CI green, docs added | T-01 |
