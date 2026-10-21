"""arq task: generate bilingual embeddings for a published question.

Enqueued by the /admin approve-and-publish action. One row per language
variant so cross-lingual search works in both directions.
"""

import logging

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from kasauti_api.db.base import async_session_factory
from kasauti_api.db.models import Question, QuestionEmbedding
from kasauti_api.db.models.cost_ledger import LlmFeature
from kasauti_api.domain.llm.cost_ledger import record_usage
from kasauti_api.domain.llm.embedding_provider import EmbeddingProvider, get_embedding_provider

logger = logging.getLogger(__name__)


def _embeddable_text(question: Question, lang: str) -> str | None:
    text = question.question_text_en if lang == "en" else question.question_text_hi
    if not text:
        return None
    if question.math_notation_latex:
        text = f"{text}\n{question.math_notation_latex}"
    return text


async def embed_question(ctx: dict, question_id: int) -> str:
    provider: EmbeddingProvider = ctx.get("embedding_provider") or get_embedding_provider()

    async with async_session_factory() as session:
        question = (
            await session.execute(select(Question).where(Question.id == question_id))
        ).scalar_one()

        variants = [
            (lang, text)
            for lang in ("en", "hi")
            if (text := _embeddable_text(question, lang)) is not None
        ]
        if not variants:
            return f"question {question_id}: no text to embed"

        vectors, usage = await provider.embed(
            [text for _, text in variants], input_type="document"
        )
        await record_usage(
            session,
            feature=LlmFeature.embedding,
            usage=usage,
            related_entity_type="question",
            related_entity_id=str(question_id),
        )

        for (lang, _), vector in zip(variants, vectors, strict=True):
            stmt = (
                pg_insert(QuestionEmbedding)
                .values(
                    question_id=question_id,
                    lang=lang,
                    embedding=vector,
                    embedding_model=provider.model_name,
                )
                .on_conflict_do_update(
                    index_elements=["question_id", "lang"],
                    set_={"embedding": vector, "embedding_model": provider.model_name},
                )
            )
            await session.execute(stmt)
        await session.commit()

    return f"question {question_id}: embedded {[lang for lang, _ in variants]}"
