"""Feature A2: Prelims MCQ option-construction pattern analysis.

    uv run python scripts/analyze_option_patterns.py
    uv run python scripts/analyze_option_patterns.py --topic-path gs3.indian_economy
    uv run python scripts/analyze_option_patterns.py --year-from 2019 --no-eras

A thin CLI over `domain/intelligence/option_patterns.py`, so the figure in the committed
report and the figure the API serves come from one implementation and cannot disagree.
Writes a dated markdown report to `benchmarks/reports/prelims-option-patterns/`.

Requires `scripts/derive_question_facts.py` to have been run — the option geometry it
denormalises is what makes these statistics a GROUP BY rather than a corpus scan.
"""

import argparse
import asyncio
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api" / "src"))

from kasauti_api.db.base import async_session_factory  # noqa: E402
from kasauti_api.domain.intelligence.option_patterns import (  # noqa: E402
    archetype_mix,
    option_pattern_report,
    render_markdown,
)
from kasauti_api.domain.intelligence.scope import (  # noqa: E402
    PATTERN_ERA_START,
    QuestionScope,
)

REPORT_DIR = REPO_ROOT / "benchmarks" / "reports" / "prelims-option-patterns"


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic-path", default=None)
    parser.add_argument("--year-from", type=int, default=None)
    parser.add_argument("--year-to", type=int, default=None)
    parser.add_argument(
        "--no-eras", action="store_true",
        help="one pooled section instead of the 2022+ / pre-2022 split",
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
            (f"{PATTERN_ERA_START} onwards — the current pattern",
             QuestionScope(**base, era="recent")),
            (f"Before {PATTERN_ERA_START} — context only",
             QuestionScope(**base, era="legacy")),
            ("All years pooled", QuestionScope(**base)),
        ]

    reports, archetypes = [], {}
    async with async_session_factory() as session:
        for name, scope in eras:
            reports.append((name, await option_pattern_report(session, scope)))
            archetypes[name] = await archetype_mix(session, scope)

    if reports[0][1].keyed_questions == 0:
        print("No keyed questions found. Run load_answer_key.py, then "
              "derive_question_facts.py.")
        return

    markdown = render_markdown(reports, archetypes=archetypes)
    out = Path(args.out) if args.out else (
        REPORT_DIR / f"{date.today().isoformat()}_option_patterns.md"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(markdown, encoding="utf-8")
    print(markdown)
    print(f"\nreport written: {out.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    asyncio.run(main())
