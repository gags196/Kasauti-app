"""Feature A1 (topic analysis + prediction) and Feature B (one-pager) generation.

Both jobs share the same corpus-gathering step: every published question tagged
to the topic's subtree, oldest first, so the model can see framing evolution.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kasauti_api.db.models import Paper, Question, Topic
from kasauti_api.db.models.taxonomy import Stage
from kasauti_api.domain.ingestion.extract import load_prompt
from kasauti_api.domain.intelligence.scope import QuestionScope, Rollup, question_ids
from kasauti_api.domain.llm.provider import LLMProvider, LlmUsage
from kasauti_api.domain.llm.schemas import OnePagerResult, TopicAnalysisResult

TOPIC_ANALYSIS_PROMPT_REF = "prompts/intelligence/topic_analysis_v1.md"
ONE_PAGER_PROMPT_REF = "prompts/intelligence/one_pager_v1.md"

# Below this corpus size, synthesis over-generalizes; refuse rather than fake it.
MIN_QUESTIONS_FOR_ANALYSIS = 3


@dataclass(frozen=True)
class CorpusQuestion:
    year: int
    stage: str
    text: str


async def gather_topic_corpus(
    session: AsyncSession,
    topic: Topic,
    *,
    stage: Stage | None = None,
    rollup: Rollup = "subtree",
    year_max: int | None = None,
) -> list[CorpusQuestion]:
    """Every published question under this topic, oldest first.

    `year_max` exists for backtesting: it builds a corpus deliberately blind to later
    papers, so a generated analysis can be scored against years it never saw.
    """
    scope = QuestionScope(
        topic_path=str(topic.path), rollup=rollup, stage=stage, year_to=year_max
    )
    stmt = (
        select(Question.year, Paper.stage, Question.question_text_en,
               Question.question_text_hi, Question.math_notation_latex)
        .join(Paper, Paper.id == Question.paper_id)
        .where(Question.id.in_(question_ids(scope)))
        .order_by(Question.year, Question.id)
    )

    corpus = []
    for year, paper_stage, text_en, text_hi, latex in (await session.execute(stmt)).all():
        text = text_en or text_hi or ""
        if latex:
            text = f"{text}\n{latex}"
        corpus.append(CorpusQuestion(year=year, stage=paper_stage.value, text=text))
    return corpus


def _corpus_block(topic: Topic, corpus: list[CorpusQuestion]) -> str:
    lines = [f"Topic: {topic.name_en} / {topic.name_hi} (path: {topic.path})", ""]
    lines += [f"[{q.year} · {q.stage}] {q.text}" for q in corpus]
    return "\n".join(lines)


async def generate_topic_analysis(
    provider: LLMProvider, topic: Topic, corpus: list[CorpusQuestion]
) -> tuple[TopicAnalysisResult, LlmUsage]:
    return await provider.parse_structured(
        prompt=_corpus_block(topic, corpus),
        system=load_prompt(TOPIC_ANALYSIS_PROMPT_REF),
        schema=TopicAnalysisResult,
        tier="standard",
        max_tokens=8000,
    )


async def generate_one_pager(
    provider: LLMProvider, topic: Topic, corpus: list[CorpusQuestion]
) -> tuple[OnePagerResult, LlmUsage]:
    return await provider.parse_structured(
        prompt=_corpus_block(topic, corpus),
        system=load_prompt(ONE_PAGER_PROMPT_REF),
        schema=OnePagerResult,
        tier="standard",
        max_tokens=12000,
    )
