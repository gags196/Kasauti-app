"""The single definition of "which questions are in scope" for every intelligence query.

Rankings, coverage, trends, option patterns and topic profiles all need the same
thing: published questions, optionally narrowed to a topic subtree, a paper stage,
a subject, or a year range. Each one having written its own version is what let
`topic_importance` rank `gs3.science_technology` on **1** question while
`gather_topic_corpus` saw the **247** in its subtree. The fix is not to make two
queries agree — it is for there to be one.

Consumers compose against `question_ids(...)`, which returns a `Select` meant to be
used as a semi-join (`Question.id.in_(question_ids(scope))`) rather than executed.
"""

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import ColumnElement, Select, func, select
from sqlalchemy_utils import Ltree

from kasauti_api.db.models import Paper, Question, QuestionTopicMap, Topic
from kasauti_api.db.models.questions import QuestionStatus
from kasauti_api.db.models.taxonomy import Stage

# UPSC changed how it builds Prelims questions in 2022. Measured over the 1,400-question
# Paper 1 corpus, pre-2022 (n=900) against 2022+ (n=500): the "How many of the above"
# count format went 0% -> 18%, "Consider the following statements" 22% -> 40%, and the
# `subset_of_numbered` option family fell 56% -> 45%. A statistic pooled across that
# break describes an exam nobody is sitting, so every analysis is era-aware and "recent"
# is the default the product leads with.
#
# The subset figure was recorded here as "29% -> 15%" and reproduces under no definition
# of the family — before or after DERIVED_REV 3 corrected 2025's archetypes. The other
# two reproduce exactly. Re-measure a figure before citing it; `var/` scratch scripts do
# not survive a session but a wrong comment does.
PATTERN_ERA_START = 2022

# Papers that are published to learners but must never be pooled into an analysis
# unless they are asked for by name.
#
# Prelims Paper II is the case this exists for. It is a *qualifying* aptitude paper —
# comprehension, reasoning, numeracy — scored separately at 33% and contributing nothing
# to the merit list. Pooling it into the corpus would put csat.* rows in a ranking that
# claims to say what UPSC asks most, shrink every GS topic's share by the size of a paper
# that does not test GS at all, and hand the Elimination Lab eighty items whose options
# are built by different rules from the ones it is testing. None of that would raise an
# error; every number on /rankings, /trends, /patterns and /elimination would simply move.
#
# Naming a paper explicitly (`QuestionScope(paper_id=...)`) opts back in, which is how a
# future CSAT-specific analysis would ask for it.
EXCLUDED_FROM_ANALYSIS = ("prelims-gs2",)

Rollup = Literal["direct", "subtree"]
Era = Literal["all", "recent", "legacy"]

# Topic.depth counts labels *below* the subject root, so the tree is only two levels
# deep: 1 = branch (gs3.indian_economy), 2 = leaf (gs3.indian_economy.inclusive_growth).
# Subject roots (gs3) are not topic rows at all.
BRANCH_DEPTH = 1
LEAF_DEPTH = 2


def era_years(era: Era) -> tuple[int | None, int | None]:
    """Inclusive (year_from, year_to) bounds for an era name."""
    if era == "recent":
        return PATTERN_ERA_START, None
    if era == "legacy":
        return None, PATTERN_ERA_START - 1
    return None, None


@dataclass(frozen=True)
class QuestionScope:
    """Which published questions an intelligence query is about.

    `topic_path` + `rollup` select a topic (or its whole subtree); the rest narrow by
    paper and year. Explicit `year_from`/`year_to` win over `era` so a caller can ask
    for an arbitrary window without fighting the era default.
    """

    topic_path: str | None = None
    rollup: Rollup = "subtree"
    stage: Stage | None = None
    subject_id: int | None = None
    paper_id: int | None = None
    era: Era = "all"
    year_from: int | None = None
    year_to: int | None = None

    def years(self) -> tuple[int | None, int | None]:
        lo, hi = era_years(self.era)
        return (
            self.year_from if self.year_from is not None else lo,
            self.year_to if self.year_to is not None else hi,
        )

    def describe(self) -> str:
        """Human-readable scope line, so a report can never omit what it measured."""
        bits = []
        if self.topic_path:
            bits.append(f"{self.topic_path} ({self.rollup})")
        if self.stage is not None:
            bits.append(self.stage.value)
        if self.paper_id is None and EXCLUDED_FROM_ANALYSIS:
            bits.append("excluding " + ", ".join(EXCLUDED_FROM_ANALYSIS))
        lo, hi = self.years()
        if lo is not None or hi is not None:
            bits.append(f"{lo or 'earliest'}–{hi or 'latest'}")
        return ", ".join(bits) if bits else "all published questions"


def keyed_mcq_scope(
    *, era: Era = "all", topic_path: str | None = None
) -> QuestionScope:
    """Scope for an analysis that is answer-key machinery.

    Option-construction patterns, the Elimination Lab and per-statement decoding all work
    by reading the *official key*: which of the four printed options UPSC marked correct.
    Mains has no key and no options at all, so a Mains question is not a weak data point
    for these — it is not a data point at all.

    Excluding it has to be said out loud rather than left to `EXCLUDED_FROM_ANALYSIS`,
    which names only `prelims-gs2`. That list was written when Paper 1 and CSAT were the
    only two papers, so "everything except CSAT" and "Prelims Paper 1" were the same set.
    They stopped being the same set the day Mains GS1 was ingested, and nothing anywhere
    said so.

    Most of these analyses still *look* right, but only by accident: they filter on
    `QuestionProfile.correct_label IS NOT NULL`, which Mains rows happen to fail. The three
    that carry no such filter — `option_patterns.archetype_mix`, `.format_mix`, and the
    coverage table built by `elimination.load_statement_records` — were already counting
    ~1,800 keyless Mains rows into their `unknown` / `(no printed marker)` / "unkeyed or
    dropped" buckets. That is the proof the accident does not hold, so the pin is explicit
    here instead of implied by a NULL somewhere else.

    `describe()` reports the stage, so a report cannot print a scope line that omits it.
    """
    return QuestionScope(stage=Stage.prelims, era=era, topic_path=topic_path)


def topic_match(topic_path: str, rollup: Rollup = "subtree") -> ColumnElement[bool]:
    """Predicate on `Topic.path` for one topic, or that topic and everything under it."""
    path = Ltree(topic_path)
    return Topic.path == path if rollup == "direct" else Topic.path.descendant_of(path)


def question_conditions(scope: QuestionScope) -> list[ColumnElement[bool]]:
    """Filters that apply to Question/Paper columns only.

    Callers that have already joined `Paper` can splat these into their own `where`
    instead of paying for the `question_ids` semi-join.
    """
    conds: list[ColumnElement[bool]] = [Question.status == QuestionStatus.published]
    if scope.paper_id is not None:
        conds.append(Question.paper_id == scope.paper_id)
    elif EXCLUDED_FROM_ANALYSIS:
        # Only when no paper was named: asking for a paper by id is asking for it.
        conds.append(Paper.code.notin_(EXCLUDED_FROM_ANALYSIS))
    if scope.stage is not None:
        conds.append(Paper.stage == scope.stage)
    year_from, year_to = scope.years()
    if year_from is not None:
        conds.append(Question.year >= year_from)
    if year_to is not None:
        conds.append(Question.year <= year_to)
    return conds


def question_ids(scope: QuestionScope) -> Select:
    """`SELECT questions.id` for the scope — intended as a subquery, not executed.

    Distinct because a question tagged to two topics in the same subtree would
    otherwise be counted twice.
    """
    stmt = select(Question.id).join(Paper, Paper.id == Question.paper_id)
    if scope.topic_path is not None or scope.subject_id is not None:
        stmt = stmt.join(
            QuestionTopicMap, QuestionTopicMap.question_id == Question.id
        ).join(Topic, Topic.id == QuestionTopicMap.topic_id)
        if scope.topic_path is not None:
            stmt = stmt.where(topic_match(scope.topic_path, scope.rollup))
        if scope.subject_id is not None:
            stmt = stmt.where(Topic.subject_id == scope.subject_id)
    return stmt.where(*question_conditions(scope)).distinct()


def newest_year(scope: QuestionScope) -> Select:
    """`SELECT max(year)` **within the scope** — the anchor a relative year window
    must use.

    `topic_importance` previously anchored its `window_years` on the newest published
    question anywhere, so with Prelims 2026 loaded a `stage=mains, window_years=5`
    query was windowed against 2026 and returned nothing.
    """
    return select(func.max(Question.year)).where(Question.id.in_(question_ids(scope)))
