"""Final pipeline stage: publish a reviewed scan's questions to learners.

The `/admin` "Approve & publish" action assumes a human has just looked at the rows on
screen. Driving the same transition from a CLI removes that pair of eyes, so the checks
the founder was performing visually are written down here instead — a question with only
one language, or no topic tag, is not fit to put in front of a learner, and publishing is
the point of no return where it becomes visible.

Marks are a separate matter. Prelims papers state marks once on the instruction page and
never against individual questions, so extraction correctly leaves `marks` null (see
`content/prompts/extraction/pyq_scan_v4.md`). Filling them in is a founder assertion read
off that page — hence an explicit argument here, never an inference.
"""

from dataclasses import dataclass, field

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from kasauti_api.db.models import (
    Question,
    QuestionOption,
    QuestionStimulus,
    QuestionTopicMap,
    SourceScan,
)
from kasauti_api.db.models.questions import OcrStatus, QuestionStatus, StimulusKind

# UPSC MCQs always print four options. A question carrying some but not four means
# extraction dropped one, which the answer key would then silently mis-apply.
EXPECTED_MCQ_OPTIONS = 4


@dataclass
class ReadinessReport:
    total: int = 0
    missing_en: list[str] = field(default_factory=list)
    missing_hi: list[str] = field(default_factory=list)
    untagged: list[str] = field(default_factory=list)
    bad_option_count: list[tuple[str, int]] = field(default_factory=list)
    stimulus_missing_en: list[str] = field(default_factory=list)
    stimulus_missing_hi: list[str] = field(default_factory=list)
    orphan_stimuli: list[str] = field(default_factory=list)
    unresolved_stimulus_ref: list[tuple[str, str]] = field(default_factory=list)
    figure_missing_asset: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.total > 0 and not (
            self.missing_en
            or self.missing_hi
            or self.untagged
            or self.bad_option_count
            or self.stimulus_missing_en
            or self.stimulus_missing_hi
            or self.orphan_stimuli
            or self.unresolved_stimulus_ref
            or self.figure_missing_asset
        )

    def problems(self) -> list[str]:
        out = []
        if not self.total:
            out.append("no questions on this scan — nothing to publish")
        if self.missing_en:
            out.append(f"missing English text: {', '.join(self.missing_en)}")
        if self.missing_hi:
            out.append(f"missing Hindi text: {', '.join(self.missing_hi)}")
        if self.untagged:
            out.append(f"no topic tag: {', '.join(self.untagged)}")
        if self.bad_option_count:
            detail = ", ".join(f"{n} has {c}" for n, c in self.bad_option_count)
            out.append(f"not {EXPECTED_MCQ_OPTIONS} options: {detail}")
        if self.stimulus_missing_en:
            out.append(f"passage missing English: {', '.join(self.stimulus_missing_en)}")
        if self.stimulus_missing_hi:
            out.append(f"passage missing Hindi: {', '.join(self.stimulus_missing_hi)}")
        if self.orphan_stimuli:
            out.append(f"passage with no items: {', '.join(self.orphan_stimuli)}")
        if self.unresolved_stimulus_ref:
            detail = ", ".join(f"{n} -> {r}" for n, r in self.unresolved_stimulus_ref)
            out.append(f"item points at a passage that was not extracted: {detail}")
        if self.figure_missing_asset:
            detail = ", ".join(self.figure_missing_asset)
            out.append(f"figure with no cropped image attached: {detail}")
        return out


@dataclass
class PublishResult:
    published_ids: list[int] = field(default_factory=list)
    marks_backfilled: int = 0

    def summary(self) -> str:
        return (
            f"{len(self.published_ids)} question(s) published, "
            f"{self.marks_backfilled} marks backfilled"
        )


async def check_scan_ready(session: AsyncSession, scan_id: int) -> ReadinessReport:
    """Everything that would make a question unfit to show a learner.

    Bilingual is not optional here: the learner UI shows both languages side by side
    (`components/bilingual.tsx`), so a one-language question renders as a hole.
    """
    questions = (
        await session.execute(
            select(Question)
            .where(Question.source_scan_id == scan_id)
            .order_by(Question.id)
        )
    ).scalars().all()

    report = ReadinessReport(total=len(questions))
    if not questions:
        return report

    ids = [q.id for q in questions]
    tagged = set(
        (
            await session.execute(
                select(QuestionTopicMap.question_id).where(
                    QuestionTopicMap.question_id.in_(ids)
                )
            )
        ).scalars()
    )
    option_counts = dict(
        (
            await session.execute(
                select(QuestionOption.question_id, func.count(QuestionOption.id))
                .where(QuestionOption.question_id.in_(ids))
                .group_by(QuestionOption.question_id)
            )
        ).all()
    )
    # Mains papers have no options at all; Prelims papers have four on every question.
    # Infer which kind of paper this is from the scan itself rather than hardcoding a
    # paper code, so the check works for any MCQ paper added later.
    is_mcq_scan = bool(option_counts)

    for question in questions:
        number = question.question_number
        if not (question.question_text_en or "").strip():
            report.missing_en.append(number)
        if not (question.question_text_hi or "").strip():
            report.missing_hi.append(number)
        if question.id not in tagged:
            report.untagged.append(number)
        if is_mcq_scan:
            count = option_counts.get(question.id, 0)
            if count != EXPECTED_MCQ_OPTIONS:
                report.bad_option_count.append((number, count))

    await _check_stimuli(session, scan_id, questions, report)
    return report


async def _check_stimuli(
    session: AsyncSession,
    scan_id: int,
    questions: list[Question],
    report: ReadinessReport,
) -> None:
    """A comprehension item is only answerable if its passage arrived intact.

    Three ways that fails, all silent without this. A passage missing one language
    renders as a hole for half the learners, exactly as a one-language question does.
    A passage with no items attached means the extractor's refs did not line up. And an
    item whose extracted `stimulus_ref` never resolved to a row is worse than either:
    it looks like a self-contained question and is unanswerable, so it is caught by
    comparing the committed rows against what extraction actually said.
    """
    stimuli = (
        await session.execute(
            select(QuestionStimulus).where(QuestionStimulus.source_scan_id == scan_id)
        )
    ).scalars().all()

    used = {q.stimulus_id for q in questions if q.stimulus_id is not None}
    for stimulus in stimuli:
        if not (stimulus.text_en or "").strip():
            report.stimulus_missing_en.append(stimulus.ref)
        if not (stimulus.text_hi or "").strip():
            report.stimulus_missing_hi.append(stimulus.ref)
        if stimulus.id not in used:
            report.orphan_stimuli.append(stimulus.ref)
        if stimulus.kind == StimulusKind.figure and not stimulus.asset_key:
            report.figure_missing_asset.append(stimulus.ref)

    scan = (
        await session.execute(select(SourceScan).where(SourceScan.id == scan_id))
    ).scalar_one_or_none()
    raw = (scan.raw_extraction_json or {}) if scan else {}
    committed = {q.question_number: q for q in questions}
    for extracted in raw.get("questions", []) or []:
        ref = extracted.get("stimulus_ref")
        number = extracted.get("question_number")
        if not ref:
            continue
        question = committed.get(number)
        if question is not None and question.stimulus_id is None:
            report.unresolved_stimulus_ref.append((str(number), str(ref)))


async def publish_scan(
    session: AsyncSession, scan_id: int, *, marks: float | None = None
) -> PublishResult:
    """Publish every question on a scan and mark the scan itself published.

    Does not commit. Does not check readiness — call `check_scan_ready` first; keeping
    them separate is what lets the CLI report problems without writing anything.
    """
    questions = (
        await session.execute(
            select(Question)
            .where(Question.source_scan_id == scan_id)
            .order_by(Question.id)
        )
    ).scalars().all()
    if not questions:
        return PublishResult()

    result = PublishResult(published_ids=[q.id for q in questions])

    if marks is not None:
        # Only where it is currently NULL: a question whose marks are already set was
        # either printed with them or corrected by hand, and neither should be overwritten.
        backfill = await session.execute(
            update(Question)
            .where(Question.source_scan_id == scan_id, Question.marks.is_(None))
            .values(marks=marks)
        )
        result.marks_backfilled = backfill.rowcount or 0

    await session.execute(
        update(Question)
        .where(Question.source_scan_id == scan_id)
        .values(status=QuestionStatus.published)
    )
    await session.execute(
        update(SourceScan)
        .where(SourceScan.id == scan_id)
        .values(ocr_status=OcrStatus.published)
    )
    return result
