"""Split a paper already in R2 into page-range slices, upload them, and register each.

A whole paper cannot be extracted in one call. Two independent limits force slicing:
Anthropic's 32 MB per-request cap (the 2026 Prelims booklet is 34 MB), and `extract_scan`'s
32,000 output tokens against the ~65,000 a bilingual 100-question paper produces — which
would truncate silently around question 49 rather than failing.

So every paper is sliced. This does the whole preparation in one pass:

    uv run python scripts/prepare_scan_slices.py "Prelims/Paper1/2025.pdf" \\
        --paper-code prelims-gs1 --year 2025 --slices 2-15,16-29,30-43,44-55

Idempotent at each step: an already-downloaded PDF is not re-fetched, an existing R2
object is not re-uploaded, and an already-registered key reuses its scan row. A run that
died halfway can simply be repeated.

Slice boundaries must fall between page pairs, never inside one. UPSC prints one page in
one language then the same questions in the other, so a slice that ends between them
leaves half a question in each — the exact failure the extraction prompt is written to
avoid. Which language leads varies by year (2017-2026 Hindi first, 2016 English first),
so the parity of the first page varies too; the even-page-count check below catches a
ragged slice but not a whole split offset by one. Verify the boundaries by eye.
"""

import argparse
import asyncio
import io
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api" / "src"))

import pypdfium2 as pdfium  # noqa: E402
from botocore.exceptions import ClientError  # noqa: E402
from kasauti_api.db.base import async_session_factory  # noqa: E402
from kasauti_api.settings import get_settings  # noqa: E402
from kasauti_api.storage import download_bytes, r2_client, upload_bytes  # noqa: E402
from pdf_pages import parse_pages  # noqa: E402  (same directory)
from register_r2_scan import register_scan, resolve_paper  # noqa: E402

DERIVED_PREFIX = "derived"


def object_exists(bucket: str, key: str) -> bool:
    try:
        r2_client().head_object(Bucket=bucket, Key=key)
        return True
    except ClientError:
        return False


def local_copy(bucket: str, key: str, dest_dir: Path, name: str | None) -> Path:
    """Fetch the source PDF once. Slicing is local; only the slices go back to R2."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / (name or Path(key).name)
    if path.exists():
        print(f"source already local: {path} ({path.stat().st_size / 1_048_576:.2f} MB)")
        return path
    print(f"downloading s3://{bucket}/{key} ...")
    path.write_bytes(download_bytes(bucket, key))
    print(f"  -> {path} ({path.stat().st_size / 1_048_576:.2f} MB)")
    return path


def slice_bytes(pdf_path: Path, pages: list[int]) -> bytes:
    """Extract a page range as its own PDF, in memory."""
    src = pdfium.PdfDocument(str(pdf_path))
    dst = pdfium.PdfDocument.new()
    dst.import_pages(src, pages)
    buffer = io.BytesIO()
    dst.save(buffer)
    return buffer.getvalue()


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("key", help="R2 key of the whole paper, e.g. Prelims/Paper1/2025.pdf")
    parser.add_argument("--exam-code", default="upsc-cse")
    parser.add_argument("--paper-code", required=True)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument(
        "--slices",
        required=True,
        help="comma-separated 1-based page ranges, e.g. '2-15,16-29,30-43'",
    )
    parser.add_argument(
        "--local-name",
        help="filename for the downloaded source, e.g. prelims_p1_2025.pdf",
    )
    parser.add_argument("--local-dir", type=Path, default=REPO_ROOT / "var" / "papers")
    args = parser.parse_args()

    bucket = get_settings().r2_bucket_scans
    source = await asyncio.to_thread(
        local_copy, bucket, args.key, args.local_dir, args.local_name
    )

    total_pages = len(pdfium.PdfDocument(str(source)))
    stem = Path(args.key).stem
    prefix = f"{DERIVED_PREFIX}/{Path(args.key).parent.as_posix()}"

    specs = []
    for spec in args.slices.split(","):
        pages = parse_pages(spec.strip(), total_pages)
        if not pages:
            raise SystemExit(f"slice {spec!r} selects no pages of {total_pages}")
        if len(pages) % 2:
            print(
                f"  ! slice {spec} covers {len(pages)} pages — an odd count means a "
                "bilingual page pair is split across slices. Check the boundary."
            )
        specs.append((spec.strip(), pages))

    print(f"{total_pages} page(s) in source; {len(specs)} slice(s) to prepare\n")

    scan_ids = []
    async with async_session_factory() as session:
        exam, paper = await resolve_paper(session, args.exam_code, args.paper_code)

        for spec, pages in specs:
            derived_key = f"{prefix}/{stem}_p{pages[0] + 1:03d}-{pages[-1] + 1:03d}.pdf"

            if await asyncio.to_thread(object_exists, bucket, derived_key):
                print(f"{spec}: already in R2 -> {derived_key}")
            else:
                data = await asyncio.to_thread(slice_bytes, source, pages)
                size_mb = len(data) / 1_048_576
                if size_mb > 32:
                    raise SystemExit(
                        f"slice {spec} is {size_mb:.2f} MB, over Anthropic's 32 MB "
                        "request limit — use narrower page ranges"
                    )
                await asyncio.to_thread(
                    upload_bytes, bucket, derived_key, data, "application/pdf"
                )
                print(f"{spec}: {len(pages)} page(s), {size_mb:.2f} MB -> {derived_key}")

            scan, created = await register_scan(
                session,
                exam=exam,
                paper=paper,
                year=args.year,
                key=derived_key,
                page_range=spec,
            )
            scan_ids.append(scan.id)
            print(f"       source_scan {scan.id} {'registered' if created else '(existing)'}")

        await session.commit()

    print("\nNext, per slice — render the page pairs, then extract:")
    for (spec, _), scan_id in zip(specs, scan_ids, strict=True):
        print(f"  uv run python scripts/pdf_pages.py pair {source} --pages {spec}")
        print(f"  uv run python scripts/run_pipeline_manual.py extract {scan_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
