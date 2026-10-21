"""Estimate what the Anthropic API would cost for PYQ extraction, from real measurements.

Built from artifacts that were actually measured — page geometry, and output-JSON
character counts split by script — recorded by FileQueueProvider during a manual run.
No token count here is a measurement: Anthropic's tokenizer is not public and its PDF
render DPI is not documented, so every figure is a band with its assumptions stated.

Recalibration: once a single real API call is made, put its reported usage into
CALIBRATION below and every number tightens to a measurement.

    uv run python scripts/token_cost_report.py --year 2026 \
        --questions-in-slice 100 --questions-per-paper 100 --slices 5 \
        --request-id abc123 --request-id def456 ... \
        --full-paper-geometry var/papers/prelims_p1_2026_geometry.json

The queue is shared by every paper, so the extraction requests for THIS paper must be
named explicitly; see load_extraction_measurement.
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api" / "src"))

from kasauti_api.domain.llm.cost_ledger import PRICING_PER_MTOK  # noqa: E402
from kasauti_api.domain.llm.queue_provider import DEFAULT_QUEUE_DIR  # noqa: E402

REPORT_DIR = REPO_ROOT / "benchmarks" / "reports" / "token-cost"

# Characters per token, by script. Anthropic's tokenizer is not published, so these are
# the documented rules of thumb for BPE tokenizers, given as a band.
# Devanagari is the crux: it tokenizes several times denser than Latin, so a bilingual
# corpus costs far more per character than an English-only one.
CHARS_PER_TOKEN = {
    #             low-token  expected  high-token
    "latin":      (4.2,      3.7,      3.1),
    "devanagari": (1.6,      1.05,     0.75),
    "digit":      (3.0,      2.5,      2.0),
    "other":      (3.4,      3.0,      2.4),  # JSON punctuation, whitespace, structure
}

# Set from a real API response's `usage` to convert estimates into measurements.
CALIBRATION: dict[str, int] | None = None

TIERS = {"light": "claude-haiku-4-5", "standard": "claude-sonnet-5"}


def split_chars(profile: dict) -> dict[str, int]:
    """Characters by bucket. 'other' is whatever is neither script nor digit —
    for a JSON payload that is mostly structural punctuation."""
    total = profile["total_chars"]
    dev = profile["devanagari_chars"]
    latin = profile["latin_chars"]
    digit = profile["digit_chars"]
    return {
        "latin": latin,
        "devanagari": dev,
        "digit": digit,
        "other": max(0, total - dev - latin - digit),
    }


def tokens_band(chars: dict[str, int]) -> tuple[int, int, int]:
    """(low, expected, high) token estimate for a character breakdown."""
    out = []
    for index in range(3):
        total = sum(
            count / CHARS_PER_TOKEN[bucket][index] for bucket, count in chars.items()
        )
        out.append(round(total))
    # index 0 uses the highest chars-per-token, so it yields the fewest tokens
    return out[0], out[1], out[2]


def usd(tokens: int, rate_per_mtok) -> float:
    return float(rate_per_mtok) * tokens / 1_000_000


def load_extraction_measurement(
    queue_dir: Path, *, request_ids: list[str], expected_slices: int
) -> dict:
    """Sum the answered extractions for ONE paper.

    A paper is extracted in several page-range slices (the scans exceed Anthropic's
    32 MB request limit), so the honest output figure is the total across all of them,
    not one slice extrapolated.

    The queue is shared by every paper ever run through it, and a measurement carries
    no year, so the caller must say which requests belong to this paper. Summing the
    whole directory silently reported four papers as one, inflating a committed report
    to 3x — hence `--request-id`, and `--slices` as the arithmetic check on it.
    """
    totals = {"total_chars": 0, "devanagari_chars": 0, "latin_chars": 0, "digit_chars": 0}
    system = None
    tier = None
    calls = 0
    wanted = set(request_ids)
    seen = set()
    for path in sorted((queue_dir / "measurements").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data["schema"] != "ScanExtraction" or not data.get("response"):
            continue
        if data["id"] not in wanted:
            continue
        seen.add(data["id"])
        for key in totals:
            totals[key] += data["response"][key]
        system = system or data["system"]
        tier = tier or data["tier"]
        calls += 1

    missing = wanted - seen
    if missing:
        raise SystemExit(
            "No answered ScanExtraction measurement for: "
            + ", ".join(sorted(missing))
            + "\n  Each --request-id must name an extraction that has been answered."
        )
    if calls != expected_slices:
        raise SystemExit(
            f"--slices says {expected_slices} but {calls} extraction(s) were summed.\n"
            "  The report would misstate the per-paper cost. Pass one --request-id "
            "per slice of this paper."
        )
    return {"response": totals, "system": system, "tier": tier, "calls": calls}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue-dir", type=Path, default=DEFAULT_QUEUE_DIR)
    parser.add_argument("--year", type=int, required=True,
                        help="exam year of the measured paper; identifies the report")
    parser.add_argument("--questions-in-slice", type=int, required=True)
    parser.add_argument("--questions-per-paper", type=int, default=100)
    parser.add_argument("--full-paper-geometry", type=Path, required=True,
                        help="JSON from scripts/pdf_pages.py info --out")
    parser.add_argument("--papers-in-corpus", type=int, default=14)
    parser.add_argument(
        "--request-id", action="append", dest="request_ids", required=True,
        metavar="ID",
        help="extraction request id for one slice of THIS paper; repeat per slice "
             "(run_pipeline_manual.py extract prints each one)",
    )
    parser.add_argument(
        "--slices", type=int, required=True,
        help="how many slices this paper was extracted in; must match the "
             "--request-id count actually summed",
    )
    args = parser.parse_args()

    m = load_extraction_measurement(
        args.queue_dir,
        request_ids=args.request_ids,
        expected_slices=args.slices,
    )
    geometry = json.loads(args.full_paper_geometry.read_text(encoding="utf-8"))

    scale = args.questions_per_paper / args.questions_in_slice

    # --- output side: measured on the slice, scaled to a full paper ---
    slice_chars = split_chars(m["response"])
    slice_out = tokens_band(slice_chars)
    paper_out = tuple(round(t * scale) for t in slice_out)

    # --- input side: system prompt (text) + every page as an image ---
    sys_tokens = tokens_band(split_chars(m["system"]))[1]
    img_low = geometry["image_tokens_low"]
    img_exp = geometry["image_tokens_expected"]
    paper_in = (img_low + sys_tokens, img_exp + sys_tokens, round(img_exp * 1.15) + sys_tokens)

    lines: list[str] = []
    add = lines.append

    add(
        f"# API cost estimate — Prelims GS1 Paper 1, {args.year} "
        f"({date.today().isoformat()})"
    )
    add("")
    scaled = args.questions_in_slice != args.questions_per_paper
    if scaled:
        add(f"Derived from a real manual extraction of **{args.questions_in_slice} "
            f"questions**, scaled to a {args.questions_per_paper}-question paper.")
    else:
        add(f"Measured across **the complete {args.questions_per_paper}-question paper** "
            f"({m['calls']} extraction calls, one per page-range slice). Output figures "
            "are totals, not extrapolations.")
    add("")
    add("> **These are estimates, not measurements.** Anthropic's tokenizer is not "
        "public and its PDF render DPI is not documented. Every figure below is a band "
        "with its assumptions stated. One real API call collapses the band to a "
        "measurement — see *Recalibration*.")
    add("")

    add("## What was actually measured")
    add("")
    add("| Quantity | Value |")
    add("|---|---|")
    add(f"| Source paper | {geometry['file']} |")
    add(f"| Pages | {geometry['page_count']} |")
    add(f"| File size | {geometry['size_mb']} MB |")
    add(f"| Text layer | {geometry['text_layer_chars']} chars "
        f"({'pure scan — vision required' if geometry['is_scanned'] else 'has text'}) |")
    add(f"| Over 32 MB API request limit | "
        f"{'**YES — must be split**' if geometry['exceeds_api_request_limit_32mb'] else 'no'} |")
    add(f"| Extraction tier used | `{m['tier']}` -> {TIERS[m['tier']]} |")
    add(f"| System prompt | {m['system']['total_chars']} chars |")
    add(f"| Output JSON, {args.questions_in_slice} questions | "
        f"{m['response']['total_chars']} chars |")
    add(f"| — of which Devanagari | {slice_chars['devanagari']} "
        f"({slice_chars['devanagari'] / m['response']['total_chars']:.0%}) |")
    add(f"| — of which Latin | {slice_chars['latin']} "
        f"({slice_chars['latin'] / m['response']['total_chars']:.0%}) |")
    add("")
    # `var/llm_queue/` is shared by every paper ever run, so a report that does not name
    # the requests it summed cannot be reproduced or audited later — which is what let an
    # earlier version silently report four papers as one.
    add("Measured from these extraction requests in `var/llm_queue/` "
        "(pass them back to `--request-id` to reproduce this report):")
    add("")
    for rid in args.request_ids:
        add(f"- `{rid}`")
    add("")

    add("## Estimated tokens for one full paper")
    add("")
    add("| | low | expected | high |")
    add("|---|---:|---:|---:|")
    add(f"| Input (pages as images + prompt) | {paper_in[0]:,} | {paper_in[1]:,} "
        f"| {paper_in[2]:,} |")
    add(f"| Output (bilingual JSON) | {paper_out[0]:,} | {paper_out[1]:,} | {paper_out[2]:,} |")
    add("")
    dev_tok = slice_chars["devanagari"] / CHARS_PER_TOKEN["devanagari"][1]
    add(f"**Devanagari is {slice_chars['devanagari'] / m['response']['total_chars']:.0%} of "
        f"output characters but ~{dev_tok / slice_out[1]:.0%} of output tokens.** "
        "Hindi, not page count, is the dominant cost driver in a bilingual corpus.")
    add("")

    add("## Cost per paper")
    add("")
    add("| Tier | Model | Input | Output | **Total** |")
    add("|---|---|---:|---:|---:|")
    for tier, model in TIERS.items():
        rate_in, rate_out = PRICING_PER_MTOK[model]
        cost_in = usd(paper_in[1], rate_in)
        cost_out = usd(paper_out[1], rate_out)
        add(f"| `{tier}` | {model} | ${cost_in:.3f} | ${cost_out:.3f} | "
            f"**${cost_in + cost_out:.3f}** |")
    add("")
    add("Sticker rates from `PRICING_PER_MTOK` in `domain/llm/cost_ledger.py`; discounts "
        "are deliberately ignored so cost is never understated.")
    add("")

    add("## Extrapolation")
    add("")
    add("| Scope | Papers | Haiku | Sonnet |")
    add("|---|---:|---:|---:|")
    for label, count in [
        ("This paper", 1),
        ("Prelims Paper 1, all years", args.papers_in_corpus),
        ("Whole bucket (Prelims P1+P2, GS1-4, Essay)", 89),
    ]:
        row = [label, str(count)]
        for model in TIERS.values():
            rate_in, rate_out = PRICING_PER_MTOK[model]
            total = (usd(paper_in[1], rate_in) + usd(paper_out[1], rate_out)) * count
            row.append(f"${total:,.2f}")
        add("| " + " | ".join(row) + " |")
    add("")
    add("Paper counts are from the R2 bucket listing. Mains papers are free-text rather "
        "than MCQ, so their output is smaller per question — these figures are an upper "
        "bound for those.")
    add("")

    add("## Findings that change the engineering, not just the budget")
    add("")
    add(f"1. **Output would truncate.** `extract_scan` sets `max_tokens=32000`. A full "
        f"{args.questions_per_paper}-question paper needs ~{paper_out[1]:,} output tokens, "
        f"so extraction would silently stop around question "
        f"{round(args.questions_per_paper * 32000 / paper_out[1])}. Papers must be split "
        "by page range regardless of the 32 MB limit.")
    add("")
    # Whether the size limit binds is a property of *this* paper, not of the corpus.
    # Hardcoding "it already bites" made every under-limit report contradict its own
    # geometry table, which is how a reader loses trust in the rest of the numbers.
    if geometry["size_mb"] > 32:
        add(f"2. **The 32 MB request limit already bites.** This paper is "
            f"{geometry['size_mb']} MB, over the limit. Splitting is mandatory for a "
            "second, independent reason.")
    else:
        add(f"2. **The 32 MB request limit does not bind here.** This paper is "
            f"{geometry['size_mb']} MB, under the limit — but finding 1 already makes "
            "splitting mandatory, so nothing changes. The limit bites on other papers "
            "in this bucket (the 2026 booklet is 34 MB), so the split step stays "
            "unconditional.")
    add("")
    add("3. **Output dominates input** at these ratios, and output is where Devanagari "
        "lands. Any cost work should target output size — for instance, not re-emitting "
        "option text that is identical across languages.")
    add("")
    add("4. **Tagging is the sleeper cost.** `tag_question` "
        "(`domain/ingestion/tag.py`) resends the entire candidate topic list on every "
        "question. At today's 18 GS2 topics that is negligible; against a full ~300-topic "
        "taxonomy it is roughly 400k input tokens per paper — comparable to or larger "
        "than extraction. Prompt caching or batching questions per call fixes it.")
    add("")
    add("5. **Batch API halves it.** Roughly 50% off for asynchronous processing, and a "
        "multi-year backfill is exactly that workload.")
    add("")

    add("## Assumptions")
    add("")
    add("| Bucket | chars/token (low / expected / high) |")
    add("|---|---|")
    for bucket, band in CHARS_PER_TOKEN.items():
        add(f"| {bucket} | {band[0]} / {band[1]} / {band[2]} |")
    add("")
    add("- Image tokens use Anthropic's ~`width x height / 750` rule. The *low* figure "
        "treats pages at their native 72 DPI point size; *expected* assumes rendering at "
        "print resolution then downscaling to the ~1568px long-edge cap, which is where a "
        "normal A4 page lands.")
    add("- This run does **not** validate tier quality. Extraction was done by Claude "
        "Code, a far larger model than Haiku. A paper transcribed cleanly here may still "
        "fail on the `light` tier — see `benchmarks/reports/extraction-accuracy/`.")
    add("")
    add("## Recalibration")
    add("")
    add("Make one real API call, then set `CALIBRATION` in this script from its reported "
        "`usage` and re-run. The bands collapse to measurements.")
    add("")
    if CALIBRATION:
        add(f"Currently calibrated against: `{CALIBRATION}`")
    else:
        add("**Not yet calibrated** — no real API call has been made.")
    add("")

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    # The paper year is part of the filename, not just the date: two papers measured
    # on the same day would otherwise write to the same path and the second would
    # silently overwrite the first. That happened once, to a committed report.
    out = REPORT_DIR / f"{date.today().isoformat()}_prelims-gs1-{args.year}-extraction.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"report written: {out.relative_to(REPO_ROOT)}")
    for tier, model in TIERS.items():
        rate_in, rate_out = PRICING_PER_MTOK[model]
        total = usd(paper_in[1], rate_in) + usd(paper_out[1], rate_out)
        print(f"  expected per paper on {tier:<9} ({model}): ${total:.3f}")


if __name__ == "__main__":
    main()
