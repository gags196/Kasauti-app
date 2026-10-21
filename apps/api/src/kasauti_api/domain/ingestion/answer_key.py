"""Apply an official Prelims answer key to stored MCQ options.

Correctness enters the system only here. Extraction must never assert it, so this is the
one place `question_options.is_correct` is written, and it must be conservative: any key
entry it cannot fully justify leaves the options NULL rather than guessing.

Two cases the naive "set the matching label true, everything else false" approach gets
wrong, both present in the real 2026 key:

  Dropped questions. UPSC withdraws questions and marks them `X` (the 2026 Paper I key
  drops Q64: "No. of Questions Dropped 1"). Writing all-false would assert "we know none
  of these is correct", which is false — the question has no valid answer at all. It
  would also read to a learner as a known answer that is missing, because the UI only
  shows "answer key pending" when every option is NULL.

  Label mismatch. If the key names an option the question does not have, that usually
  means the key belongs to a different booklet series. Series have different question
  orders, so silently applying it would corrupt every answer in the paper. Refuse.
"""

from dataclasses import dataclass, field

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from kasauti_api.db.models import Question, QuestionOption

# UPSC marks a withdrawn question with X. Blank and dash appear in some transcriptions.
DROPPED_LABELS = {"X", "-", "--", ""}


@dataclass
class KeyLoadResult:
    applied: int = 0
    dropped: list[str] = field(default_factory=list)
    unknown_label: list[tuple[str, str]] = field(default_factory=list)
    missing_question: list[str] = field(default_factory=list)

    @property
    def has_integrity_error(self) -> bool:
        """A key naming options the paper does not have is the signature of a
        series mismatch — a data-integrity failure, not a gap."""
        return bool(self.unknown_label)

    def summary(self) -> str:
        parts = [f"{self.applied} applied"]
        if self.dropped:
            parts.append(f"{len(self.dropped)} dropped ({', '.join(self.dropped)})")
        if self.missing_question:
            parts.append(f"{len(self.missing_question)} not ingested")
        if self.unknown_label:
            parts.append(f"{len(self.unknown_label)} LABEL MISMATCH")
        return ", ".join(parts)


async def apply_answer_key(
    session: AsyncSession,
    *,
    paper_id: int,
    year: int,
    key: dict[str, str],
) -> KeyLoadResult:
    """Set is_correct for questions covered by `key`. Does not commit.

    `key` maps printed question number -> correct option label.
    """
    result = KeyLoadResult()

    questions = (
        await session.execute(
            select(Question).where(Question.paper_id == paper_id, Question.year == year)
        )
    ).scalars().all()
    by_number = {q.question_number.strip(): q for q in questions}

    for raw_number, raw_label in key.items():
        number = raw_number.strip()
        label = raw_label.strip().upper()

        question = by_number.get(number)
        if question is None:
            result.missing_question.append(number)
            continue

        if label in DROPPED_LABELS:
            # Leave every option NULL: unknown, not known-wrong.
            result.dropped.append(number)
            continue

        option_labels = set(
            (
                await session.execute(
                    select(QuestionOption.option_label).where(
                        QuestionOption.question_id == question.id
                    )
                )
            ).scalars()
        )
        if label not in {o.strip().upper() for o in option_labels}:
            result.unknown_label.append((number, label))
            continue

        await session.execute(
            update(QuestionOption)
            .where(QuestionOption.question_id == question.id)
            .values(is_correct=QuestionOption.option_label == label)
        )
        result.applied += 1

    return result
