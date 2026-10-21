"""Pin the hand-rolled statistics against published critical values.

These functions exist instead of a scipy dependency, so the "we wrote our own chi-square"
risk has to be bounded by tests rather than by trust.
"""

import math

import pytest
from kasauti_api.domain.intelligence.statistics import (
    binomial_sf_two_sided,
    chi2_sf,
    chi_square_uniform,
    label_permutation_rate,
    poisson_binomial_p,
    stratified_permutation_rate,
)


def test_chi2_critical_values():
    """Standard table: for df=3, p=0.05 at 7.815 and p=0.01 at 11.345."""
    assert chi2_sf(7.815, 3) == pytest.approx(0.05, abs=0.001)
    assert chi2_sf(11.345, 3) == pytest.approx(0.01, abs=0.001)
    assert chi2_sf(3.841, 1) == pytest.approx(0.05, abs=0.001)
    assert chi2_sf(0.0, 3) == 1.0



def test_chi_square_uniform_on_the_real_answer_labels():
    """A/B/C/D over the 1,391 keyed questions. ~8.3 with p just under 0.05 — which
    fails the Bonferroni-corrected threshold of 0.01 used across five hypotheses.
    The honest answer to "is there a letter bias" is no."""
    stat, df, p = chi_square_uniform([324, 386, 360, 321])
    assert df == 3
    assert 8.0 < stat < 8.6
    assert 0.03 < p < 0.05


def test_chi_square_uniform_of_a_flat_distribution():
    stat, df, p = chi_square_uniform([25, 25, 25, 25])
    assert stat == 0.0
    assert p == 1.0


def test_binomial_two_sided():
    assert binomial_sf_two_sided(50, 100, 0.5) == pytest.approx(1.0, abs=0.001)
    assert binomial_sf_two_sided(70, 100, 0.5) < 1e-4
    # The real "correct option is longest" figure: 211/939 against a 25% null is
    # slightly *below* chance and nowhere near significant.
    assert binomial_sf_two_sided(211, 939, 0.25) > 0.05


def test_binomial_handles_large_n_without_overflow():
    """Log-space throughout — comb(1400, 700) * 0.25**700 would underflow to zero."""
    p = binomial_sf_two_sided(350, 1400, 0.25)
    assert 0.0 <= p <= 1.0
    assert p == pytest.approx(1.0, abs=0.05)


def test_poisson_binomial_uses_per_trial_rates():
    """Three questions with 1, 2 and 3 dated options out of four: expected hits are
    0.25 + 0.5 + 0.75, not 3 x some single rate."""
    expected, p = poisson_binomial_p(2, [0.25, 0.5, 0.75])
    assert expected == pytest.approx(1.5, abs=1e-9)
    assert 0.0 <= p <= 1.0


def test_label_permutation_null_is_not_simply_one_over_four():
    """When the flagged position and the correct label share a marginal skew, the null
    rate is above 25% — which is the whole reason a plain 0.25 baseline is wrong."""
    # Every question flags D, and D is the answer in 40 of 100 questions.
    pairs = [("D", "D")] * 40 + [("D", "A")] * 60
    rate = label_permutation_rate(pairs, iterations=400, seed=1)
    assert rate == pytest.approx(0.40, abs=0.03)

    # With a flat correct-label marginal the null does collapse to ~1/4.
    flat = [("D", label) for label in "ABCD" * 50]
    assert label_permutation_rate(flat, iterations=400, seed=1) == pytest.approx(0.25, abs=0.03)


def test_label_permutation_is_deterministic_for_a_seed():
    pairs = [("A", "A"), ("B", "C"), ("C", "C"), ("D", "B")] * 10
    assert label_permutation_rate(pairs, iterations=200, seed=7) == (
        label_permutation_rate(pairs, iterations=200, seed=7)
    )


def test_stratified_permutation_pools_by_stratum_size():
    """Shuffling across strata would let a subset-family answer land on an entity
    question, destroying the structure being controlled for."""
    strata = {
        "subset": [("D", "D")] * 30 + [("D", "A")] * 10,   # 75% within stratum
        "entity": [("A", label) for label in "ABCD" * 15],  # ~25% within stratum
    }
    pooled = stratified_permutation_rate(strata, iterations=400, seed=3)
    weighted = (0.75 * 40 + 0.25 * 60) / 100
    assert pooled == pytest.approx(weighted, abs=0.04)


def test_empty_inputs_are_safe():
    assert label_permutation_rate([]) == 0.0
    assert stratified_permutation_rate({}) == 0.0
    assert binomial_sf_two_sided(0, 0, 0.25) == 1.0
    assert chi_square_uniform([]) == (0.0, 0, 1.0)
    assert not math.isnan(chi2_sf(1.0, 2))
