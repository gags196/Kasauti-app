"""Turn a hand-prepared Markdown transcription of a Mains GS3 paper into ScanExtraction answers.

A third sibling of `md_mains_to_extraction.py` (GS1) and `md_mains_gs2_to_extraction.py` (GS2),
not a call to either: GS3's transcripts use yet another dialect, confirmed by inspection rather
than assumed from precedent (per ARCHITECTURE.md's ingestion runbook).

## The GS3 dialect (2013-2025), and how it differs from GS1's and GS2's

- There is no `**हिन्दी**`/`**English**` marker anywhere in any year's transcript, and no
  `##`/`###` heading for the question number either. Each question starts **inline**, at the
  start of a line, as `Qn.` (2013-2016, 2018-2019 mostly, 2025) or, in years whose OCR dropped
  the leading "Q" for the whole paper (2017, 2024) or for one stray question (2018 Q4, 2019 Q20),
  plain `n.`. Both forms are matched by one regex; the question number is restricted to 1-2
  digits so a stray 4-digit year (`2022.`, `2023.` — both appear mid-sentence, quoting a scheme's
  launch year, in 2023 and 2024) is never mistaken for a heading.
- 2013 is the one year with sub-parts, `Qn(a).`/`Qn(b).` inline (not a nested heading the way
  GS1's 2013 uses `### (a)`) — Q9, Q16, Q17 each split into two 5-mark halves.
- Hindi and English are not marked at all; they are told apart by **script**, counting Devanagari
  (U+0900-097F) vs Latin letters per line and bucketing accordingly. This is necessary because
  a wrapped English sentence can carry a spurious blank line in its middle (a PDF-to-text
  artifact, e.g. 2017/2024's "...(Answer\\n\\nin 150 words) 10") — blank lines are simply
  dropped, not treated as a language boundary the way GS1/GS2's explicit markers allowed.
- Marks are the trailing token on the English text's own last *content* line, same shape as
  GS2's dialect (a bare integer, or the unicode half "12½") — never a "+" split across sub-parts,
  since GS3's only split question (2013 Q9/16/17) already carries the split as two headed
  sub-parts rather than one line with "5+5". Every year prints real per-question marks (unlike
  GS2's 2014-2016, GS3 never falls back to a computed uniform value).
- **A question is closed the instant its marks token is found**, not at the next heading or EOF.
  Every transcript ends with page-footer junk after its last question — a repeated `kkk`
  end-of-paper marker, a booklet print code (`HI-ESC-O-GSC/ 62 4 7BS—6050`), or in 2018's case
  outright OCR garbage (`मी अल न a0 4 छछ9-. 0674`) that would otherwise script-classify as
  Hindi and corrupt the stem. Closing on the marks token discards all of it uniformly, without
  a single footer-pattern regex to keep in sync across years.

**It trusts nothing** in the same sense as its GS1/GS2 siblings: every expected question number
1..N present with no gaps or duplicates, every question carrying non-empty text in both
languages, and the paper's total marks summing to 250.

    uv run python scripts/md_mains_gs3_to_extraction.py gs3_md_files/2020.md \\
        --year 2020 --scan-id 730 --out var/papers/mains_gs3 --expect 20
"""

import argparse
import json
import re
import sys
from pathlib import Path

# "Q1." / "1." (a stray year like "2023." is excluded by the 1-2 digit limit) with the
# question's own text starting right on the same line.
HEADING_RE = re.compile(r"^(?:Q\.?\s*)?([0-9]{1,2})(?:\(([a-cA-C])\))?\.\s*(.*)$")
# Trailing marks token on a line: "10", "12½" — never a "+" form in GS3. Required to follow a
# closing ")" or "]" (the "(Answer in N words)" / "[N words]" instruction) so a bare number at a
# wrap boundary — a cited year ("...Companies Bill, 2013"), an Act, a COP number — is never
# mistaken for marks.
MARKS_TRAIL_RE = re.compile(r"[)\]]\s*(\d+)(½)?\s*$")

DEVANAGARI_RE = re.compile(r"[ऀ-ॿ]")
LATIN_RE = re.compile(r"[A-Za-z]")

EXPECTED_TOTAL_MARKS = 250


def join(lines: list[str]) -> str:
    return "\n".join(line for line in lines if line.strip()).strip()


def marks_value(digits: str, half: str | None) -> float:
    return int(digits) + (0.5 if half else 0)


def strip_trailing_marks(text: str) -> tuple[str, float | None]:
    """Split off a trailing marks token from the last line of a stem, if present."""
    if not text:
        return text, None
    lines = text.split("\n")
    last = lines[-1]
    match = MARKS_TRAIL_RE.search(last)
    if not match:
        return text, None
    value = marks_value(match.group(1), match.group(2))
    lines[-1] = last[: match.start(1)].rstrip()
    if not lines[-1]:
        lines.pop()
    return "\n".join(lines), value


def classify(line: str) -> str | None:
    """Which language a transcript line belongs to, by script majority; None for no letters."""
    devanagari = len(DEVANAGARI_RE.findall(line))
    latin = len(LATIN_RE.findall(line))
    if devanagari == 0 and latin == 0:
        return None
    return "hi" if devanagari > latin else "en"


def parse(path: Path) -> tuple[list[dict], list[str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    problems: list[str] = []
    questions: dict[str, dict] = {}

    qnum: int | None = None
    part: str | None = None
    closed = True
    hindi_buf: list[str] = []
    english_buf: list[str] = []

    def number() -> str:
        assert qnum is not None
        return f"{qnum}({part.lower()})" if part else str(qnum)

    def close_on_marks() -> None:
        nonlocal closed
        en_text, marks = strip_trailing_marks(join(english_buf))
        n = number()
        if n in questions:
            problems.append(f"duplicate question number {n}")
        questions[n] = {
            "question_number": n,
            "marks": marks,
            "text_en": en_text,
            "text_hi": join(hindi_buf),
            "math_latex": None,
            "options": [],
            "tables": [],
            "stimulus_ref": None,
            "confidence": 0.9,
        }
        closed = True

    for raw in lines:
        strip = raw.strip()
        if not strip or strip == "---" or strip.startswith("## Page"):
            continue

        m = HEADING_RE.match(strip)
        if m:
            if qnum is not None and not closed:
                problems.append(f"Q{number()}: no trailing marks found before next heading")
            qnum, part, closed = int(m.group(1)), m.group(2), False
            hindi_buf, english_buf = [], []
            rest = m.group(3)
            if rest:
                cls = classify(rest)
                if cls == "hi":
                    hindi_buf.append(rest)
                elif cls == "en":
                    english_buf.append(rest)
                    if MARKS_TRAIL_RE.search(rest):
                        close_on_marks()
            continue

        if closed:
            continue  # footer junk after the last question's marks were found

        cls = classify(strip)
        if cls == "hi":
            hindi_buf.append(strip)
        elif cls == "en":
            english_buf.append(strip)
            if MARKS_TRAIL_RE.search(strip):
                close_on_marks()

    if qnum is not None and not closed:
        problems.append(f"Q{number()}: no trailing marks found by end of file")

    for n, q in questions.items():
        if not q["text_en"]:
            problems.append(f"Q{n}: empty English stem")
        if not q["text_hi"]:
            problems.append(f"Q{n}: empty Hindi stem")
        if q["marks"] is None:
            problems.append(f"Q{n}: no marks")

    return [questions[n] for n in questions], problems


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path, help="one year's Mains GS3 markdown transcript")
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--scan-id", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--expect", type=int, required=True,
                        help="top-level questions in the paper")
    parser.add_argument("--paper-name", default="General Studies Paper III")
    parser.add_argument("--issues", action="append", default=[])
    args = parser.parse_args()

    questions, problems = parse(args.file)

    top_level = sorted({int(q["question_number"].split("(")[0]) for q in questions})
    missing = sorted(set(range(1, args.expect + 1)) - set(top_level))
    if missing or top_level != list(range(1, args.expect + 1)):
        problems.append(f"expected top-level questions 1..{args.expect}; missing {missing}")

    total_marks = sum(q["marks"] for q in questions if q["marks"] is not None)
    if abs(total_marks - EXPECTED_TOTAL_MARKS) > 1e-6:
        problems.append(f"total marks {total_marks} != {EXPECTED_TOTAL_MARKS}")

    if problems:
        print("REFUSING to write — the Markdown does not hold together:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        raise SystemExit(1)

    def sort_key(q: dict) -> tuple[int, str]:
        base, _, rest = q["question_number"].partition("(")
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
