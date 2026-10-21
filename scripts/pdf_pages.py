"""Render PDF pages to PNG and report exact page geometry.

Two jobs, both needed because these papers are scanned images:
  1. Make pages readable by an agent with no system poppler install.
  2. Record page count and pixel dimensions, which drive the image-token half of the
     API cost estimate (Anthropic bills roughly width*height/750 tokens per image).

    uv run python scripts/pdf_pages.py info var/papers/2026.pdf
    uv run python scripts/pdf_pages.py render var/papers/2026.pdf --pages 1-8 --scale 2

Rendered pages land next to the PDF in <stem>_pages/page_NNN.png.
"""

import argparse
import json
from pathlib import Path

import pypdfium2 as pdfium

# Anthropic sizes image tokens at about (width * height) / 750 pixels.
PIXELS_PER_TOKEN = 750
# Images larger than ~1568px on the long edge are resized down to it, which caps the
# per-page cost. Any render at 150 DPI or above lands on this cap for a normal page.
MAX_LONG_EDGE = 1568

# The API's internal PDF render DPI is not documented, and it drives the whole input
# cost for a scanned paper, so report a band rather than a false-precision number:
#   low      — pages treated at their native point size (72 DPI). Optimistic.
#   expected — rendered at >=150 DPI and downscaled to the 1568px long-edge cap.
#              This is where a normal A4 page lands, so treat it as the planning number.
LOW_DPI = 72


def parse_pages(spec: str | None, total: int) -> list[int]:
    if not spec:
        return list(range(total))
    pages: list[int] = []
    for part in spec.split(","):
        if "-" in part:
            start, end = part.split("-", 1)
            pages.extend(range(int(start) - 1, int(end)))
        else:
            pages.append(int(part) - 1)
    return [p for p in pages if 0 <= p < total]


def page_geometry(pdf: pdfium.PdfDocument) -> list[dict]:
    out = []
    for index, page in enumerate(pdf):
        width, height = page.get_size()  # PDF points (1/72 inch)

        # Low: the page as-is at 72 DPI.
        low_tokens = width * height / PIXELS_PER_TOKEN

        # Expected: rendered at print resolution, then downscaled to the long-edge cap.
        cap_scale = MAX_LONG_EDGE / max(width, height)
        exp_w, exp_h = width * cap_scale, height * cap_scale
        expected_tokens = exp_w * exp_h / PIXELS_PER_TOKEN

        out.append(
            {
                "page": index + 1,
                "width_pt": round(width, 1),
                "height_pt": round(height, 1),
                "capped_px": [round(exp_w), round(exp_h)],
                "image_tokens_low": round(low_tokens),
                "image_tokens_expected": round(expected_tokens),
            }
        )
    return out


def cmd_info(args: argparse.Namespace) -> None:
    pdf = pdfium.PdfDocument(str(args.pdf))
    geometry = page_geometry(pdf)
    # A text layer means the API can read the page as text instead of pixels, which is
    # an order of magnitude cheaper — so it is the first thing to check on any scan.
    text_chars = sum(
        len(pdf[i].get_textpage().get_text_range().strip()) for i in range(len(pdf))
    )
    summary = {
        "file": str(args.pdf),
        "size_mb": round(args.pdf.stat().st_size / 1_048_576, 2),
        "page_count": len(geometry),
        "text_layer_chars": text_chars,
        "is_scanned": text_chars < 100 * len(geometry),
        "image_tokens_low": sum(g["image_tokens_low"] for g in geometry),
        "image_tokens_expected": sum(g["image_tokens_expected"] for g in geometry),
        "exceeds_api_request_limit_32mb": args.pdf.stat().st_size > 32 * 1_048_576,
        "exceeds_api_page_limit_100": len(geometry) > 100,
        "pages": geometry if args.verbose else geometry[:3],
    }
    print(json.dumps(summary, indent=2))
    if args.out:
        Path(args.out).write_text(
            json.dumps({**summary, "pages": geometry}, indent=2), encoding="utf-8"
        )
        print(f"\nfull geometry written to {args.out}")


def cmd_split(args: argparse.Namespace) -> None:
    """Write a page range out as its own PDF.

    Needed for real: the 2026 Prelims paper is 34 MB against Anthropic's 32 MB
    per-request limit, so whole-paper extraction is impossible via the API. Splitting
    also keeps a bilingual question block (Hindi page + its English page) intact.
    """
    src = pdfium.PdfDocument(str(args.pdf))
    pages = parse_pages(args.pages, len(src))
    if not pages:
        raise SystemExit(f"no pages selected from {args.pdf} ({len(src)} pages)")

    dst = pdfium.PdfDocument.new()
    dst.import_pages(src, pages)

    out = args.out or args.pdf.with_name(
        f"{args.pdf.stem}_p{pages[0] + 1:03d}-{pages[-1] + 1:03d}.pdf"
    )
    dst.save(str(out))
    size_mb = Path(out).stat().st_size / 1_048_576
    print(f"{len(pages)} page(s) -> {out}  ({size_mb:.2f} MB)")
    if size_mb > 32:
        print("  WARNING: still over Anthropic's 32 MB per-request limit")


def cmd_pair(args: argparse.Namespace) -> None:
    """Stitch each page beside its other-language counterpart into one image.

    UPSC prints one language's page then the same questions in the other. Putting the
    pair side by side means both languages of a question are visible at once, which is
    what extraction actually needs — and halves the number of images to read.

    Which language leads varies by year — 2017-2026 print Hindi first, 2016 English
    first — so this pairs consecutive pages from the given range and takes no view on
    the order. Getting the range's starting parity right is the caller's job.
    """
    from PIL import Image

    src = pdfium.PdfDocument(str(args.pdf))
    pages = parse_pages(args.pages, len(src))
    if len(pages) % 2:
        raise SystemExit(
            f"--pages must cover whole page pairs; got {len(pages)} pages. "
            "A pair is a page followed by the same questions in the other language."
        )

    out_dir = args.out_dir or args.pdf.parent / f"{args.pdf.stem}_pairs"
    out_dir.mkdir(parents=True, exist_ok=True)

    for left, right in zip(pages[::2], pages[1::2], strict=True):
        images = [src[i].render(scale=args.scale).to_pil() for i in (left, right)]
        width = sum(im.width for im in images)
        height = max(im.height for im in images)
        canvas = Image.new("RGB", (width, height), "white")
        offset = 0
        for im in images:
            canvas.paste(im, (offset, 0))
            offset += im.width
        path = out_dir / f"pair_{left + 1:03d}_{right + 1:03d}.png"
        canvas.save(path)
        print(f"{path}  {canvas.width}x{canvas.height}")
    print(f"\n{len(pages) // 2} pair(s) -> {out_dir}")


def cmd_render(args: argparse.Namespace) -> None:
    pdf = pdfium.PdfDocument(str(args.pdf))
    pages = parse_pages(args.pages, len(pdf))
    out_dir = args.out_dir or args.pdf.parent / f"{args.pdf.stem}_pages"
    out_dir.mkdir(parents=True, exist_ok=True)

    for index in pages:
        image = pdf[index].render(scale=args.scale).to_pil()
        path = out_dir / f"page_{index + 1:03d}.png"
        image.save(path)
        print(f"{path}  {image.width}x{image.height}")
    print(f"\n{len(pages)} page(s) -> {out_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_info = sub.add_parser("info")
    p_info.add_argument("pdf", type=Path)
    p_info.add_argument("--verbose", action="store_true")
    p_info.add_argument("--out")

    p_render = sub.add_parser("render")
    p_render.add_argument("pdf", type=Path)
    p_render.add_argument("--pages", help="e.g. '1-8' or '1,3,5'; default all")
    p_render.add_argument("--scale", type=float, default=2.0)
    p_render.add_argument("--out-dir", type=Path)

    p_split = sub.add_parser("split")
    p_split.add_argument("pdf", type=Path)
    p_split.add_argument("--pages", required=True, help="e.g. '2-5'")
    p_split.add_argument("--out", type=Path)

    p_pair = sub.add_parser("pair")
    p_pair.add_argument("pdf", type=Path)
    p_pair.add_argument("--pages", required=True, help="whole page pairs, e.g. '6-13'")
    p_pair.add_argument("--scale", type=float, default=2.0)
    p_pair.add_argument("--out-dir", type=Path)

    args = parser.parse_args()
    {
        "info": cmd_info,
        "render": cmd_render,
        "split": cmd_split,
        "pair": cmd_pair,
    }[args.command](args)


if __name__ == "__main__":
    main()
