"""Rubric YAML → typed objects. The one place rubric *structure* is interpreted.

`scripts/validate_rubrics.py` imports `achievable_marks` and `iter_points` from here
rather than re-deriving them, so the CI content check and the evaluation engine can never
disagree about what a rubric says. The JSON Schema stays the authority on what a rubric
file may contain; this module is the authority on what one means.

The shape that matters: a `steps` entry is either a leaf point or a **group of
alternative points** with a `credit_cap`. GS marking is "any three of these six", so a
group's six points are not worth twice its three — the cap is what the group contributes,
and `expect_k` records how many a strong answer makes. None of that is arithmetic the
learner ever sees: no mark is predicted anywhere in this system. Marks survive in the
rubric only to *order and weight the feedback* — see `Rubric.partial_credit_rules`.
"""

import enum
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from kasauti_api.settings import get_settings

# Rubric YAML says "evaluation/gs_content_point_v1.md"; `load_prompt` wants the ref
# relative to content/. The schema documents rubric_prompt_ref as a path under
# content/prompts/, so the two differ by exactly this prefix.
PROMPTS_PREFIX = "prompts/"


class RubricError(ValueError):
    """A rubric file that parses as YAML but is not a usable rubric."""


class VerificationMethod(enum.Enum):
    llm_judged = "llm_judged"
    symbolic = "symbolic"
    human = "human"


@dataclass(frozen=True)
class Verification:
    method: VerificationMethod
    #: llm_judged only — path under content/prompts/ of the judging prompt.
    rubric_prompt_ref: str | None = None
    #: symbolic only — name of a checker registered in domain/rubric/symbolic.py.
    check: str | None = None
    params: dict = field(default_factory=dict)
    #: human only.
    note: str | None = None

    @property
    def prompt_ref(self) -> str:
        """The judging prompt's ref relative to content/, for `load_prompt`."""
        if self.rubric_prompt_ref is None:
            raise RubricError(f"{self.method.value} verification has no rubric_prompt_ref")
        return PROMPTS_PREFIX + self.rubric_prompt_ref


@dataclass(frozen=True)
class RubricPoint:
    """One content point: a single claim an answer either states or does not."""

    id: str
    marks: float
    verification: Verification
    description_en: str | None = None
    description_hi: str | None = None
    #: Set when this point lives inside an alternative-credit group.
    group_id: str | None = None

    def description(self, language: str = "en") -> str:
        """The point as the judge and the learner see it, in the reader's language
        where the rubric author supplied it. Falls back rather than showing an id."""
        if language == "hi" and self.description_hi:
            return self.description_hi
        return self.description_en or self.description_hi or self.id


@dataclass(frozen=True)
class RubricGroup:
    """A set of ALTERNATIVE points, of which a strong answer makes only some."""

    id: str
    credit_cap: float
    points: tuple[RubricPoint, ...]
    description_en: str | None = None
    description_hi: str | None = None
    #: How many points a strong answer is expected to make. Feedback only.
    expect_k: int | None = None

    def description(self, language: str = "en") -> str:
        if language == "hi" and self.description_hi:
            return self.description_hi
        return self.description_en or self.description_hi or self.id


@dataclass(frozen=True)
class Rubric:
    rubric_id: str
    topic_path: str
    total_marks: float
    entries: tuple[RubricPoint | RubricGroup, ...]
    #: Set only for a question UPSC actually printed, which the corpus therefore holds.
    question_ref: dict = field(default_factory=dict)
    #: The question verbatim, for a rubric grading something outside the PYQ corpus.
    question_text_en: str | None = None
    question_text_hi: str | None = None
    #: Where that non-PYQ question came from.
    question_source: str | None = None
    partial_credit_rules: tuple[str, ...] = ()
    source_path: Path | None = None

    def question_text(self, language: str = "en") -> str | None:
        """The question as the rubric carries it, or None when it must be resolved from
        the corpus via `question_ref`."""
        if language == "hi" and self.question_text_hi:
            return self.question_text_hi
        return self.question_text_en or self.question_text_hi

    @property
    def points(self) -> tuple[RubricPoint, ...]:
        """Every leaf point, in rubric order, groups flattened."""
        return tuple(iter_points_of(self))

    @property
    def groups(self) -> tuple[RubricGroup, ...]:
        return tuple(e for e in self.entries if isinstance(e, RubricGroup))

    def point(self, point_id: str) -> RubricPoint:
        for point in self.points:
            if point.id == point_id:
                return point
        raise KeyError(point_id)


def iter_points_of(rubric: Rubric) -> Iterator[RubricPoint]:
    for entry in rubric.entries:
        if isinstance(entry, RubricGroup):
            yield from entry.points
        else:
            yield entry


def _parse_verification(raw: dict, *, point_id: str) -> Verification:
    method = raw.get("method")
    try:
        parsed = VerificationMethod(method)
    except ValueError as error:
        raise RubricError(
            f"point {point_id!r} has unknown verification method {method!r}"
        ) from error
    return Verification(
        method=parsed,
        rubric_prompt_ref=raw.get("rubric_prompt_ref"),
        check=raw.get("check"),
        params=raw.get("params") or {},
        note=raw.get("note"),
    )


def _parse_point(raw: dict, *, group_id: str | None = None) -> RubricPoint:
    for required in ("id", "marks", "verification"):
        if required not in raw:
            raise RubricError(f"step {raw.get('id', '?')!r} is missing {required!r}")
    return RubricPoint(
        id=raw["id"],
        marks=float(raw["marks"]),
        verification=_parse_verification(raw["verification"], point_id=raw["id"]),
        description_en=raw.get("description_en"),
        description_hi=raw.get("description_hi"),
        group_id=group_id,
    )


def _parse_group(raw: dict) -> RubricGroup:
    for required in ("id", "credit_cap", "points"):
        if required not in raw:
            raise RubricError(f"group {raw.get('id', '?')!r} is missing {required!r}")
    return RubricGroup(
        id=raw["id"],
        credit_cap=float(raw["credit_cap"]),
        points=tuple(_parse_point(p, group_id=raw["id"]) for p in raw["points"]),
        description_en=raw.get("description_en"),
        description_hi=raw.get("description_hi"),
        expect_k=raw.get("expect_k"),
    )


def parse_rubric(data: dict, *, source_path: Path | None = None) -> Rubric:
    for required in ("rubric_id", "topic_path", "total_marks", "steps"):
        if required not in data:
            raise RubricError(f"rubric is missing {required!r} ({source_path})")

    entries: list[RubricPoint | RubricGroup] = []
    for raw in data["steps"]:
        # A group is told from a leaf by carrying alternative `points` — the same
        # discriminator the JSON Schema's oneOf uses and validate_rubrics walks by.
        entries.append(_parse_group(raw) if "points" in raw else _parse_point(raw))

    rubric = Rubric(
        rubric_id=data["rubric_id"],
        topic_path=data["topic_path"],
        total_marks=float(data["total_marks"]),
        entries=tuple(entries),
        question_ref=data.get("question_ref") or {},
        question_text_en=data.get("question_text_en"),
        question_text_hi=data.get("question_text_hi"),
        question_source=data.get("question_source"),
        partial_credit_rules=tuple(data.get("partial_credit_rules") or ()),
        source_path=source_path,
    )

    ids = [p.id for p in rubric.points] + [g.id for g in rubric.groups]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        # Verdicts come back keyed by id; two points sharing one would silently
        # collapse into a single verdict applied to both.
        raise RubricError(f"rubric {rubric.rubric_id!r} reuses ids: {', '.join(duplicates)}")
    return rubric


def achievable_marks(rubric: Rubric) -> float:
    """Leaf steps plus each group's `credit_cap` — never the sum of a group's points.

    "Any three of these six" is worth three. The naive sum is what made an honestly
    written 10-mark rubric total 13 and forced the group construct into the DSL.
    """
    total = 0.0
    for entry in rubric.entries:
        total += entry.credit_cap if isinstance(entry, RubricGroup) else entry.marks
    return total


def rubrics_dir() -> Path:
    return get_settings().content_dir / "rubrics"


def iter_rubric_paths() -> Iterator[Path]:
    """Every rubric file in content/rubrics/, excluding the schema directory."""
    for path in sorted(rubrics_dir().rglob("*.yaml")):
        if "schema" not in path.parts:
            yield path


def load_rubric_path(path: Path) -> Rubric:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RubricError(f"{path} does not contain a YAML mapping")
    return parse_rubric(data, source_path=path)


def load_rubric(rubric_id: str) -> Rubric:
    """Load by `rubric_id`, wherever it sits under content/rubrics/.

    Rubrics are filed by subject directory but referenced by id — the id already
    carries its version suffix, so it is the stable handle.
    """
    matches = [p for p in iter_rubric_paths() if p.stem == rubric_id]
    if not matches:
        raise RubricError(
            f"no rubric {rubric_id!r} under {rubrics_dir()}; "
            f"known: {', '.join(sorted(p.stem for p in iter_rubric_paths())) or '(none)'}"
        )
    if len(matches) > 1:
        raise RubricError(f"rubric {rubric_id!r} is defined more than once: {matches}")
    return load_rubric_path(matches[0])
