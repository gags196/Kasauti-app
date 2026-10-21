"""Option-pattern hypotheses, over synthetic rows — no database needed.

The point of these tests is that a *planted* signal is found and a *manufactured*
artifact is not. The second matters more: the inherited version of this analysis reported
the shape of UPSC's printing conventions as though it were examiner behaviour.
"""

from kasauti_api.domain.intelligence.option_patterns import (
    FAMILYWISE_ALPHA,
    _Row,
    h_catch_all,
    h_dated_options,
    h_label_position,
    h_length_outlier,
)
from kasauti_api.domain.intelligence.statistics import MIN_N_FOR_VERDICT, verdict

LABELS = ["A", "B", "C", "D"]


def _row(texts: dict[str, str], correct: str, *, archetype="entity_choice", year=2024):
    lengths = sorted(len(t) for t in texts.values())
    longest = (
        max(texts, key=lambda label: len(texts[label]))
        if lengths[-1] != lengths[-2]
        else None
    )
    from kasauti_api.domain.intelligence.facts import NONE_OF_ABOVE_RE
    from kasauti_api.domain.intelligence.option_patterns import YEAR_IN_OPTION_RE

    return _Row(
        question_id=0, year=year, archetype=archetype, correct_label=correct,
        labels=list(texts), texts=texts,
        correct_is_longest=None if longest is None else (correct == longest),
        longest_label=longest,
        catch_all_labels=[k for k, t in texts.items() if NONE_OF_ABOVE_RE.search(t)],
        dated_labels=[k for k, t in texts.items() if YEAR_IN_OPTION_RE.search(t)],
    )


def _subset_row(correct: str, *, year=2024):
    """The 691-question family. "Neither 1 nor 2" is always the longest string here —
    the artifact the archetype-stratified baseline exists to absorb."""
    return _row(
        {"A": "1 only", "B": "2 only", "C": "Both 1 and 2", "D": "Neither 1 nor 2"},
        correct, archetype="subset_of_numbered", year=year,
    )


def test_verdict_requires_both_significance_and_sample_size():
    assert verdict(0.9, 0.25, 10, 0.0001, FAMILYWISE_ALPHA) == "underpowered"
    assert verdict(0.9, 0.25, 500, 0.02, FAMILYWISE_ALPHA) == "noise"  # fails 0.01
    assert verdict(0.9, 0.25, 500, 0.0001, FAMILYWISE_ALPHA) == "signal"
    assert verdict(0.05, 0.25, 500, 0.0001, FAMILYWISE_ALPHA) == "inverse_signal"
    assert verdict(0.9, 0.25, 500, None, FAMILYWISE_ALPHA) == "noise"


def test_printing_convention_alone_does_not_become_a_finding():
    """Every question is the subset family, and the answer is uniform over labels. The
    longest option ("Neither 1 nor 2") is therefore correct about a quarter of the time
    *by construction*. A 25% flat null would call that nothing; the stratified null must
    also call it nothing — and crucially must not call it a signal."""
    rows = [_subset_row(LABELS[i % 4]) for i in range(400)]
    result = h_length_outlier(rows, FAMILYWISE_ALPHA)
    assert result.n == 400
    assert result.verdict == "noise"
    assert result.baseline_basis == "archetype-permutation"


def test_a_planted_length_signal_is_found():
    """The longest option moves around the option set, and is the answer 90% of the
    time. The label marginal stays flat, so nothing but length explains the rate."""
    rows = []
    for i in range(400):
        longest = LABELS[i % 4]
        texts = {label: ("x" * 40 if label == longest else "short") for label in LABELS}
        # 90% of the time the answer is the long one; otherwise the next label along.
        correct = longest if i % 10 else LABELS[(i + 1) % 4]
        rows.append(_row(texts, correct))
    result = h_length_outlier(rows, FAMILYWISE_ALPHA)
    assert result.rate == 0.9
    assert result.baseline < 0.35  # flat label marginal → null stays near a quarter
    assert result.verdict == "signal"


def test_a_pure_label_skew_does_not_masquerade_as_a_length_signal():
    """If D is nearly always both the longest option and the answer, the length
    hypothesis must stay silent — the finding belongs to the label hypothesis, and
    reporting it twice would double-count one effect across a corrected threshold.

    This is precisely the subset family's shape, which is why the null is built by
    permuting correct labels rather than assumed to be a flat quarter.
    """
    rows = [_subset_row("D") for _ in range(360)]
    rows += [_subset_row(LABELS[i % 3]) for i in range(40)]
    assert h_length_outlier(rows, FAMILYWISE_ALPHA).verdict == "noise"
    # The skew is real, and this is where it should surface.
    assert h_label_position(rows, FAMILYWISE_ALPHA).verdict == "signal"


def test_ties_are_excluded_from_the_length_hypothesis():
    """Four options of identical length contribute nothing — they cannot, since no
    option is the longest."""
    tied = [
        _row({"A": "aaaa", "B": "bbbb", "C": "cccc", "D": "dddd"}, "A")
        for _ in range(50)
    ]
    assert h_length_outlier(tied, FAMILYWISE_ALPHA).n == 0


def test_escape_hatch_covers_the_subset_family_wording():
    """"Neither 1 nor 2" is "none of the above" in different words. Counting only the
    literal phrase left n=5 in the recent era, which answers nothing either way."""
    rows = [_subset_row(LABELS[i % 4]) for i in range(120)]
    result = h_catch_all(rows, FAMILYWISE_ALPHA)
    assert result.n == 120
    assert result.verdict == "noise"


def test_dated_option_null_accounts_for_how_many_options_are_dated():
    """A question with three dated options gives the event a 75% chance, not 25%.
    Pooling those as one binomial would manufacture a finding."""
    rows = [
        _row({"A": "In 1947", "B": "In 1950", "C": "In 1962", "D": "Never"}, "A")
        for _ in range(60)
    ]
    result = h_dated_options(rows, FAMILYWISE_ALPHA)
    assert result.n == 60
    assert result.baseline == 0.75
    # Correct is dated every time, but so are three options in four — barely above null.
    assert result.rate == 1.0
    assert result.baseline_basis == "share-of-options"


def test_label_position_on_a_flat_distribution_is_noise():
    rows = [_row({label: label * 5 for label in LABELS}, LABELS[i % 4]) for i in range(400)]
    assert h_label_position(rows, FAMILYWISE_ALPHA).verdict == "noise"


def test_label_position_finds_a_real_skew():
    rows = [_row({label: label * 5 for label in LABELS}, "B") for i in range(300)]
    rows += [_row({label: label * 5 for label in LABELS}, LABELS[i % 4]) for i in range(100)]
    assert h_label_position(rows, FAMILYWISE_ALPHA).verdict == "signal"


def test_empty_input_is_underpowered_not_an_error():
    for hypothesis in (h_catch_all, h_length_outlier, h_dated_options):
        result = hypothesis([], FAMILYWISE_ALPHA)
        assert result.n == 0
        assert result.verdict == "underpowered"
        assert not result.is_signal


def test_min_n_guard_is_the_documented_one():
    assert MIN_N_FOR_VERDICT == 30
    assert FAMILYWISE_ALPHA == 0.05 / 5
