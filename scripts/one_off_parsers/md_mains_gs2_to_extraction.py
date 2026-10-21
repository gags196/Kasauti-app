"""Turn a hand-prepared Markdown transcription of a Mains GS2 paper into ScanExtraction answers.

A sibling of `md_mains_to_extraction.py` (GS1), not a call to it: GS2's transcripts use a
materially different dialect, confirmed by inspection rather than assumed from GS1's precedent
(per ARCHITECTURE.md's ingestion runbook).

## The GS2 dialect (2013-2025), and how it differs from GS1's

- The question-number heading is `### N.` (three `#`) — GS1 uses two.
- No sub-parts (a)/(b) appear in any GS2 year 2013-2025.
- Marks are not a separate bold line. They are the trailing token(s) on the **English**
  paragraph's last line, e.g. "...municipalities? (Answer in 150 words) 10" or, for one
  two-part question (2017 Q10), "... (Answer in 150 words) 5+5" (sum the parts; no "=" form
  appears in GS2 the way it does in GS1's 2016 dialect). Most years also echo the same trailing
  number on the Hindi line; some years (2017-2022, 2024-2025) omit it there. Either way the
  trailing number/expression is stripped from whichever line(s) carry it before storing the stem.
- **2014, 2015 and 2016 carry no per-question marks at all** — the instructions state "All
  questions carry equal marks" (2014, 2016) or, for 2015, the transcript simply dropped the
  printed "12½" (confirmed against the rendered scan, source_scan 718 p.2 — every question prints
  12½). All three are pinned to 250/20 = 12.5 marks per question via `--uniform-marks-years`.

**It trusts nothing** in the same sense as its GS1 sibling: every expected question number 1..N
present with no gaps or duplicates, every question carrying non-empty text in both languages, and
the paper's total marks summing to 250.

    uv run python scripts/md_mains_gs2_to_extraction.py GS2_md_files/2020.md \\
        --year 2020 --scan-id 723 --out var/papers/mains_gs2 --expect 20
"""

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

QUESTION_RE = re.compile(r"^###\s+(\d+)\.\s*$")
HEADING_RE = re.compile(r"^#{1,6}\s")
EMPHASIS_RE = re.compile(r"\*{1,3}(.+?)\*{1,3}")
# Trailing marks token(s) on a line: "10", "12½", "5+5" — never an "=" form in GS2.
MARKS_TRAIL_RE = re.compile(r"((?:\d+(?:\.5)?|½)(?:\+(?:\d+(?:\.5)?|½))*)\s*$")

EXPECTED_TOTAL_MARKS = 250
UNIFORM_MARKS_YEARS = {2014, 2015, 2016}


def plain(text: str) -> str:
    """Markdown emphasis removed, leaving the words the paper actually prints."""
    return EMPHASIS_RE.sub(lambda match: match.group(1), text).strip()


def join(lines: list[str]) -> str:
    return "\n".join(line for line in lines if line.strip()).strip()


def marks_value(expr: str) -> float:
    parts = [12.5 if part == "½" else float(part.replace("½", ".5")) for part in expr.split("+")]
    return sum(parts)


def strip_trailing_marks(text: str) -> tuple[str, float | None]:
    """Split off a trailing marks expression from the last line of a stem, if present."""
    if not text:
        return text, None
    lines = text.split("\n")
    last = lines[-1]
    match = MARKS_TRAIL_RE.search(last)
    if not match:
        return text, None
    value = marks_value(match.group(1))
    lines[-1] = last[: match.start()].rstrip()
    if not lines[-1]:
        lines.pop()
    return "\n".join(lines), value


@dataclass
class Entry:
    number: int
    hindi: list[str] = field(default_factory=list)
    english: list[str] = field(default_factory=list)


def parse(path: Path, *, uniform: bool) -> tuple[list[dict], list[str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    problems: list[str] = []
    questions: dict[int, dict] = {}

    qnum: int | None = None
    mode: str | None = None
    hindi_buf: list[str] = []
    english_buf: list[str] = []

    def flush() -> None:
        if qnum is None:
            return
        hi_raw = plain(join(hindi_buf))
        en_raw = plain(join(english_buf))
        en_text, en_marks = strip_trailing_marks(en_raw)
        hi_text, hi_marks = strip_trailing_marks(hi_raw)

        if uniform:
            marks = None  # filled in by caller once the question count is known
        else:
            marks = en_marks
            if marks is None:
                problems.append(f"Q{qnum}: no trailing marks found on the English line")
            elif hi_marks is not None and hi_marks != marks:
                problems.append(f"Q{qnum}: Hindi marks {hi_marks} != English marks {marks}")

        if qnum in questions:
            problems.append(f"duplicate question number {qnum}")
        questions[qnum] = {
            "question_number": str(qnum),
            "marks": marks,
            "text_en": en_text,
            "text_hi": hi_text,
            "math_latex": None,
            "options": [],
            "tables": [],
            "stimulus_ref": None,
            "confidence": 0.9,
        }

    for raw in lines:
        line = raw.rstrip()
        strip = line.strip()

        m_q = QUESTION_RE.match(strip)
        if m_q:
            flush()
            qnum = int(m_q.group(1))
            mode = None
            hindi_buf, english_buf = [], []
            continue

        if strip == "**हिन्दी**":
            mode = "hindi"
            continue
        if strip == "**English**":
            mode = "english"
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

    flush()

    if uniform:
        per_q = EXPECTED_TOTAL_MARKS / len(questions) if questions else 0
        for q in questions.values():
            q["marks"] = per_q

    for n, q in questions.items():
        if not q["text_en"]:
            problems.append(f"Q{n}: empty English stem")
        if not q["text_hi"]:
            problems.append(f"Q{n}: empty Hindi stem")

    return [questions[n] for n in sorted(questions)], problems


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path, help="one year's Mains GS2 markdown transcript")
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--scan-id", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--expect", type=int, required=True, help="top-level questions in the paper"
    )
    parser.add_argument("--paper-name", default="General Studies Paper II")
    parser.add_argument("--issues", action="append", default=[])
    args = parser.parse_args()

    uniform = args.year in UNIFORM_MARKS_YEARS
    questions, problems = parse(args.file, uniform=uniform)

    numbers = sorted(int(q["question_number"]) for q in questions)
    missing = sorted(set(range(1, args.expect + 1)) - set(numbers))
    if missing or numbers != list(range(1, args.expect + 1)):
        problems.append(f"expected top-level questions 1..{args.expect}; missing {missing}")

    total_marks = sum(q["marks"] for q in questions)
    if abs(total_marks - EXPECTED_TOTAL_MARKS) > 1e-6:
        problems.append(f"total marks {total_marks} != {EXPECTED_TOTAL_MARKS}")

    if problems:
        print("REFUSING to write — the Markdown does not hold together:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        raise SystemExit(1)

    args.out.mkdir(parents=True, exist_ok=True)
    payload = {
        "questions": questions,
        "stimuli": [],
        "year_seen": args.year,
        "paper_title_seen": f"Civil Services (Main) Examination, {args.year} - {args.paper_name}",
        "overall_confidence": 0.9,
        "issues": args.issues,
    }
    name = args.out / f"extraction_{args.year}_scan{args.scan_id}.json"
    name.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"scan {args.scan_id}: {len(questions)} questions, {total_marks} marks -> {name}")


if __name__ == "__main__":
    main()
