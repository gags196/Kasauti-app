"""Ranking + topic-analysis + one-pager jobs against local Postgres with a
fake LLM provider. Requires the taxonomy seed."""

import pytest
from kasauti_api.db.base import async_session_factory
from kasauti_api.db.models import (
    Exam,
    LlmUsageEvent,
    Paper,
    Question,
    QuestionTopicMap,
    Topic,
    TopicAnalysis,
    TopicNote,
)
from kasauti_api.db.models.intelligence import TopicNoteStatus
from kasauti_api.db.models.questions import QuestionLanguage, QuestionStatus, TaggedBy
from kasauti_api.db.models.taxonomy import Stage
from kasauti_api.domain.intelligence.generation import gather_topic_corpus
from kasauti_api.domain.intelligence.option_patterns import archetype_mix, format_mix
from kasauti_api.domain.intelligence.rankings import (
    RankedTopic,
    drop_redundant_parents,
    topic_importance,
)
from kasauti_api.domain.intelligence.scope import (
    QuestionScope,
    keyed_mcq_scope,
    question_ids,
)
from kasauti_api.domain.llm.provider import LlmUsage
from kasauti_api.domain.llm.schemas import (
    OnePagerContent,
    OnePagerResult,
    OnePagerSection,
    PredictedAngle,
    TopicAnalysisResult,
)
from kasauti_api.workers.intelligence_tasks import analyze_topic, generate_topic_note
from sqlalchemy import delete, func, select
from sqlalchemy_utils import Ltree

FAKE_USAGE = LlmUsage(provider="anthropic", model="claude-sonnet-5",
                      input_tokens=2000, output_tokens=800)

TOPIC_PATH = "gs2.constitution.basic_structure"
PARENT_PATH = "gs2.constitution"


class FakeIntelProvider:
    async def parse_structured(self, *, prompt, schema, documents=None, system=None,
                               tier="standard", max_tokens=16000):
        if schema is TopicAnalysisResult:
            return (
                TopicAnalysisResult(
                    pattern_summary_en="Asked in 2016, 2019 and 2023; framing shifted "
                    "from doctrine recall to applied federalism scenarios.",
                    pattern_summary_hi="2016, 2019 और 2023 में पूछा गया; प्रश्नों का झुकाव "
                    "सिद्धांत से अनुप्रयोग की ओर रहा है।",
                    predicted_angles=[
                        PredictedAngle(
                            angle_en="Basic structure vs recent tribunal reforms",
                            angle_hi="मूल संरचना बनाम हालिया अधिकरण सुधार",
                            rationale_en="Applied-scenario framing rising since 2019",
                        )
                    ],
                ),
                FAKE_USAGE,
            )
        if schema is OnePagerResult:
            content_en = OnePagerContent(
                title="Basic Structure Doctrine",
                overview="The judicially evolved limit on Parliament's amending power.",
                sections=[
                    OnePagerSection(
                        heading="Anchor facts",
                        points=["Kesavananda Bharati (1973)", "Article 368"],
                    )
                ],
                keywords=["Kesavananda", "Article 368"],
            )
            content_hi = OnePagerContent(
                title="मूल संरचना सिद्धांत",
                overview="संसद की संशोधन शक्ति पर न्यायिक रूप से विकसित सीमा।",
                sections=[
                    OnePagerSection(
                        heading="मुख्य तथ्य",
                        points=["केशवानंद भारती (1973)", "अनुच्छेद 368"],
                    )
                ],
                keywords=["केशवानंद", "अनुच्छेद 368"],
            )
            return OnePagerResult(content_en=content_en, content_hi=content_hi), FAKE_USAGE
        raise AssertionError(f"unexpected schema {schema}")


async def _baselines(session, topic) -> tuple[int, int, int]:
    """Counts already attributable to this topic before the test inserts anything:
    (all-time mains ranking, 5-year mains ranking, mains corpus size)."""

    def count_for(ranked) -> int:
        return next((r.question_count for r in ranked if r.topic_id == topic.id), 0)

    all_time = count_for(await topic_importance(session, stage=Stage.mains, limit=200))
    five_year = count_for(
        await topic_importance(session, stage=Stage.mains, window_years=5, limit=200)
    )
    corpus = len(await gather_topic_corpus(session, topic, stage=Stage.mains))
    return all_time, five_year, corpus


async def _rollup_counts(session, topic_id: int, *, rollup="subtree") -> tuple[int, int]:
    """(direct, subtree) for one topic, or (0, 0) if it is not in the ranking."""
    ranked = await topic_importance(
        session, stage=Stage.mains, rollup=rollup, limit=1000
    )
    row = next((r for r in ranked if r.topic_id == topic_id), None)
    return (0, 0) if row is None else (row.question_count, row.subtree_count)


def _ranked(path: str, subtree: int) -> RankedTopic:
    return RankedTopic(
        topic_id=abs(hash(path)) % 100_000, path=path, name_en=path, name_hi=path,
        question_count=0, latest_year=2026, subtree_count=subtree,
        depth=path.count(".") ,
    )


def test_drop_redundant_parents():
    """Pure unit test: the live corpus never triggers this rule (every branch
    aggregates more than any one child), so it would otherwise ship unexercised."""
    # gs2.social_justice holds nothing of its own — its whole corpus is one leaf's.
    redundant = [
        _ranked("gs2.social_justice", 43),
        _ranked("gs2.social_justice.health_education", 43),
    ]
    assert [t.path for t in drop_redundant_parents(redundant)] == [
        "gs2.social_justice.health_education"
    ]

    # A branch that genuinely aggregates two leaves is kept alongside them.
    aggregating = [
        _ranked("gs3.science_technology", 247),
        _ranked("gs3.science_technology.general_science", 98),
        _ranked("gs3.science_technology.it_space_computers", 62),
    ]
    assert len(drop_redundant_parents(aggregating)) == 3

    # A same-count topic that is *not* a descendant must not trigger the skip —
    # "gs2.polity" is not a prefix-path of "gs2.polity_reforms".
    coincidence = [_ranked("gs2.polity", 55), _ranked("gs2.polity_reforms", 55)]
    assert len(drop_redundant_parents(coincidence)) == 2


@pytest.mark.asyncio
async def test_subtree_rollup_reaches_parent_topics():
    """A question tagged to a leaf must count toward its parent's subtree, but not
    toward the parent's direct count.

    This is the bug the ranking shipped with: `topic_importance` counted direct tags
    only, so `gs3.science_technology` ranked on 1 question while 247 sat on its leaves.
    """
    async with async_session_factory() as session:
        exam = (
            await session.execute(select(Exam).where(Exam.code == "upsc-cse"))
        ).scalar_one_or_none()
        if exam is None:
            pytest.skip("taxonomy not seeded — run scripts/seed_taxonomy.py")
        mains = (
            await session.execute(
                select(Paper).where(Paper.exam_id == exam.id, Paper.code == "mains-gs2")
            )
        ).scalar_one()
        leaf = (
            await session.execute(select(Topic).where(Topic.path == Ltree(TOPIC_PATH)))
        ).scalar_one()
        parent = (
            await session.execute(
                select(Topic).where(Topic.path == Ltree(PARENT_PATH))
            )
        ).scalar_one()
        leaf_id, parent_id = leaf.id, parent.id

        base_leaf = await _rollup_counts(session, leaf_id)
        base_parent = await _rollup_counts(session, parent_id)

        q_ids = []
        for n in range(3):
            q = Question(
                exam_id=exam.id, paper_id=mains.id, year=2020 + n,
                question_number=f"rollup-{n}", marks=15, language=QuestionLanguage.en,
                question_text_en="Rollup fixture question.",
                status=QuestionStatus.published,
            )
            session.add(q)
            await session.flush()
            session.add(QuestionTopicMap(question_id=q.id, topic_id=leaf_id,
                                         confidence=1.0, tagged_by=TaggedBy.human))
            q_ids.append(q.id)
        await session.commit()

    try:
        async with async_session_factory() as session:
            leaf_direct, leaf_subtree = await _rollup_counts(session, leaf_id)
            parent_direct, parent_subtree = await _rollup_counts(session, parent_id)

        assert leaf_direct == base_leaf[0] + 3
        assert leaf_subtree == base_leaf[1] + 3
        # Nothing was tagged to the parent itself...
        assert parent_direct == base_parent[0]
        # ...but its subtree saw all three.
        assert parent_subtree == base_parent[1] + 3
    finally:
        async with async_session_factory() as session:
            await session.execute(
                delete(QuestionTopicMap).where(QuestionTopicMap.question_id.in_(q_ids))
            )
            await session.execute(delete(Question).where(Question.id.in_(q_ids)))
            await session.commit()


@pytest.mark.asyncio
async def test_ranking_analysis_and_one_pager():
    async with async_session_factory() as session:
        exam = (
            await session.execute(select(Exam).where(Exam.code == "upsc-cse"))
        ).scalar_one_or_none()
        if exam is None:
            pytest.skip("taxonomy not seeded — run scripts/seed_taxonomy.py")
        mains = (
            await session.execute(
                select(Paper).where(Paper.exam_id == exam.id, Paper.code == "mains-gs2")
            )
        ).scalar_one()
        topic = (
            await session.execute(select(Topic).where(Topic.path == Ltree(TOPIC_PATH)))
        ).scalar_one()
        topic_id = topic.id

        # The local DB is shared with demo fixtures and real ingested questions,
        # so this test asserts on the delta it creates, never on absolute counts.
        base_all, base_5y, base_corpus = await _baselines(session, topic)
        # Rows that already existed, so cleanup only removes what this test made.
        pre_analyses = set(
            (
                await session.execute(
                    select(TopicAnalysis.id).where(TopicAnalysis.topic_id == topic_id)
                )
            ).scalars()
        )
        pre_notes = set(
            (
                await session.execute(
                    select(TopicNote.id).where(TopicNote.topic_id == topic_id)
                )
            ).scalars()
        )

        # Anchor years to the newest published question *in the scope this test queries*
        # — mains — not to the newest anywhere. `topic_importance` anchors its 5-year
        # window inside the scope too (see newest_year), so anchoring on a global max that
        # Prelims 2026 owns would insert a mains question newer than any real one, shift
        # the window a year forward, and drop the oldest year out of it. The baselines were
        # measured against the unshifted window, so the deltas below would not add up.
        # This was invisible until Mains was ingested: before that this topic had no mains
        # questions at all, so every baseline was 0 and any window agreed.
        newest = (
            await session.execute(
                select(func.max(Question.year))
                .join(Paper, Paper.id == Question.paper_id)
                .where(
                    Question.status == QuestionStatus.published,
                    Paper.stage == Stage.mains,
                )
            )
        ).scalar() or 2023
        # in 5y window: newest, newest-4 · outside: newest-9
        years = (newest, newest - 4, newest - 9)

        q_ids = []
        for year in years:
            q = Question(
                exam_id=exam.id, paper_id=mains.id, year=year, question_number="3",
                marks=15, language=QuestionLanguage.en,
                question_text_en=f"Discuss the basic structure doctrine ({year}).",
                status=QuestionStatus.published,
            )
            session.add(q)
            await session.flush()
            session.add(QuestionTopicMap(question_id=q.id, topic_id=topic.id,
                                         confidence=1.0, tagged_by=TaggedBy.human))
            q_ids.append(q.id)
        await session.commit()

    try:
        async with async_session_factory() as session:
            ranking = await topic_importance(session, stage=Stage.mains, limit=200)
            top = next(r for r in ranking if r.topic_id == topic_id)
            assert top.question_count == base_all + 3
            assert top.latest_year == newest

            recent = await topic_importance(
                session, stage=Stage.mains, window_years=5, limit=200
            )
            r = next(x for x in recent if x.topic_id == topic_id)
            assert r.question_count == base_5y + 2

        fake = FakeIntelProvider()
        result = await analyze_topic({"llm_provider": fake}, topic_id, "mains")
        assert "analysis stored" in result
        result = await generate_topic_note({"llm_provider": fake}, topic_id)
        assert "one-pager v" in result

        async with async_session_factory() as session:
            # Newest row is the one this test just generated; the topic may
            # already carry earlier analyses/notes from other data.
            analysis = (
                await session.execute(
                    select(TopicAnalysis)
                    .where(TopicAnalysis.topic_id == topic_id)
                    .order_by(TopicAnalysis.id.desc())
                    .limit(1)
                )
            ).scalar_one()
            assert analysis.question_count == base_corpus + 3
            assert analysis.predicted_angles[0]["angle_hi"].startswith("मूल संरचना")

            note = (
                await session.execute(
                    select(TopicNote)
                    .where(TopicNote.topic_id == topic_id)
                    .order_by(TopicNote.version.desc())
                    .limit(1)
                )
            ).scalar_one()
            assert note.status == TopicNoteStatus.draft
            assert note.content_hi["title"] == "मूल संरचना सिद्धांत"
    finally:
        async with async_session_factory() as session:
            await session.execute(
                delete(TopicAnalysis).where(
                    TopicAnalysis.topic_id == topic_id,
                    TopicAnalysis.id.notin_(pre_analyses),
                )
            )
            await session.execute(
                delete(TopicNote).where(
                    TopicNote.topic_id == topic_id, TopicNote.id.notin_(pre_notes)
                )
            )
            await session.execute(
                delete(QuestionTopicMap).where(QuestionTopicMap.question_id.in_(q_ids))
            )
            await session.execute(
                delete(LlmUsageEvent).where(
                    LlmUsageEvent.related_entity_type == "topic",
                    LlmUsageEvent.related_entity_id == str(topic_id),
                )
            )
            await session.execute(delete(Question).where(Question.id.in_(q_ids)))
            await session.commit()


@pytest.mark.asyncio
async def test_qualifying_paper_is_out_of_the_default_analysis_corpus():
    """Prelims Paper II is published to learners but is not part of any analysis.

    It is a qualifying aptitude paper: pooling it would put csat.* rows in a ranking
    that claims to say what UPSC asks most, and would move every number on /rankings,
    /trends, /patterns and /elimination without raising anything. Asking for it by
    paper_id is the deliberate opt-in.
    """
    async with async_session_factory() as session:
        csat = (
            await session.execute(select(Paper).where(Paper.code == "prelims-gs2"))
        ).scalar_one_or_none()
        if csat is None:
            pytest.skip("CSAT paper not seeded — run scripts/seed_taxonomy.py")

        published_csat = (
            await session.execute(
                select(func.count(Question.id)).where(
                    Question.paper_id == csat.id,
                    Question.status == QuestionStatus.published,
                )
            )
        ).scalar_one()
        if not published_csat:
            pytest.skip("no published CSAT questions in this database")

        # The default scope must not see a single one of them...
        leaked = (
            await session.execute(
                select(func.count(Question.id)).where(
                    Question.id.in_(question_ids(QuestionScope())),
                    Question.paper_id == csat.id,
                )
            )
        ).scalar_one()
        assert leaked == 0

        # ...nor may `stage=prelims` sneak them in, which is the filter that looks
        # like it would be enough and is not.
        leaked_by_stage = (
            await session.execute(
                select(func.count(Question.id)).where(
                    Question.id.in_(question_ids(QuestionScope(stage=Stage.prelims))),
                    Question.paper_id == csat.id,
                )
            )
        ).scalar_one()
        assert leaked_by_stage == 0

        # Naming the paper is how a CSAT-specific analysis asks for it.
        by_name = (
            await session.execute(
                select(func.count(Question.id)).where(
                    Question.id.in_(question_ids(QuestionScope(paper_id=csat.id)))
                )
            )
        ).scalar_one()
        assert by_name == published_csat


@pytest.mark.asyncio
async def test_answer_key_analyses_never_see_mains():
    """The option/elimination analyses are answer-key machinery, so Mains is not in them.

    This is the same failure `EXCLUDED_FROM_ANALYSIS` exists to prevent, arriving through
    a different door. That list names only `prelims-gs2`, which *was* the same set as
    "Prelims Paper 1" right up until Mains GS1 was ingested. `archetype_mix` and
    `format_mix` carry no `correct_label` filter, so they were counting every keyless
    Mains question into their `unknown` / `(no printed marker)` buckets — the bug this
    pins shut.
    """
    async with async_session_factory() as session:
        mains_published = (
            await session.execute(
                select(func.count(Question.id))
                .join(Paper, Paper.id == Question.paper_id)
                .where(
                    Question.status == QuestionStatus.published,
                    Paper.stage == Stage.mains,
                )
            )
        ).scalar_one()
        if not mains_published:
            pytest.skip("no published Mains questions in this database")

        scope = keyed_mcq_scope()
        leaked = (
            await session.execute(
                select(func.count(Question.id))
                .join(Paper, Paper.id == Question.paper_id)
                .where(
                    Question.id.in_(question_ids(scope)),
                    Paper.stage == Stage.mains,
                )
            )
        ).scalar_one()
        assert leaked == 0

        # The unfiltered mixes are the two that were actually wrong, so assert on their
        # output rather than only on the scope that feeds them: every Mains question the
        # old default swept in has to be exactly the difference.
        for mix in (archetype_mix, format_mix):
            pooled = await mix(session, QuestionScope())
            pinned = await mix(session, scope)
            assert sum(pinned.values()) > 0
            assert sum(pooled.values()) - sum(pinned.values()) == mains_published

        # A scope line that omits the pin would let a report claim the wrong corpus.
        assert Stage.prelims.value in scope.describe()


@pytest.mark.asyncio
async def test_ranking_splits_stages_instead_of_summing_them():
    """An unstaged ranking reports both stages, and the pair sums to the headline count.

    Prelims Paper 1 tags onto the gs1-gs4 trees via `paper_subject_map`, so once Mains
    landed every one of those topics carried two stages at once and a single number was
    describing two different exams.
    """
    async with async_session_factory() as session:
        ranked = await topic_importance(
            session, rollup="subtree", max_depth=1, limit=25
        )
        if not ranked:
            pytest.skip("no ranked topics in this database")

        for row in ranked:
            assert row.prelims_count + row.mains_count == row.subtree_count

        # A stage-scoped ranking has a zero on the other side, not a copy of the total.
        for row in await topic_importance(
            session, rollup="subtree", max_depth=1, limit=25, stage=Stage.prelims
        ):
            assert row.mains_count == 0
            assert row.prelims_count == row.subtree_count

        # The split follows whichever count the ranking sorted on.
        for row in await topic_importance(session, rollup="direct", limit=25):
            assert row.prelims_count + row.mains_count == row.question_count
