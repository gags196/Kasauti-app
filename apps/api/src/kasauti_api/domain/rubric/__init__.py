"""The Mains answer evaluator.

`loader` reads a rubric; `engine` judges one answer against it, point by point;
`evidence` decides in Python whether a claimed hit is actually in the learner's words.
Nothing here produces a mark — see `engine.AnswerReport`.
"""

from kasauti_api.domain.rubric.engine import (
    AnswerReport,
    GroupOutcome,
    PointOutcome,
    PointStatus,
    judge_answer,
    rubric_version,
)
from kasauti_api.domain.rubric.evidence import find_quote, quote_is_supported
from kasauti_api.domain.rubric.loader import (
    Rubric,
    RubricError,
    RubricGroup,
    RubricPoint,
    achievable_marks,
    iter_rubric_paths,
    load_rubric,
    load_rubric_path,
    parse_rubric,
)

__all__ = [
    "AnswerReport",
    "GroupOutcome",
    "PointOutcome",
    "PointStatus",
    "Rubric",
    "RubricError",
    "RubricGroup",
    "RubricPoint",
    "achievable_marks",
    "find_quote",
    "iter_rubric_paths",
    "judge_answer",
    "load_rubric",
    "load_rubric_path",
    "parse_rubric",
    "quote_is_supported",
    "rubric_version",
]
