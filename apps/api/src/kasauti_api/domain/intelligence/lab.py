"""The Elimination Lab: what the shortcut would have told you, and what the key says.

The rules measured in `elimination.py` do not work — one of fifteen reaches significance
over fourteen years, none over the 2022+ era. This module is what the corpus supports
*instead* of an advisor: replay each rule against a real question the learner is looking
at, next to the official answer, so the shortcut is checked rather than trusted.

Every claim it makes is checkable on the spot:

- **The truth labels are the answer key**, decoded by `statements.py` — not a model's
  opinion about whether a statement is true.
- **The measured rate beside each rule is the same number the committed report prints**,
  because it comes from the same `elimination_report` call. A rule cannot look better in
  the product than it does in the benchmark.
- **A question the key cannot decode says so.** Roughly half the corpus prints no numbered
  statements, and for those the lab shows the reason rather than a thinner analysis.

The one thing this module must never do is present a firing as advice. A rule's verdict
travels with every firing, so "not a usable signal" is on screen wherever the rule is.
"""

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from kasauti_api.db.models import Question, QuestionOption
from kasauti_api.db.models.questions import QuestionStatus
from kasauti_api.domain.intelligence.elimination import (
    COMPOUND_RE,
    STATEMENT_RULES,
    RuleResult,
    elimination_report,
)
from kasauti_api.domain.intelligence.scope import QuestionScope
from kasauti_api.domain.intelligence.statements import decode_question

# Outcomes of following a rule on one statement, from the answer key's point of view.
HELPED = "helped"
MISLED = "misled"


@dataclass(frozen=True)
class LabStatement:
    index: int
    text: str
    is_true: bool
    is_claim: bool


@dataclass(frozen=True)
class LabFiring:
    rule_key: str
    title_en: str
    docx_claim: str
    statement_index: int
    # "eliminate" when the document says the marker means false, "keep" when it says true.
    advice: str
    outcome: str
    # The rule's corpus-wide measurement, carried so the screen can never show a firing
    # without showing how often the rule is right.
    measured_rate: float | None
    measured_baseline: float | None
    measured_verdict: str | None
    measured_n: int


@dataclass(frozen=True)
class LabOptionFiring:
    rule_key: str
    title_en: str
    docx_claim: str
    option_label: str
    advice: str
    outcome: str
    measured_rate: float | None
    measured_baseline: float | None
    measured_verdict: str | None
    measured_n: int


@dataclass(frozen=True)
class QuestionLab:
    question_id: int
    year: int
    question_number: str
    decodable: bool
    # Why not, in the decoder's own words, when `decodable` is False.
    skipped_reason: str | None
    statements: list[LabStatement]
    firings: list[LabFiring]
    option_firings: list[LabOptionFiring]
    helped: int
    misled: int


# The report is a 0.6-second corpus scan, and the lab needs it on every question view.
# Memoised per scope and invalidated by the published-question count, which is one cheap
# COUNT and changes exactly when a paper is ingested — the only event that can move these
# numbers. A time-based TTL would instead be stale for its whole window after an ingest
# and recompute pointlessly the rest of the time.
_CACHE: dict[QuestionScope, tuple[int, dict[str, RuleResult]]] = {}


async def rule_statistics(
    session: AsyncSession, scope: QuestionScope | None = None
) -> dict[str, RuleResult]:
    """Measured rate, baseline and verdict per rule key, as the report computes them."""
    scope = scope or QuestionScope()
    # QuestionScope is a frozen dataclass, so it keys the cache directly — a hand-built
    # tuple of its fields would silently stop distinguishing scopes the day one is added.
    published = (
        await session.execute(
            select(func.count(Question.id)).where(
                Question.status == QuestionStatus.published
            )
        )
    ).scalar_one()

    cached = _CACHE.get(scope)
    if cached is not None and cached[0] == published:
        return cached[1]

    report = await elimination_report(session, scope)
    stats = {result.key: result for result in report.results}
    _CACHE[scope] = (published, stats)
    return stats


def clear_cache() -> None:
    """For tests, and for a process that has just ingested a paper."""
    _CACHE.clear()


def _outcome(advice: str, is_true: bool) -> str:
    followed_and_right = (advice == "eliminate" and not is_true) or (
        advice == "keep" and is_true
    )
    return HELPED if followed_and_right else MISLED


async def question_lab(
    session: AsyncSession,
    question_id: int,
    *,
    scope: QuestionScope | None = None,
) -> QuestionLab | None:
    """Replay every rule against one published question. None if it does not exist."""
    question = (
        await session.execute(
            select(Question).where(
                Question.id == question_id,
                Question.status == QuestionStatus.published,
            )
        )
    ).scalar_one_or_none()
    if question is None:
        return None

    options = (
        (
            await session.execute(
                select(QuestionOption)
                .where(QuestionOption.question_id == question_id)
                .order_by(QuestionOption.option_label)
            )
        )
        .scalars()
        .all()
    )
    stats = await rule_statistics(session, scope)

    decoded = decode_question(
        question_id=question.id,
        year=question.year,
        question_number=question.question_number,
        stem_en=question.question_text_en,
        options=[(o.option_label, o.option_text_en, o.is_correct) for o in options],
    )

    statements = [
        LabStatement(index=r.index, text=r.text, is_true=r.is_true, is_claim=r.is_claim)
        for r in decoded.records
    ]
    firings: list[LabFiring] = []
    for record in decoded.records:
        if not record.is_claim:
            continue
        for rule in STATEMENT_RULES:
            if not rule.pattern.search(record.text):
                continue
            advice = "keep" if rule.claims_true else "eliminate"
            measured = stats.get(rule.key)
            firings.append(
                LabFiring(
                    rule_key=rule.key,
                    title_en=rule.title_en,
                    docx_claim=rule.docx_claim,
                    statement_index=record.index,
                    advice=advice,
                    outcome=_outcome(advice, record.is_true),
                    measured_rate=measured.rate if measured else None,
                    measured_baseline=measured.baseline if measured else None,
                    measured_verdict=measured.verdict if measured else None,
                    measured_n=measured.n if measured else 0,
                )
            )

    option_firings = _option_firings(options, stats)
    outcomes = [f.outcome for f in firings] + [f.outcome for f in option_firings]
    return QuestionLab(
        question_id=question.id,
        year=question.year,
        question_number=question.question_number,
        decodable=bool(decoded.records),
        skipped_reason=decoded.skipped,
        statements=statements,
        firings=firings,
        option_firings=option_firings,
        helped=sum(1 for o in outcomes if o == HELPED),
        misled=sum(1 for o in outcomes if o == MISLED),
    )


def _option_firings(
    options: list[QuestionOption], stats: dict[str, RuleResult]
) -> list[LabOptionFiring]:
    """The one option rule that reads as an instruction on a single question.

    The odd-one-out rule is deliberately left out: it always fires, on exactly one option
    of every question, so on a single screen it is indistinguishable from a coin toss with
    a caption. Its corpus figure (25.0% against a 24.9% null) is where it belongs.
    """
    correct = [o.option_label for o in options if o.is_correct]
    if len(correct) != 1:
        return []
    flagged = [
        o.option_label for o in options if COMPOUND_RE.search(o.option_text_en or "")
    ]
    if len(flagged) != 1:
        return []
    measured = stats.get("compound_nomenclature")
    outcome = HELPED if flagged[0] == correct[0] else MISLED
    return [
        LabOptionFiring(
            rule_key="compound_nomenclature",
            title_en="Option joins two entities with a hyphen",
            docx_claim="'usually the correct answer'",
            option_label=flagged[0],
            advice="pick",
            outcome=outcome,
            measured_rate=measured.rate if measured else None,
            measured_baseline=measured.baseline if measured else None,
            measured_verdict=measured.verdict if measured else None,
            measured_n=measured.n if measured else 0,
        )
    ]
