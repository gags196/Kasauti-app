"""Turn a hand-prepared Markdown transcription of a Mains GS paper into ScanExtraction answers.

Mirrors `md_paper_to_extraction.py`'s role for CSAT, but for a different animal: Mains
questions carry no options and no answer key, marks are printed per question (or per
sub-part), and a paper is short enough (20-25 items) to need no slicing — one file maps
to one registered scan.

**It trusts nothing.** Every structural property the corpus depends on is asserted here:
every expected question number 1..N present with no gaps or duplicates, every question
carrying marks in both languages, and the paper's total marks summing to 250. What it
cannot check is whether the words are the printed words — that is what the runbook's
spot-check against the rendered scan is for (see ARCHITECTURE.md).

## The Markdown dialect it reads

One file per year. Heading style for the question number varies by year (`## 1.`,
`## Q.1`, `## Q1.` all appear across 2013-2025) so the number is pulled out with a
tolerant regex rather than assumed literal. A question with sub-parts nests them as
`### (a)` / `### (b)` headings under the parent `## N.` heading (seen only in 2013).
Inside each question or sub-part:

    ## 2.
    ### (a)
    **हिन्दी**
    <hindi stem, word limit inline as printed>
    **English**
    <english stem, word limit inline as printed>
    **5**

The trailing bold number is that question/part's marks, printed once after the English
text — unicode half ("12½") appears in 2015-2016 and is parsed as 12.5.

    uv run python scripts/md_mains_to_extraction.py GS1_md_files/2020.md \
        --year 2020 --scan-id 710 --out var/papers/mains_gs1 --expect 20
"""

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# "## 1." / "## Q.1" / "## Q1." — the question-number heading, dialect varies by year.
QUESTION_RE = re.compile(r"^##\s+(?:Q\.?\s*)?(\d+)\.?\s*$")
# "### (a)" — a sub-part heading nested under a parent question.
SUBPART_RE = re.compile(r"^###\s+\(([a-cA-C])\)\s*$")
# "**12**", "**12½**", or a split total "**7+5=12½**" (2016's dialect prints the
# per-part breakdown before the "="); only the final total after "=" matters here.
MARKS_RE = re.compile(r"^\*\*(?:[0-9½+]+=)?(\d+)(½)?\*\*$")
HEADING_RE = re.compile(r"^#{1,6}\s")
EMPHASIS_RE = re.compile(r"\*{1,3}(.+?)\*{1,3}")

EXPECTED_TOTAL_MARKS = 250


def plain(text: str) -> str:
    """Markdown emphasis removed, leaving the words the paper actually prints."""
    return EMPHASIS_RE.sub(lambda match: match.group(1), text).strip()


def join(lines: list[str]) -> str:
    return "\n".join(line for line in lines if line.strip()).strip()


@dataclass
class Entry:
    number: str
    hindi: list[str] = field(default_factory=list)
    english: list[str] = field(default_factory=list)
    marks: float | None = None


def parse(path: Path) -> tuple[list[dict], list[str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    problems: list[str] = []
    questions: dict[str, dict] = {}

    qnum: int | None = None
    part: str | None = None
    mode: str | None = None
    hindi_buf: list[str] = []
    english_buf: list[str] = []

    def number() -> str:
        assert qnum is not None
        return f"{qnum}({part.lower()})" if part else str(qnum)

    for raw in lines:
        line = raw.rstrip()
        strip = line.strip()

        m_q = QUESTION_RE.match(strip)
        if m_q:
            qnum, part, mode = int(m_q.group(1)), None, None
            hindi_buf, english_buf = [], []
            continue

        m_part = SUBPART_RE.match(strip)
        if m_part:
            if qnum is None:
                problems.append(f"sub-part {strip!r} with no parent question heading")
                continue
            part, mode = m_part.group(1), None
            hindi_buf, english_buf = [], []
            continue

        if strip == "**हिन्दी**":
            mode = "hindi"
            continue
        if strip == "**English**":
            mode = "english"
            continue

        m_marks = MARKS_RE.match(strip)
        if m_marks and qnum is not None:
            value = int(m_marks.group(1)) + (0.5 if m_marks.group(2) else 0)
            n = number()
            if n in questions:
                problems.append(f"duplicate question number {n}")
            questions[n] = {
                "question_number": n,
                "marks": value,
                "text_en": plain(join(english_buf)),
                "text_hi": plain(join(hindi_buf)),
                "math_latex": None,
                "options": [],
                "tables": [],
                "stimulus_ref": None,
                "confidence": 0.9,
            }
            mode = None
            hindi_buf, english_buf = [], []
            continue

        if HEADING_RE.match(strip):
            mode = None
            continue

        if not strip or strip == "---":
            continue

        if mode == "hindi":
            hindi_buf.append(line)
        elif mode == "english":
            english_buf.append(line)

    for n, q in questions.items():
        if not q["text_en"]:
            problems.append(f"Q{n}: empty English stem")
        if not q["text_hi"]:
            problems.append(f"Q{n}: empty Hindi stem")

    return [questions[n] for n in questions], problems


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path, help="one year's Mains GS markdown transcript")
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--scan-id", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--expect", type=int, required=True,
                        help="top-level questions in the paper")
    parser.add_argument("--paper-name", default="General Studies Paper I")
    parser.add_argument("--issues", action="append", default=[])
    args = parser.parse_args()

    questions, problems = parse(args.file)

    top_level = sorted({int(q["question_number"].split("(")[0]) for q in questions})
    missing = sorted(set(range(1, args.expect + 1)) - set(top_level))
    if missing or top_level != list(range(1, args.expect + 1)):
        problems.append(f"expected top-level questions 1..{args.expect}; missing {missing}")

    total_marks = sum(q["marks"] for q in questions)
    if total_marks != EXPECTED_TOTAL_MARKS:
        problems.append(f"total marks {total_marks} != {EXPECTED_TOTAL_MARKS}")

    if problems:
        print("REFUSING to write — the Markdown does not hold together:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        raise SystemExit(1)

    def sort_key(q: dict) -> tuple[int, str]:
        n = q["question_number"]
        base, _, rest = n.partition("(")
        return (int(base), rest)

    ordered = sorted(questions, key=sort_key)

    args.out.mkdir(parents=True, exist_ok=True)
    payload = {
        "questions": ordered,
        "stimuli": [],
        "year_seen": args.year,
        "paper_title_seen": f"Civil Services (Main) Examination, {args.year} - {args.paper_name}",
        "overall_confidence": 0.9,
        "issues": args.issues,
    }
    name = args.out / f"extraction_{args.year}_scan{args.scan_id}.json"
    name.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"scan {args.scan_id}: {len(ordered)} questions, {total_marks} marks -> {name}")


if __name__ == "__main__":
    main()
