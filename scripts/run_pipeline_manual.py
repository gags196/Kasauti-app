"""Drive the real pipeline stages with Claude Code answering instead of the API.

Calls the production arq task functions directly, injecting FileQueueProvider through
the `ctx` seam they already support — so no pipeline code changes, and the code path
under test is the one that will run in production.

    uv run python scripts/run_pipeline_manual.py extract <scan_id>
    uv run python scripts/run_pipeline_manual.py tag <scan_id>
    uv run python scripts/run_pipeline_manual.py analyze <topic_id> [--scope combined]
    uv run python scripts/run_pipeline_manual.py one-pager <topic_id>

Each command either completes, or queues LLM requests and stops having written nothing.
Answer the queue (scripts/llm_queue.py), then run the same command again.
"""

import argparse
import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api" / "src"))

from kasauti_api.db.base import async_session_factory  # noqa: E402
from kasauti_api.db.models import Paper, Question, QuestionTopicMap, SourceScan  # noqa: E402
from kasauti_api.db.models.cost_ledger import LlmFeature  # noqa: E402
from kasauti_api.db.models.questions import TaggedBy  # noqa: E402
from kasauti_api.domain.ingestion.tag import (  # noqa: E402
    TAG_BATCH_SIZE,
    candidate_topics_for_paper,
    tag_questions,
)
from kasauti_api.domain.llm.cost_ledger import record_usage  # noqa: E402
from kasauti_api.domain.llm.queue_provider import (  # noqa: E402
    DEFAULT_QUEUE_DIR,
    FileQueueProvider,
    LlmRequestPending,
)
from kasauti_api.workers.ingestion_tasks import process_scan  # noqa: E402
from kasauti_api.workers.intelligence_tasks import (  # noqa: E402
    analyze_topic,
    generate_topic_note,
)
from sqlalchemy import func, select  # noqa: E402

PENDING_HINT = (
    "\n  {n} request(s) queued. Next:\n"
    "    uv run python scripts/llm_queue.py list --pending\n"
    "  Answer them, then re-run this command."
)


def queued_count(provider: FileQueueProvider) -> int:
    answered = {p.stem for p in provider.paths.responses.glob("*.json")}
    return sum(1 for p in provider.paths.requests.glob("*.json") if p.stem not in answered)


async def cmd_extract(provider: FileQueueProvider, args: argparse.Namespace) -> None:
    """Extraction + first tagging sweep.

    process_scan creates question rows, so running it twice on the same scan would
    duplicate them — guard unless explicitly forced.
    """
    async with async_session_factory() as session:
        existing = (
            await session.execute(
                select(func.count(Question.id)).where(Question.source_scan_id == args.scan_id)
            )
        ).scalar_one()
    if existing and not args.force:
        raise SystemExit(
            f"scan {args.scan_id} already has {existing} questions — re-running would "
            "duplicate them.\n"
            "  To apply queued tag answers instead:  run_pipeline_manual.py tag "
            f"{args.scan_id}\n"
            "  To extract anyway (creates duplicates): --force"
        )

    try:
        result = await process_scan({"llm_provider": provider}, args.scan_id)
    except LlmRequestPending as pending:
        # Nothing was committed — process_scan commits only at the end.
        print(f"extraction queued as {pending.request_id}")
        print(PENDING_HINT.format(n=queued_count(provider)))
        return
    print(result)
    pending = queued_count(provider)
    if pending:
        print(PENDING_HINT.format(n=pending))


async def cmd_tag(provider: FileQueueProvider, args: argparse.Namespace) -> None:
    """Idempotent tagging pass: only questions with no topic map are touched, so this
    can be re-run safely as answers arrive."""
    tagged = queued = failed = 0

    async with async_session_factory() as session:
        scan = (
            await session.execute(select(SourceScan).where(SourceScan.id == args.scan_id))
        ).scalar_one()
        paper = (
            await session.execute(select(Paper).where(Paper.id == scan.paper_id))
        ).scalar_one()
        topics = await candidate_topics_for_paper(session, paper.id)
        if not topics:
            raise SystemExit(
                f"Paper {paper.code} has no candidate topics. Prelims papers tag against "
                "mapped Mains subjects — check tag_subjects in content/taxonomy/ and "
                "re-run scripts/seed_taxonomy.py."
            )

        untagged = (
            await session.execute(
                select(Question)
                .where(
                    Question.source_scan_id == args.scan_id,
                    ~select(QuestionTopicMap.question_id)
                    .where(QuestionTopicMap.question_id == Question.id)
                    .exists(),
                )
                .order_by(Question.id)
            )
        ).scalars().all()

        batches = [
            untagged[i : i + TAG_BATCH_SIZE]
            for i in range(0, len(untagged), TAG_BATCH_SIZE)
        ]
        print(
            f"{len(untagged)} untagged question(s), {len(topics)} candidate topics, "
            f"{len(batches)} batch(es) of up to {TAG_BATCH_SIZE}"
        )
        valid_paths = {str(t.path): t for t in topics}

        for batch in batches:
            try:
                result, usage = await tag_questions(provider, batch, topics)
            except LlmRequestPending:
                queued += len(batch)
                continue
            await record_usage(
                session,
                feature=LlmFeature.pyq_tagging,
                usage=usage,
                related_entity_type="question_batch",
                related_entity_id=",".join(str(q.id) for q in batch),
            )
            by_number = {q.question_number.strip(): q for q in batch}
            for entry in result.results:
                question = by_number.get(entry.question_number.strip())
                if question is None:
                    print(f"  ! batch returned unknown question {entry.question_number}")
                    continue
                applied = 0
                for tag in entry.tags:
                    topic = valid_paths.get(tag.topic_path)
                    if topic is None:
                        print(f"  ! question {question.id}: unknown path {tag.topic_path}")
                        continue
                    session.add(
                        QuestionTopicMap(
                            question_id=question.id,
                            topic_id=topic.id,
                            confidence=tag.confidence,
                            tagged_by=TaggedBy.model,
                        )
                    )
                    applied += 1
                if applied:
                    tagged += 1
                else:
                    failed += 1

        await session.commit()

    print(f"tagged {tagged}, queued {queued}, no valid topic {failed}")
    if queued:
        print(PENDING_HINT.format(n=queued))


async def cmd_analyze(provider: FileQueueProvider, args: argparse.Namespace) -> None:
    try:
        print(await analyze_topic({"llm_provider": provider}, args.topic_id, args.scope))
    except LlmRequestPending as pending:
        print(f"analysis queued as {pending.request_id}")
        print(PENDING_HINT.format(n=queued_count(provider)))


async def cmd_one_pager(provider: FileQueueProvider, args: argparse.Namespace) -> None:
    try:
        print(await generate_topic_note({"llm_provider": provider}, args.topic_id))
    except LlmRequestPending as pending:
        print(f"one-pager queued as {pending.request_id}")
        print(PENDING_HINT.format(n=queued_count(provider)))


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue-dir", type=Path, default=DEFAULT_QUEUE_DIR)
    sub = parser.add_subparsers(dest="command", required=True)

    p_extract = sub.add_parser("extract")
    p_extract.add_argument("scan_id", type=int)
    p_extract.add_argument("--force", action="store_true")

    p_tag = sub.add_parser("tag")
    p_tag.add_argument("scan_id", type=int)

    p_analyze = sub.add_parser("analyze")
    p_analyze.add_argument("topic_id", type=int)
    p_analyze.add_argument("--scope", default="combined",
                           choices=["prelims", "mains", "combined"])

    p_note = sub.add_parser("one-pager")
    p_note.add_argument("topic_id", type=int)

    args = parser.parse_args()
    provider = FileQueueProvider(args.queue_dir)

    handlers = {
        "extract": cmd_extract,
        "tag": cmd_tag,
        "analyze": cmd_analyze,
        "one-pager": cmd_one_pager,
    }
    await handlers[args.command](provider, args)


if __name__ == "__main__":
    asyncio.run(main())
