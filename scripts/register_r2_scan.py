"""Register a PDF that is ALREADY in R2 as a source_scans row.

`ingest_scan.py` uploads a local file and generates its own key scheme. The PYQ corpus
was uploaded straight to the bucket under its own layout (Prelims/Paper1/2026.pdf), so
this points a scan row at an existing object instead of re-uploading it.

    uv run python scripts/register_r2_scan.py Prelims/Paper1/2026.pdf \\
        --paper-code prelims-gs1 --year 2026

Idempotent: re-registering the same key returns the existing scan.
"""

import argparse
import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api" / "src"))

from botocore.exceptions import ClientError  # noqa: E402
from kasauti_api.db.base import async_session_factory  # noqa: E402
from kasauti_api.db.models import Exam, Paper, SourceScan  # noqa: E402
from kasauti_api.settings import get_settings  # noqa: E402
from kasauti_api.storage import r2_client  # noqa: E402
from sqlalchemy import select  # noqa: E402


def head_object(bucket: str, key: str) -> dict:
    try:
        return r2_client().head_object(Bucket=bucket, Key=key)
    except ClientError as error:
        raise SystemExit(
            f"R2 object not found: s3://{bucket}/{key}\n"
            f"  {error}\n"
            "  Check KASAUTI_R2_* credentials and KASAUTI_R2_BUCKET_SCANS in .env."
        ) from error


async def resolve_paper(session, exam_code: str, paper_code: str):
    """The (exam, paper) a scan hangs off, with the errors that name their own fix."""
    exam = (
        await session.execute(select(Exam).where(Exam.code == exam_code))
    ).scalar_one_or_none()
    if exam is None:
        raise SystemExit(
            f"Exam {exam_code!r} not seeded — run scripts/seed_taxonomy.py first."
        )
    paper = (
        await session.execute(
            select(Paper).where(Paper.exam_id == exam.id, Paper.code == paper_code)
        )
    ).scalar_one_or_none()
    if paper is None:
        raise SystemExit(f"Paper {paper_code!r} not found for exam {exam_code!r}.")
    return exam, paper


async def register_scan(
    session, *, exam, paper, year: int, key: str, page_range: str | None = None
) -> tuple[SourceScan, bool]:
    """Point a scan row at an R2 object. Returns (scan, created). Does not commit.

    Idempotent by r2_key so a re-run of a partially-completed backfill is harmless.
    """
    existing = (
        await session.execute(select(SourceScan).where(SourceScan.r2_key == key))
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False

    scan = SourceScan(
        exam_id=exam.id,
        paper_id=paper.id,
        year=year,
        r2_key=key,
        page_range=page_range,
    )
    session.add(scan)
    await session.flush()
    return scan, True


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("key", help="R2 object key, e.g. Prelims/Paper1/2026.pdf")
    parser.add_argument("--exam-code", default="upsc-cse")
    parser.add_argument("--paper-code", required=True)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--page-range", help="e.g. '1-25', recorded for provenance")
    args = parser.parse_args()

    settings = get_settings()
    bucket = settings.r2_bucket_scans
    meta = await asyncio.to_thread(head_object, bucket, args.key)
    size_mb = meta["ContentLength"] / 1_048_576

    async with async_session_factory() as session:
        exam, paper = await resolve_paper(session, args.exam_code, args.paper_code)
        scan, created = await register_scan(
            session,
            exam=exam,
            paper=paper,
            year=args.year,
            key=args.key,
            page_range=args.page_range,
        )
        if not created:
            print(f"already registered: source_scan {scan.id} -> {args.key}")
            return
        await session.commit()
        print(
            f"source_scan {scan.id} registered -> s3://{bucket}/{args.key} ({size_mb:.2f} MB)\n"
            f"  next: uv run python scripts/run_pipeline_manual.py extract {scan.id}"
        )


if __name__ == "__main__":
    asyncio.run(main())
