"""Rebuild the deterministic half of question_profiles. No LLM, no network.

    uv run python scripts/derive_question_facts.py                 # all published questions
    uv run python scripts/derive_question_facts.py --year 2025
    uv run python scripts/derive_question_facts.py --check         # drift vs the answer key

Everything written here is recomputable from `questions` and `question_options`, so this
is safe to re-run at any time; the upsert deliberately leaves the LLM-classified columns
(`format`, `depth`, `current_affairs_anchored`, …) untouched, so a rebuild never destroys
hand-answered classification work.

**Run this after `load_answer_key.py`.** `correct_label` and the option geometry are
denormalised from `question_options` so that every option statistic is a GROUP BY rather
than a full-corpus scan; loading or correcting a key therefore makes them stale. `--check`
reports exactly that drift without writing anything.

Every matched row is rewritten on every run, deliberately. An earlier version skipped
rows already at the current `DERIVED_REV`, which was a real correctness hole rather than
a saving: a corrected answer key leaves `derived_rev` untouched, so the stale row was
never repaired and `--check` kept reporting drift that a plain run could not fix.
Recomputing all 1,400 rows takes well under a second, which is not worth a footgun.
`DERIVED_REV` remains as the marker of which rule version produced a row.
"""

import argparse
import asyncio
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api" / "src"))

from kasauti_api.db.base import async_session_factory  # noqa: E402
from kasauti_api.db.models import (  # noqa: E402
    Paper,
    Question,
    QuestionProfile,
)
from kasauti_api.db.models.questions import QuestionStatus  # noqa: E402
from kasauti_api.domain.intelligence.facts import (  # noqa: E402
    DERIVED_REV,
    OptionInput,
    detect_format,
    option_facts,
    stem_facts,
)
from sqlalchemy import select  # noqa: E402
from sqlalchemy.dialects.postgresql import insert  # noqa: E402
from sqlalchemy.orm import selectinload  # noqa: E402

# Written by this script and no other. Everything outside this set belongs to the
# classification pass and must survive a rebuild untouched.
DERIVED_COLUMNS = (
    "derived_rev", "derived_at", "regex_format", "statement_count", "option_count",
    "option_archetype", "stem_chars_en", "stem_chars_hi", "has_table",
    "has_all_of_above", "has_none_of_above", "correct_label", "correct_is_longest",
    "longest_margin", "dated_option_count", "dated_correct",
)


def facts_for(question: Question) -> dict:
    options = [
        OptionInput(o.option_label, o.option_text_en, o.option_text_hi, o.is_correct)
        for o in sorted(question.options, key=lambda o: o.option_label)
    ]
    stem = stem_facts(
        text_en=question.question_text_en,
        text_hi=question.question_text_hi,
        tables=question.tables,
    )
    opts = option_facts(options)
    return {
        "question_id": question.id,
        "derived_rev": DERIVED_REV,
        "derived_at": datetime.now(UTC),
        "regex_format": detect_format(
            question.question_text_en or question.question_text_hi, stem, opts
        ),
        "statement_count": stem.statement_count,
        "option_count": opts.option_count,
        "option_archetype": opts.archetype,
        "stem_chars_en": stem.stem_chars_en,
        "stem_chars_hi": stem.stem_chars_hi,
        "has_table": stem.has_table,
        "has_all_of_above": opts.has_all_of_above,
        "has_none_of_above": opts.has_none_of_above,
        "correct_label": opts.correct_label,
        "correct_is_longest": opts.correct_is_longest,
        "longest_margin": opts.longest_margin,
        "dated_option_count": opts.dated_option_count,
        "dated_correct": opts.dated_correct,
    }


async def load_questions(session, *, year: int | None, paper_code: str | None):
    stmt = (
        select(Question)
        .options(selectinload(Question.options))
        .where(Question.status == QuestionStatus.published)
        .order_by(Question.year, Question.id)
    )
    if year is not None:
        stmt = stmt.where(Question.year == year)
    if paper_code is not None:
        stmt = stmt.join(Paper, Paper.id == Question.paper_id).where(
            Paper.code == paper_code
        )
    return (await session.execute(stmt)).scalars().all()


async def run_check(questions) -> int:
    """Report rows whose stored option geometry no longer matches the live key."""
    async with async_session_factory() as session:
        stored = {
            p.question_id: p
            for p in (await session.execute(select(QuestionProfile))).scalars()
        }

    drift = []
    for question in questions:
        profile = stored.get(question.id)
        if profile is None:
            continue
        fresh = facts_for(question)
        if profile.correct_label != fresh["correct_label"]:
            drift.append(
                f"  q{question.id} ({question.year} Q{question.question_number}): "
                f"stored {profile.correct_label!r}, key says {fresh['correct_label']!r}"
            )
        elif profile.derived_rev != DERIVED_REV:
            drift.append(
                f"  q{question.id}: derived_rev {profile.derived_rev} < {DERIVED_REV}"
            )

    missing = [q.id for q in questions if q.id not in stored]
    if missing:
        print(f"{len(missing)} published questions have no profile row yet")
    if drift:
        print(f"{len(drift)} profiles are stale:")
        print("\n".join(drift[:40]))
        if len(drift) > 40:
            print(f"  … and {len(drift) - 40} more")
    if not drift and not missing:
        print(f"All {len(questions)} profiles are current at derived_rev={DERIVED_REV}.")
    return len(drift) + len(missing)


def summarise(rows: list[dict]) -> None:
    formats = Counter(
        r["regex_format"].value if r["regex_format"] else "(no marker)" for r in rows
    )
    archetypes = Counter(
        r["option_archetype"].value if r["option_archetype"] else "(none)" for r in rows
    )
    keyed = [r for r in rows if r["correct_is_longest"] is not None]
    longest = sum(1 for r in keyed if r["correct_is_longest"])

    print(f"\n{len(rows)} questions profiled at derived_rev={DERIVED_REV}\n")
    print("  regex format (a cross-check, not the taxonomy — 47% carry no marker):")
    for name, n in formats.most_common():
        print(f"    {name:24} {n:5}")
    print("\n  option archetype:")
    for name, n in archetypes.most_common():
        print(f"    {name:24} {n:5}")
    if keyed:
        print(
            f"\n  correct option is the longest: {longest}/{len(keyed)} "
            f"({longest / len(keyed):.1%}) — ties excluded, and this figure is NOT "
            "comparable to a 25% baseline; see option_patterns."
        )


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=None)
    parser.add_argument("--paper-code", default=None)
    parser.add_argument(
        "--check", action="store_true",
        help="report stale rows and exit non-zero; writes nothing",
    )
    args = parser.parse_args()

    async with async_session_factory() as session:
        questions = await load_questions(
            session, year=args.year, paper_code=args.paper_code
        )
    if not questions:
        print("No published questions match. Ingest and publish a paper first.")
        return

    if args.check:
        sys.exit(1 if await run_check(questions) else 0)

    rows = [facts_for(q) for q in questions]

    # asyncpg caps a single statement at 32767 bound parameters; each row binds
    # len(row) values, so a corpus-wide upsert must be chunked once the corpus
    # is large enough to cross that line (it wasn't, until this session).
    chunk_size = max(1, 30000 // len(rows[0]))
    upserted = 0
    async with async_session_factory() as session:
        for start in range(0, len(rows), chunk_size):
            chunk = rows[start : start + chunk_size]
            stmt = insert(QuestionProfile).values(chunk)
            update = {c: stmt.excluded[c] for c in DERIVED_COLUMNS}
            stmt = stmt.on_conflict_do_update(
                index_elements=[QuestionProfile.question_id], set_=update
            )
            result = await session.execute(stmt)
            upserted += result.rowcount
        await session.commit()

    print(f"upserted {upserted} of {len(rows)} profile rows")
    summarise(rows)


if __name__ == "__main__":
    asyncio.run(main())
