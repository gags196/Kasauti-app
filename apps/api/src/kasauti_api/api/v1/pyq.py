"""Phase-1 PYQ intelligence endpoints: rankings, topic analysis, one-pagers,
question detail, semantic search."""

import asyncio
import mimetypes
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from kasauti_api.db.base import get_session
from kasauti_api.db.models import (
    Question,
    QuestionStimulus,
    QuestionTopicMap,
    Topic,
    TopicAnalysis,
    TopicNote,
)
from kasauti_api.db.models.cost_ledger import LlmFeature
from kasauti_api.db.models.intelligence import AnalysisScope, TopicNoteStatus
from kasauti_api.db.models.questions import QuestionStatus, StimulusKind
from kasauti_api.db.models.taxonomy import Stage
from kasauti_api.domain.intelligence.elimination import VERDICT_LABELS
from kasauti_api.domain.intelligence.lab import question_lab, rule_statistics
from kasauti_api.domain.intelligence.option_patterns import (
    VERDICT_LABELS as PATTERN_VERDICT_LABELS,
)
from kasauti_api.domain.intelligence.option_patterns import (
    archetype_mix,
    option_pattern_report,
)
from kasauti_api.domain.intelligence.rankings import topic_importance
from kasauti_api.domain.intelligence.recurrence import corpus_recurrence, topic_recurrence
from kasauti_api.domain.intelligence.scope import (
    Era,
    QuestionScope,
    Rollup,
    era_years,
    keyed_mcq_scope,
)
from kasauti_api.domain.intelligence.topic_profile import (
    build_depth_profile,
    transfer_prediction,
)
from kasauti_api.domain.intelligence.trends import Dimension, era_shift, mix_by_year
from kasauti_api.domain.llm.cost_ledger import record_usage
from kasauti_api.domain.llm.embedding_provider import get_embedding_provider
from kasauti_api.domain.retrieval.hybrid_search import SearchFilters, search_questions
from kasauti_api.settings import get_settings
from kasauti_api.storage import download_bytes

router = APIRouter(prefix="/api/v1/pyq", tags=["pyq"])


# ---------- response models ----------


class TopicOut(BaseModel):
    id: int
    path: str
    depth: int
    slug: str
    name_en: str
    name_hi: str

    @classmethod
    def from_row(cls, t: Topic) -> "TopicOut":
        return cls(id=t.id, path=str(t.path), depth=t.depth, slug=t.slug,
                   name_en=t.name_en, name_hi=t.name_hi)


class RankingOut(BaseModel):
    topic_id: int
    path: str
    name_en: str
    name_hi: str
    # question_count is tags on this topic itself; subtree_count includes everything
    # below it. On branch topics they differ by an order of magnitude, because the
    # tagger almost always lands on a leaf — see rankings.py.
    question_count: int
    subtree_count: int
    depth: int
    latest_year: int
    # The same headline count split by stage, so an unstaged ranking can show what it is
    # made of instead of summing two exams into one bar. Sums to question_count under
    # rollup="direct" and to subtree_count under "subtree" — see RankedTopic.
    prelims_count: int
    mains_count: int


class AnalysisOut(BaseModel):
    topic_id: int
    scope: str
    generated_at: str
    question_count: int
    pattern_summary_en: str
    pattern_summary_hi: str
    predicted_angles: list[dict]
    prediction_outcomes: dict | None


class NoteOut(BaseModel):
    topic_id: int
    version: int
    generated_at: str
    question_count: int
    content_en: dict
    content_hi: dict


class OptionOut(BaseModel):
    label: str
    text_en: str | None
    text_hi: str | None
    is_correct: bool | None


class StimulusOut(BaseModel):
    """The passage or shared directions block this item is answered from.

    Null on every self-contained question, which is all of Prelims Paper I. It is a
    separate object rather than part of the text because one block serves several
    items — see db/models/questions.py::QuestionStimulus.
    """

    id: int
    kind: str
    text_en: str | None
    text_hi: str | None


class QuestionOut(BaseModel):
    id: int
    year: int
    paper_id: int
    question_number: str
    marks: float | None
    language: str
    text_en: str | None
    text_hi: str | None
    math_latex: str | None
    options: list[OptionOut]
    # Match-the-list and data tables, in the ExtractedTable shape. Kept as loose JSON
    # because the shape varies per question and nothing queries inside one.
    tables: list[dict]
    stimulus: StimulusOut | None
    topic_paths: list[str]


class SearchHitOut(BaseModel):
    question: QuestionOut
    score: float


class TrendCellOut(BaseModel):
    year: int
    bucket: str
    count: int
    share: float


class EraShiftOut(BaseModel):
    bucket: str
    legacy_count: int
    legacy_share: float
    recent_count: int
    recent_share: float
    delta: float


class TrendsOut(BaseModel):
    """Per-year mix of one question dimension, plus the 2022 era comparison.

    `profiled_share` and `note` are not decoration. The model-assigned dimensions are
    backfilled newest-first, so a chart drawn today covers part of the corpus, and a
    chart that does not say so implies coverage it does not have."""

    dimension: str
    scope_note: str
    years: list[int]
    buckets: list[str]
    total_by_year: dict[str, int]
    profiled_share: float
    note: str | None
    cells: list[TrendCellOut]
    shifts: list[EraShiftOut]


class PatternHypothesisOut(BaseModel):
    key: str
    title_en: str
    n: int
    hits: int
    rate: float
    baseline: float
    baseline_basis: str
    p_value: float | None
    verdict: str
    verdict_label: str
    note: str | None


class PatternsOut(BaseModel):
    """Feature A2: does the *construction* of the options leak the answer?

    This is the founder's fourth question — same-letter answers, odd-one-out, the
    unfamiliar-three tell, dated options — measured rather than asserted. The baseline is
    never a flat 25%: it is built by permuting which option is correct within each option
    archetype, because "Both 1 and 2" is mechanically the longest string in half the
    corpus."""

    scope_note: str
    keyed_questions: int
    year_from: int | None
    year_to: int | None
    alpha: float
    label_distribution: dict[str, int]
    label_chi2_p: float
    archetype_mix: dict[str, int]
    hypotheses: list[PatternHypothesisOut]


class YearCountOut(BaseModel):
    year: int
    count: int


class BranchCoverageOut(BaseModel):
    topic_id: int
    path: str
    name_en: str
    name_hi: str
    depth: int
    direct_count: int
    subtree_count: int
    first_year: int | None
    latest_year: int | None
    probe_status: str


class RepeatedPairOut(BaseModel):
    similarity: float
    earlier_id: int
    earlier_year: int
    earlier_text: str | None
    later_id: int
    later_year: int
    later_text: str | None
    years_apart: int


class DepthProfileOut(BaseModel):
    """How deeply a topic has been probed, and where it has not been.

    `profiled_count` is deliberately separate from `question_count`: the cognitive half
    of this profile depends on a classification pass that has not run, and the mixes must
    say which subset they describe rather than implying the whole topic."""

    topic_id: int
    path: str
    name_en: str
    name_hi: str
    question_count: int
    profiled_count: int
    probe_status: str
    first_year: int | None
    latest_year: int | None
    gap_years: list[int]
    format_mix: dict[str, int]
    depth_mix: dict[str, int]
    archetype_mix: dict[str, int]
    mean_statement_count: float | None
    recurrence_rate: float | None
    year_counts: list[YearCountOut]
    branches: list[BranchCoverageOut]
    repeats: list[RepeatedPairOut]


class PeerTopicOut(BaseModel):
    topic_id: int
    path: str
    name_en: str
    name_hi: str
    subtree_count: int
    profiled_count: int
    basis: str


class ProjectionOut(BaseModel):
    """What comparable topics suggest this one will be examined like.

    Entirely deterministic — the peers' *measured* mix, never a model's speculation — so
    the claim is "topics like this one are examined this way", which the corpus supports,
    and not "this will be asked", which it does not. `confidence_note` always travels
    with it: a projection from three peers is not the same object as one from thirty."""

    topic_id: int
    peers: list[PeerTopicOut]
    peer_question_count: int
    expected_format_mix: dict[str, float]
    expected_depth_mix: dict[str, float]
    expected_questions_per_year: float | None
    untouched_branches: list[BranchCoverageOut]
    confidence_note: str


class TopicRecurrenceOut(BaseModel):
    topic_id: int
    path: str
    questions: int
    recurring: int
    rate: float


class RecurrenceOut(BaseModel):
    """Which topics ask the same question twice, and at what similarity 'twice' means.

    The curve is reported alongside the rates because "questions repeat" is only a
    meaningful claim next to how alike 'repeat' was taken to mean."""

    threshold: float
    curve: dict[str, int]
    corpus_questions: int
    topics: list[TopicRecurrenceOut]


class RuleStatOut(BaseModel):
    """One elimination rule as measured over the corpus.

    `verdict` and `verdict_label` travel with every rule everywhere it is shown. The
    whole feature rests on a learner never seeing a rule fire without seeing how often
    it is actually right — see `domain/intelligence/lab.py`."""

    key: str
    title_en: str
    docx_claim: str
    family: str
    n: int
    rate: float
    baseline: float
    p_value: float | None
    verdict: str
    verdict_label: str
    note: str | None


class LabStatementOut(BaseModel):
    index: int
    text: str
    is_true: bool
    is_claim: bool


class LabFiringOut(BaseModel):
    rule_key: str
    title_en: str
    docx_claim: str
    # Exactly one of these is set: a statement rule points at a numbered statement, an
    # option rule at an option label.
    statement_index: int | None
    option_label: str | None
    advice: str
    outcome: str
    measured_rate: float | None
    measured_baseline: float | None
    measured_verdict: str | None
    measured_n: int


class QuestionLabOut(BaseModel):
    question_id: int
    year: int
    question_number: str
    decodable: bool
    # The decoder's own words when the answer key cannot pin the statements — about half
    # the corpus prints no numbered statements at all, and saying so is the honest answer.
    skipped_reason: str | None
    statements: list[LabStatementOut]
    firings: list[LabFiringOut]
    helped: int
    misled: int


# ---------- endpoints ----------


@router.get("/topics", response_model=list[TopicOut])
async def list_topics(
    subject_id: int | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[TopicOut]:
    stmt = select(Topic).order_by(Topic.path)
    if subject_id is not None:
        stmt = stmt.where(Topic.subject_id == subject_id)
    topics = (await session.execute(stmt)).scalars().all()
    return [TopicOut.from_row(t) for t in topics]


@router.get("/rankings", response_model=list[RankingOut])
async def rankings(
    window: Literal["all", "5y"] = "all",
    era: Era = "all",
    stage: Literal["prelims", "mains"] | None = None,
    subject_id: int | None = None,
    rollup: Rollup = "direct",
    max_depth: int | None = Query(default=None, ge=1, le=2),
    limit: int = Query(default=50, le=200),
    session: AsyncSession = Depends(get_session),
) -> list[RankingOut]:
    """Topic importance ranking — the shared Prelims/Mains view (MVP Feature A1/B).

    `era=recent` restricts to 2022+, where UPSC's question construction visibly changed.
    `rollup=subtree` ranks branch topics by everything beneath them; pair it with
    `max_depth=1` for a non-overlapping list of branches, since otherwise a parent and
    its children all appear and the parent's count includes the children's.
    """
    year_from, year_to = era_years(era)
    ranked = await topic_importance(
        session,
        subject_id=subject_id,
        stage=Stage(stage) if stage else None,
        window_years=5 if window == "5y" else None,
        rollup=rollup,
        max_depth=max_depth,
        year_from=year_from,
        year_to=year_to,
        limit=limit,
    )
    return [RankingOut(**r.__dict__) for r in ranked]


@router.get("/topics/{topic_id}/analysis", response_model=AnalysisOut)
async def topic_analysis(
    topic_id: int,
    scope: Literal["prelims", "mains", "combined"] = "combined",
    session: AsyncSession = Depends(get_session),
) -> AnalysisOut:
    analysis = (
        await session.execute(
            select(TopicAnalysis)
            .where(
                TopicAnalysis.topic_id == topic_id,
                TopicAnalysis.scope == AnalysisScope(scope),
                # Backtest analyses are generated blind to recent years and written after
                # the live one, so without this they would win "newest" and be served to
                # learners as the current view.
                TopicAnalysis.is_backtest.is_(False),
            )
            .order_by(TopicAnalysis.generated_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if analysis is None:
        raise HTTPException(404, "No analysis generated for this topic/scope yet")
    return AnalysisOut(
        topic_id=analysis.topic_id,
        scope=analysis.scope.value,
        generated_at=analysis.generated_at.isoformat(),
        question_count=analysis.question_count,
        pattern_summary_en=analysis.pattern_summary_en,
        pattern_summary_hi=analysis.pattern_summary_hi,
        predicted_angles=analysis.predicted_angles,
        prediction_outcomes=analysis.prediction_outcomes,
    )


@router.get("/topics/{topic_id}/note", response_model=NoteOut)
async def topic_note(
    topic_id: int,
    session: AsyncSession = Depends(get_session),
) -> NoteOut:
    note = (
        await session.execute(
            select(TopicNote)
            .where(
                TopicNote.topic_id == topic_id,
                TopicNote.status == TopicNoteStatus.published,
            )
            .order_by(TopicNote.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if note is None:
        raise HTTPException(404, "No published one-pager for this topic yet")
    return NoteOut(
        topic_id=note.topic_id,
        version=note.version,
        generated_at=note.generated_at.isoformat(),
        question_count=note.question_count,
        content_en=note.content_en,
        content_hi=note.content_hi,
    )


def _question_out(q: Question) -> QuestionOut:
    return QuestionOut(
        id=q.id,
        year=q.year,
        paper_id=q.paper_id,
        question_number=q.question_number,
        marks=float(q.marks) if q.marks is not None else None,
        language=q.language.value,
        text_en=q.question_text_en,
        text_hi=q.question_text_hi,
        math_latex=q.math_notation_latex,
        options=[
            OptionOut(label=o.option_label, text_en=o.option_text_en,
                      text_hi=o.option_text_hi, is_correct=o.is_correct)
            for o in sorted(q.options, key=lambda o: o.option_label)
        ],
        tables=q.tables or [],
        stimulus=(
            StimulusOut(
                id=q.stimulus.id,
                kind=q.stimulus.kind.value,
                text_en=q.stimulus.text_en,
                text_hi=q.stimulus.text_hi,
            )
            if q.stimulus is not None
            else None
        ),
        topic_paths=[str(m.topic.path) for m in q.topic_maps if m.topic is not None],
    )


_QUESTION_LOAD = (
    selectinload(Question.options),
    selectinload(Question.stimulus),
    selectinload(Question.topic_maps).selectinload(QuestionTopicMap.topic),
)


@router.get("/questions/{question_id}", response_model=QuestionOut)
async def get_question(
    question_id: int,
    session: AsyncSession = Depends(get_session),
) -> QuestionOut:
    question = (
        await session.execute(
            select(Question)
            .options(*_QUESTION_LOAD)
            .where(Question.id == question_id, Question.status == QuestionStatus.published)
        )
    ).scalar_one_or_none()
    if question is None:
        raise HTTPException(404, "Question not found")
    return _question_out(question)


@router.get("/figures/{stimulus_id}")
async def get_figure(
    stimulus_id: int,
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Stream a cropped diagram (route-counting grids, growth curves, and the like)
    out of R2. Content-addressed by stimulus id, so a long cache lifetime is safe —
    an asset never changes under an id, only gets attached once by
    scripts/attach_figure.py.
    """
    stimulus = (
        await session.execute(
            select(QuestionStimulus).where(QuestionStimulus.id == stimulus_id)
        )
    ).scalar_one_or_none()
    if (
        stimulus is None
        or stimulus.kind != StimulusKind.figure
        or not stimulus.asset_key
    ):
        raise HTTPException(404, "No figure for this stimulus")

    data = await asyncio.to_thread(
        download_bytes, get_settings().r2_bucket_question_assets, stimulus.asset_key
    )
    content_type = mimetypes.guess_type(stimulus.asset_key)[0] or "application/octet-stream"
    return Response(
        content=data,
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@router.get("/search", response_model=list[SearchHitOut])
async def search(
    query: str = Query(min_length=2),
    topic_path: str | None = None,
    paper_id: int | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    k: int = Query(default=20, le=50),
    session: AsyncSession = Depends(get_session),
) -> list[SearchHitOut]:
    """Cross-lingual semantic search: query in Hindi or English, matches both."""
    provider = get_embedding_provider()
    vectors, usage = await provider.embed([query], input_type="query")
    await record_usage(session, feature=LlmFeature.embedding, usage=usage,
                       related_entity_type="search_query")
    await session.commit()

    hits = await search_questions(
        session,
        query_embedding=vectors[0],
        filters=SearchFilters(
            paper_id=paper_id, topic_path=topic_path,
            year_from=year_from, year_to=year_to,
            embedding_model=provider.model_name,
        ),
        k=k,
    )
    # Re-fetch with option/topic eager loads for serialization
    ids = [h.question.id for h in hits]
    questions = {
        q.id: q
        for q in (
            await session.execute(
                select(Question).options(*_QUESTION_LOAD).where(Question.id.in_(ids))
            )
        ).scalars()
    }
    return [
        SearchHitOut(question=_question_out(questions[h.question.id]), score=h.score)
        for h in hits
        if h.question.id in questions
    ]


@router.get("/elimination/rules", response_model=list[RuleStatOut])
async def elimination_rules(
    era: Era = "all",
    session: AsyncSession = Depends(get_session),
) -> list[RuleStatOut]:
    """Every elimination rule with its measured rate, baseline and verdict.

    Fifteen rules from the coaching circuit; one reaches significance over all fourteen
    years and none does from 2022 onwards. Pass `era=recent` to see that directly.
    """
    stats = await rule_statistics(session, keyed_mcq_scope(era=era))
    return [
        RuleStatOut(
            key=r.key, title_en=r.title_en, docx_claim=r.docx_claim, family=r.family,
            n=r.n, rate=r.rate, baseline=r.baseline, p_value=r.p_value,
            verdict=r.verdict, verdict_label=VERDICT_LABELS[r.verdict], note=r.note,
        )
        for r in stats.values()
    ]


@router.get("/questions/{question_id}/elimination", response_model=QuestionLabOut)
async def question_elimination(
    question_id: int,
    era: Era = "all",
    session: AsyncSession = Depends(get_session),
) -> QuestionLabOut:
    """Replay the elimination rules against one question, beside the official key."""
    lab = await question_lab(session, question_id, scope=keyed_mcq_scope(era=era))
    if lab is None:
        raise HTTPException(404, "Question not found")
    firings = [
        LabFiringOut(
            rule_key=f.rule_key, title_en=f.title_en, docx_claim=f.docx_claim,
            statement_index=f.statement_index, option_label=None,
            advice=f.advice, outcome=f.outcome, measured_rate=f.measured_rate,
            measured_baseline=f.measured_baseline, measured_verdict=f.measured_verdict,
            measured_n=f.measured_n,
        )
        for f in lab.firings
    ] + [
        LabFiringOut(
            rule_key=f.rule_key, title_en=f.title_en, docx_claim=f.docx_claim,
            statement_index=None, option_label=f.option_label,
            advice=f.advice, outcome=f.outcome, measured_rate=f.measured_rate,
            measured_baseline=f.measured_baseline, measured_verdict=f.measured_verdict,
            measured_n=f.measured_n,
        )
        for f in lab.option_firings
    ]
    return QuestionLabOut(
        question_id=lab.question_id, year=lab.year,
        question_number=lab.question_number, decodable=lab.decodable,
        skipped_reason=lab.skipped_reason,
        statements=[
            LabStatementOut(index=s.index, text=s.text, is_true=s.is_true,
                            is_claim=s.is_claim)
            for s in lab.statements
        ],
        firings=firings, helped=lab.helped, misled=lab.misled,
    )


@router.get("/trends", response_model=TrendsOut)
async def trends(
    dimension: Dimension = "regex_format",
    stage: Literal["prelims", "mains"] | None = None,
    topic_path: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> TrendsOut:
    """How the mix of question types has moved year by year, and across the 2022 break.

    Defaults to `stage=prelims` rather than to the whole corpus. Every `Dimension` here
    reads an MCQ-derived `question_profiles` column, so an unpinned scope does not widen
    the analysis, it dilutes it: the ~1,800 keyless Mains questions all land in the same
    "(no printed marker)" bucket and swamp the Prelims format mix this page exists to show.
    Pass `stage=mains` explicitly to see what those columns hold for Mains — which today
    is almost nothing, and is the Mains-analytics build, not this endpoint.
    """
    scope = QuestionScope(
        topic_path=topic_path, stage=Stage(stage) if stage else Stage.prelims
    )
    series = await mix_by_year(session, dimension=dimension, scope=scope)
    shifts = await era_shift(session, dimension=dimension, scope=scope)
    return TrendsOut(
        dimension=series.dimension,
        scope_note=series.scope_note,
        years=series.years,
        buckets=series.buckets,
        total_by_year={str(y): n for y, n in series.total_by_year.items()},
        profiled_share=series.profiled_share,
        note=series.note,
        cells=[
            TrendCellOut(year=c.year, bucket=c.bucket, count=c.count, share=c.share)
            for c in series.cells
        ],
        shifts=[
            EraShiftOut(
                bucket=sh.bucket,
                legacy_count=sh.legacy_count, legacy_share=sh.legacy_share,
                recent_count=sh.recent_count, recent_share=sh.recent_share,
                delta=sh.delta,
            )
            for sh in shifts
        ],
    )


@router.get("/patterns", response_model=PatternsOut)
async def patterns(
    era: Era = "all",
    session: AsyncSession = Depends(get_session),
) -> PatternsOut:
    """Option-construction patterns (Feature A2), with honest verdicts."""
    scope = keyed_mcq_scope(era=era)
    report = await option_pattern_report(session, scope)
    mix = await archetype_mix(session, scope)
    return PatternsOut(
        scope_note=report.scope_note,
        keyed_questions=report.keyed_questions,
        year_from=report.year_from,
        year_to=report.year_to,
        alpha=report.alpha,
        label_distribution=report.label_distribution,
        label_chi2_p=report.label_chi2[2],
        archetype_mix=mix,
        hypotheses=[
            PatternHypothesisOut(
                key=h.key, title_en=h.title_en, n=h.n, hits=h.hits, rate=h.rate,
                baseline=h.baseline, baseline_basis=h.baseline_basis,
                p_value=h.p_value, verdict=h.verdict,
                verdict_label=PATTERN_VERDICT_LABELS[h.verdict], note=h.note,
            )
            for h in report.hypotheses
        ],
    )


@router.get("/recurrence", response_model=RecurrenceOut)
async def recurrence(
    stage: Literal["prelims", "mains"] | None = None,
    threshold: float = Query(default=0.75, ge=0.5, le=0.99),
    min_questions: int = Query(default=10, ge=3),
    session: AsyncSession = Depends(get_session),
) -> RecurrenceOut:
    """Which topics ask the same question archetype twice."""
    stage_value = Stage(stage) if stage else None
    rows = await topic_recurrence(
        session, stage=stage_value, threshold=threshold, min_questions=min_questions
    )
    curve = await corpus_recurrence(session, stage=stage_value)
    return RecurrenceOut(
        threshold=threshold,
        curve={f"{t:.2f}": n for t, n in curve.items()},
        corpus_questions=sum(r.questions for r in rows),
        topics=[
            TopicRecurrenceOut(
                topic_id=r.topic_id, path=r.path, questions=r.questions,
                recurring=r.recurring, rate=r.rate,
            )
            for r in rows
        ],
    )


def _branch_out(branch) -> BranchCoverageOut:
    return BranchCoverageOut(
        topic_id=branch.topic_id, path=branch.path, name_en=branch.name_en,
        name_hi=branch.name_hi, depth=branch.depth, direct_count=branch.direct_count,
        subtree_count=branch.subtree_count, first_year=branch.first_year,
        latest_year=branch.latest_year, probe_status=branch.probe_status,
    )


async def _topic_or_404(session: AsyncSession, topic_id: int) -> Topic:
    topic = (
        await session.execute(select(Topic).where(Topic.id == topic_id))
    ).scalar_one_or_none()
    if topic is None:
        raise HTTPException(404, "Topic not found")
    return topic


@router.get("/topics/{topic_id}/profile", response_model=DepthProfileOut)
async def topic_profile(
    topic_id: int,
    stage: Literal["prelims", "mains"] | None = None,
    session: AsyncSession = Depends(get_session),
) -> DepthProfileOut:
    """The depth profile: how far a topic has been probed, and where it has not."""
    topic = await _topic_or_404(session, topic_id)
    profile = await build_depth_profile(
        session, topic, stage=Stage(stage) if stage else None
    )
    return DepthProfileOut(
        topic_id=profile.topic_id, path=profile.path, name_en=profile.name_en,
        name_hi=profile.name_hi, question_count=profile.question_count,
        profiled_count=profile.profiled_count, probe_status=profile.probe_status,
        first_year=profile.first_year, latest_year=profile.latest_year,
        gap_years=profile.gap_years, format_mix=profile.format_mix,
        depth_mix=profile.depth_mix, archetype_mix=profile.archetype_mix,
        mean_statement_count=profile.mean_statement_count,
        recurrence_rate=profile.recurrence_rate,
        year_counts=[
            YearCountOut(year=yc.year, count=yc.count) for yc in profile.year_counts
        ],
        branches=[_branch_out(b) for b in profile.branches],
        repeats=[
            RepeatedPairOut(
                similarity=r.similarity, earlier_id=r.earlier_id,
                earlier_year=r.earlier_year, earlier_text=r.earlier_text,
                later_id=r.later_id, later_year=r.later_year, later_text=r.later_text,
                years_apart=r.years_apart,
            )
            for r in profile.repeats
        ],
    )


@router.get("/topics/{topic_id}/projection", response_model=ProjectionOut)
async def topic_projection(
    topic_id: int,
    stage: Literal["prelims", "mains"] | None = None,
    session: AsyncSession = Depends(get_session),
) -> ProjectionOut:
    """What comparable topics suggest about how this one will be examined."""
    topic = await _topic_or_404(session, topic_id)
    projection = await transfer_prediction(
        session, topic, stage=Stage(stage) if stage else None
    )
    return ProjectionOut(
        topic_id=projection.topic_id,
        peers=[
            PeerTopicOut(
                topic_id=p.topic_id, path=p.path, name_en=p.name_en, name_hi=p.name_hi,
                subtree_count=p.subtree_count, profiled_count=p.profiled_count,
                basis=p.basis,
            )
            for p in projection.peers
        ],
        peer_question_count=projection.peer_question_count,
        expected_format_mix=projection.expected_format_mix,
        expected_depth_mix=projection.expected_depth_mix,
        expected_questions_per_year=projection.expected_questions_per_year,
        untouched_branches=[_branch_out(b) for b in projection.untouched_branches],
        confidence_note=projection.confidence_note,
    )
