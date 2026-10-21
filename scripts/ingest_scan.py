"""Intake a scanned PYQ paper: upload the PDF to R2, create a source_scans row,
and enqueue the extraction job.

    uv run python scripts/ingest_scan.py path/to/paper.pdf --paper-code mains-maths-1 --year 2019
"""

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api" / "src"))

from arq import create_pool  # noqa: E402
from kasauti_api.db.base import async_session_factory  # noqa: E402
from kasauti_api.db.models import Exam, Paper, SourceScan  # noqa: E402
from kasauti_api.settings import get_settings  # noqa: E402
from kasauti_api.storage import upload_bytes  # noqa: E402
from kasauti_api.workers.queue import redis_settings  # noqa: E402
from sqlalchemy import select  # noqa: E402


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--exam-code", default="upsc-cse")
    parser.add_argument("--paper-code", required=True)
    parser.add_argument("--year", type=int, required=True)
    args = parser.parse_args()

    pdf_bytes = args.pdf.read_bytes()
    key = f"scans/{args.exam_code}/{args.year}/{args.paper_code}/{uuid.uuid4().hex[:8]}.pdf"

    async with async_session_factory() as session:
        exam = (
            await session.execute(select(Exam).where(Exam.code == args.exam_code))
        ).scalar_one()
        paper = (
            await session.execute(
                select(Paper).where(Paper.exam_id == exam.id, Paper.code == args.paper_code)
            )
        ).scalar_one()

        await asyncio.to_thread(
            upload_bytes, get_settings().r2_bucket_scans, key, pdf_bytes, "application/pdf"
        )

        scan = SourceScan(exam_id=exam.id, paper_id=paper.id, year=args.year, r2_key=key)
        session.add(scan)
        await session.commit()
        scan_id = scan.id

    redis = await create_pool(redis_settings())
    job = await redis.enqueue_job("process_scan", scan_id)
    print(f"source_scan {scan_id} created, extraction job {job.job_id} enqueued")


if __name__ == "__main__":
    asyncio.run(main())
