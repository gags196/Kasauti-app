"""arq tasks for the PYQ ingestion pipeline.

Flow per scan: download from R2 → vision extraction → draft question rows →
topic tagging → status=human_review. Publishing is a human action in /admin,
which enqueues embedding generation (Phase 1, task: hybrid search).
"""

import asyncio
import logging

from sqlalchemy import select

from kasauti_api.db.base import async_session_factory
from kasauti_api.db.models import (
    Paper,
    Question,
    QuestionOption,
    QuestionStimulus,
    QuestionTopicMap,
    SourceScan,
    StimulusKind,
    Topic,
)
from kasauti_api.db.models.cost_ledger import LlmFeature
from kasauti_api.db.models.questions import OcrStatus, QuestionLanguage, QuestionStatus, TaggedBy
from kasauti_api.domain.ingestion.extract import extract_scan
from kasauti_api.domain.ingestion.tag import candidate_topics_for_paper, tag_question
from kasauti_api.domain.llm.claude_provider import ClaudeProvider
from kasauti_api.domain.llm.cost_ledger import record_usage
from kasauti_api.settings import get_settings
from kasauti_api.storage import download_bytes

logger = logging.getLogger(__name__)


def _language(text_en: str | None, text_hi: str | None) -> QuestionLanguage:
    if text_en and text_hi:
        return QuestionLanguage.bilingual
    return QuestionLanguage.hi if text_hi else QuestionLanguage.en


async def process_scan(ctx: dict, scan_id: int) -> str:
    provider: ClaudeProvider = ctx.get("llm_provider") or ClaudeProvider()

    async with async_session_factory() as session:
        scan = (
            await session.execute(select(SourceScan).where(SourceScan.id == scan_id))
        ).scalar_one()
        paper = (
            await session.execute(select(Paper).where(Paper.id == scan.paper_id))
        ).scalar_one()

        pdf_bytes = await asyncio.to_thread(
            download_bytes, get_settings().r2_bucket_scans, scan.r2_key
        )

        extraction, usage = await extract_scan(
            provider, pdf_bytes, optional_subject_code=paper.optional_subject_code
        )
        await record_usage(
            session,
            feature=LlmFeature.pyq_ingestion,
            usage=usage,
            related_entity_type="source_scan",
            related_entity_id=str(scan.id),
        )
        scan.raw_extraction_json = extraction.model_dump()
        scan.ocr_confidence = extraction.overall_confidence
        scan.ocr_status = OcrStatus.extracted
        await session.flush()

        topics: list[Topic] = await candidate_topics_for_paper(session, paper.id)
        if not topics:
            logger.warning("Paper %s has no candidate topics; questions stay untagged", paper.id)

        # Passages and shared directions blocks land first, so the questions below can
        # point at them. Keyed on the extractor's own ref, which is unique per scan.
        stimulus_ids: dict[str, int] = {}
        for es in extraction.stimuli:
            try:
                kind = StimulusKind(es.kind.strip().lower())
            except ValueError:
                logger.warning("Unknown stimulus kind %r on ref %s; skipping", es.kind, es.ref)
                continue
            stimulus = (
                await session.execute(
                    select(QuestionStimulus).where(
                        QuestionStimulus.source_scan_id == scan.id,
                        QuestionStimulus.ref == es.ref,
                    )
                )
            ).scalar_one_or_none()
            if stimulus is None:
                stimulus = QuestionStimulus(source_scan_id=scan.id, ref=es.ref)
                session.add(stimulus)
            stimulus.paper_id = paper.id
            stimulus.year = scan.year
            stimulus.kind = kind
            stimulus.text_en = es.text_en
            stimulus.text_hi = es.text_hi
            await session.flush()
            stimulus_ids[es.ref] = stimulus.id

        for eq in extraction.questions:
            if eq.stimulus_ref and eq.stimulus_ref not in stimulus_ids:
                # An item pointing at a block that was never extracted would be
                # unanswerable. Say so loudly; publish readiness refuses it later.
                logger.warning(
                    "Question %s references unknown stimulus %r",
                    eq.question_number,
                    eq.stimulus_ref,
                )
            question = Question(
                exam_id=scan.exam_id,
                paper_id=paper.id,
                year=scan.year,
                question_number=eq.question_number,
                marks=eq.marks,
                language=_language(eq.text_en, eq.text_hi),
                question_text_en=eq.text_en,
                question_text_hi=eq.text_hi,
                question_text_original=eq.text_en or eq.text_hi,
                math_notation_latex=eq.math_latex,
                tables=[t.model_dump() for t in eq.tables] or None,
                source_scan_id=scan.id,
                stimulus_id=stimulus_ids.get(eq.stimulus_ref) if eq.stimulus_ref else None,
                status=QuestionStatus.human_review,
            )
            session.add(question)
            await session.flush()

            for opt in eq.options:
                session.add(
                    QuestionOption(
                        question_id=question.id,
                        option_label=opt.label.strip().upper()[:4],
                        option_text_en=opt.text_en,
                        option_text_hi=opt.text_hi,
                    )
                )

            if not topics:
                continue
            try:
                tag_result, tag_usage = await tag_question(provider, question, topics)
                await record_usage(
                    session,
                    feature=LlmFeature.pyq_tagging,
                    usage=tag_usage,
                    related_entity_type="question",
                    related_entity_id=str(question.id),
                )
                valid_paths = {str(t.path): t for t in topics}
                for tag in tag_result.tags:
                    topic = valid_paths.get(tag.topic_path)
                    if topic is None:
                        logger.warning("Tagger returned unknown path %s", tag.topic_path)
                        continue
                    session.add(
                        QuestionTopicMap(
                            question_id=question.id,
                            topic_id=topic.id,
                            confidence=tag.confidence,
                            tagged_by=TaggedBy.model,
                        )
                    )
            except Exception:
                logger.exception("Tagging failed for question %s; leaving untagged", question.id)

        scan.ocr_status = OcrStatus.human_review
        await session.commit()

    return f"scan {scan_id}: {len(extraction.questions)} questions extracted, pending review"
