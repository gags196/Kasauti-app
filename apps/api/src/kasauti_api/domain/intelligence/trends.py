"""How the mix of question types has moved year by year.

Plain SQL over `question_profiles`. The headline this exists to carry: the count format
("How many of the above are correct?") went from **zero occurrences before 2022** to a
sixth of the paper, while the classic "1 only / 2 only / Both / Neither" option family
almost halved. That is the clearest evidence that a fourteen-year average describes an
exam nobody is sitting.

Two honesty properties are built into the return type rather than left to the caller:

* **`profiled_share`** — the fraction of in-scope questions that actually carry the field
  being charted. The model-assigned dimensions (`format`, `depth`) are backfilled
  newest-first, so for a long while a format chart will be drawn from part of the corpus.
  A chart that does not say so implies full coverage.
* **`note`** — set whenever coverage is partial or per-year counts are too thin to read.
  Per *leaf topic* the corpus averages about 1.3 questions a year; a fitted slope on that
  is noise, so trends are honest at paper and branch level and nowhere finer.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy import String, case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from kasauti_api.db.models import Question, QuestionProfile
from kasauti_api.domain.intelligence.scope import QuestionScope, question_ids

Dimension = Literal["format", "regex_format", "depth", "archetype"]

# Below this, a year's bar is drawn from too few questions to mean anything on its own.
MIN_QUESTIONS_PER_YEAR = 20
NOT_CLASSIFIED = "(not classified)"
NO_MARKER = "(no printed marker)"

_COLUMNS = {
    "format": QuestionProfile.format,
    "regex_format": QuestionProfile.regex_format,
    "depth": QuestionProfile.depth,
    "archetype": QuestionProfile.option_archetype,
}
# `regex_format` is derived from the printed text, so a NULL means "this question carries
# no recognisable marker" — a fact about the paper. For the model-assigned columns a NULL
# means "the classification pass has not reached this question yet" — a fact about us.
_NULL_BUCKET = {
    "format": NOT_CLASSIFIED,
    "depth": NOT_CLASSIFIED,
    "regex_format": NO_MARKER,
    "archetype": NO_MARKER,
}


@dataclass(frozen=True)
class TrendCell:
    year: int
    bucket: str
    count: int
    share: float


@dataclass(frozen=True)
class TrendSeries:
    dimension: str
    scope_note: str
    years: list[int]
    buckets: list[str]
    total_by_year: dict[int, int]
    profiled_share: float
    cells: list[TrendCell] = field(default_factory=list)
    note: str | None = None

    def share_of(self, year: int, bucket: str) -> float:
        return next(
            (c.share for c in self.cells if c.year == year and c.bucket == bucket), 0.0
        )


async def mix_by_year(
    session: AsyncSession,
    *,
    dimension: Dimension = "regex_format",
    scope: QuestionScope | None = None,
    top_n: int = 12,
) -> TrendSeries:
    """Per-year distribution of one profile dimension across the scope."""
    scope = scope or QuestionScope()
    column = _COLUMNS[dimension]
    null_bucket = _NULL_BUCKET[dimension]

    # Cast the enum to text so the NULL bucket label can share the column with it.
    bucket = case((column.is_(None), null_bucket), else_=cast(column, String))
    rows = (
        await session.execute(
            select(Question.year, bucket.label("bucket"), func.count(Question.id))
            .join(QuestionProfile, QuestionProfile.question_id == Question.id)
            .where(Question.id.in_(question_ids(scope)))
            .group_by(Question.year, "bucket")
            .order_by(Question.year)
        )
    ).all()
    if not rows:
        return TrendSeries(dimension, scope.describe(), [], [], {}, 0.0,
                           note="no profiled questions in scope")

    total_by_year: dict[int, int] = defaultdict(int)
    counts: dict[tuple[int, str], int] = {}
    for year, name, n in rows:
        counts[(year, name)] = counts.get((year, name), 0) + n
        total_by_year[year] += n

    classified = sum(n for (_, name), n in counts.items() if name != null_bucket)
    total = sum(total_by_year.values())
    profiled_share = classified / total if total else 0.0

    # Keep the largest buckets; the rest would be a forest of one-question slivers.
    by_bucket: dict[str, int] = defaultdict(int)
    for (_, name), n in counts.items():
        by_bucket[name] += n
    buckets = [b for b, _ in sorted(by_bucket.items(), key=lambda kv: -kv[1])[:top_n]]

    years = sorted(total_by_year)
    cells = [
        TrendCell(year, name, counts[(year, name)],
                  counts[(year, name)] / total_by_year[year])
        for year in years
        for name in buckets
        if (year, name) in counts
    ]

    notes = []
    if profiled_share < 0.999:
        notes.append(
            f"{profiled_share:.0%} of questions in scope carry a {dimension} value"
        )
    thin = [y for y in years if total_by_year[y] < MIN_QUESTIONS_PER_YEAR]
    if thin:
        notes.append(
            f"fewer than {MIN_QUESTIONS_PER_YEAR} questions in "
            f"{', '.join(str(y) for y in thin)} — read those years as anecdote"
        )

    return TrendSeries(
        dimension=dimension,
        scope_note=scope.describe(),
        years=years,
        buckets=buckets,
        total_by_year=dict(total_by_year),
        profiled_share=profiled_share,
        cells=cells,
        note="; ".join(notes) or None,
    )


@dataclass(frozen=True)
class EraShift:
    """One bucket's share before and after the 2022 pattern break."""

    bucket: str
    legacy_count: int
    legacy_share: float
    recent_count: int
    recent_share: float

    @property
    def delta(self) -> float:
        return self.recent_share - self.legacy_share


async def era_shift(
    session: AsyncSession,
    *,
    dimension: Dimension = "regex_format",
    scope: QuestionScope | None = None,
) -> list[EraShift]:
    """Each bucket's share in 2022+ against its share before, biggest mover first.

    This is the comparison the product leads with, so it is computed once here rather
    than assembled differently by each caller.
    """
    base = scope or QuestionScope()
    legacy, recent = [
        await mix_by_year(
            session,
            dimension=dimension,
            scope=QuestionScope(
                topic_path=base.topic_path, rollup=base.rollup, stage=base.stage,
                subject_id=base.subject_id, paper_id=base.paper_id, era=era,
            ),
            top_n=50,
        )
        for era in ("legacy", "recent")
    ]

    def totals(series: TrendSeries) -> tuple[dict[str, int], int]:
        counts: dict[str, int] = defaultdict(int)
        for cell in series.cells:
            counts[cell.bucket] += cell.count
        return counts, sum(counts.values())

    legacy_counts, legacy_total = totals(legacy)
    recent_counts, recent_total = totals(recent)

    shifts = [
        EraShift(
            bucket=bucket,
            legacy_count=legacy_counts.get(bucket, 0),
            legacy_share=legacy_counts.get(bucket, 0) / legacy_total if legacy_total else 0.0,
            recent_count=recent_counts.get(bucket, 0),
            recent_share=recent_counts.get(bucket, 0) / recent_total if recent_total else 0.0,
        )
        for bucket in sorted(set(legacy_counts) | set(recent_counts))
    ]
    return sorted(shifts, key=lambda s: abs(s.delta), reverse=True)
