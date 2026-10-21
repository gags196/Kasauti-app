"""Validate every rubric YAML in content/rubrics/ against the rubric JSON Schema.

Run in CI and locally before committing rubric edits:
    uv run python scripts/validate_rubrics.py
Exits non-zero on the first invalid rubric. Also checks that the *achievable* marks
reach total_marks, that every group's cap can bind, and that every judging prompt exists.

The schema is the authority on what a rubric file may contain; the structural checks
below run through `domain/rubric/loader.py`, which is the authority on what one means.
Deriving "achievable marks" twice is how a rubric passes CI and then evaluates
differently, so it is derived once, there.
"""

import json
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api" / "src"))

from kasauti_api.domain.rubric.loader import (  # noqa: E402
    RubricError,
    RubricGroup,
    achievable_marks,
    parse_rubric,
)

RUBRICS_DIR = REPO_ROOT / "content" / "rubrics"
SCHEMA_PATH = RUBRICS_DIR / "schema" / "rubric.schema.json"
PROMPTS_DIR = REPO_ROOT / "content" / "prompts"


def prompt_ref_errors(rubric) -> list[str]:
    """Rubric points that name a judging prompt which does not exist.

    A dangling `rubric_prompt_ref` is invisible until the evaluator runs and fails on one
    point of one answer, so it is worth catching in CI alongside the schema.
    """
    messages: list[str] = []
    for point in rubric.points:
        ref = point.verification.rubric_prompt_ref
        if ref is None:
            continue
        if not (PROMPTS_DIR / ref).is_file():
            messages.append(
                f"point {point.id!r} references prompt {ref!r}, "
                f"which does not exist under content/prompts/"
            )
    return messages


def question_errors(rubric) -> list[str]:
    """A rubric must say what question it grades, and say it honestly.

    `question_ref` is resolved against the ingested corpus at judge time, so it asserts
    "UPSC printed this". The first rubric written carried a ref to a paper/year/number
    that exists but is a different question — the answer was a coaching test-series one —
    and the evaluator silently judged it against UPSC's actual question of that number.
    A rubric that is not grading a PYQ must carry the question text and name its source.
    """
    messages: list[str] = []
    if rubric.question_ref and rubric.question_text_en:
        messages.append(
            "carries both question_ref and question_text_en — one question, one "
            "provenance: use question_ref only for a question that is in the corpus"
        )
    elif not rubric.question_ref and not rubric.question_text_en:
        messages.append(
            "names no question: give question_ref for a UPSC past question, or "
            "question_text_en + question_source for anything else"
        )
    elif rubric.question_text_en and not rubric.question_source:
        messages.append(
            "carries question_text_en with no question_source — a non-PYQ question must "
            "name where it came from, or it reads as a UPSC question"
        )
    return messages


def mark_errors(rubric) -> list[str]:
    """Marks problems with one rubric's arithmetic.

    A group of alternative points contributes its `credit_cap`, not the sum of its
    points — "any three of these six" is worth three, not six. Checking the *achievable*
    total keeps a real invariant rather than dropping the check because groups made the
    naive sum wrong.
    """
    messages: list[str] = []

    for group in rubric.groups:
        available = sum(point.marks for point in group.points)
        # A cap at or above what the points can yield is not a cap; it means the author
        # meant every point to count and the group is doing nothing.
        if group.credit_cap >= available:
            messages.append(
                f"group {group.id!r} caps credit at {group.credit_cap:g} but its points "
                f"only offer {available:g} — the cap never binds, so use plain steps instead"
            )
        if group.expect_k is not None and group.expect_k > len(group.points):
            messages.append(
                f"group {group.id!r} expects {group.expect_k} points but defines "
                f"only {len(group.points)}"
            )

    achievable = achievable_marks(rubric)
    if abs(achievable - rubric.total_marks) > 1e-9:
        messages.append(
            f"achievable marks total {achievable:g} "
            f"(leaf steps + each group's credit_cap), but total_marks is "
            f"{rubric.total_marks:g}"
        )
    return messages


def main() -> int:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)

    rubric_files = [p for p in RUBRICS_DIR.rglob("*.yaml") if "schema" not in p.parts]
    if not rubric_files:
        print("No rubrics found (ok during scaffolding).")
        return 0

    failures = 0
    for path in sorted(rubric_files):
        rel = path.relative_to(REPO_ROOT)
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        errors = sorted(validator.iter_errors(data), key=lambda e: e.json_path)
        for err in errors:
            print(f"FAIL {rel}: {err.json_path}: {err.message}")
            failures += 1
        if errors:
            continue

        try:
            rubric = parse_rubric(data, source_path=path)
        except RubricError as error:
            # Schema-valid but the engine cannot load it — duplicate ids, say, which the
            # schema has no way to see.
            print(f"FAIL {rel}: {error}")
            failures += 1
            continue

        messages = mark_errors(rubric) + prompt_ref_errors(rubric) + question_errors(rubric)
        for message in messages:
            print(f"FAIL {rel}: {message}")
        failures += len(messages)
        if not messages:
            groups = sum(1 for e in rubric.entries if isinstance(e, RubricGroup))
            print(
                f"ok   {rel} - {len(rubric.points)} points"
                f"{f' in {groups} group(s)' if groups else ''}, "
                f"{rubric.total_marks:g} marks"
            )

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
