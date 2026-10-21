"""Enqueue intelligence jobs for every topic with enough published questions.

    uv run python scripts/run_intelligence.py analysis --scope combined --dry-run
    uv run python scripts/run_intelligence.py analysis --scope prelims --max-depth 1
    uv run python scripts/run_intelligence.py one-pager

Eligibility counts the topic's whole **subtree**, because that is what
`gather_topic_corpus` actually sends to the model. Counting direct tags instead — which
this script used to do — meant `gs3.science_technology` was never queued despite holding
247 questions across its leaves, since only one is tagged to the branch itself.

Subtree counting alone would go too far the other way: every ancestor's corpus is a
superset of its descendants', so a naive run enqueues a branch and all of its leaves and
asks the model near-identical questions several times over. `--max-depth` and the
redundant-parent skip are what keep that in check, which matters most while requests are
answered by hand.
"""

import argparse
import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api" / "src"))

from arq import create_pool  # noqa: E402
from kasauti_api.db.base import async_session_factory  # noqa: E402
from kasauti_api.db.models.taxonomy import Stage  # noqa: E402
from kasauti_api.domain.intelligence.generation import (  # noqa: E402
    MIN_QUESTIONS_FOR_ANALYSIS,
)
from kasauti_api.domain.intelligence.rankings import (  # noqa: E402
    RankedTopic,
    drop_redundant_parents,
    topic_importance,
)
from kasauti_api.workers.queue import redis_settings  # noqa: E402

SCOPE_STAGES = {"prelims": Stage.prelims, "mains": Stage.mains, "combined": None}


async def eligible_topics(
    *,
    stage: Stage | None,
    min_questions: int,
    max_depth: int | None,
    subject_id: int | None,
) -> list[RankedTopic]:
    async with async_session_factory() as session:
        ranked = await topic_importance(
            session,
            stage=stage,
            subject_id=subject_id,
            rollup="subtree",
            max_depth=max_depth,
            limit=1000,
        )
    ranked = [t for t in ranked if t.subtree_count >= min_questions]
    return drop_redundant_parents(ranked)


async def one_pager_topic_ids(min_questions: int) -> list[RankedTopic]:
    """One-pagers are Mains-only by construction (see intelligence_tasks)."""
    return await eligible_topics(
        stage=Stage.mains, min_questions=min_questions, max_depth=None, subject_id=None
    )


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("job", choices=["analysis", "one-pager"])
    parser.add_argument("--scope", default="combined", choices=sorted(SCOPE_STAGES))
    parser.add_argument(
        "--min-questions", type=int, default=MIN_QUESTIONS_FOR_ANALYSIS,
        help=f"subtree corpus size required (default {MIN_QUESTIONS_FOR_ANALYSIS})",
    )
    parser.add_argument(
        "--max-depth", type=int, default=None,
        help="1 = branch topics only, 2 = include leaves (default: no limit)",
    )
    parser.add_argument("--subject-id", type=int, default=None)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="list what would be enqueued and stop — every request is answered by hand",
    )
    args = parser.parse_args()

    if args.job == "one-pager":
        topics = await one_pager_topic_ids(args.min_questions)
    else:
        topics = await eligible_topics(
            stage=SCOPE_STAGES[args.scope],
            min_questions=args.min_questions,
            max_depth=args.max_depth,
            subject_id=args.subject_id,
        )
    topic_ids = [t.topic_id for t in topics]

    if not topic_ids:
        print("No topics have enough published questions yet.")
        return

    for t in topics:
        print(f"  {t.topic_id:5}  {t.path:56} {t.subtree_count}")

    if args.dry_run:
        print(f"\n--dry-run: {len(topic_ids)} topics would be enqueued, nothing sent")
        return

    redis = await create_pool(redis_settings())
    for topic_id in topic_ids:
        if args.job == "analysis":
            await redis.enqueue_job("analyze_topic", topic_id, args.scope)
        else:
            await redis.enqueue_job("generate_topic_note", topic_id)
    print(f"enqueued {args.job} for {len(topic_ids)} topics")


if __name__ == "__main__":
    asyncio.run(main())
