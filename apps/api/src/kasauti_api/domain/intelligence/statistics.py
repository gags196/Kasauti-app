"""Small statistics helpers, implemented here rather than pulled from scipy.

Five numbers do not justify a 30 MB dependency on every deploy and in CI. Each function
below is pinned by a unit test against published critical values, so the "we wrote our own
chi-square" risk is bounded by tests rather than by trust.

`verdict` lives here too, rather than in the analysis that first needed it. Two reports
now decide "is this a usable signal", and one shared rule — significant *and* powered, or
it is not a finding — is the only way their verdicts can be read against each other.
"""

import math
import random
from collections.abc import Sequence

_MAX_ITER = 300
_EPS = 3e-14


def _gamma_series(a: float, x: float) -> float:
    """Regularized lower incomplete gamma P(a, x) by series — good for x < a + 1."""
    term = total = 1.0 / a
    ap = a
    for _ in range(_MAX_ITER):
        ap += 1
        term *= x / ap
        total += term
        if abs(term) < abs(total) * _EPS:
            break
    return total * math.exp(-x + a * math.log(x) - math.lgamma(a))


def _gamma_continued_fraction(a: float, x: float) -> float:
    """Regularized upper incomplete gamma Q(a, x) by continued fraction — x >= a + 1."""
    tiny = 1e-300
    b = x + 1.0 - a
    c = 1.0 / tiny
    d = 1.0 / b
    h = d
    for i in range(1, _MAX_ITER):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < tiny:
            d = tiny
        c = b + an / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < _EPS:
            break
    return h * math.exp(-x + a * math.log(x) - math.lgamma(a))


def chi2_sf(x: float, df: int) -> float:
    """Upper-tail probability of the chi-square distribution."""
    if x <= 0:
        return 1.0
    a, half = df / 2.0, x / 2.0
    if half < a + 1.0:
        return 1.0 - _gamma_series(a, half)
    return _gamma_continued_fraction(a, half)


def chi_square_uniform(counts: Sequence[int]) -> tuple[float, int, float]:
    """Goodness-of-fit against a uniform distribution. Returns (statistic, df, p)."""
    total = sum(counts)
    k = len(counts)
    if total == 0 or k < 2:
        return 0.0, max(k - 1, 0), 1.0
    expected = total / k
    stat = sum((c - expected) ** 2 / expected for c in counts)
    return stat, k - 1, chi2_sf(stat, k - 1)


def _log_binom_pmf(k: int, n: int, p: float) -> float:
    if p <= 0.0:
        return 0.0 if k == 0 else -math.inf
    if p >= 1.0:
        return 0.0 if k == n else -math.inf
    return (
        math.lgamma(n + 1)
        - math.lgamma(k + 1)
        - math.lgamma(n - k + 1)
        + k * math.log(p)
        + (n - k) * math.log1p(-p)
    )


def binomial_sf_two_sided(hits: int, n: int, p0: float) -> float:
    """Exact two-sided binomial test: total probability of outcomes no more likely
    than the one observed. Log-space throughout, so n in the thousands is fine."""
    if n <= 0:
        return 1.0
    observed = _log_binom_pmf(hits, n, p0)
    if observed == -math.inf:
        return 0.0
    # Small slack so floating-point noise does not exclude an equally likely outcome.
    threshold = observed + 1e-9
    total = sum(
        math.exp(lp)
        for lp in (_log_binom_pmf(k, n, p0) for k in range(n + 1))
        if lp <= threshold
    )
    return min(1.0, total)


def poisson_binomial_p(hits: int, probabilities: Sequence[float]) -> tuple[float, float]:
    """Two-sided p for a sum of independent Bernoulli trials with *differing* rates.

    Used where each question offers a different chance of the event — e.g. "is the correct
    option a dated one", when questions carry different numbers of dated options. Treating
    that as one binomial would misstate the null. Normal approximation; returns
    (expected_hits, p).
    """
    expected = sum(probabilities)
    variance = sum(p * (1 - p) for p in probabilities)
    if variance <= 0:
        return expected, 1.0
    z = (hits - expected) / math.sqrt(variance)
    return expected, math.erfc(abs(z) / math.sqrt(2))


def label_permutation_rate(
    pairs: Sequence[tuple[str, str]], *, iterations: int = 5000, seed: int = 0
) -> float:
    """Null rate for "the flagged option is the correct one", by shuffling which option
    is correct across questions.

    `pairs` is (flagged_label, correct_label) per question. Shuffling the correct labels
    preserves both marginal distributions — how often each of A/B/C/D is the answer, and
    how often each position carries the flag — and breaks only their pairing. That is the
    null a plain 25% gets wrong: in the 691 `subset_of_numbered` questions "Both 1 and 2"
    is *mechanically* the longest string, so position and length are not independent of
    the printing convention.
    """
    if not pairs:
        return 0.0
    flagged = [f for f, _ in pairs]
    correct = [c for _, c in pairs]
    rng = random.Random(seed)
    hits = 0
    for _ in range(iterations):
        rng.shuffle(correct)
        hits += sum(1 for f, c in zip(flagged, correct, strict=True) if f == c)
    return hits / (iterations * len(pairs))


def stratified_permutation_rate(
    strata: dict[str, Sequence[tuple[str, str]]],
    *,
    iterations: int = 5000,
    seed: int = 0,
) -> float:
    """`label_permutation_rate` applied within each stratum, pooled by stratum size.

    Shuffling across the whole corpus would let a `subset_of_numbered` answer land on an
    `entity_choice` question, which destroys exactly the structure being controlled for.
    """
    total = sum(len(rows) for rows in strata.values())
    if total == 0:
        return 0.0
    return sum(
        label_permutation_rate(rows, iterations=iterations, seed=seed + i) * len(rows)
        for i, rows in enumerate(strata.values())
    ) / total


# Below this a rate is reported but never given a verdict: n is the honest answer.
MIN_N_FOR_VERDICT = 30


def verdict(
    rate: float, baseline: float, n: int, p_value: float | None, alpha: float
) -> str:
    """One rule for every pattern claim: significant against a corrected alpha, and
    powered enough to be worth reading. `inverse_signal` is not a lesser result — for an
    elimination rule it is the useful direction."""
    if n < MIN_N_FOR_VERDICT:
        return "underpowered"
    if p_value is None or p_value > alpha:
        return "noise"
    return "signal" if rate > baseline else "inverse_signal"


def hypergeometric_pooled_p(
    hits: int, trials: Sequence[tuple[int, int, int]]
) -> tuple[float, float, float]:
    """Null for "does this marker pick out true statements", pooled over questions.

    Each trial is `(statements, true_statements, marked)` for one question. Under the
    null the marker is unrelated to truth, so the marked statements are a draw without
    replacement from that question's statements and the hits are hypergeometric. Pooling
    the per-question mean and variance is what stops a question with four statements and
    three true ones from being compared against a flat 50%.

    A single binomial over all statements would be wrong twice over: statements inside a
    question are not independent (their true-count is fixed by the answer key), and the
    true rate varies question to question. Returns (expected_hits, baseline_rate, p).
    """
    expected = variance = 0.0
    marked_total = 0
    for statements, true_statements, marked in trials:
        if statements <= 0 or marked <= 0:
            continue
        marked_total += marked
        share = true_statements / statements
        expected += marked * share
        if statements > 1:
            variance += (
                marked * share * (1 - share) * (statements - marked) / (statements - 1)
            )
    if marked_total == 0:
        return 0.0, 0.0, 1.0
    baseline = expected / marked_total
    if variance <= 0:
        # Every question was all-true or all-false, or every statement was marked: the
        # observation was fixed before the marker was applied, so there is nothing to test.
        return expected, baseline, 1.0
    z = (abs(hits - expected) - 0.5) / math.sqrt(variance)
    return expected, baseline, math.erfc(max(z, 0.0) / math.sqrt(2))
