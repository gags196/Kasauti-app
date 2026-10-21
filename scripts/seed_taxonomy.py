"""Seed the syllabus taxonomy from content/taxonomy/*.yaml into the database.

Idempotent: exams/papers/subjects upsert by code, topics upsert by ltree path,
so re-running after YAML edits updates names/descriptions in place.

    uv run python scripts/seed_taxonomy.py
"""

import asyncio
import sys
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_utils import Ltree

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api" / "src"))

from kasauti_api.db.base import async_session_factory  # noqa: E402
from kasauti_api.db.models import Exam, Paper, PaperSubjectMap, Subject, Topic  # noqa: E402
from kasauti_api.db.models.taxonomy import Stage  # noqa: E402

TAXONOMY_DIR = REPO_ROOT / "content" / "taxonomy"


def to_ltree_label(slug: str) -> str:
    return slug.replace("-", "_")


async def upsert_exam(session: AsyncSession, spec: dict) -> Exam:
    exam = (
        await session.execute(select(Exam).where(Exam.code == spec["code"]))
    ).scalar_one_or_none()
    if exam is None:
        exam = Exam(code=spec["code"])
        session.add(exam)
    exam.name_en = spec["name_en"]
    exam.name_hi = spec["name_hi"]
    await session.flush()
    return exam


async def upsert_paper(session: AsyncSession, exam: Exam, spec: dict) -> Paper:
    paper = (
        await session.execute(
            select(Paper).where(Paper.exam_id == exam.id, Paper.code == spec["code"])
        )
    ).scalar_one_or_none()
    if paper is None:
        paper = Paper(exam_id=exam.id, code=spec["code"])
        session.add(paper)
    paper.name_en = spec["name_en"]
    paper.name_hi = spec["name_hi"]
    paper.stage = Stage(spec["stage"])
    paper.optional_subject_code = spec.get("optional_subject_code")
    await session.flush()
    return paper


async def upsert_subject(session: AsyncSession, paper: Paper, spec: dict) -> Subject:
    subject = (
        await session.execute(
            select(Subject).where(Subject.paper_id == paper.id, Subject.code == spec["code"])
        )
    ).scalar_one_or_none()
    if subject is None:
        subject = Subject(paper_id=paper.id, code=spec["code"])
        session.add(subject)
    subject.name_en = spec["name_en"]
    subject.name_hi = spec["name_hi"]
    await session.flush()
    return subject


async def upsert_topic(
    session: AsyncSession,
    subject: Subject,
    spec: dict,
    parent: Topic | None,
    parent_path: str,
) -> int:
    path = f"{parent_path}.{to_ltree_label(spec['slug'])}" if parent_path else to_ltree_label(
        spec["slug"]
    )
    topic = (
        await session.execute(select(Topic).where(Topic.path == Ltree(path)))
    ).scalar_one_or_none()
    if topic is None:
        topic = Topic(path=Ltree(path), subject_id=subject.id)
        session.add(topic)
    topic.subject_id = subject.id
    topic.parent_id = parent.id if parent else None
    topic.depth = path.count(".")
    topic.slug = spec["slug"]
    topic.name_en = spec["name_en"]
    topic.name_hi = spec["name_hi"]
    topic.description_en = spec.get("description_en")
    topic.description_hi = spec.get("description_hi")
    await session.flush()

    count = 1
    for child in spec.get("children", []):
        count += await upsert_topic(session, subject, child, topic, path)
    return count


async def link_tag_subjects(
    session: AsyncSession, exam: Exam, paper: Paper, tag_subjects: list
) -> None:
    """Point a paper (e.g. Prelims) at existing subjects' topic trees for tagging.

    Each entry is either a bare subject code, or a mapping that also caps how deep
    that subject contributes:  {code: gs4, max_depth: 0}
    """
    for entry in tag_subjects:
        if isinstance(entry, dict):
            code, max_depth = entry["code"], entry.get("max_depth")
        else:
            code, max_depth = entry, None

        subject = (
            await session.execute(
                select(Subject)
                .join(Paper, Paper.id == Subject.paper_id)
                .where(Paper.exam_id == exam.id, Subject.code == code)
            )
        ).scalar_one()
        existing = (
            await session.execute(
                select(PaperSubjectMap).where(
                    PaperSubjectMap.paper_id == paper.id,
                    PaperSubjectMap.subject_id == subject.id,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            existing = PaperSubjectMap(paper_id=paper.id, subject_id=subject.id)
            session.add(existing)
        existing.max_topic_depth = max_depth
    await session.flush()


async def seed_file(session: AsyncSession, path: Path) -> int:
    spec = yaml.safe_load(path.read_text(encoding="utf-8"))
    exam = await upsert_exam(session, spec["exam"])
    total = 0
    for paper_spec in spec["papers"]:
        paper = await upsert_paper(session, exam, paper_spec)
        for subject_spec in paper_spec.get("subjects", []):
            subject = await upsert_subject(session, paper, subject_spec)
            root_path = to_ltree_label(subject_spec["code"])
            for topic_spec in subject_spec.get("topics", []):
                total += await upsert_topic(session, subject, topic_spec, None, root_path)
        if paper_spec.get("tag_subjects"):
            await link_tag_subjects(session, exam, paper, paper_spec["tag_subjects"])
    return total


async def main() -> None:
    files = sorted(TAXONOMY_DIR.glob("*.yaml"))
    if not files:
        print(f"No taxonomy files in {TAXONOMY_DIR}")
        return
    async with async_session_factory() as session:
        for path in files:
            n = await seed_file(session, path)
            print(f"{path.name}: {n} topics upserted")
        await session.commit()


if __name__ == "__main__":
    asyncio.run(main())
