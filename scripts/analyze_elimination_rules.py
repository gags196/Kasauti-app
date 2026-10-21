"""Verify the the coaching-circuit elimination-rule list rules against the real Prelims corpus.

    uv run python scripts/analyze_elimination_rules.py
    uv run python scripts/analyze_elimination_rules.py --no-eras
    uv run python scripts/analyze_elimination_rules.py --topic-path gs3.indian_economy

A thin CLI over `domain/intelligence/elimination.py`, so a figure in the committed report
and a figure the product shows a learner come from one implementation and cannot disagree.
Writes a dated markdown report to `benchmarks/reports/prelims-elimination/`.

**All years lead here**, unlike the option-pattern report. The statement-level evidence
comes almost entirely from the "1 only / 2 only / Both / Neither" family, which fell from
56% of questions before 2022 to 45% after, so a 2022-onwards-only reading would return
"too few to conclude anything" for most of the document and settle nothing. The recent era
follows as its own section: a rule whose direction reverses there must not ship.

Requires `scripts/derive_question_facts.py` to have been run at DERIVED_REV >= 3 — the
option archetype it writes is what scopes the option-level rules to `entity_choice`.
"""

import argparse
import asyncio
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api" / "src"))

from kasauti_api.db.base import async_session_factory  # noqa: E402
from kasauti_api.domain.intelligence.elimination import (  # noqa: E402
    elimination_report,
    render_markdown,
)
from kasauti_api.domain.intelligence.scope import (  # noqa: E402
    PATTERN_ERA_START,
    QuestionScope,
)

REPORT_DIR = REPO_ROOT / "benchmarks" / "reports" / "prelims-elimination"


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic-path", default=None)
    parser.add_argument("--year-from", type=int, default=None)
    parser.add_argument("--year-to", type=int, default=None)
    parser.add_argument(
        "--no-eras", action="store_true",
        help="one pooled section instead of the all-years / 2022+ / pre-2022 split",
    )
    parser.add_argument("--out", default=None, help="override the report path")
    args = parser.parse_args()

    base = dict(
        topic_path=args.topic_path, year_from=args.year_from, year_to=args.year_to
    )
    if args.no_eras or args.year_from or args.year_to:
        eras = [("All years in scope", QuestionScope(**base))]
    else:
        eras = [
            ("All years — the full evidence", QuestionScope(**base)),
            (f"{PATTERN_ERA_START} onwards — does the rule survive the pattern change?",
             QuestionScope(**base, era="recent")),
            (f"Before {PATTERN_ERA_START} — context", QuestionScope(**base, era="legacy")),
        ]

    reports = []
    async with async_session_factory() as session:
        for name, scope in eras:
            reports.append((name, await elimination_report(session, scope)))

    if reports[0][1].questions_decoded == 0:
        print("No decodable questions found. Run load_answer_key.py, then "
              "derive_question_facts.py.")
        return

    markdown = render_markdown(reports)
    out = Path(args.out) if args.out else (
        REPORT_DIR / f"{date.today().isoformat()}_elimination_rules.md"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(markdown, encoding="utf-8")
    print(markdown)
    print(f"\nreport written: {out.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    asyncio.run(main())
