"""Turn a hand-prepared Markdown transcription of a Mains Mathematics Optional Paper II
into ScanExtraction answers.

The seventh `md_*_to_extraction.py` sibling (GS1-4, Essay, Maths Paper I). Paper II's
Markdown dialect turned out to be the one case where a sibling *does* transfer almost
whole: every year 2014-2025 is `## N.` / `## QN.` question headings + `### (a)` sub-part
headings + single-`#` section dividers + lone bold marks tokens — exactly Paper I's
2016-2021/2023/2024 shape, applied uniformly. So this file is Paper I's parser with the
paper title changed; the shared behaviour (four heading dialects, `+`/`=`/`×` marks
tokens, combined and inline-split sub-part marks, the `$$…$$`-fence-aware Hindi/English
split) is all still exercised and still needed:

- **The paper is ~100% LaTeX.** Every stem is prose interleaved with `$...$` and fenced
  `$$ ... $$` blocks. It is kept **verbatim** in `text_en`/`text_hi`; the web app renders
  the delimiters with KaTeX. `math_latex` stays null (it is a single-string field and
  cannot hold a dozen interleaved expressions).

- **Marks arithmetic is different.** Eight questions, printed in two sections (A = 1..4,
  B = 5..8). The candidate attempts five (Q1 and Q5 compulsory + three of the rest), but
  every question is printed and every question is worth **50 marks**, so a complete paper
  transcribes to **400** marks, not 250. The checks are: questions 1..8 all present, every
  top-level question's parts summing to exactly 50, and the paper to exactly 400.

- **Four heading dialects across 2014-2025**, all handled by one tolerant regex:
    * `## Q1.` (bare) + `### (a)` / `### (b) (i)` sub-part headings   — 2014 only
    * `## Q. 1(a)` / `## Q. 3(c) (i)`                                 — 2015
    * `## 1. (a)` / `## 1. (a) (i)`                                   — 2016-2021, 2023, 2024
    * `## Q1. (a)` / `## Q2. (c) (i)`                                 — 2022, 2025
  One row is emitted per marks-bearing leaf: `1(a)`, `2(c)(i)`, `5(e)(ii)`. A `## Qn.` line
  carrying only a rubric ("सभी प्रश्नों के उत्तर दीजिए") opens no row; its `### (x)` children do.

- **Two ways a leaf's marks are printed away from a single heading**, both handled:
    * combined over consecutive sub-part headings — 2015's `## Q. 7(a) (i)` then
      `## Q. 7(a) (ii)` share one `**6+6=12**`; the addends are dealt out in order.
    * one heading, several inline `(i)`/`(ii)` runs each with its own marks token — 2019's
      `## 4. (c)` prints `(i) … **12**` then `(ii) … **8**`; the first flushed leaf is
      renamed `4(c)(i)` and `4(c)(ii)` opened.

- **Section headers** are single-`#` lines naming a section: `# खण्ड A / SECTION A`,
  `# खण्ड—अ / SECTION—A` (2015 uses Devanagari अ/ब), `# खण्ड ‘A’ / SECTION ‘A’`, and in
  2022/2025 split across two lines (`# खण्ड A` then `# SECTION A`).

- **Marks lines** are a lone bold token: `**10**`, `**15+5=20**` (value after `=`),
  `**10+10**` (summed), `**7+5=12½**` (½ = 0.5). `**10×5=50**` (2014's compulsory-section
  header, a product) is skipped — the five `**10**` parts under it carry the real marks.

- **Hindi/English split within a block.** Hindi always leads; English is the trailing run.
  The boundary is the first non-fenced prose line with a Latin letter and no Devanagari.
  Lines inside `$$ ... $$` fences never move the boundary — a fenced `ax-2y+z=0` is
  all-Latin but belongs to whichever language is currently open.

**It trusts nothing** — same contract as its siblings. What it cannot check is whether the
words are the printed words; that is the runbook's spot-check against the rendered R2 scan.

    uv run python scripts/md_mains_maths_p2_to_extraction.py Math_P2_md/2019.md \\
        --year 2019 --scan-id 782 --out var/papers/mains_maths_p2
"""

import argparse
import json
import re
import sys
from pathlib import Path

# "## Q1." / "## Q. 1(a)" / "## 1. (a) (i)" / "## Q2. (c) (i)" — number, optional part
# letter, optional roman sub-part, then any trailing text on the line.
QUESTION_RE = re.compile(
    r"^#{2,3}\s+(?:Q\.?\s*)?(\d{1,2})\s*\.?\s*"
    r"(?:\(([a-z])\)\s*)?"
    r"(?:\(([ivx]+)\)\s*)?"
    r"(.*)$"
)
# "### (a)" / "### (b) (i)" — a nested sub-part heading (2014 only).
SUBPART_RE = re.compile(r"^###\s+\(([a-z])\)\s*(?:\(([ivx]+)\)\s*)?$")
# "#### (i)" — a roman sub-heading nested under "### (a)". Usually decorative (several
# roman items share one combined mark at the end, so it merges into one leaf), but 2025's
# Q8(c) gives (i) and (ii) their own separate marks tokens, making them real leaves.
ROMAN_HEADING_RE = re.compile(r"^####\s+\(([ivx]+)\)\s*$")
# A single-# section divider: mentions SECTION or खण्ड.
SECTION_RE = re.compile(r"^#\s+.*(?:SECTION|खण्ड)", re.I)
# A lone bold marks token on its own line.
MARKS_RE = re.compile(r"^\*\*\s*([0-9+×xX*=½.\s]+?)\s*\*\*$")
# A product total like "10×5=50" — the 2014 compulsory-section header.
PRODUCT_RE = re.compile(r"\d+\s*[×xX*]\s*\d+\s*=\s*\d+")
# An inline "(ii) ..." run marker at the start of a line (case-2 continuation).
INLINE_ROMAN_RE = re.compile(r"^\((i{1,3}|iv|v|vi{0,3})\)\s+\S")

DEVANAGARI_RE = re.compile(r"[ऀ-ॿ]")
INLINE_MATH_RE = re.compile(r"\$[^$]*\$")
TEX_COMMAND_RE = re.compile(r"\\[A-Za-z]+")
LATIN_WORD_RE = re.compile(r"[A-Za-z]{2,}")


ROMAN_ONLY_RE = re.compile(r"^[ivx]+$", re.I)


def is_english_prose(line: str) -> bool:
    """True when this line is English prose (not a formula, not a bare enumerator).

    A Hindi-run line that is nothing but an inline formula ("I. $x\\frac{...}$,") is all
    Latin but is not English prose — so strip `$...$` spans and `\\command` tokens first,
    then look for a real word. A word made only of i/v/x is a roman-numeral marker
    ("(ii)", "(iii)"), not English — Paper II's Q8-style stems list conditions as
    "(i) …$math$" lines inside the *Hindi* run, and those must not flip the language.
    Devanagari anywhere means it is still Hindi.
    """
    if DEVANAGARI_RE.search(line):
        return False
    bare = TEX_COMMAND_RE.sub(" ", INLINE_MATH_RE.sub(" ", line))
    return any(not ROMAN_ONLY_RE.match(w) for w in LATIN_WORD_RE.findall(bare))

ROMANS = ["i", "ii", "iii", "iv", "v", "vi", "vii"]
EXPECTED_TOTAL_MARKS = 400
EXPECTED_PER_QUESTION = 50
EXPECTED_QUESTIONS = list(range(1, 9))


def addends(expr: str) -> list[float]:
    """The parts a bold token stands for. '6+6=12' -> [6, 6]; '15+5=20' -> [15, 5];
    '10' -> [10]; '12½' -> [12.5]. A trailing '=total' is dropped."""
    expr = expr.replace(" ", "")
    if "=" in expr:
        expr = expr.split("=", 1)[0]
    out = []
    for part in expr.split("+"):
        out.append(int(part.rstrip("½")) + (0.5 if part.endswith("½") else 0.0))
    return out


def split_bilingual(block: list[str]) -> tuple[str, str]:
    """Route each line to Hindi or English by what the line itself is.

    Paper I could assume one Hindi run then one English run — a single boundary. Paper II
    interleaves them: a stem with "(i)/(ii)" conditions or `#### (i)` sub-parts prints
    Hindi-(i), English-(i), Hindi-(ii), English-(ii). So the language is not latched: a
    line with Devanagari is always Hindi, a line of English prose is always English, and
    a line that is neither (a `$$…$$` fence, a bare formula, a "(ii)" marker) stays with
    whichever language was last positively identified.

    Lines inside `$$ ... $$` fences and multi-line `$ … $` spans never change the side.
    """
    hi: list[str] = []
    en: list[str] = []
    in_fence = False
    inline_open = False  # sitting inside a multi-line `$ ... $` span
    cur = hi
    for raw in block:
        s = raw.strip()
        if s == "$$":
            in_fence = not in_fence
            cur.append(raw)
            continue
        if in_fence or inline_open or not s:
            cur.append(raw if s else "")
            inline_open ^= (s.replace("$$", "").count("$") % 2 == 1)
            continue
        if DEVANAGARI_RE.search(s):
            cur = hi
        elif is_english_prose(s):
            cur = en
        cur.append(raw)
        inline_open ^= (s.replace("$$", "").count("$") % 2 == 1)

    def tidy(lines: list[str]) -> str:
        return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()

    return tidy(en), tidy(hi)


def new_leaf(key: str, buf: list[str], marks: float | None) -> dict:
    text_en, text_hi = split_bilingual(buf)
    return {
        "question_number": key,
        "marks": marks,
        "text_en": text_en,
        "text_hi": text_hi,
        "math_latex": None,
        "options": [],
        "tables": [],
        "stimulus_ref": None,
        "confidence": 0.9,
    }


def parse(path: Path) -> tuple[list[dict], list[str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    problems: list[str] = []
    rows: dict[str, dict] = {}

    started = False
    q_num: int | None = None
    part: str | None = None
    roman: str | None = None
    buf: list[str] = []
    open_row = False
    pending: list[tuple[str, list[str]]] = []  # sub-parts awaiting a combined marks token
    just_flushed: str | None = None  # key of the last leaf written, for case-2 continuation

    def key() -> str:
        k = f"{q_num}({part})"
        if roman:
            k += f"({roman})"
        return k

    def record(leaf: dict) -> None:
        if leaf["question_number"] in rows:
            problems.append(f"duplicate leaf {leaf['question_number']}")
        rows[leaf["question_number"]] = leaf

    def close_marks(expr: str) -> None:
        nonlocal open_row, pending, just_flushed, buf
        leaves = list(pending)
        if open_row:
            leaves.append((key(), buf))
        if not leaves:
            problems.append(f"marks token '**{expr}**' with no open question")
            return
        values = addends(expr)
        if len(leaves) == 1:
            values = [sum(values)]
        elif len(values) != len(leaves):
            problems.append(
                f"marks '**{expr}**' has {len(values)} parts for {len(leaves)} "
                f"sub-questions {[lk for lk, _ in leaves]}"
            )
            values = values + [None] * (len(leaves) - len(values))
        # Not strict: a length mismatch is already reported as a problem above and the
        # short case padded, so any surplus marks value is deliberately dropped here.
        for (lk, lbuf), value in zip(leaves, values, strict=False):
            record(new_leaf(lk, lbuf, value))
        just_flushed = leaves[-1][0]
        pending = []
        open_row = False
        buf = []

    for raw in lines:
        line = raw.rstrip()
        strip = line.strip()

        if SECTION_RE.match(strip):
            started = True
            if open_row or pending:
                problems.append("section break with an unclosed question")
            open_row, pending, just_flushed = False, [], None
            continue
        if not started:
            continue

        m_sub = SUBPART_RE.match(strip)
        m_q = None if m_sub else QUESTION_RE.match(strip)

        if m_sub or m_q:
            if open_row:
                # A sibling sub-part opened before this one's marks were printed —
                # 2015's 7(a)(i)/7(a)(ii) sharing one "**6+6=12**".
                pending.append((key(), buf))
                open_row = False
            just_flushed = None
            if m_sub:
                if q_num is None:
                    problems.append(f"sub-part {strip!r} with no parent question")
                    continue
                part, roman = m_sub.group(1), m_sub.group(2)
                buf, open_row = [], True
            else:
                q_num = int(m_q.group(1))
                part, roman = m_q.group(2), m_q.group(3)
                rest = m_q.group(4).strip()
                if part is None:  # bare "## Q1." rubric heading (2014)
                    buf, open_row = [], False
                else:
                    buf, open_row = ([rest] if rest else []), True
            continue

        m_marks = MARKS_RE.match(strip)
        if m_marks:
            expr = m_marks.group(1)
            if PRODUCT_RE.search(expr):
                continue  # "10×5=50" compulsory-section header
            close_marks(expr)
            continue

        m_roman = ROMAN_HEADING_RE.match(strip)
        if m_roman:
            if any(line.strip() for line in buf):
                # Content already accumulated since the last heading/close with no
                # marks token of its own — this and the previous roman item are
                # merging into one combined leaf (the common case). Drop any
                # provisional roman tag so the eventual key stays untagged.
                roman = None
            else:
                # Nothing accumulated yet: either right after the parent "### (a)",
                # or right after a previous roman item's own marks token closed it.
                # Tag this item so a marks token before the next "####" closes it
                # as its own leaf (2025 Q8(c)).
                roman = m_roman.group(1)
                open_row = True
            just_flushed = None
            continue

        if strip in ("---", "***") or re.match(r"^#{1,6}\s", strip):
            just_flushed = None
            continue

        if not open_row and not pending and just_flushed and strip:
            # Case-2: content after a leaf's marks but before the next heading — an inline
            # "(ii) ..." run under the same part. Rename the first leaf to "(i)".
            prev = rows[just_flushed]
            if not prev["question_number"].endswith(")("):  # guard, always true
                pass
            if roman is None:
                del rows[just_flushed]
                roman = "i"
                prev["question_number"] = key()
                record(prev)
            nxt = INLINE_ROMAN_RE.match(strip)
            roman = nxt.group(1) if nxt else ROMANS[ROMANS.index(roman) + 1]
            buf, open_row, just_flushed = [line], True, None
            continue

        if open_row:
            buf.append(line)

    if open_row or pending:
        problems.append("file ended with an unclosed question")

    present = sorted({int(r["question_number"].split("(")[0]) for r in rows.values()})
    if present != EXPECTED_QUESTIONS:
        problems.append(f"expected questions 1..8; got {present}")

    for n in present:
        leaves = [
            (r["question_number"], r["marks"])
            for r in rows.values()
            if int(r["question_number"].split("(")[0]) == n
        ]
        subtotal = sum(m or 0 for _, m in leaves)
        if abs(subtotal - EXPECTED_PER_QUESTION) > 1e-6:
            problems.append(f"Q{n} parts sum to {subtotal}, not 50 — {leaves}")

    for k, r in rows.items():
        if not r["text_en"]:
            problems.append(f"{k}: empty English stem")
        if not r["text_hi"]:
            problems.append(f"{k}: empty Hindi stem")
        if r["marks"] is None:
            problems.append(f"{k}: no marks")

    total = sum(r["marks"] or 0 for r in rows.values())
    if abs(total - EXPECTED_TOTAL_MARKS) > 1e-6:
        problems.append(f"total marks {total} != {EXPECTED_TOTAL_MARKS}")

    def sort_key(item: tuple[str, dict]) -> tuple:
        base, _, rest = item[0].partition("(")
        return (int(base), rest)

    ordered = [r for _, r in sorted(rows.items(), key=sort_key)]
    return ordered, problems


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("file", type=Path, help="one year's Maths Paper I markdown transcript")
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--scan-id", type=int, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--issues", action="append", default=[])
    args = ap.parse_args()

    rows, problems = parse(args.file)

    if problems:
        print("REFUSING to write — the Markdown does not hold together:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        raise SystemExit(1)

    args.out.mkdir(parents=True, exist_ok=True)
    payload = {
        "questions": rows,
        "stimuli": [],
        "year_seen": args.year,
        "paper_title_seen": (
            f"Civil Services (Main) Examination, {args.year} - Mathematics Optional Paper II"
        ),
        "overall_confidence": 0.9,
        "issues": args.issues,
    }
    name = args.out / f"extraction_{args.year}_scan{args.scan_id}.json"
    name.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    total = sum(r["marks"] for r in rows)
    print(f"scan {args.scan_id}: {len(rows)} leaves, {total} marks -> {name}")


if __name__ == "__main__":
    main()
