"""Transcribe a handwritten answer booklet, with Claude Code answering instead of the API.

Calls the production transcription stage (`domain/extraction/handwriting.py`) through the
FileQueueProvider seam, so the path exercised here is the one that will run in production.

    uv run python scripts/transcribe_answer.py booklet.pdf --pages 3-4 --language hi \\
        --out var/answers/2026-09-01_hi-01

    # or from images already on disk
    uv run python scripts/transcribe_answer.py page1.jpg page2.jpg --language hi --out ...

The first run queues one LLM request and writes nothing; answer it with
`scripts/llm_queue.py`, then run the same command again. On success it writes
`<out>.json` (the full HandwrittenAnswer, uncertain spans and all) and `<out>.txt` (the
plain transcript), which is what `run_evaluation.py judge --answer` consumes.

Pages are extracted from a PDF into a one-page PDF per page rather than rendered to PNG:
a page image and a page of PDF cost about the same to read, and keeping the PDF avoids
introducing a rasterisation step between the source and the thing being measured. The
split pages are cached in `<out>_pages/` — see `documents_for` for why that is required
rather than merely tidy.
"""

import argparse
import asyncio
import io
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api" / "src"))

# Windows consoles default to cp1252, which raises UnicodeEncodeError on the first
# Devanagari character printed. A tool whose whole purpose is Hindi text must not crash
# when asked to show any; replace what the terminal genuinely cannot render and carry on.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import pypdfium2 as pdfium  # noqa: E402
from kasauti_api.db.base import async_session_factory  # noqa: E402
from kasauti_api.db.models.cost_ledger import LlmFeature  # noqa: E402
from kasauti_api.domain.extraction.handwriting import transcribe_answer  # noqa: E402
from kasauti_api.domain.llm.cost_ledger import record_usage  # noqa: E402
from kasauti_api.domain.llm.provider import DocumentInput  # noqa: E402
from kasauti_api.domain.llm.queue_provider import (  # noqa: E402
    DEFAULT_QUEUE_DIR,
    FileQueueProvider,
    LlmRequestPending,
)

MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


def parse_pages(spec: str | None, total: int) -> list[int]:
    """1-based page spec ('3-4', '1,5,9') to 0-based indices."""
    if not spec:
        return list(range(total))
    pages: list[int] = []
    for part in spec.split(","):
        if "-" in part:
            start, end = part.split("-", 1)
            pages.extend(range(int(start) - 1, int(end)))
        else:
            pages.append(int(part) - 1)
    out = [p for p in pages if 0 <= p < total]
    if not out:
        raise SystemExit(f"--pages {spec!r} selects nothing from a {total}-page document")
    return out


def documents_for(
    paths: list[Path], page_spec: str | None, page_dir: Path
) -> list[DocumentInput]:
    """One DocumentInput per page, with extracted PDF pages cached on disk.

    The cache is not an optimisation. `FileQueueProvider` derives a request id by hashing
    the attached document bytes so that re-running a job is a cache hit rather than a new
    question — and pdfium writes a fresh document id into every save, so splitting the
    same page twice produces different bytes and therefore a different request id. Left
    alone, the first run queues a request, the answer is written, and the second run
    queues a *different* request forever: the job can never complete. Splitting once and
    reusing the file fixes it, and leaves the exact pages that were read sitting next to
    the transcript where they can be checked.
    """
    documents: list[DocumentInput] = []
    page_dir.mkdir(parents=True, exist_ok=True)
    for path in paths:
        media_type = MEDIA_TYPES.get(path.suffix.lower())
        if media_type is None:
            raise SystemExit(f"{path}: unsupported file type {path.suffix!r}")
        if media_type != "application/pdf":
            documents.append(DocumentInput(data=path.read_bytes(), media_type=media_type))
            continue

        source = pdfium.PdfDocument(str(path))
        for index in parse_pages(page_spec, len(source)):
            cached = page_dir / f"{path.stem}_p{index + 1:03d}.pdf"
            if not cached.exists():
                single = pdfium.PdfDocument.new()
                single.import_pages(source, [index])
                stream = io.BytesIO()
                single.save(stream)
                cached.write_bytes(stream.getvalue())
            documents.append(
                DocumentInput(data=cached.read_bytes(), media_type="application/pdf")
            )
    return documents


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sources", nargs="+", type=Path, help="PDF and/or image pages")
    parser.add_argument("--pages", help="1-based page spec, PDFs only, e.g. 3-4 or 1,5")
    parser.add_argument("--language", choices=["en", "hi"], help="expected script (a hint)")
    parser.add_argument("--tier", default="standard", choices=["light", "standard"])
    parser.add_argument("--out", type=Path, required=True, help="output path without suffix")
    parser.add_argument("--queue-dir", type=Path, default=DEFAULT_QUEUE_DIR)
    args = parser.parse_args()

    page_dir = args.out.parent / f"{args.out.name}_pages"
    documents = documents_for(args.sources, args.pages, page_dir)
    print(f"{len(documents)} page(s) (cached in {page_dir}), tier {args.tier}")

    provider = FileQueueProvider(args.queue_dir)
    try:
        answer, usage = await transcribe_answer(
            provider,
            documents,
            page_count=len(documents),
            language_hint=args.language,
            tier=args.tier,
        )
    except LlmRequestPending as pending:
        print(f"transcription queued as {pending.request_id}")
        print(
            "  Next:\n"
            f"    uv run python scripts/llm_queue.py show {pending.request_id}\n"
            "  Answer it, then re-run this command."
        )
        return

    async with async_session_factory() as session:
        await record_usage(
            session,
            feature=LlmFeature.rubric_eval,
            usage=usage,
            related_entity_type="answer_transcript",
            related_entity_id=args.out.name[:64],
        )
        await session.commit()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    json_path = args.out.with_suffix(".json")
    text_path = args.out.with_suffix(".txt")
    json_path.write_text(
        answer.model_dump_json(indent=2, exclude_none=False), encoding="utf-8"
    )
    text_path.write_text(answer.text, encoding="utf-8")

    words = len(answer.text.split())
    print(
        f"language {answer.language}, {len(answer.pages)} page(s), ~{words} words, "
        f"{len(answer.uncertain_spans)} uncertain span(s)"
    )
    for span in answer.uncertain_spans:
        readings = " | ".join(span.readings) or "(no alternative reading)"
        print(f'  ? "{span.text}" ({span.confidence:.2f}) -> {readings}')
    print(f"\nwrote {json_path}\nwrote {text_path}")
    print(
        "\nConfirm the transcript (especially the spans above) before judging anything "
        "from it - a silently smoothed word becomes a rubric point nobody can audit."
    )


if __name__ == "__main__":
    asyncio.run(main())
