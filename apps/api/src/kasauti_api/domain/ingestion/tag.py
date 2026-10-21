"""Stage 3 of the PYQ pipeline: LLM-assisted topic tagging against the taxonomy."""

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from kasauti_api.db.models import PaperSubjectMap, Question, Subject, Topic
from kasauti_api.domain.ingestion.extract import load_prompt
from kasauti_api.domain.llm.provider import LLMProvider, LlmUsage
from kasauti_api.domain.llm.schemas import BatchTopicTagResult, TopicTagResult

TAGGING_PROMPT_REF = "prompts/pyq_tagging/tag_topics_v1.md"
BATCH_TAGGING_PROMPT_REF = "prompts/pyq_tagging/tag_topics_v2.md"

# Questions per batched tagging call. The candidate topic list is the bulk of the
# prompt and is identical for every question in a paper, so batching divides that cost
# by this number. Kept modest so one bad call re-runs cheaply and output stays well
# inside max_tokens.
TAG_BATCH_SIZE = 10

# Below this the tag is kept but the question is routed to human review.
TAG_CONFIDENCE_REVIEW_THRESHOLD = 0.7


async def candidate_topics_for_subject(session: AsyncSession, subject_id: int) -> list[Topic]:
    result = await session.execute(
        select(Topic).where(Topic.subject_id == subject_id).order_by(Topic.path)
    )
    return list(result.scalars())


async def candidate_topics_for_paper(session: AsyncSession, paper_id: int) -> list[Topic]:
    """Topics a paper's questions may be tagged with: the paper's own subjects'
    trees plus any tag-target subjects via paper_subject_map. Prelims Paper I has
    no subjects of its own — it tags entirely against mapped Mains subjects, because
    UPSC's Paper I syllabus is seven broad bullets that the detailed Mains tree already
    covers. Prelims Paper II is the opposite case: its published syllabus has no Mains
    counterpart at all, so it carries its own `csat` subject and takes the first branch
    below.

    A mapped subject may cap the depth it contributes (`max_topic_depth`). That is for
    subjects a paper only brushes against: Prelims tested ethics three times in 2026 and
    not at all in earlier years, so pulling all 35 fine-grained gs4 topics into every
    tagging prompt would both invite spuriously specific tags and inflate the prompt,
    which is resent for every batch.
    """
    own_subjects = list(
        (await session.execute(select(Subject.id).where(Subject.paper_id == paper_id)))
        .scalars()
    )
    mapped = (
        await session.execute(
            select(PaperSubjectMap.subject_id, PaperSubjectMap.max_topic_depth).where(
                PaperSubjectMap.paper_id == paper_id
            )
        )
    ).all()

    conditions = []
    if own_subjects:
        conditions.append(Topic.subject_id.in_(own_subjects))
    for subject_id, max_depth in mapped:
        if max_depth is None:
            conditions.append(Topic.subject_id == subject_id)
        else:
            conditions.append(
                (Topic.subject_id == subject_id) & (Topic.depth <= max_depth)
            )
    if not conditions:
        return []

    result = await session.execute(select(Topic).where(or_(*conditions)).order_by(Topic.path))
    return list(result.scalars())


def format_topic_list(topics: list[Topic]) -> str:
    return "\n".join(f"{t.path} | {t.name_en} | {t.name_hi}" for t in topics)


def _question_block(question: Question) -> str:
    parts = [f"Question {question.question_number} ({question.marks or '?'} marks)"]
    if question.question_text_en:
        parts.append(f"EN: {question.question_text_en}")
    if question.question_text_hi:
        parts.append(f"HI: {question.question_text_hi}")
    if question.math_notation_latex:
        parts.append(f"LATEX: {question.math_notation_latex}")
    return "\n".join(parts)


async def tag_question(
    provider: LLMProvider,
    question: Question,
    topics: list[Topic],
) -> tuple[TopicTagResult, LlmUsage]:
    """Tag a single question. Prefer `tag_questions` — this resends the entire
    candidate topic list for one question, which is the pipeline's biggest waste."""
    prompt = _question_block(question) + "\n\nCandidate topics:\n" + format_topic_list(topics)
    return await provider.parse_structured(
        prompt=prompt,
        system=load_prompt(TAGGING_PROMPT_REF),
        schema=TopicTagResult,
        tier="light",
        max_tokens=1000,
    )


async def tag_questions(
    provider: LLMProvider,
    questions: list[Question],
    topics: list[Topic],
) -> tuple[BatchTopicTagResult, LlmUsage]:
    """Tag several questions in one call, sending the topic list once.

    At 124 candidate topics the list is ~17.7k characters. Per-question tagging resends
    it for every question — about 1.8M characters for a 100-question paper, more than
    the extraction itself. Batching divides that by the batch size.
    """
    prompt = "\n\n".join(
        [
            "Candidate topics:\n" + format_topic_list(topics),
            "Questions to tag:",
            *[_question_block(q) for q in questions],
        ]
    )
    return await provider.parse_structured(
        prompt=prompt,
        system=load_prompt(BATCH_TAGGING_PROMPT_REF),
        schema=BatchTopicTagResult,
        tier="light",
        max_tokens=400 * len(questions) + 500,
    )
