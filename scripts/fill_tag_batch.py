"""Fill an exported tagging batch from a flat {question_number: [[topic_path, conf]]} map.

`llm_queue.py export-batch` writes one item per batched tagging call, and the batches are
an artifact of `TAG_BATCH_SIZE` — ten questions each, split wherever that lands. Whoever
is choosing topics is thinking about questions, not about batch boundaries, so this reads
the printed question numbers back out of each item's prompt and routes the tags itself.

Write the map once per slice, covering every question in it:

    {
      "1":  [["gs3.indian_economy.investment_models", 0.9]],
      "2":  [["gs3.indian_economy", 0.85], ["gs3.indian_economy.government_budgeting", 0.6]]
    }

    uv run python scripts/llm_queue.py export-batch tags.json --schema BatchTopicTagResult
    uv run python scripts/fill_tag_batch.py tags.json tagmap.json
    uv run python scripts/llm_queue.py answer-batch tags.json

Exits non-zero naming any question the map missed, rather than writing a batch that would
silently leave those questions untagged.
"""

import argparse
import json
import re
from pathlib import Path

# export-batch renders each question as "Question <number> (<marks> marks)".
QUESTION_HEADING = re.compile(r"^Question (\S+) \(", re.M)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("batch", type=Path, help="file written by llm_queue.py export-batch")
    parser.add_argument("tag_map", type=Path, help="{question_number: [[topic_path, conf]]}")
    args = parser.parse_args()

    batch = json.loads(args.batch.read_text(encoding="utf-8"))
    tag_map = json.loads(args.tag_map.read_text(encoding="utf-8"))

    filled = 0
    for item in batch["items"]:
        numbers = QUESTION_HEADING.findall(item["prompt"])
        missing = [n for n in numbers if n not in tag_map]
        if missing:
            raise SystemExit(f"no tags supplied for question(s): {', '.join(missing)}")
        item["answer"] = {
            "results": [
                {
                    "question_number": number,
                    "tags": [
                        {"topic_path": path, "confidence": confidence}
                        for path, confidence in tag_map[number]
                    ],
                }
                for number in numbers
            ]
        }
        filled += len(numbers)

    args.batch.write_text(
        json.dumps(batch, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"filled {filled} question(s) across {len(batch['items'])} batch item(s)")
    print(f"  next: uv run python scripts/llm_queue.py answer-batch {args.batch}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
