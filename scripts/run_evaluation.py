"""Judge one Mains answer against one rubric, with Claude Code answering instead of the API.

Calls the production evaluator (`domain/rubric/engine.py`) through the FileQueueProvider
seam, so the code path exercised here is the one that will run in production — the same
arrangement `run_pipeline_manual.py` uses for ingestion.

    uv run python scripts/run_evaluation.py show gs1-2024-q2-subsidiary-alliance-v1
    uv run python scripts/run_evaluation.py judge gs1-2024-q2-subsidiary-alliance-v1 \
        --answer var/answers/shakti-gs1-q2.txt
    uv run python scripts/run_evaluation.py judge <rubric_id> --fixture \
        benchmarks/fixtures/mains-eval/gs1-2024-q2.yaml

The question text comes from the corpus when the rubric names a `question_ref`, so the
judge reads the same wording the learner sat; `--question-file` overrides it.

The first `judge` run queues an LLM request and writes nothing. Answer it
(`scripts/llm_queue.py show <id>` / `answer <id> file.json`), then run the same command
again.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api" / "src"))

# Windows consoles default to cp1252, which raises UnicodeEncodeError on the first
# Devanagari character printed. A tool whose whole purpose is Hindi text must not crash
# when asked to show any; replace what the terminal genuinely cannot render and carry on.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import yaml  # noqa: E402
from kasauti_api.db.base import async_session_factory  # noqa: E402
from kasauti_api.db.models import Paper, Question  # noqa: E402
from kasauti_api.db.models.cost_ledger import LlmFeature  # noqa: E402
from kasauti_api.domain.llm.cost_ledger import record_usage  # noqa: E402
from kasauti_api.domain.llm.queue_provider import (  # noqa: E402
    DEFAULT_QUEUE_DIR,
    FileQueueProvider,
    LlmRequestPending,
)
from kasauti_api.domain.rubric import (  # noqa: E402
    AnswerReport,
    PointStatus,
    Rubric,
    RubricGroup,
    judge_answer,
    load_rubric,
)
from sqlalchemy import select  # noqa: E402

STATUS_MARK = {
    PointStatus.hit: "[hit]",
    PointStatus.partial: "[partial]",
    PointStatus.miss: "[miss]",
    PointStatus.unsupported: "[unsupported]",
    PointStatus.not_judged: "[not judged]",
}


async def resolve_question(
    rubric: Rubric, args: argparse.Namespace, language: str
) -> tuple[str | None, str]:
    """The question to judge against, and where it came from.

    The provenance is returned so it can be printed. It is not decoration: a rubric that
    named the wrong paper/year/number once resolved to a real but entirely different UPSC
    question, and the run looked normal — the substitution was only visible in the queued
    prompt. Whatever the judge reads, the operator sees named.
    """
    if args.question_file:
        return Path(args.question_file).read_text(encoding="utf-8"), str(args.question_file)
    carried = rubric.question_text(language)
    if carried:
        return carried, rubric.question_source or "carried by the rubric"
    ref = rubric.question_ref
    if not ref:
        return None, "nowhere"
    from_corpus = await question_text_from_corpus(rubric)
    return from_corpus, f"the corpus, via question_ref {ref}"


async def question_text_from_corpus(rubric: Rubric) -> str | None:
    """The printed question, read from the ingested corpus via the rubric's question_ref."""
    ref = rubric.question_ref
    if not {"paper", "year", "question_number"} <= ref.keys():
        return None
    async with async_session_factory() as session:
        paper = (
            await session.execute(select(Paper).where(Paper.code == ref["paper"]))
        ).scalar_one_or_none()
        if paper is None:
            return None
        question = (
            await session.execute(
                select(Question).where(
                    Question.paper_id == paper.id,
                    Question.year == ref["year"],
                    Question.question_number == str(ref["question_number"]),
                )
            )
        ).scalars().first()
        if question is None:
            return None
        marks = f" ({question.marks:g} marks)" if question.marks else ""
        return f"{question.question_text_en}{marks}"


def render_report(report: AnswerReport, rubric: Rubric) -> str:
    lines = [
        f"Rubric {report.rubric_id} ({report.rubric_version}), language {report.language}",
        "",
    ]
    group_of = {g.group_id: g for g in report.groups}
    seen_groups: set[str] = set()

    for entry in rubric.entries:
        if isinstance(entry, RubricGroup):
            group = group_of[entry.id]
            if entry.id not in seen_groups:
                seen_groups.add(entry.id)
                expected = "" if group.expect_k is None else f", {group.expect_k} expected"
                lines.append(
                    f"{entry.id}: {group.credited} of {group.defined} made{expected}"
                    + ("  <- more than the question rewards" if group.over_covered else "")
                )
            point_ids = [p.id for p in entry.points]
        else:
            point_ids = [entry.id]

        for point_id in point_ids:
            outcome = next(o for o in report.outcomes if o.point_id == point_id)
            indent = "    " if outcome.group_id else "  "
            lines.append(f"{indent}{STATUS_MARK[outcome.status]} {outcome.point_id}")
            if outcome.quote:
                flag = (
                    "  (evidence overlaps an illegible span)"
                    if outcome.evidence_uncertain
                    else ""
                )
                lines.append(f'{indent}  > "{outcome.quote}"{flag}')
            if outcome.comment:
                lines.append(f"{indent}  {outcome.comment}")
            if outcome.not_judged_reason:
                lines.append(f"{indent}  ! {outcome.not_judged_reason}")

    if report.illegible_spans:
        lines += ["", "Illegible in the transcript:"]
        lines += [f'  - "{span}"' for span in report.illegible_spans]

    if report.unsupported:
        lines += [
            "",
            "Claimed without locatable evidence (a defect here, not in the answer):",
        ]
        lines += [f"  - {o.point_id}: {o.not_judged_reason}" for o in report.unsupported]

    missed = report.missed_by_weight()
    if missed:
        lines += ["", "Missed, heaviest first:"]
        lines += [f"  - {o.point_id} - {o.description}" for o in missed]

    # No total is printed, here or anywhere: the counts below are of points, not marks.
    lines += [
        "",
        f"{len(report.by_status(PointStatus.hit))} hit, "
        f"{len(report.by_status(PointStatus.partial))} partial, "
        f"{len(missed)} missed, "
        f"{len(report.unsupported)} unsupported, "
        f"{len(report.by_status(PointStatus.not_judged))} not judged "
        f"(of {len(report.outcomes)} points). No mark is predicted.",
    ]
    return "\n".join(lines)


def report_as_dict(report: AnswerReport) -> dict:
    return {
        "rubric_id": report.rubric_id,
        "rubric_version": report.rubric_version,
        "language": report.language,
        "points": [
            {
                "point_id": o.point_id,
                "status": o.status.value,
                "quote": o.quote,
                "comment": o.comment,
                "group_id": o.group_id,
                "evidence_uncertain": o.evidence_uncertain,
                "not_judged_reason": o.not_judged_reason,
            }
            for o in report.outcomes
        ],
        "groups": [
            {
                "group_id": g.group_id,
                "credited": list(g.credited_ids),
                "missed": list(g.missed_ids),
                "expect_k": g.expect_k,
                "over_covered": g.over_covered,
            }
            for g in report.groups
        ],
        "illegible_spans": list(report.illegible_spans),
    }


def cmd_show(args: argparse.Namespace) -> None:
    rubric = load_rubric(args.rubric_id)
    print(f"{rubric.rubric_id}  topic {rubric.topic_path}  {rubric.total_marks:g} marks")
    if rubric.question_ref:
        print(f"  question: {rubric.question_ref}")
    for entry in rubric.entries:
        if isinstance(entry, RubricGroup):
            expected = "" if entry.expect_k is None else f", expect {entry.expect_k}"
            print(f"  group {entry.id} (cap {entry.credit_cap:g}{expected})")
            for point in entry.points:
                print(f"    - {point.id}: {point.description()}")
        else:
            print(f"  - {entry.id} ({entry.marks:g}): {entry.description()}")


async def cmd_judge(provider: FileQueueProvider, args: argparse.Namespace) -> None:
    rubric = load_rubric(args.rubric_id)

    if args.fixture:
        fixture = yaml.safe_load(Path(args.fixture).read_text(encoding="utf-8"))
        answer_text = fixture["answer"]
        language = fixture.get("language", args.language)
        question_text, provenance = fixture.get("question"), str(args.fixture)
        if not question_text:
            question_text, provenance = await resolve_question(rubric, args, language)
    else:
        answer_text = Path(args.answer).read_text(encoding="utf-8")
        language = args.language
        question_text, provenance = await resolve_question(rubric, args, language)

    if not question_text:
        raise SystemExit(
            f"no question text: rubric {rubric.rubric_id!r} names "
            f"{rubric.question_ref or 'no question_ref'} and the corpus has no matching "
            "row. Pass --question-file."
        )

    print(f"question from {provenance}:\n  {' '.join(question_text.split())[:300]}\n")

    try:
        report, usages = await judge_answer(
            provider,
            rubric,
            question_text=question_text,
            answer_text=answer_text,
            language=language,
        )
    except LlmRequestPending as pending:
        print(f"judging queued as {pending.request_id}")
        print(
            "  Next:\n"
            f"    uv run python scripts/llm_queue.py show {pending.request_id}\n"
            "  Answer it, then re-run this command."
        )
        return

    async with async_session_factory() as session:
        for usage in usages:
            await record_usage(
                session,
                feature=LlmFeature.rubric_eval,
                usage=usage,
                related_entity_type="rubric",
                related_entity_id=rubric.rubric_id[:64],
            )
        await session.commit()

    print(render_report(report, rubric))
    if args.json:
        Path(args.json).write_text(
            json.dumps(report_as_dict(report), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\nwrote {args.json}")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue-dir", type=Path, default=DEFAULT_QUEUE_DIR)
    sub = parser.add_subparsers(dest="command", required=True)

    p_show = sub.add_parser("show", help="print a rubric's content points")
    p_show.add_argument("rubric_id")

    p_judge = sub.add_parser("judge", help="judge one answer against one rubric")
    p_judge.add_argument("rubric_id")
    p_judge.add_argument("--answer", type=Path, help="plain-text transcript of the answer")
    p_judge.add_argument("--fixture", type=Path, help="a benchmarks/fixtures YAML instead")
    p_judge.add_argument("--question-file", type=Path)
    p_judge.add_argument("--language", default="en", choices=["en", "hi"])
    p_judge.add_argument("--json", type=Path, help="also write the report as JSON")

    args = parser.parse_args()
    if args.command == "show":
        cmd_show(args)
        return
    if not (args.answer or args.fixture):
        raise SystemExit("judge needs --answer or --fixture")
    await cmd_judge(FileQueueProvider(args.queue_dir), args)


if __name__ == "__main__":
    asyncio.run(main())
