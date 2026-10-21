"""Elimination-rule scoring, over synthetic statements — no database needed.

Same standard as the option-pattern tests: a *planted* signal must be found, and a
*manufactured* one must not. The manufactured case here is specific and is the whole
reason the null is hypergeometric rather than a flat rate — a marker that happens to
appear in hard questions, where fewer statements are true, looks like a discovery under
any corpus-wide baseline while carrying no information at all.
"""

import re

from kasauti_api.domain.intelligence.elimination import (
    FAMILYWISE_ALPHA,
    RULE_COUNT,
    STATEMENT_RULES,
    StatementRule,
    evaluate_dichotomy,
    evaluate_statement_rule,
)
from kasauti_api.domain.intelligence.statements import StatementRecord
from kasauti_api.domain.intelligence.statistics import hypergeometric_pooled_p

MARKER = StatementRule(
    key="marker", title_en="Marker", docx_claim="claimed to be decisive",
    claims_true=False, pattern=re.compile(r"\bonly\b", re.IGNORECASE),
)


def _question(question_id: int, statements: list[tuple[str, bool]]) -> list[StatementRecord]:
    true_count = sum(1 for _, is_true in statements if is_true)
    return [
        StatementRecord(
            question_id=question_id, year=2024, question_number=str(question_id),
            index=i + 1, text=text, is_true=is_true, is_claim=True,
            statement_count=len(statements), true_count=true_count, source="subset",
        )
        for i, (text, is_true) in enumerate(statements)
    ]


def _run(records, alpha=FAMILYWISE_ALPHA):
    return evaluate_statement_rule(MARKER, records, alpha)


def test_a_planted_signal_is_found():
    """The marker sits on the false statement in every question."""
    records = []
    for qid in range(60):
        records += _question(qid, [
            ("this one is only ever wrong", False),
            ("a plain true statement", True),
        ])
    result = _run(records)
    assert result.n == 60
    assert result.rate == 0.0
    assert result.baseline == 0.5
    assert result.verdict == "inverse_signal"


def test_a_marker_that_tracks_question_difficulty_is_not_a_finding():
    """The artifact that matters. The marker appears only in questions where one
    statement in four is true, so it is right 25% of the time against a corpus base rate
    of 62.5% — and carries no information whatsoever, because within those questions it
    is spread evenly over true and false statements. A flat baseline would report it as a
    strong inverse signal; the hypergeometric null puts it exactly on 25%."""
    records = []
    for qid in range(40):  # hard questions: 1 of 4 true, every statement marked
        records += _question(qid, [
            ("only a", qid % 4 == 0), ("only b", qid % 4 == 1),
            ("only c", qid % 4 == 2), ("only d", qid % 4 == 3),
        ])
    for qid in range(40, 80):  # easy questions, unmarked: 3 of 4 true
        records += _question(qid, [
            ("plain a", True), ("plain b", True),
            ("plain c", True), ("plain d", False),
        ])

    corpus_true_rate = sum(1 for r in records if r.is_true) / len(records)
    result = _run(records)
    assert round(corpus_true_rate, 3) == 0.5  # what a flat baseline would compare against
    assert result.rate == 0.25
    assert result.baseline == 0.25  # what the marked questions actually offered
    assert result.verdict == "noise"


def test_a_marker_on_every_statement_of_a_question_can_never_be_a_finding():
    """When the marker takes all four statements the hit count is fixed by the answer
    key before the marker is applied. There is no variance to test, and the honest p is 1."""
    records = []
    for qid in range(50):
        records += _question(qid, [("only a", True), ("only b", False)])
    result = _run(records)
    assert result.p_value == 1.0
    assert result.verdict == "noise"


def test_a_real_effect_in_too_few_statements_stays_underpowered():
    """A perfect 12-for-12 is not a finding. n rules before p does."""
    records = []
    for qid in range(12):
        records += _question(qid, [("only wrong", False), ("right", True)])
    result = _run(records)
    assert result.rate == 0.0
    assert result.verdict == "underpowered"


def test_hypergeometric_matches_brute_force():
    """Two statements, one true, one of them marked: the marked one is true half the
    time, exactly."""
    expected, baseline, p = hypergeometric_pooled_p(50, [(2, 1, 1)] * 100)
    assert expected == 50.0
    assert baseline == 0.5
    assert p > 0.9
    # 90 hits out of 100 fair coins is not a coincidence.
    _, _, p_extreme = hypergeometric_pooled_p(90, [(2, 1, 1)] * 100)
    assert p_extreme < 1e-10


def test_dichotomy_measures_shared_theme_not_the_split_itself():
    """Split answers are common in two-statement questions generally. The docx claims
    *shared theme* is what forces the split, so the baseline has to be the split rate
    over all two-statement questions — otherwise the rule takes credit for the norm."""
    records = []
    for qid in range(40):  # unrelated pair, split answer
        records += _question(qid, [("alpha beta gamma delta", True),
                                   ("epsilon zeta eta theta", False)])
    for qid in range(40, 80):  # same-theme pair, both true — contradicts the claim
        records += _question(qid, [("arable land in india is measured", True),
                                   ("arable land in india is irrigated", True)])
    result = evaluate_dichotomy(records, FAMILYWISE_ALPHA)
    assert result.n == 40
    assert result.rate == 0.0
    assert result.baseline == 0.5
    assert result.verdict == "inverse_signal"


def test_every_rule_declares_what_it_tells_the_candidate_to_do():
    """`claims_true` is what turns a significance test into "would following this have
    earned or cost a mark". A rule without it cannot appear in the learner-facing lab."""
    assert {r.key for r in STATEMENT_RULES if r.claims_true} == {
        "moderate_modifier", "milestone_first", "rounded_target", "recency_framing",
    }


def test_the_rule_family_is_counted_for_the_bonferroni_threshold():
    """Adding a rule without widening the correction is how a report starts finding
    patterns it has not earned."""
    assert RULE_COUNT == len(STATEMENT_RULES) + 4
    assert FAMILYWISE_ALPHA == 0.05 / RULE_COUNT
