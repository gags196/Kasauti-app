"""Inspect and answer the file-queue LLM requests written by FileQueueProvider.

Lets the pipeline run with no Anthropic key: the pipeline queues a request, this CLI
shows it, an agent/human writes a schema-valid answer, and re-running the job picks the
answer up from cache.

    uv run python scripts/llm_queue.py status
    uv run python scripts/llm_queue.py list [--schema TopicTagResult] [--pending]
    uv run python scripts/llm_queue.py show <id> [--schema-out schema.json]
    uv run python scripts/llm_queue.py answer <id> answer.json
    uv run python scripts/llm_queue.py export-batch tags.json --schema TopicTagResult
    uv run python scripts/llm_queue.py answer-batch tags.json

Batch mode matters: a 100-question paper produces 100 tagging requests, which would be
unworkable one file at a time.
"""

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api" / "src"))

from kasauti_api.domain.llm.queue_provider import (  # noqa: E402
    DEFAULT_QUEUE_DIR,
    QueuePaths,
    schema_registry,
)


def load_requests(paths: QueuePaths) -> list[dict]:
    out = []
    for path in sorted(paths.requests.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        data["_answered"] = (paths.responses / f"{data['id']}.json").exists()
        out.append(data)
    return out


def cmd_status(paths: QueuePaths, _: argparse.Namespace) -> int:
    requests = load_requests(paths)
    answered = sum(1 for r in requests if r["_answered"])
    print(f"queue: {paths.root}")
    print(f"  total     {len(requests)}")
    print(f"  answered  {answered}")
    print(f"  pending   {len(requests) - answered}")
    by_schema: dict[str, list[int]] = {}
    for r in requests:
        entry = by_schema.setdefault(r["schema"], [0, 0])
        entry[0] += 1
        entry[1] += 1 if r["_answered"] else 0
    for schema, (total, done) in sorted(by_schema.items()):
        print(f"    {schema:<24} {done}/{total} answered")
    return 0


def cmd_list(paths: QueuePaths, args: argparse.Namespace) -> int:
    requests = load_requests(paths)
    if args.schema:
        requests = [r for r in requests if r["schema"] == args.schema]
    if args.pending:
        requests = [r for r in requests if not r["_answered"]]
    if not requests:
        print("no matching requests")
        return 0
    for r in requests:
        mark = "answered" if r["_answered"] else "PENDING "
        docs = f" · {len(r['documents'])} doc(s)" if r["documents"] else ""
        print(f"{mark}  {r['id']}  {r['schema']:<22} tier={r['tier']:<9}{docs}")
    return 0


def cmd_show(paths: QueuePaths, args: argparse.Namespace) -> int:
    path = paths.requests / f"{args.id}.json"
    if not path.exists():
        print(f"no such request: {args.id}", file=sys.stderr)
        return 1
    data = json.loads(path.read_text(encoding="utf-8"))

    print(f"=== request {data['id']} ===")
    print(f"schema      {data['schema']}")
    print(f"tier        {data['tier']}   max_tokens {data['max_tokens']}")
    answered = (paths.responses / f"{data['id']}.json").exists()
    print(f"answered    {answered}")

    for doc in data["documents"]:
        pages = doc["page_count_hint"]
        pages_note = f"{pages} pages (hint)" if pages else "page count unknown"
        print(f"document    {doc['path']}")
        print(f"            {doc['media_type']}, {doc['bytes'] / 1_048_576:.2f} MB, {pages_note}")

    print("\n--- SYSTEM ---")
    print(data["system"] or "(none)")
    print("\n--- PROMPT ---")
    print(data["prompt"])

    if args.schema_out:
        Path(args.schema_out).write_text(
            json.dumps(data["schema_json"], ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\nJSON Schema written to {args.schema_out}")
    else:
        print("\n--- JSON SCHEMA ---")
        print(json.dumps(data["schema_json"], ensure_ascii=False, indent=2))
    return 0


def validate_answer(request: dict, payload: object) -> str:
    """Validate against the exact schema the request was created with.

    Failing here is the point — it keeps a malformed answer from reaching the DB.
    """
    schema_cls = schema_registry().get(request["schema"])
    if schema_cls is None:
        raise SystemExit(f"unknown schema {request['schema']!r}")
    raw = json.dumps(payload, ensure_ascii=False)
    try:
        schema_cls.model_validate_json(raw)
    except ValidationError as error:
        raise SystemExit(
            f"answer for {request['id']} does not satisfy {request['schema']}:\n{error}"
        ) from error
    return raw


def cmd_answer(paths: QueuePaths, args: argparse.Namespace) -> int:
    request_path = paths.requests / f"{args.id}.json"
    if not request_path.exists():
        print(f"no such request: {args.id}", file=sys.stderr)
        return 1
    request = json.loads(request_path.read_text(encoding="utf-8"))
    payload = json.loads(Path(args.file).read_text(encoding="utf-8"))

    raw = validate_answer(request, payload)
    (paths.responses / f"{args.id}.json").write_text(raw, encoding="utf-8")
    print(f"answer stored for {args.id} ({request['schema']}) — re-run the job")
    return 0


def cmd_export_batch(paths: QueuePaths, args: argparse.Namespace) -> int:
    """One file holding every pending request of a schema, to fill in a single pass."""
    requests = [r for r in load_requests(paths) if not r["_answered"]]
    if args.schema:
        requests = [r for r in requests if r["schema"] == args.schema]
    if not requests:
        print("nothing pending to export")
        return 0

    batch = {
        "schema_json": requests[0]["schema_json"],
        "system": requests[0]["system"],
        "items": [
            {"id": r["id"], "schema": r["schema"], "prompt": r["prompt"], "answer": None}
            for r in requests
        ],
    }
    Path(args.file).write_text(
        json.dumps(batch, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"{len(requests)} pending request(s) written to {args.file}")
    print("Fill in each item's \"answer\" field, then: answer-batch " + args.file)
    return 0


def cmd_answer_batch(paths: QueuePaths, args: argparse.Namespace) -> int:
    batch = json.loads(Path(args.file).read_text(encoding="utf-8"))
    by_id = {r["id"]: r for r in load_requests(paths)}

    stored = skipped = 0
    for item in batch["items"]:
        if item.get("answer") is None:
            skipped += 1
            continue
        request = by_id.get(item["id"])
        if request is None:
            raise SystemExit(f"unknown request id in batch: {item['id']}")
        raw = validate_answer(request, item["answer"])
        (paths.responses / f"{item['id']}.json").write_text(raw, encoding="utf-8")
        stored += 1

    print(f"{stored} answer(s) stored, {skipped} left unanswered")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue-dir", type=Path, default=DEFAULT_QUEUE_DIR)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status")

    p_list = sub.add_parser("list")
    p_list.add_argument("--schema")
    p_list.add_argument("--pending", action="store_true")

    p_show = sub.add_parser("show")
    p_show.add_argument("id")
    p_show.add_argument("--schema-out")

    p_answer = sub.add_parser("answer")
    p_answer.add_argument("id")
    p_answer.add_argument("file")

    p_export = sub.add_parser("export-batch")
    p_export.add_argument("file")
    p_export.add_argument("--schema")

    p_batch = sub.add_parser("answer-batch")
    p_batch.add_argument("file")

    args = parser.parse_args()
    paths = QueuePaths(args.queue_dir)
    paths.ensure()

    handlers = {
        "status": cmd_status,
        "list": cmd_list,
        "show": cmd_show,
        "answer": cmd_answer,
        "export-batch": cmd_export_batch,
        "answer-batch": cmd_answer_batch,
    }
    return handlers[args.command](paths, args)


if __name__ == "__main__":
    raise SystemExit(main())
