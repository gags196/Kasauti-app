"""Turn a hand-prepared Markdown transcription of a CSAT paper into ScanExtraction answers.

The founder can convert a scanned Paper 2 booklet to Markdown outside this repo, which
removes the slowest step of the ingestion runbook — reading forty page-pair images and
typing out 80 bilingual questions. This script is the bridge from that Markdown to the
file queue, so the rest of the pipeline (tagging, answer key, publish gate, embeddings)
runs exactly as it does for a paper read from the scans.

**It trusts nothing.** Markdown produced by OCR can drop a question, mis-number one, lose
an option, or silently omit a passage — all of which look fine until a learner sits the
paper. Every structural property the corpus depends on is asserted here and the script
refuses to write anything if one fails: 80 questions numbered 1..80 with no gaps or
duplicates, four options each, both languages present, and every passage carrying the
same run of items in Hindi as in English. What it cannot check is whether the words are
the printed words; that is what the runbook's spot-check against the scan is for.

## The Markdown dialect it reads

One file per ten questions. Inside each file, the English half then the Hindi half, and
inside each half an optional directions block, passages, and questions:

    # Questions 1 to 10 - ...
    ## English Version
    **Directions for the following 3 (three) items :**
    Read the following two passages ...
    ### Passage-1
    <passage text>
    **1. <stem>**
    1. <statement>
    Select the correct answer using the code given below.
    (a) ...
    (b) ...
    (c) ...
    (d) ...
    ### Passage-2
    **3. ...**
    ...
    ## Hindi Version (हिन्दी संस्करण)
    **निम्नलिखित 3 (तीन) प्रश्नांशों के लिए निर्देश :**
    ### परिच्छेद-1
    **1. ...**

The directions line's item count is load-bearing. "Directions for the following 3 items"
means the *first three* questions in the file belong to passages; everything after them
stands alone. Attaching by "most recent passage heading" alone would sweep every later
standalone question into the last passage, which is exactly the kind of error that
produces a plausible-looking corpus and unanswerable questions.

    uv run python scripts/md_paper_to_extraction.py "Paper 2 files/2022_P2" \
        --year 2022 --out var/papers/p2 --slice 1-20:428 --slice 21-40:429
"""

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

EXPECTED_OPTIONS = 4

# "**1. Which of the following ...**" — the bold question heading.
QUESTION_RE = re.compile(r"^\*\*(\d+)\.\s*(.*?)\*\*\s*$")
# "(a) 1 and 2 only"
OPTION_RE = re.compile(r"^\(([a-dA-D])\)\s*(.*)$")
# "### Passage-1" / "### परिच्छेद-1" / "### Passage"
PASSAGE_RE = re.compile(r"^###\s+(Passage|परिच्छेद)\b")
# "**Directions for the following 3 (three) items :**" — the count is what matters.
DIRECTIONS_RE = re.compile(r"^\*\*(Directions|निम्नलिखित).*?(\d+)\s*\(.*$")
HEADING_RE = re.compile(r"^#{1,6}\s")
# The paper prints "Question :" and "Statement-1 :" in plain type; the transcription
# marks them up. Emphasis is the transcriber's formatting, not the booklet's text, and a
# learner reading "*Question :*" in a rendered paragraph is reading a bug.
EMPHASIS_RE = re.compile(r"\*{1,3}(.+?)\*{1,3}")


def plain(text: str) -> str:
    """Markdown emphasis removed, leaving the words the paper actually prints."""
    return EMPHASIS_RE.sub(lambda match: match.group(1), text).strip()


@dataclass
class ParsedQuestion:
    number: int
    stem: list[str] = field(default_factory=list)
    options: dict[str, str] = field(default_factory=dict)
    passage_ref: str | None = None

    def text(self) -> str:
        return "\n".join(plain(line) for line in self.stem if line.strip()).strip()


@dataclass
class ParsedHalf:
    """One language's side of one file."""

    directions: str = ""
    passages: dict[str, list[str]] = field(default_factory=dict)
    questions: list[ParsedQuestion] = field(default_factory=list)


def parse_half(lines: list[str]) -> ParsedHalf:
    half = ParsedHalf()
    directions_count: int | None = None
    directions_lines: list[str] = []
    current_question: ParsedQuestion | None = None
    # Passages are keyed by the first question that follows them, which is unique across
    # the whole paper and survives the two halves being parsed independently.
    pending_passage_lines: list[str] | None = None
    passage_order: list[tuple[str, list[str]]] = []
    mode = "preamble"

    for raw in lines:
        line = raw.rstrip()

        directions_match = DIRECTIONS_RE.match(line)
        if directions_match and directions_count is None:
            directions_count = int(directions_match.group(2))
            mode = "directions"
            continue

        if PASSAGE_RE.match(line):
            pending_passage_lines = []
            passage_order.append(("", pending_passage_lines))
            current_question = None
            mode = "passage"
            continue

        question_match = QUESTION_RE.match(line)
        if question_match:
            current_question = ParsedQuestion(number=int(question_match.group(1)))
            if question_match.group(2).strip():
                current_question.stem.append(plain(question_match.group(2)))
            half.questions.append(current_question)
            # The first question after a passage heading names that passage.
            if pending_passage_lines is not None and passage_order[-1][0] == "":
                passage_order[-1] = (
                    f"passage-q{current_question.number}",
                    pending_passage_lines,
                )
                pending_passage_lines = None
            mode = "question"
            continue

        if HEADING_RE.match(line):
            # Any other heading (## Hindi Version, --- separators handled below) ends
            # whatever block we were in without starting a new one.
            current_question = None
            pending_passage_lines = None
            mode = "preamble"
            continue

        if not line.strip() or line.strip() == "---":
            continue

        if mode == "directions":
            directions_lines.append(plain(line))
        elif mode == "passage" and pending_passage_lines is not None:
            pending_passage_lines.append(plain(line))
        elif mode == "question" and current_question is not None:
            option_match = OPTION_RE.match(line.strip())
            if option_match:
                current_question.options[option_match.group(1).upper()] = (
                    plain(option_match.group(2))
                )
            else:
                current_question.stem.append(plain(line))

    half.directions = " ".join(directions_lines).strip()
    half.passages = {ref: body for ref, body in passage_order if ref}

    # Attach passages to exactly the first `directions_count` questions. See module
    # docstring: without this cap the trailing standalone questions inherit the last
    # passage and become questions about a text they do not belong to.
    if directions_count:
        attached = 0
        active: str | None = None
        for question in half.questions:
            for ref in half.passages:
                if ref == f"passage-q{question.number}":
                    active = ref
            if attached < directions_count and active is not None:
                question.passage_ref = active
                attached += 1
    return half


def split_halves(text: str) -> tuple[list[str], list[str]]:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("## Hindi Version") or line.startswith("## हिन्दी"):
            return lines[:index], lines[index:]
    raise SystemExit("no '## Hindi Version' heading — cannot split the two languages")


def parse_file(path: Path) -> tuple[ParsedHalf, ParsedHalf]:
    text = path.read_text(encoding="utf-8")
    english_lines, hindi_lines = split_halves(text)
    return parse_half(english_lines), parse_half(hindi_lines)


def build(folder: Path, year: int) -> tuple[list[dict], dict[str, dict]]:
    questions: dict[int, dict] = {}
    stimuli: dict[str, dict] = {}
    problems: list[str] = []

    for path in sorted(folder.glob("*.md")):
        english, hindi = parse_file(path)

        en_numbers = [q.number for q in english.questions]
        hi_numbers = [q.number for q in hindi.questions]
        if en_numbers != hi_numbers:
            problems.append(f"{path.name}: EN {en_numbers} != HI {hi_numbers}")
            continue

        hindi_by_number = {q.number: q for q in hindi.questions}
        for ref, body in english.passages.items():
            hindi_body = hindi.passages.get(ref)
            if hindi_body is None:
                problems.append(f"{path.name}: passage {ref} missing on the Hindi side")
                continue
            lead_en = english.directions
            lead_hi = hindi.directions
            stimuli[ref] = {
                "ref": ref,
                "kind": "passage",
                "text_en": (lead_en + "\n\n" + "\n".join(body)).strip(),
                "text_hi": (lead_hi + "\n\n" + "\n".join(hindi_body)).strip(),
            }

        for english_question in english.questions:
            hindi_question = hindi_by_number[english_question.number]
            if english_question.passage_ref != hindi_question.passage_ref:
                problems.append(
                    f"{path.name}: Q{english_question.number} attaches to "
                    f"{english_question.passage_ref} in English and "
                    f"{hindi_question.passage_ref} in Hindi"
                )
            questions[english_question.number] = {
                "question_number": str(english_question.number),
                "marks": None,
                "text_en": english_question.text(),
                "text_hi": hindi_question.text(),
                "math_latex": None,
                "options": [
                    {
                        "label": label,
                        "text_en": english_question.options.get(label),
                        "text_hi": hindi_question.options.get(label),
                    }
                    for label in ("A", "B", "C", "D")
                ],
                "tables": [],
                "stimulus_ref": english_question.passage_ref,
                "confidence": 0.9,
            }
            for side, parsed in (("English", english_question), ("Hindi", hindi_question)):
                if len(parsed.options) != EXPECTED_OPTIONS:
                    problems.append(
                        f"Q{parsed.number}: {len(parsed.options)} {side} option(s), "
                        f"expected {EXPECTED_OPTIONS}"
                    )
                if not parsed.text():
                    problems.append(f"Q{parsed.number}: empty {side} stem")

    if problems:
        print("REFUSING to write — the Markdown does not hold together:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        raise SystemExit(1)

    ordered = [questions[n] for n in sorted(questions)]
    return ordered, stimuli


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path, help="folder of per-ten-question .md files")
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--slice",
        action="append",
        required=True,
        metavar="LO-HI:SCAN_ID",
        help="question range and the source_scans id it was registered as, e.g. 1-20:428",
    )
    parser.add_argument("--expect", type=int, default=80, help="questions in the paper")
    parser.add_argument("--issues", action="append", default=[])
    args = parser.parse_args()

    questions, stimuli = build(args.folder, args.year)

    numbers = [int(q["question_number"]) for q in questions]
    missing = sorted(set(range(1, args.expect + 1)) - set(numbers))
    if missing or len(numbers) != args.expect:
        raise SystemExit(
            f"expected {args.expect} questions numbered 1..{args.expect}; "
            f"got {len(numbers)}, missing {missing}"
        )

    args.out.mkdir(parents=True, exist_ok=True)
    for spec in args.slice:
        span, scan_id = spec.split(":")
        lo, hi = (int(part) for part in span.split("-"))
        in_slice = [q for q in questions if lo <= int(q["question_number"]) <= hi]
        used = {q["stimulus_ref"] for q in in_slice if q["stimulus_ref"]}
        # A passage whose items straddle a slice boundary would arrive without them.
        for ref in used:
            owners = [
                int(q["question_number"]) for q in questions if q["stimulus_ref"] == ref
            ]
            if min(owners) < lo or max(owners) > hi:
                raise SystemExit(
                    f"slice {span} splits {ref}: its items are {owners}. "
                    "Move the boundary — a passage and its items must stay together."
                )
        payload = {
            "questions": in_slice,
            "stimuli": [stimuli[ref] for ref in stimuli if ref in used],
            "year_seen": args.year,
            "paper_title_seen": (
                f"Civil Services (Preliminary) Examination, {args.year} "
                "- General Studies Paper II"
            ),
            "overall_confidence": 0.9,
            "issues": args.issues,
        }
        name = args.out / f"extraction_{args.year}_scan{scan_id}_q{lo:02d}-{hi:02d}.json"
        name.write_text(
            json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        print(
            f"scan {scan_id}: {len(in_slice)} questions, "
            f"{len(payload['stimuli'])} stimuli -> {name}"
        )


if __name__ == "__main__":
    main()
