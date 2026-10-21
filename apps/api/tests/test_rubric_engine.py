"""The Mains evaluator: rubric loading, evidence verification, and the group rollup.

No DB and no model. The provider is faked so what is under test is the engine's own
arithmetic and its trust boundary — whether a claimed hit survives being checked against
the learner's actual words — rather than any model's judgement.
"""

import dataclasses

import pytest
import yaml
from kasauti_api.domain.llm.provider import LlmUsage
from kasauti_api.domain.llm.schemas import ContentPointBatch, ContentPointVerdict
from kasauti_api.domain.rubric import (
    AnswerReport,
    PointStatus,
    achievable_marks,
    find_quote,
    iter_rubric_paths,
    judge_answer,
    load_rubric,
    load_rubric_path,
    parse_rubric,
)
from kasauti_api.domain.rubric.evidence import normalise
from kasauti_api.domain.rubric.loader import RubricError
from kasauti_api.settings import REPO_ROOT

FIXTURE = REPO_ROOT / "benchmarks" / "fixtures" / "mains-eval" / "gs1-2024-q2.yaml"

FAKE_USAGE = LlmUsage(provider="fake", model="fake-standard", input_tokens=0, output_tokens=0)


class ReplayProvider:
    """Returns a fixed set of verdicts, keyed by point id, for whatever ids are asked."""

    def __init__(self, verdicts: dict[str, ContentPointVerdict], illegible=()):
        self.verdicts = verdicts
        self.illegible = list(illegible)
        self.prompts: list[str] = []

    async def parse_structured(self, *, prompt, schema, documents=None, system=None,
                               tier="standard", max_tokens=16000):
        assert schema is ContentPointBatch, schema
        self.prompts.append(prompt)
        return (
            ContentPointBatch(verdicts=self.verdicts, illegible_spans=self.illegible),
            FAKE_USAGE,
        )


def load_fixture() -> dict:
    return yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))


def fixture_verdicts(data: dict) -> dict[str, ContentPointVerdict]:
    return {
        point_id: ContentPointVerdict(**raw) for point_id, raw in data["verdicts"].items()
    }


# --- loading -----------------------------------------------------------------------


def test_every_repo_rubric_loads_and_its_achievable_marks_reach_its_total():
    """The same invariant scripts/validate_rubrics.py enforces, asserted through the
    engine's own loader — a rubric that passes CI must be one the evaluator can read."""
    paths = list(iter_rubric_paths())
    assert paths, "no rubrics found under content/rubrics/"
    for path in paths:
        rubric = load_rubric_path(path)
        assert achievable_marks(rubric) == pytest.approx(rubric.total_marks), path


def test_a_group_contributes_its_cap_not_the_sum_of_its_points():
    """'Any three of these six' is worth three. Summing the six is what made an honestly
    written 10-mark rubric total 13 and forced the group construct into the DSL."""
    rubric = load_rubric("gs1-2024-q2-subsidiary-alliance-v1")
    group = rubric.groups[0]
    assert sum(p.marks for p in group.points) == 6
    assert group.credit_cap == 3
    assert achievable_marks(rubric) == 10
    # The group's points are still individually addressable — that per-point breakdown
    # is the product now that no mark is predicted.
    assert len(rubric.points) == 10
    assert all(p.group_id == group.id for p in group.points)


def test_duplicate_ids_are_rejected():
    """Verdicts come back keyed by id; two points sharing one would collapse into a
    single verdict silently applied to both. The JSON Schema cannot see this."""
    data = {
        "rubric_id": "dupe-v1",
        "topic_path": "gs1.x",
        "total_marks": 2,
        "steps": [
            {"id": "same", "marks": 1, "verification": {"method": "human"}},
            {"id": "same", "marks": 1, "verification": {"method": "human"}},
        ],
    }
    with pytest.raises(RubricError, match="reuses ids"):
        parse_rubric(data)


# --- evidence ----------------------------------------------------------------------


TRANSCRIPT = (
    "They had to station British army in their territory, which were to be\n"
    "maintained by the states themselves.\n"
    'This was further extended by "Doctrine of Lapse" under Dalhousie.\n'
    "राज्य अपनी सेना नहीं रख सकते थे।"
)


@pytest.mark.parametrize(
    "quote",
    [
        # Verbatim.
        "maintained by the states themselves",
        # Across a line wrap in the transcript — the page wrapped, the quote did not.
        "which were to be maintained by",
        # Curly quotes in the quote, straight in the transcript.
        "further extended by “Doctrine of Lapse” under Dalhousie",
        # Two stretches of one sentence joined by an ellipsis, as a judge writes them.
        "They had to station British army ... the states themselves",
        # Devanagari, so Hindi answers are held to the same rule as English ones.
        "राज्य अपनी सेना नहीं रख सकते थे",
    ],
)
def test_a_real_quote_is_found(quote):
    assert find_quote(quote, TRANSCRIPT) is not None


@pytest.mark.parametrize(
    "quote",
    [
        # A paraphrase. This is the whole reason the check exists.
        "they could not keep soldiers of their own",
        # Ellipsis fragments present but in the wrong order — "and later" means later.
        "the states themselves ... They had to station British army",
        "",
    ],
)
def test_words_that_are_not_there_are_not_found(quote):
    assert find_quote(quote, TRANSCRIPT) is None


def test_normalise_folds_only_form():
    assert normalise("  A   b\nC ") == normalise("a b c")
    assert normalise("“x”") == normalise('"x"')


# --- judging -----------------------------------------------------------------------


def _rubric_and_answer():
    data = load_fixture()
    return load_rubric(data["rubric_id"]), data


@pytest.mark.asyncio
async def test_worked_example_reproduces_the_published_verdicts():
    """benchmarks/reports/mains-eval/2026-09-01_worked-example-gs1-q2.md, replayed.

    Every quote in that report must still be locatable in the transcript, and the group
    must still read 5 of 6 against an expect_k of 3. Drift in either is a signal.
    """
    rubric, data = _rubric_and_answer()
    provider = ReplayProvider(fixture_verdicts(data))

    report, usages = await judge_answer(
        provider,
        rubric,
        question_text=data["question"],
        answer_text=data["answer"],
        language=data["language"],
    )

    expected = data["expected"]
    assert len(report.by_status(PointStatus.hit)) == expected["hits"]
    assert len(report.by_status(PointStatus.partial)) == expected["partials"]
    assert len(report.by_status(PointStatus.miss)) == expected["misses"]
    assert len(report.unsupported) == expected["unsupported"], (
        "a published quote no longer matches the transcript: "
        f"{[o.point_id for o in report.unsupported]}"
    )

    group = next(g for g in report.groups if g.group_id == "treaty-features")
    want = expected["groups"]["treaty-features"]
    assert group.credited == want["credited"]
    assert len(group.missed_ids) == want["missed"]
    assert group.expect_k == want["expect_k"]
    # Five features stated where three were expected: words spent on marks already
    # earned, which is the finding the group construct exists to make visible.
    assert group.over_covered is want["over_covered"]
    assert group.meets_expectation is True

    # The one partial is the useful piece of feedback, and it is on an AIR-1 answer.
    assert [o.point_id for o in report.by_status(PointStatus.partial)] == [
        "addresses-in-vs-of"
    ]
    assert len(usages) == 1  # one prompt ref across the rubric, so one call


@pytest.mark.asyncio
async def test_a_hit_whose_quote_is_not_in_the_answer_is_unsupported_not_a_hit():
    """The failure this engine exists to catch. A judge asserting a point with invented
    evidence must not reach the learner as a hit — and must not be quietly recorded as a
    miss either, because that would blame the answer for a defect in us."""
    rubric, data = _rubric_and_answer()
    verdicts = fixture_verdicts(data)
    verdicts["feature-british-resident"] = ContentPointVerdict(
        present=True,
        quote="a British Resident was posted at the durbar to oversee the state",
        comment="Stated clearly.",
    )
    report, _ = await judge_answer(
        ReplayProvider(verdicts),
        rubric,
        question_text=data["question"],
        answer_text=data["answer"],
        language="en",
    )

    outcome = next(o for o in report.outcomes if o.point_id == "feature-british-resident")
    assert outcome.status is PointStatus.unsupported
    assert outcome.quote is None
    assert "not in the transcript" in outcome.not_judged_reason
    assert not outcome.credited

    # It counts for the group neither way: unknown is not "the learner missed it".
    group = next(g for g in report.groups if g.group_id == "treaty-features")
    assert "feature-british-resident" not in group.credited_ids
    assert "feature-british-resident" not in group.missed_ids
    assert group.credited == 4


@pytest.mark.asyncio
async def test_present_with_no_quote_is_unsupported():
    rubric, data = _rubric_and_answer()
    verdicts = fixture_verdicts(data)
    verdicts["links-doctrine-of-lapse"] = ContentPointVerdict(
        present=True, quote=None, comment="It is clearly implied throughout."
    )
    report, _ = await judge_answer(
        ReplayProvider(verdicts),
        rubric,
        question_text=data["question"],
        answer_text=data["answer"],
        language="en",
    )
    outcome = next(o for o in report.outcomes if o.point_id == "links-doctrine-of-lapse")
    assert outcome.status is PointStatus.unsupported
    assert "no supporting quote" in outcome.not_judged_reason


@pytest.mark.asyncio
async def test_a_point_the_judge_skipped_is_not_judged_rather_than_missed():
    """Absence of a judgement is not a judgement of absence. Silently reporting a skipped
    point as missing would tell the learner to add something they may already have."""
    rubric, data = _rubric_and_answer()
    verdicts = fixture_verdicts(data)
    del verdicts["names-annexed-states"]

    report, _ = await judge_answer(
        ReplayProvider(verdicts),
        rubric,
        question_text=data["question"],
        answer_text=data["answer"],
        language="en",
    )
    outcome = next(o for o in report.outcomes if o.point_id == "names-annexed-states")
    assert outcome.status is PointStatus.not_judged
    assert outcome.point_id not in [o.point_id for o in report.missed_by_weight()]


@pytest.mark.asyncio
async def test_evidence_overlapping_an_illegible_span_is_flagged():
    """A hit resting on words the same call admitted it could not read is not a hit
    anyone should act on — the documented failure mode is smoothing unclear handwriting
    into the token that ought to be there and then crediting the point."""
    rubric, data = _rubric_and_answer()
    report, _ = await judge_answer(
        ReplayProvider(
            fixture_verdicts(data),
            illegible=["Hyderabad, Bharatpur, Satara, Jaunpur"],
        ),
        rubric,
        question_text=data["question"],
        answer_text=data["answer"],
        language="en",
    )
    flagged = [o.point_id for o in report.outcomes if o.evidence_uncertain]
    assert flagged == ["names-annexed-states"]
    assert report.illegible_spans


@pytest.mark.asyncio
async def test_missed_points_are_ordered_by_rubric_weight():
    """The rubric's only surviving use for marks: order the feedback, so the costliest
    gap is read first. Never a total."""
    rubric, data = _rubric_and_answer()
    verdicts = fixture_verdicts(data)
    for point_id in ("feature-no-own-army", "addresses-in-vs-of", "links-doctrine-of-lapse"):
        verdicts[point_id] = ContentPointVerdict(
            present=False, quote=None, comment="Not stated."
        )
    report, _ = await judge_answer(
        ReplayProvider(verdicts),
        rubric,
        question_text=data["question"],
        answer_text=data["answer"],
        language="en",
    )
    ordered = [o.point_id for o in report.missed_by_weight()]
    assert ordered[0] == "addresses-in-vs-of"  # 2 marks
    assert set(ordered[1:]) == {
        "feature-no-own-army",
        "feature-no-europeans-employed",
        "links-doctrine-of-lapse",
    }


@pytest.mark.asyncio
async def test_the_prompt_carries_the_points_the_question_and_the_answer():
    rubric, data = _rubric_and_answer()
    provider = ReplayProvider(fixture_verdicts(data))
    await judge_answer(
        provider,
        rubric,
        question_text=data["question"],
        answer_text=data["answer"],
        language="en",
    )
    prompt = provider.prompts[0]
    for point in rubric.points:
        assert f"id: {point.id}" in prompt
    assert "British Empire in India" in prompt
    assert "Richard Wellesley" in prompt
    # The rubric author's notes reach the judge — they are what tells it that a state
    # outside the listed set still counts.
    assert "Do not penalise a state that is correct" in prompt


@pytest.mark.asyncio
async def test_an_empty_transcript_is_refused_rather_than_scored_as_a_blank_answer():
    rubric, data = _rubric_and_answer()
    with pytest.raises(ValueError, match="empty"):
        await judge_answer(
            ReplayProvider(fixture_verdicts(data)),
            rubric,
            question_text=data["question"],
            answer_text="   \n  ",
        )


def test_the_report_has_nowhere_to_put_a_mark():
    """Structural, not stylistic. UPSC has never released an evaluated booklet, so a
    predicted score has no observable truth to be right or wrong about; the contract is
    kept by the type having no field that could hold one, exactly as ContentPointVerdict
    has none. If a field named below ever appears, that guarantee is gone."""
    fields = {f.name for f in dataclasses.fields(AnswerReport)}
    forbidden = {"score", "total", "marks", "marks_awarded", "band", "percentage", "grade"}
    assert not (fields & forbidden)
    assert not any(
        "score" in name or "mark" in name or "grade" in name for name in fields
    ), fields


def test_the_fixture_and_the_rubric_cover_the_same_points():
    """A rubric edit that adds a point without updating the fixture would otherwise make
    the regression test pass on a smaller rubric than the one in the repo."""
    data = load_fixture()
    rubric = load_rubric(data["rubric_id"])
    assert set(data["verdicts"]) == {p.id for p in rubric.points}


def test_fixture_path_is_outside_the_private_corpus():
    """The gold/labeled corpus is deliberately un-committable. This fixture is a
    published topper answer already reproduced in benchmarks/reports/, so it lives with
    the benchmarks — not under labeled_corpus/ or gold_standard/."""
    assert FIXTURE.is_file()
    assert "labeled_corpus" not in FIXTURE.parts
    assert "gold_standard" not in FIXTURE.parts
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "labeled_corpus" in gitignore
