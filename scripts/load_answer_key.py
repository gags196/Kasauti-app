"""Load an official Prelims answer key: marks the correct option per question.

Feature A2 (option-pattern analysis) depends on this — without answer keys there is
nothing to analyze. Correctness is written nowhere else in the system.

CSV format (header required):  question_number,correct_label
    1,B
    2,D
    64,X      <- UPSC marks a dropped/withdrawn question with X

    uv run python scripts/load_answer_key.py key.csv --paper-code prelims-gs1 --year 2023

Keys are booklet-series specific. If the key names options the paper does not have, this
exits non-zero without committing rather than corrupting every answer in the paper.
"""

import argparse
import asyncio
import csv
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api" / "src"))

from kasauti_api.db.base import async_session_factory  # noqa: E402
from kasauti_api.db.models import Exam, Paper  # noqa: E402
from kasauti_api.domain.ingestion.answer_key import apply_answer_key  # noqa: E402
from sqlalchemy import select  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_file", type=Path)
    parser.add_argument("--exam-code", default="upsc-cse")
    parser.add_argument("--paper-code", required=True)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--quiet-missing", action="store_true",
                        help="don't list questions that aren't ingested yet")
    args = parser.parse_args()

    with args.csv_file.open(encoding="utf-8-sig", newline="") as f:
        key = {
            row["question_number"].strip(): row["correct_label"].strip().upper()
            for row in csv.DictReader(f)
        }

    async with async_session_factory() as session:
        exam = (
            await session.execute(select(Exam).where(Exam.code == args.exam_code))
        ).scalar_one()
        paper = (
            await session.execute(
                select(Paper).where(Paper.exam_id == exam.id, Paper.code == args.paper_code)
            )
        ).scalar_one()

        result = await apply_answer_key(
            session, paper_id=paper.id, year=args.year, key=key
        )

        if result.has_integrity_error:
            # Do not commit a partially-applied key: a label the paper does not have
            # almost always means this key belongs to a different booklet series.
            await session.rollback()
            print("ABORTED — the key names options these questions do not have:")
            for number, label in result.unknown_label[:10]:
                print(f"    Q{number}: key says {label}")
            print(
                "\n  This is the signature of a booklet-series mismatch. Series have\n"
                "  different question orders, so applying this key would corrupt every\n"
                "  answer in the paper. Check the series on the paper and on the key.\n"
                "  Nothing was written."
            )
            return 1

        await session.commit()

    print(f"answer key applied: {result.summary()}")
    if result.dropped:
        print(
            f"  dropped questions left with no correct option (is_correct stays NULL): "
            f"{', '.join(result.dropped)}"
        )
    if result.missing_question and not args.quiet_missing:
        preview = ", ".join(result.missing_question[:15])
        extra = len(result.missing_question) - 15
        more = f" (+{extra} more)" if extra > 0 else ""
        print(f"  not ingested yet, skipped: {preview}{more}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
