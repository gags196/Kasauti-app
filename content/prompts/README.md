# Prompts

Versioned prompt files referenced by code and rubrics (e.g. `rubric_prompt_ref` in rubric YAML).
Naming: `{purpose}_v{n}.md`. Never edit a prompt in place after it has appeared in a
benchmark report — bump the version so `benchmark_runs.rubric_version`/git history stay honest.

- `extraction/` — PYQ scan extraction and handwritten-answer extraction prompts
- `evaluation/` — step-judge prompts for `llm_judged` rubric steps
- `pyq_tagging/` — topic-tagging prompts for ingestion
