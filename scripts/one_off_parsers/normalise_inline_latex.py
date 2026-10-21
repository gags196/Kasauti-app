"""Rewrite inline `$...$` LaTeX in question stems to the plain-text house convention.

Three of the four ingested CSAT years keep the stem readable (`x^2 < y < 1`, `6^129 x 7^307`)
and put markup in `questions.math_notation_latex`, which the web app renders in its own block.
CSAT 2024 came in with LaTeX inline in the stem as well, and there is no math renderer — see
`apps/web/src/app/globals.css` — so a learner reads a literal `$a\\times b$`.

This rewrites the stem only. `math_notation_latex` is left alone: LaTeX belongs in it.

    uv run python scripts/normalise_inline_latex.py --paper-code prelims-gs2 --year 2024
    uv run python scripts/normalise_inline_latex.py --paper-code prelims-gs2 --year 2024 --apply

Idempotent: a stem with no `$` is never touched, so a repeat run is a no-op.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api" / "src"))

from kasauti_api.db.base import async_session_factory  # noqa: E402
from sqlalchemy import text as sqltext  # noqa: E402

# Applied in order. The spacing that `\times` -> " x " leaves behind is collapsed at the end.
SUBSTITUTIONS: list[tuple[str, str]] = [
    (r"\\times", " x "),
    (r"\\div", " ÷ "),
    (r"\\cdots", "..."),
    (r"\\ldots", "..."),
    (r"\\dots", "..."),
    (r"\\le\b", "≤"),
    (r"\\ge\b", "≥"),
    (r"\\neq\b", "≠"),
    (r"\\sqrt\{([^{}]*)\}", r"sqrt(\1)"),
    (r"\\text\{([^{}]*)\}", r"\1"),
    (r"\^\{([^{}]*)\}", r"^\1"),      # 25^{50} -> 25^50, matching 2022/2025/2026
    (r"_\{([^{}]*)\}", r"_\1"),
    (r"\\_", "_"),
    (r"\\ ", " "),
    (r"\$", ""),
]

# Two 2024 stems need more than de-LaTeXing, because the markup encoded the wrong glyph.
# Both were read off the scan (booklet KSPC-B-GSPT/61A, pages 5 and 15).
OVERRIDES: dict[tuple[int, str], dict[str, str]] = {
    # The printed placeholder is an asterisk, not a multiplication sign: "In the expression
    # 5 * 4 * 3 * 2 * 1, * is chosen from +, -, x". Storing x for the placeholder made the
    # question contradict itself, so this is a content fix, not a formatting one.
    (2024, "6"): {
        "en": (
            "In the expression 5 * 4 * 3 * 2 * 1, * is chosen from +, -, x each at most "
            "two times. What is the smallest non-negative value of the expression?"
        ),
        "hi": (
            "व्यंजक 5 * 4 * 3 * 2 * 1 में, * को +, -, x में से, प्रत्येक अधिक-से-अधिक दो बार "
            "चुना जाता है। व्यंजक का न्यूनतम ऋणेतर मान क्या है?"
        ),
        "latex": "5 * 4 * 3 * 2 * 1",
    },
    # The underscores are printed as spaced blanks: "A _ BCD _ BBCDABC _ DABC _ D".
    (2024, "24"): {
        "en": (
            "Consider the sequence A _ BCD _ BBCDABC _ DABC _ D that follows a certain "
            "pattern. Which one of the following completes the sequence?"
        ),
        "hi": (
            "अनुक्रम A _ BCD _ BBCDABC _ DABC _ D पर विचार कीजिए जो एक निश्चित पैटर्न का "
            "अनुसरण करता है। निम्नलिखित में से कौन-सा, इस अनुक्रम को पूरा करता है?"
        ),
    },
}


def delatex(text: str | None) -> str | None:
    """Strip inline math markup, leaving the reading order and every character intact."""
    if not text or "$" not in text:
        return text
    out = text
    for pattern, replacement in SUBSTITUTIONS:
        out = re.sub(pattern, replacement, out)
    # Collapse only the runs the spaced operators above introduce. Never touch newlines
    # (stems are multi-line) and never close up a space before punctuation: UPSC prints
    # "Consider the following :" and "x ... x", and the other three years store it that way.
    out = re.sub(r"[ \t]+", " ", out)
    return "\n".join(line.strip() for line in out.split("\n")).strip()


SELECT = """
select q.id, q.year, q.question_number as n, q.question_text_en as en, q.question_text_hi as hi
from questions q join papers p on p.id = q.paper_id
where p.code = :paper and q.year = :year
  and (q.question_text_en like '%$%' or q.question_text_hi like '%$%')
order by q.question_number::int
"""


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--paper-code", required=True)
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--apply", action="store_true", help="write; otherwise report only")
    args = ap.parse_args()

    async with async_session_factory() as session:
        rows = (
            await session.execute(
                sqltext(SELECT), {"paper": args.paper_code, "year": args.year}
            )
        ).mappings().all()

        if not rows:
            print(f"nothing to do: no {args.paper_code} {args.year} stem contains '$'")
            return 0

        changed = 0
        for r in rows:
            override = OVERRIDES.get((r["year"], r["n"]), {})
            new_en = override.get("en") or delatex(r["en"])
            new_hi = override.get("hi") or delatex(r["hi"])
            if new_en == r["en"] and new_hi == r["hi"]:
                continue
            changed += 1
            tag = "  [OVERRIDE]" if override else ""
            print(f"--- Q{r['n']}{tag}")
            print(f"  en-  {r['en']}")
            print(f"  en+  {new_en}")
            print(f"  hi-  {r['hi']}")
            print(f"  hi+  {new_hi}")
            print()
            if args.apply:
                params = {"id": r["id"], "en": new_en, "hi": new_hi}
                sets = "question_text_en = :en, question_text_hi = :hi"
                if "latex" in override:
                    sets += ", math_notation_latex = :latex"
                    params["latex"] = override["latex"]
                await session.execute(
                    sqltext(f"update questions set {sets} where id = :id"), params
                )

        if args.apply:
            await session.commit()

        verb = "rewrote" if args.apply else "would rewrite"
        print(f"{verb} {changed} of {len(rows)} stems ({args.paper_code} {args.year})")
        if not args.apply:
            print("dry run — pass --apply to write")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
