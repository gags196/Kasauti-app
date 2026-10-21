"""Turn a hand-prepared Markdown transcription of a Mains Essay paper into ScanExtraction answers.

A fifth sibling of the GS parsers (`md_mains_to_extraction.py` and friends), not a call to
any of them: the Essay dialect is its own animal, confirmed by reading all 13 years
2013-2025 (per ARCHITECTURE.md's ingestion runbook — verify the dialect, never assume precedent).

## The Essay dialect (2013-2025)

Every file opens with cover furniture (exam name, booklet code, निबन्ध / ESSAY, time,
maximum marks, the two instruction blocks). Then the essay topics.

- **2014-2025**: an English instruction line ("Write two essays, choosing one topic from
  each of the following Sections A and B ... **125×2=250**") precedes two sections. Each
  section is a `##` heading carrying `SECTION A` / `SECTION B` (and its Hindi twin
  `खण्ड A`), printed variously as `## खण्ड—A / SECTION—A`, `## खण्ड 'A' / SECTION 'A'`, or
  as two separate headings `## खण्ड A` then `## SECTION A` (2023-2024). Under each section
  are four topics, each a `### N.` heading followed by one Hindi line and one English line.
  Section B's printed numbers are 1-4 in 2014-2017 and 5-8 from 2018 on; either way this
  script renumbers to a single 1..8 run in order of appearance.
- **2013**: no sections at all. Four topics as `## Q. 1` .. `## Q. 4`, candidate writes
  ONE. The topics are printed *before* the instruction/cover blocks in the transcript;
  a heading that is neither a `## Q. N` nor a section closes the current topic, so the
  trailing cover block is ignored naturally.

Hindi and English are told apart by Devanagari-vs-Latin character majority per line
(the GS3 approach) — there are no `**हिन्दी**` / `**English**` markers.

Essay carries **no per-question marks** (a topic is worth 250 in 2013, 125 in 2014-2025,
but only if chosen). `marks` is left null here and filled at publish time with
`publish_scan.py --marks`.

**It trusts nothing:** exactly `--expect` topics, numbered 1..N with no gaps or
duplicates, each carrying non-empty text in both languages, and — for 2014+ — exactly
two sections of four.

    uv run python scripts/md_essay_to_extraction.py UPSC_Essay_md/2020.md \\
        --year 2020 --scan-id 762 --out var/papers/essay --expect 8
"""

import argparse
import json
import re
import sys
from pathlib import Path

Q_HASH2_RE = re.compile(r"^##\s+Q\.\s*(\d+)\s*$")  # 2013:  "## Q. 1"
Q_HASH3_RE = re.compile(r"^###\s+(\d+)\.\s*$")  # 2014+: "### 1."
HEADING_RE = re.compile(r"^#{1,6}\s")
SECTION_RE = re.compile(r"(?:SECTION|खण्ड)\s*[^0-9A-Za-zऀ-ॿ]*\s*([AB])(?![A-Za-z])")
EMPHASIS_RE = re.compile(r"\*{1,3}(.+?)\*{1,3}")


def plain(text: str) -> str:
    return EMPHASIS_RE.sub(lambda m: m.group(1), text).strip()


def is_hindi(line: str) -> bool:
    dev = sum(1 for c in line if "ऀ" <= c <= "ॿ")
    lat = sum(1 for c in line if c.isascii() and c.isalpha())
    return dev > lat


def parse(path: Path, *, expect: int) -> tuple[list[dict], list[str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    sectioned = expect != 4  # 2013 (expect 4) has no sections
    problems: list[str] = []
    questions: list[dict] = []

    in_question = False
    hindi_buf: list[str] = []
    english_buf: list[str] = []
    current_section: str | None = None
    section_counts: dict[str, int] = {}

    def flush() -> None:
        nonlocal in_question
        if not in_question:
            return
        in_question = False
        number = len(questions) + 1
        hi = plain(" ".join(hindi_buf))
        en = plain(" ".join(english_buf))
        questions.append(
            {
                "question_number": str(number),
                "marks": None,
                "text_en": en,
                "text_hi": hi,
                "math_latex": None,
                "options": [],
                "tables": [],
                "stimulus_ref": None,
                "confidence": 0.9,
            }
        )
        if current_section:
            section_counts[current_section] = section_counts.get(current_section, 0) + 1

    for raw in lines:
        strip = raw.strip()

        m_q = Q_HASH2_RE.match(strip) or Q_HASH3_RE.match(strip)
        if m_q:
            flush()
            in_question = True
            hindi_buf, english_buf = [], []
            continue

        if HEADING_RE.match(strip):
            flush()
            m_sec = SECTION_RE.search(strip)
            if m_sec:
                current_section = m_sec.group(1)
            continue

        if not strip or strip == "---":
            continue

        if in_question:
            (hindi_buf if is_hindi(strip) else english_buf).append(strip)

    flush()

    numbers = [int(q["question_number"]) for q in questions]
    if numbers != list(range(1, expect + 1)):
        problems.append(f"expected topics 1..{expect}; got {numbers}")

    for q in questions:
        if not q["text_en"]:
            problems.append(f"Q{q['question_number']}: empty English text")
        if not q["text_hi"]:
            problems.append(f"Q{q['question_number']}: empty Hindi text")

    if sectioned:
        if sorted(section_counts) != ["A", "B"]:
            problems.append(f"expected sections A and B; saw {sorted(section_counts)}")
        for sec, n in sorted(section_counts.items()):
            if n != expect // 2:
                problems.append(f"section {sec} has {n} topics, expected {expect // 2}")

    return questions, problems


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path, help="one year's Essay markdown transcript")
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--scan-id", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--expect", type=int, required=True, help="topics in the paper (4 or 8)")
    parser.add_argument("--issues", action="append", default=[])
    args = parser.parse_args()

    questions, problems = parse(args.file, expect=args.expect)

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
        "paper_title_seen": f"Civil Services (Main) Examination, {args.year} - Essay",
        "overall_confidence": 0.9,
        "issues": args.issues,
    }
    name = args.out / f"extraction_{args.year}_scan{args.scan_id}.json"
    name.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"scan {args.scan_id}: {len(questions)} topics -> {name}")


if __name__ == "__main__":
    main()
