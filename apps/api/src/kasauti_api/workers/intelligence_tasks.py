"""arq tasks for Feature A1 (topic analysis) and Feature B (one-pager)."""

import logging

from sqlalchemy import func, select

from kasauti_api.db.base import async_session_factory
from kasauti_api.db.models import Topic, TopicAnalysis, TopicNote
from kasauti_api.db.models.cost_ledger import LlmFeature
from kasauti_api.db.models.intelligence import AnalysisScope
from kasauti_api.db.models.taxonomy import Stage
from kasauti_api.domain.intelligence.generation import (
    MIN_QUESTIONS_FOR_ANALYSIS,
    ONE_PAGER_PROMPT_REF,
    TOPIC_ANALYSIS_PROMPT_REF,
    gather_topic_corpus,
    generate_one_pager,
    generate_topic_analysis,
)
from kasauti_api.domain.llm.claude_provider import ClaudeProvider
from kasauti_api.domain.llm.cost_ledger import record_usage

logger = logging.getLogger(__name__)

_SCOPE_TO_STAGE = {
    AnalysisScope.prelims: Stage.prelims,
    AnalysisScope.mains: Stage.mains,
    AnalysisScope.combined: None,
}


async def analyze_topic(ctx: dict, topic_id: int, scope: str = "combined") -> str:
    provider = ctx.get("llm_provider") or ClaudeProvider()
    analysis_scope = AnalysisScope(scope)

    async with async_session_factory() as session:
        topic = (
            await session.execute(select(Topic).where(Topic.id == topic_id))
        ).scalar_one()
        corpus = await gather_topic_corpus(
            session, topic, stage=_SCOPE_TO_STAGE[analysis_scope]
        )
        if len(corpus) < MIN_QUESTIONS_FOR_ANALYSIS:
            return (
                f"topic {topic_id} ({topic.path}): only {len(corpus)} published "
                f"questions in scope '{scope}' — need {MIN_QUESTIONS_FOR_ANALYSIS}, skipped"
            )

        result, usage = await generate_topic_analysis(provider, topic, corpus)
        await record_usage(
            session,
            feature=LlmFeature.topic_analysis,
            usage=usage,
            related_entity_type="topic",
            related_entity_id=str(topic_id),
        )
        session.add(
            TopicAnalysis(
                topic_id=topic_id,
                scope=analysis_scope,
                model_name=usage.model,
                prompt_ref=TOPIC_ANALYSIS_PROMPT_REF,
                question_count=len(corpus),
                pattern_summary_en=result.pattern_summary_en,
                pattern_summary_hi=result.pattern_summary_hi,
                predicted_angles=[a.model_dump() for a in result.predicted_angles],
            )
        )
        await session.commit()

    return f"topic {topic_id}: analysis stored ({len(corpus)} questions, scope {scope})"


async def generate_topic_note(ctx: dict, topic_id: int) -> str:
    provider = ctx.get("llm_provider") or ClaudeProvider()

    async with async_session_factory() as session:
        topic = (
            await session.execute(select(Topic).where(Topic.id == topic_id))
        ).scalar_one()
        corpus = await gather_topic_corpus(session, topic, stage=Stage.mains)
        if len(corpus) < MIN_QUESTIONS_FOR_ANALYSIS:
            return (
                f"topic {topic_id} ({topic.path}): only {len(corpus)} published mains "
                f"questions — need {MIN_QUESTIONS_FOR_ANALYSIS}, skipped"
            )

        result, usage = await generate_one_pager(provider, topic, corpus)
        await record_usage(
            session,
            feature=LlmFeature.one_pager,
            usage=usage,
            related_entity_type="topic",
            related_entity_id=str(topic_id),
        )
        next_version = (
            await session.execute(
                select(func.coalesce(func.max(TopicNote.version), 0) + 1).where(
                    TopicNote.topic_id == topic_id
                )
            )
        ).scalar_one()
        session.add(
            TopicNote(
                topic_id=topic_id,
                version=next_version,
                model_name=usage.model,
                prompt_ref=ONE_PAGER_PROMPT_REF,
                question_count=len(corpus),
                content_en=result.content_en.model_dump(),
                content_hi=result.content_hi.model_dump(),
            )
        )
        await session.commit()

    return f"topic {topic_id}: one-pager v{next_version} stored (draft)"
