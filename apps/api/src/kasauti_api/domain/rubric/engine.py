"""The Mains answer evaluator: one rubric, one answer, a verdict per content point.

**It does not predict a mark, and `AnswerReport` has no field that could hold one.**
UPSC has never released an evaluated answer booklet, so a predicted score has no
observable truth to be right or wrong about — for anyone. "Did this answer state X" does:
it is adjudicable by one competent reader, which is what makes the output measurable as
precision/recall instead of unfalsifiable. The rubric's marks survive here only to *order*
feedback, so the heaviest missed point is reported first.

Two things are decided in Python rather than taken from the model, per the deterministic
trust boundary:

1. **Whether a claimed hit is evidenced.** Every quote is located in the transcript by
   string search (`evidence.py`). A hit whose quote is not there becomes `unsupported` —
   never a hit, and never quietly a miss.
2. **What a group of alternative points adds up to.** Hits against `expect_k`, computed
   from the verdicts, never asked of the model.
"""

import enum
from collections.abc import Sequence
from dataclasses import dataclass

from kasauti_api.domain.ingestion.extract import load_prompt
from kasauti_api.domain.llm.provider import LLMProvider, LlmUsage
from kasauti_api.domain.llm.schemas import ContentPointBatch, ContentPointVerdict
from kasauti_api.domain.rubric.evidence import find_quote, touches_illegible_span
from kasauti_api.domain.rubric.loader import (
    Rubric,
    RubricGroup,
    RubricPoint,
    VerificationMethod,
)

# Output budget per content point, plus headroom for illegible_spans. A verdict is a
# boolean, a quote and one sentence; 250 is generous and keeps a 10-point rubric in one
# call well inside any tier's limit.
TOKENS_PER_POINT = 250
TOKENS_OVERHEAD = 600


class PointStatus(enum.Enum):
    """What became of one content point. Five states, because collapsing any two of them
    loses something the learner or the operator needs."""

    hit = "hit"
    #: Gestured at but incomplete — named without explanation, or asserted without the
    #: specificity the rubric asks for. Credited, and told apart from a clean hit.
    partial = "partial"
    miss = "miss"
    #: Claimed present, but the quoted evidence is not in the transcript. A defect in the
    #: system, not in the answer — never shown to a learner as either a hit or a miss.
    unsupported = "unsupported"
    #: No verdict was reached: a symbolic or human-verified point, or a point the model
    #: silently omitted. Absence of a judgement is not a judgement of absence.
    not_judged = "not_judged"


CREDITED_STATUSES = frozenset({PointStatus.hit, PointStatus.partial})


@dataclass(frozen=True)
class PointOutcome:
    point_id: str
    description: str
    status: PointStatus
    #: The learner's own words, verbatim — present only when the quote was verified.
    quote: str | None
    comment: str
    #: The rubric's marks for this point. Orders the feedback; never summed into a score.
    weight: float
    group_id: str | None = None
    #: The evidence overlaps a span the judge flagged as illegible, so the hit may rest
    #: on smoothed handwriting rather than on what the learner wrote.
    evidence_uncertain: bool = False
    #: Why no verdict was reached, for `not_judged`.
    not_judged_reason: str | None = None

    @property
    def credited(self) -> bool:
        return self.status in CREDITED_STATUSES


@dataclass(frozen=True)
class GroupOutcome:
    """An alternative-credit group's rollup: how many of the alternatives landed,
    against how many a strong answer makes."""

    group_id: str
    description: str
    expect_k: int | None
    credited_ids: tuple[str, ...]
    missed_ids: tuple[str, ...]

    @property
    def credited(self) -> int:
        return len(self.credited_ids)

    @property
    def defined(self) -> int:
        return self.credited + len(self.missed_ids)

    @property
    def meets_expectation(self) -> bool | None:
        return None if self.expect_k is None else self.credited >= self.expect_k

    @property
    def over_covered(self) -> bool:
        """More alternatives made than the question rewards.

        Not a compliment. On a 150-word answer, a seventh treaty feature is words spent
        on marks already earned and taken from the analytical demand — which is what the
        first worked example found in an AIR-1 answer.
        """
        return self.expect_k is not None and self.credited > self.expect_k


@dataclass(frozen=True)
class AnswerReport:
    """What the learner is shown, and everything the benchmark measures.

    There is deliberately no total, score, band or percentage field here, and none may be
    added: the contract with the learner is that this reports what their answer said, not
    what it was worth.
    """

    rubric_id: str
    rubric_version: str
    language: str
    outcomes: tuple[PointOutcome, ...]
    groups: tuple[GroupOutcome, ...]
    #: Passages nobody is sure of — flagged by the transcription stage, by the judge, or
    #: by both — surfaced verbatim so a transcription failure stays visible instead of
    #: being silently scored as a missing point.
    illegible_spans: tuple[str, ...] = ()

    def by_status(self, status: PointStatus) -> tuple[PointOutcome, ...]:
        return tuple(o for o in self.outcomes if o.status is status)

    @property
    def credited(self) -> tuple[PointOutcome, ...]:
        return tuple(o for o in self.outcomes if o.credited)

    @property
    def unsupported(self) -> tuple[PointOutcome, ...]:
        """Hits the engine refused to show. A non-empty list is an operational signal —
        the judge is asserting things it cannot evidence — not learner feedback."""
        return self.by_status(PointStatus.unsupported)

    def missed_by_weight(self) -> tuple[PointOutcome, ...]:
        """Missed points, heaviest first. The rubric's only surviving use for marks:
        a learner reading three lines of feedback should read the costliest one first."""
        return tuple(
            sorted(
                self.by_status(PointStatus.miss),
                key=lambda o: -o.weight,
            )
        )


def rubric_version(rubric_id: str) -> str:
    """The version suffix every rubric_id carries (`...-v1` → `v1`)."""
    _, _, suffix = rubric_id.rpartition("-")
    return suffix


def _point_block(point: RubricPoint, language: str) -> str:
    return f"- id: {point.id}\n  {point.description(language)}"


def build_prompt(
    rubric: Rubric,
    points: Sequence[RubricPoint],
    *,
    question_text: str,
    answer_text: str,
    language: str,
) -> str:
    sections = [
        "## The question\n\n" + question_text.strip(),
        "## Content points to check\n\n"
        + "\n".join(_point_block(p, language) for p in points),
    ]
    if rubric.partial_credit_rules:
        sections.append(
            "## Notes from the rubric author\n\n"
            + "\n".join(f"- {rule}" for rule in rubric.partial_credit_rules)
        )
    sections.append(
        f"## The candidate's answer (transcript of handwriting, language: {language})"
        f"\n\n{answer_text.strip()}"
    )
    return "\n\n".join(sections)


def _outcome_for(
    point: RubricPoint,
    verdict: ContentPointVerdict | None,
    *,
    answer_text: str,
    illegible_spans: list[str],
    language: str,
) -> PointOutcome:
    description = point.description(language)
    base = {
        "point_id": point.id,
        "description": description,
        "weight": point.marks,
        "group_id": point.group_id,
    }

    if verdict is None:
        return PointOutcome(
            **base,
            status=PointStatus.not_judged,
            quote=None,
            comment="",
            not_judged_reason="the judge returned no verdict for this point",
        )

    if not verdict.present:
        return PointOutcome(
            **base, status=PointStatus.miss, quote=None, comment=verdict.comment
        )

    match = find_quote(verdict.quote, answer_text) if verdict.quote else None
    if match is None:
        # Claimed present with no quote, or with words that are not in the transcript.
        # Either way the claim is unverifiable and is not shown as a hit.
        reason = (
            "claimed present with no supporting quote"
            if not verdict.quote
            else "the quoted words are not in the transcript"
        )
        return PointOutcome(
            **base,
            status=PointStatus.unsupported,
            quote=None,
            comment=verdict.comment,
            not_judged_reason=reason,
        )

    return PointOutcome(
        **base,
        status=PointStatus.partial if verdict.partial else PointStatus.hit,
        quote=verdict.quote,
        comment=verdict.comment,
        evidence_uncertain=touches_illegible_span(match, illegible_spans, answer_text),
    )


def _group_outcome(group: RubricGroup, outcomes: dict[str, PointOutcome],
                   language: str) -> GroupOutcome:
    credited: list[str] = []
    missed: list[str] = []
    for point in group.points:
        outcome = outcomes[point.id]
        # Only a decided miss counts against the group. An unsupported or unjudged point
        # is unknown, and folding unknowns into "missed" would report a system failure to
        # the learner as a gap in their answer.
        if outcome.credited:
            credited.append(point.id)
        elif outcome.status is PointStatus.miss:
            missed.append(point.id)
    return GroupOutcome(
        group_id=group.id,
        description=group.description(language),
        expect_k=group.expect_k,
        credited_ids=tuple(credited),
        missed_ids=tuple(missed),
    )


async def judge_answer(
    provider: LLMProvider,
    rubric: Rubric,
    *,
    question_text: str,
    answer_text: str,
    language: str = "en",
    uncertain_spans: Sequence[str] = (),
) -> tuple[AnswerReport, list[LlmUsage]]:
    """Judge one answer against one rubric.

    Returns the report and the usage of every call made, for the caller to record — the
    same seam `tag_questions` uses, so the domain stays free of a DB session.

    Points are batched by their `rubric_prompt_ref`: the rubric may name a different
    judging prompt per point, and a batch shares one system prompt. In practice a GS
    rubric is one prompt and one call.

    `uncertain_spans` carries forward what the *transcription* stage was unsure it read
    (`HandwrittenAnswer.uncertain_spans`). They are unioned with whatever the judge itself
    finds illegible, and evidence overlapping either is flagged. The two see different
    things and neither subsumes the other: only the transcriber saw the ink, and only the
    judge knows which words a point turns on.
    """
    if not answer_text.strip():
        # An empty transcript judged normally returns every point missed, which reads
        # exactly like a blank answer and hides an upload or OCR failure.
        raise ValueError("answer_text is empty — nothing to judge")

    outcomes: dict[str, PointOutcome] = {}
    usages: list[LlmUsage] = []
    illegible: list[str] = list(uncertain_spans)

    batches: dict[str, list[RubricPoint]] = {}
    for point in rubric.points:
        method = point.verification.method
        if method is not VerificationMethod.llm_judged:
            outcomes[point.id] = PointOutcome(
                point_id=point.id,
                description=point.description(language),
                status=PointStatus.not_judged,
                quote=None,
                comment="",
                weight=point.marks,
                group_id=point.group_id,
                not_judged_reason=(
                    f"{method.value} verification is not implemented; "
                    "no symbolic checkers are registered yet"
                    if method is VerificationMethod.symbolic
                    else "this point is marked for human verification"
                ),
            )
            continue
        batches.setdefault(point.verification.prompt_ref, []).append(point)

    for prompt_ref, points in batches.items():
        prompt = build_prompt(
            rubric,
            points,
            question_text=question_text,
            answer_text=answer_text,
            language=language,
        )
        batch, usage = await provider.parse_structured(
            prompt=prompt,
            system=load_prompt(prompt_ref),
            schema=ContentPointBatch,
            tier="standard",
            max_tokens=TOKENS_PER_POINT * len(points) + TOKENS_OVERHEAD,
        )
        usages.append(usage)
        illegible.extend(s for s in batch.illegible_spans if s not in illegible)
        for point in points:
            outcomes[point.id] = _outcome_for(
                point,
                batch.verdicts.get(point.id),
                answer_text=answer_text,
                illegible_spans=illegible,
                language=language,
            )

    report = AnswerReport(
        rubric_id=rubric.rubric_id,
        rubric_version=rubric_version(rubric.rubric_id),
        language=language,
        outcomes=tuple(outcomes[p.id] for p in rubric.points),
        groups=tuple(_group_outcome(g, outcomes, language) for g in rubric.groups),
        illegible_spans=tuple(illegible),
    )
    return report, usages
