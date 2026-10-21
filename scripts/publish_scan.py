"""Publish a reviewed scan's questions and generate their embeddings.

The CLI counterpart of the `/admin` "Approve & publish" action, for backfilling whole
papers where clicking through fifty rows at a time is not the job. It refuses to publish
a scan that is not ready rather than putting a half-extracted question in front of a
learner — run with --dry-run to see the report without writing anything.

    uv run python scripts/publish_scan.py 114 --dry-run
    uv run python scripts/publish_scan.py 114 --marks 2.0

--marks backfills questions whose marks are NULL. Pass it only with a figure read off the
booklet's own instruction page (a 100-item paper stating "Maximum Marks : 200" is 2.0);
extraction deliberately leaves marks null because they are not printed per question, and
this step is that gap being filled deliberately, not an inference.

Embeddings are generated in-process by calling the same `embed_question` task the admin
action enqueues, so no arq worker needs to be running. The task upserts on
(question_id, lang), so re-running is safe.
"""

import argparse
import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api" / "src"))

from kasauti_api.db.base import async_session_factory  # noqa: E402
from kasauti_api.db.models import Question, SourceScan  # noqa: E402
from kasauti_api.domain.ingestion.publish import (  # noqa: E402
    check_scan_ready,
    publish_scan,
)
from kasauti_api.workers.embedding_tasks import embed_question  # noqa: E402
from sqlalchemy import select  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scan_id", type=int)
    parser.add_argument(
        "--marks",
        type=float,
        help="backfill this marks value where NULL; from the paper's instruction page",
    )
    parser.add_argument("--dry-run", action="store_true", help="report readiness, write nothing")
    parser.add_argument("--no-embed", action="store_true", help="publish without embedding")
    parser.add_argument(
        "--force",
        action="store_true",
        help="publish despite readiness problems (records them in the output)",
    )
    args = parser.parse_args()

    async with async_session_factory() as session:
        scan = (
            await session.execute(select(SourceScan).where(SourceScan.id == args.scan_id))
        ).scalar_one_or_none()
        if scan is None:
            print(f"no such source_scan: {args.scan_id}", file=sys.stderr)
            return 1

        report = await check_scan_ready(session, args.scan_id)
        print(f"scan {args.scan_id} ({scan.r2_key}, pages {scan.page_range or 'all'})")
        print(f"  {report.total} question(s)")
        for problem in report.problems():
            print(f"  ! {problem}")
        if report.ok:
            print("  ready to publish")

        if args.dry_run:
            return 0 if report.ok else 1
        if not report.ok and not args.force:
            print("\nNothing written. Fix the above, or re-run with --force.", file=sys.stderr)
            return 1

        result = await publish_scan(session, args.scan_id, marks=args.marks)
        await session.commit()
        print(f"  {result.summary()}")

    if args.no_embed or not result.published_ids:
        return 0

    print(f"\nembedding {len(result.published_ids)} question(s)...")
    failed = []
    for qid in result.published_ids:
        try:
            await embed_question({}, qid)
        except Exception as error:  # noqa: BLE001 - report and continue; re-runnable
            failed.append((qid, error))
            print(f"  ! question {qid}: {error}")
    print(f"embedded {len(result.published_ids) - len(failed)}/{len(result.published_ids)}")
    if failed:
        print("Re-run this command to retry the failures (embedding upserts, so it is safe).")
        return 1

    async with async_session_factory() as session:
        numbers = (
            await session.execute(
                select(Question.question_number)
                .where(Question.source_scan_id == args.scan_id)
                .order_by(Question.id)
            )
        ).scalars().all()
    print(f"done: Q{numbers[0]}-Q{numbers[-1]} published and embedded")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
