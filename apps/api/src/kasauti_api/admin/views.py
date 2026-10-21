"""Founder-facing admin: ingestion review queues, publish action, cost ledger.

All internal tooling lives here (plan decision: zero custom Next.js admin screens).
"""

import secrets

from arq import create_pool
from sqladmin import Admin, ModelView, action
from sqladmin.authentication import AuthenticationBackend
from sqlalchemy import update
from starlette.requests import Request
from starlette.responses import RedirectResponse

from kasauti_api.db.base import async_session_factory, engine
from kasauti_api.db.models import (
    Exam,
    LlmUsageEvent,
    Paper,
    Question,
    QuestionOption,
    QuestionTopicMap,
    SourceScan,
    Subject,
    Topic,
    TopicAnalysis,
    TopicNote,
)
from kasauti_api.db.models.intelligence import TopicNoteStatus
from kasauti_api.db.models.questions import OcrStatus, QuestionStatus
from kasauti_api.settings import get_settings
from kasauti_api.workers.queue import redis_settings


class AdminAuth(AuthenticationBackend):
    async def login(self, request: Request) -> bool:
        form = await request.form()
        s = get_settings()
        ok = secrets.compare_digest(
            str(form.get("username", "")), s.admin_username
        ) and secrets.compare_digest(str(form.get("password", "")), s.admin_password)
        if ok:
            request.session.update({"admin": True})
        return ok

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        return bool(request.session.get("admin"))


class SourceScanAdmin(ModelView, model=SourceScan):
    name_plural = "Source scans (ingestion queue)"
    column_list = [
        SourceScan.id,
        SourceScan.year,
        SourceScan.paper_id,
        SourceScan.ocr_status,
        SourceScan.ocr_confidence,
        SourceScan.reviewed_by,
    ]
    column_sortable_list = [SourceScan.id, SourceScan.year, SourceScan.ocr_confidence]
    column_searchable_list = [SourceScan.r2_key]
    column_default_sort = ("id", True)
    can_create = False


class QuestionAdmin(ModelView, model=Question):
    name_plural = "Questions (review & publish)"
    column_list = [
        Question.id,
        Question.year,
        Question.paper_id,
        Question.question_number,
        Question.marks,
        Question.language,
        Question.status,
        Question.question_text_en,
    ]
    column_sortable_list = [Question.id, Question.year, Question.status]
    column_searchable_list = [Question.question_text_en, Question.question_text_hi]
    column_default_sort = ("id", True)
    page_size = 50

    @action(
        name="publish",
        label="Approve & publish",
        confirmation_message="Publish selected questions and generate embeddings?",
        add_in_detail=True,
        add_in_list=True,
    )
    async def publish(self, request: Request):
        pks = request.query_params.get("pks", "")
        ids = [int(pk) for pk in pks.split(",") if pk]
        if ids:
            async with async_session_factory() as session:
                await session.execute(
                    update(Question)
                    .where(Question.id.in_(ids))
                    .values(status=QuestionStatus.published)
                )
                await session.commit()
            redis = await create_pool(redis_settings())
            for qid in ids:
                await redis.enqueue_job("embed_question", qid)
            await redis.close()
        return RedirectResponse(request.url_for("admin:list", identity=self.identity), 302)

    @action(
        name="mark_scan_published",
        label="Mark source scan published",
        add_in_list=True,
    )
    async def mark_scan_published(self, request: Request):
        pks = request.query_params.get("pks", "")
        ids = [int(pk) for pk in pks.split(",") if pk]
        if ids:
            async with async_session_factory() as session:
                scan_ids = {
                    row[0]
                    for row in (
                        await session.execute(
                            Question.__table__.select()
                            .with_only_columns(Question.source_scan_id)
                            .where(Question.id.in_(ids))
                        )
                    ).all()
                    if row[0] is not None
                }
                if scan_ids:
                    await session.execute(
                        update(SourceScan)
                        .where(SourceScan.id.in_(scan_ids))
                        .values(ocr_status=OcrStatus.published)
                    )
                await session.commit()
        return RedirectResponse(request.url_for("admin:list", identity=self.identity), 302)


class QuestionTopicMapAdmin(ModelView, model=QuestionTopicMap):
    name_plural = "Question–topic tags"
    column_list = [
        QuestionTopicMap.question_id,
        QuestionTopicMap.topic_id,
        QuestionTopicMap.confidence,
        QuestionTopicMap.tagged_by,
    ]


class TopicAdmin(ModelView, model=Topic):
    column_list = [Topic.id, Topic.path, Topic.name_en, Topic.name_hi, Topic.depth]
    column_searchable_list = [Topic.name_en, Topic.name_hi]
    can_create = False
    can_delete = False


class ExamAdmin(ModelView, model=Exam):
    column_list = [Exam.id, Exam.code, Exam.name_en, Exam.name_hi]


class PaperAdmin(ModelView, model=Paper):
    column_list = [Paper.id, Paper.code, Paper.name_en, Paper.stage, Paper.optional_subject_code]


class SubjectAdmin(ModelView, model=Subject):
    column_list = [Subject.id, Subject.code, Subject.name_en, Subject.paper_id]


class QuestionOptionAdmin(ModelView, model=QuestionOption):
    name_plural = "MCQ options"
    column_list = [
        QuestionOption.question_id,
        QuestionOption.option_label,
        QuestionOption.option_text_en,
        QuestionOption.is_correct,
    ]
    can_create = False


class TopicAnalysisAdmin(ModelView, model=TopicAnalysis):
    name_plural = "Topic analyses (A1)"
    column_list = [
        TopicAnalysis.id,
        TopicAnalysis.topic_id,
        TopicAnalysis.scope,
        TopicAnalysis.generated_at,
        TopicAnalysis.question_count,
        TopicAnalysis.model_name,
    ]
    column_default_sort = ("generated_at", True)
    can_create = False


class TopicNoteAdmin(ModelView, model=TopicNote):
    name_plural = "One-pagers (review & publish)"
    column_list = [
        TopicNote.id,
        TopicNote.topic_id,
        TopicNote.version,
        TopicNote.status,
        TopicNote.generated_at,
        TopicNote.question_count,
    ]
    column_default_sort = ("generated_at", True)
    can_create = False

    @action(
        name="publish_note",
        label="Publish one-pager",
        confirmation_message="Publish selected one-pagers to learners?",
        add_in_detail=True,
        add_in_list=True,
    )
    async def publish_note(self, request: Request):
        pks = request.query_params.get("pks", "")
        ids = [int(pk) for pk in pks.split(",") if pk]
        if ids:
            async with async_session_factory() as session:
                await session.execute(
                    update(TopicNote)
                    .where(TopicNote.id.in_(ids))
                    .values(status=TopicNoteStatus.published)
                )
                await session.commit()
        return RedirectResponse(request.url_for("admin:list", identity=self.identity), 302)


class LlmUsageAdmin(ModelView, model=LlmUsageEvent):
    name_plural = "LLM cost ledger"
    column_list = [
        LlmUsageEvent.created_at,
        LlmUsageEvent.feature,
        LlmUsageEvent.model,
        LlmUsageEvent.input_tokens,
        LlmUsageEvent.output_tokens,
        LlmUsageEvent.cost_usd,
        LlmUsageEvent.related_entity_type,
        LlmUsageEvent.related_entity_id,
    ]
    column_default_sort = ("created_at", True)
    can_create = False
    can_edit = False
    can_delete = False


def mount_admin(app) -> Admin:
    admin = Admin(
        app,
        engine,
        authentication_backend=AdminAuth(secret_key=get_settings().auth_secret),
    )
    for view in (
        SourceScanAdmin,
        QuestionAdmin,
        QuestionOptionAdmin,
        QuestionTopicMapAdmin,
        TopicAnalysisAdmin,
        TopicNoteAdmin,
        TopicAdmin,
        ExamAdmin,
        PaperAdmin,
        SubjectAdmin,
        LlmUsageAdmin,
    ):
        admin.add_view(view)
    return admin
