"""Turn a hand-prepared Markdown transcription of a Mains GS4 paper into ScanExtraction answers.

A fourth sibling of `md_mains_to_extraction.py` (GS1), `md_mains_gs2_to_extraction.py` (GS2)
and `md_mains_gs3_to_extraction.py` (GS3) — not a call to any of them. GS4's transcripts use
yet another dialect, and it varies year to year more than the other three papers did, so this
parser is deliberately tolerant. Confirmed by inspection per ARCHITECTURE.md's ingestion runbook.

## The GS4 dialect (2013-2025), and how it differs from GS1/2/3

- **Paper shape.** Two sections. 2013-2017 print FOURTEEN questions (Section A = 1..8,
  Section B = 9..14); 2018-2025 print TWELVE (Section A = 1..6, Section B = 7..12). Pass the
  count with `--expect`. Section B questions are long case studies; several Section A questions
  split into parts (a)/(b), and the "three quotations" question splits (a)/(b)/(c).

- **No `**हिन्दी**`/`**English**` markers**, and no consistent heading markup. A question starts
  inline at the start of a line as `N.` or `QN.` (the `Q` prefix comes and goes by year:
  2016-2018, 2023-2024 use it, the rest don't). Sub-parts appear two ways and this parser treats
  BOTH as the same question — one row per printed question number, parts concatenated, marks
  summed:
    * inline, `(b)` on its own line with no number (2013-2017, 2022-2024), or
    * as a repeated-number heading, `1. (a)` then `1.(b)` (2019, 2020, 2025).
  A heading line is only honoured when its number is the current one (a sub-part) or the next
  one in sequence, so a stray `13.` inside prose can never be mistaken for a heading.

- **Hindi vs English by script**, exactly as GS3: count Devanagari (U+0900-097F) vs Latin per
  line, bucket accordingly. Blank lines are dropped, never treated as a language boundary — a
  wrapped English sentence routinely carries a spurious mid-paragraph blank line.

- **Marks placement has four shapes across the years**, all handled:
    A. trailing on the English line after the word-limit marker — `(150 words) 10`,
       `(200 words) : 10`, or with wide OCR whitespace `(150 words)        10`
       (2013-2019, 2021, 2022, 2025).
    B. a bare number on its OWN line, right after a line that ended `(150 words)` (2020).
    C. trailing on the English *content* line, with `(Answer in 150 words)` on the FOLLOWING
       line — `...support of your answer. 10` (2023, 2024).
    D. a split total, `3×5=15` or `2×5=10`, at the end of the line (2013 Q2, 2022 Q5).
  Marks are read from English lines only; GS4's Hindi lines never carry the trailing number.

- **Page-footer junk appears mid-paper**, not just at the tail: booklet codes (`STH-G-GSF 2`,
  `CRNA-X-GSF/41`, `M-ESC-O-GSD 3`), bare page numbers, `[ P.T.O.`, `★★★`, and in 2015 an
  OCR-mangled tail (`C-803-0-FID9/52 ll 586---ग5,600`). Dropped by: a `/NN` booklet-page code,
  a `P.T.O.` marker, an all-caps/symbols line with no lowercase and no Devanagari, or a `★` run.
  The bare-number marks case (shape B) is checked before the all-caps filter so a lone `10`
  survives.

**It trusts nothing**, like its siblings: every question number 1..N present with no gaps or
duplicates, every question carrying non-empty text in both languages, at least one marks token
per question, and the paper's marks summing to exactly 250.

    uv run python scripts/md_mains_gs4_to_extraction.py GS4_md_files/2020.md \\
        --year 2020 --scan-id 745 --out var/papers/mains_gs4 --expect 12
"""

import argparse
import json
import re
import sys
from pathlib import Path

# "1." / "Q1." / "1. (a)" / "1.(b)" / "Q3.  " — number 1-2 digits so a stray 4-digit year
# ("2013." mid-sentence) is never a heading. Optional sub-part letter, then the rest inline.
HEADING_RE = re.compile(r"^(?:Q\.?\s*)?(\d{1,2})\.\s*(?:\(([a-eA-Eक-ह])\)\s*)?(.*)$")

# "खण्ड—A / SECTION—A", "खण्ड A", "SECTION 'B'", ... — a section divider, not a question.
SECTION_RE = re.compile(r"(?:SECTION|खण्ड)\s*[—–\-]?\s*['‘’\"]?\s*[AB]")

# Shape D: "3×5=15", "2 × 5 = 10", "7+5=12½" at the end of the line.
SPLIT_MARKS_RE = re.compile(r"\b\d+\s*(?:[×xX*]|\+)\s*\d+\s*=\s*(\d{1,3})(½)?\s*$")
# Shape A/C: a trailing 1-2 digit number (not part of a longer number).
TRAIL_NUM_RE = re.compile(r"(?<!\d)(\d{1,2})(½)?\s*$")
# Shape B: the whole line is just the number.
BARE_NUM_RE = re.compile(r"^(\d{1,2})(½)?$")
# A line that opens with the word-limit instruction (used to confirm a shape-C number).
NEXT_IS_WORDLIMIT_RE = re.compile(r"^\(?\s*(?:answer\s+in\b|उत्तर\b|\d+\s*words\b)", re.I)

DEVANAGARI_RE = re.compile(r"[ऀ-ॿ]")
LATIN_RE = re.compile(r"[A-Za-z]")
# A "real word": two Latin lowercase letters, or two Devanagari letters/matras in a row.
# Punctuation-only Devanagari (the danda "।") does NOT count, so a footer like
# "3 SDF-G-GSF ।" is still recognised as furniture.
WORD_RE = re.compile("[a-z]{2,}|[ऀ-ॣ]{2,}")

EXPECTED_TOTAL_MARKS = 250
BARE_MARKS_VALUES = {10.0, 12.0, 12.5, 15.0, 20.0, 25.0}


def marks_value(digits: str, half: str | None) -> float:
    return int(digits) + (0.5 if half else 0)


def classify(line: str) -> str | None:
    """Which language a line belongs to, by script majority; None if it has no letters."""
    dev = len(DEVANAGARI_RE.findall(line))
    lat = len(LATIN_RE.findall(line))
    if dev == 0 and lat == 0:
        return None
    return "hi" if dev > lat else "en"


def is_footer(line: str) -> bool:
    """Page-furniture that must never reach a stem: booklet codes, P.T.O., page numbers."""
    if not line or line == "---":
        return True
    if re.fullmatch(r"[★*●\s]+", line):  # ★★★ end-of-paper marks
        return True
    if re.search(r"/\s*\d{2}\b", line):  # booklet-page code: ".../41", "/52"
        return True
    if re.search(r"P\.?\s*T\.?\s*O\.?", line, re.I) and len(line) < 40:
        return True
    if re.search("[A-Z]{2,6}-[A-Z]-[A-Z]{2,4}", line):  # booklet code, e.g. SDF-G-GSF
        return True
    if re.search("kkk", line, re.I):  # end-of-paper marker in some transcripts
        return True
    if not WORD_RE.search(line):  # all-caps codes, bare page numbers, "[ ... ]"
        return True
    return False


def take_trailing_marks(line: str, next_content: str | None) -> tuple[str, float | None]:
    """Split a marks token off the end of an English line (shapes A, C, D)."""
    split = SPLIT_MARKS_RE.search(line)
    if split:
        return line[: split.start()].rstrip(" :"), marks_value(split.group(1), split.group(2))

    trail = TRAIL_NUM_RE.search(line)
    if not trail:
        return line, None
    here = ("words)" in line.lower()) or ("शब्द" in line)
    after = bool(next_content and NEXT_IS_WORDLIMIT_RE.match(next_content.strip()))
    if not (here or after):
        return line, None
    return line[: trail.start(1)].rstrip(" :"), marks_value(trail.group(1), trail.group(2))


def parse(path: Path, expect: int) -> tuple[list[dict], list[str]]:
    raw_lines = path.read_text(encoding="utf-8").splitlines()
    lines = [ln.strip() for ln in raw_lines]
    problems: list[str] = []
    questions: dict[int, dict] = {}

    qnum: int | None = None
    section_gap = False
    hi: list[str] = []
    en: list[str] = []
    marks_total = 0.0
    marks_seen = 0

    def flush() -> None:
        nonlocal marks_total, marks_seen
        if qnum is None:
            return
        if qnum in questions:
            problems.append(f"duplicate question number {qnum}")
        questions[qnum] = {
            "question_number": str(qnum),
            "marks": marks_total if marks_seen else None,
            "text_en": "\n".join(en).strip(),
            "text_hi": "\n".join(hi).strip(),
            "math_latex": None,
            "options": [],
            "tables": [],
            "stimulus_ref": None,
            "confidence": 0.9,
        }

    for idx, line in enumerate(lines):
        if not line:
            continue

        heading = HEADING_RE.match(line)
        if heading:
            n = int(heading.group(1))
            first = qnum is None and n == 1
            same = qnum is not None and n == qnum
            nxt = qnum is not None and n == qnum + 1
            if first or nxt:
                flush()
                qnum, hi, en = n, [], []
                marks_total, marks_seen = 0.0, 0
                section_gap = False
            elif same:
                section_gap = False
            else:
                heading = None  # a number in prose, not a real heading — fall through
            if heading:
                rest = heading.group(3).strip()
                part = heading.group(2)
                if part:
                    rest = f"({part}) {rest}".strip()
                if rest:
                    lang = _consume_text(rest, hi, en)
                    if lang == "en":
                        marks_total, marks_seen = _maybe_marks(
                            en, lines, idx, marks_total, marks_seen
                        )
                    elif lang == "hi":
                        marks_total, marks_seen = _maybe_split_marks(hi, marks_total, marks_seen)
                continue

        if SECTION_RE.search(line):
            section_gap = True
            continue

        bare = BARE_NUM_RE.match(line)
        if bare:
            val = marks_value(bare.group(1), bare.group(2))
            prev_open = bool(qnum is not None and en and en[-1].rstrip().endswith(")"))
            nxt = _next_content(lines, idx)
            next_wl = bool(nxt and NEXT_IS_WORDLIMIT_RE.match(nxt.strip()))
            if qnum is not None and val in BARE_MARKS_VALUES and (prev_open or next_wl):
                marks_total += val
                marks_seen += 1
            continue  # otherwise a stray page number — drop it

        if is_footer(line):
            continue
        if qnum is None or section_gap:
            continue

        lang = _consume_text(line, hi, en)
        if lang == "en":
            marks_total, marks_seen = _maybe_marks(en, lines, idx, marks_total, marks_seen)
        elif lang == "hi":
            marks_total, marks_seen = _maybe_split_marks(hi, marks_total, marks_seen)

    flush()

    numbers = sorted(questions)
    if numbers != list(range(1, expect + 1)):
        missing = sorted(set(range(1, expect + 1)) - set(numbers))
        problems.append(f"expected questions 1..{expect}; missing {missing}, got {numbers}")

    for n, q in questions.items():
        if not q["text_en"]:
            problems.append(f"Q{n}: empty English stem")
        if not q["text_hi"]:
            problems.append(f"Q{n}: empty Hindi stem")
        if q["marks"] is None:
            problems.append(f"Q{n}: no marks token found")

    total = sum(q["marks"] for q in questions.values() if q["marks"] is not None)
    if abs(total - EXPECTED_TOTAL_MARKS) > 1e-6:
        problems.append(f"total marks {total} != {EXPECTED_TOTAL_MARKS}")

    return [questions[n] for n in numbers], problems


def _next_content(lines: list[str], idx: int) -> str | None:
    for j in range(idx + 1, len(lines)):
        if lines[j]:
            return lines[j]
    return None


def _consume_text(line: str, hi: list[str], en: list[str]) -> str | None:
    lang = classify(line)
    cleaned = re.sub(r"\s*[=|]\s*$", "", line)
    if lang == "hi":
        hi.append(cleaned)
    elif lang == "en":
        en.append(cleaned)
    return lang


def _maybe_split_marks(buf: list[str], total: float, seen: int) -> tuple[float, int]:
    """Shape D on a Hindi line: 2022 Q5(b) prints '... : 2×5=10' only in Hindi."""
    match = SPLIT_MARKS_RE.search(buf[-1])
    if not match:
        return total, seen
    buf[-1] = buf[-1][: match.start()].rstrip(" :")
    if not buf[-1]:
        buf.pop()
    return total + marks_value(match.group(1), match.group(2)), seen + 1


def _maybe_marks(
    en: list[str], lines: list[str], idx: int, total: float, seen: int
) -> tuple[float, int]:
    stripped, value = take_trailing_marks(en[-1], _next_content(lines, idx))
    if value is None:
        return total, seen
    if stripped:
        en[-1] = stripped
    else:
        en.pop()
    return total + value, seen + 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path, help="one year's Mains GS4 markdown transcript")
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--scan-id", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--expect", type=int, required=True,
                        help="printed questions (14 up to 2017, 12 from 2018)")
    parser.add_argument("--paper-name", default="General Studies Paper IV")
    parser.add_argument("--issues", action="append", default=[])
    args = parser.parse_args()

    questions, problems = parse(args.file, args.expect)

    if problems:
        print("REFUSING to write — the Markdown does not hold together:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        raise SystemExit(1)

    total = sum(q["marks"] for q in questions)
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
    print(f"scan {args.scan_id}: {len(questions)} questions, {total} marks -> {name}")


if __name__ == "__main__":
    main()
