"""Feature A2: does the way UPSC builds an MCQ's options leak the answer?

Pure statistics over `question_profiles` and `question_options` — no LLM. One
implementation serves both the committed markdown report and the API, so a figure a
learner sees and a figure in `benchmarks/reports/` can never disagree.

Three things separate this from a naive pass, and each of them changes a verdict:

**The baseline is not 25%.** In 691 of the 1,400 questions the options are
"1 only / 2 only / Both 1 and 2 / Neither 1 nor 2", where "Both 1 and 2" is
*mechanically* the longest string. Any "the longest option is correct" rate has to be
compared against a null that preserves that printing convention, so the null is built by
permuting which option is correct **within each archetype**, not assumed.

**Five hypotheses need a corrected threshold.** At alpha=0.05 across five tests you expect
one false positive by construction. Everything here is judged against a Bonferroni
threshold, and the report prints it.

**Era matters more than the pooled figure.** UPSC's option construction changed in 2022 —
the subset family fell from 29% of questions to 15%. A pooled fourteen-year rate describes
an exam nobody is sitting, so the report leads with 2022+ and shows all-time as context.
"""

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kasauti_api.db.models import Question, QuestionOption, QuestionProfile
from kasauti_api.db.models.profiles import QuestionFormat
from kasauti_api.domain.intelligence.facts import (
    NONE_OF_ABOVE_RE,
    OptionInput,
    option_language,
)
from kasauti_api.domain.intelligence.scope import QuestionScope, question_ids
from kasauti_api.domain.intelligence.statistics import (
    binomial_sf_two_sided,
    chi_square_uniform,
    poisson_binomial_p,
    stratified_permutation_rate,
    verdict,
)

# Five hypotheses are tested, so a nominal 0.05 would produce roughly one false positive
# per report by construction. Bonferroni is conservative and easy to explain, which is
# what this report needs more than power.
HYPOTHESIS_COUNT = 5
FAMILYWISE_ALPHA = 0.05 / HYPOTHESIS_COUNT
PERMUTATION_ITERATIONS = 5000

# The founder's hypothesis is about the escape-hatch option — "is 'none of the above' a
# disguised tell". In the subset family that option is printed "Neither 1 nor 2", which is
# the same tell wearing different words, so the broad definition from facts.py is reused
# here rather than a second, stricter one being maintained alongside it. Restricting to
# the literal phrase left n=5 in the recent era, which answers nothing.
TOKEN_RE = re.compile(r"\w+", re.UNICODE)
YEAR_IN_OPTION_RE = re.compile(r"\b(1[89]\d{2}|20\d{2})\b")


@dataclass(frozen=True)
class Hypothesis:
    key: str
    title_en: str
    n: int
    hits: int
    rate: float
    baseline: float
    baseline_basis: str
    p_value: float | None
    verdict: str
    note: str | None = None

    @property
    def is_signal(self) -> bool:
        return self.verdict in ("signal", "inverse_signal")


@dataclass(frozen=True)
class OptionPatternReport:
    scope_note: str
    keyed_questions: int
    year_from: int | None
    year_to: int | None
    alpha: float
    label_distribution: dict[str, int]
    label_chi2: tuple[float, int, float]
    hypotheses: list[Hypothesis] = field(default_factory=list)


@dataclass
class _Row:
    """One keyed question, flattened to what the hypotheses need."""

    question_id: int
    year: int
    archetype: str
    correct_label: str
    labels: list[str]
    texts: dict[str, str]
    correct_is_longest: bool | None
    longest_label: str | None
    catch_all_labels: list[str]
    dated_labels: list[str]


def _tokens(text: str) -> set[str]:
    return set(TOKEN_RE.findall(text.lower()))


def _overlap(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


async def load_rows(session: AsyncSession, scope: QuestionScope) -> list[_Row]:
    """Keyed questions in scope, with their options, as flat rows.

    Only questions with exactly one correct option are included: a dropped question
    (`is_correct` NULL throughout) carries no information about option construction and
    must not be silently treated as one where option A is wrong.
    """
    stmt = (
        select(
            Question.id,
            Question.year,
            QuestionProfile.option_archetype,
            QuestionProfile.correct_label,
            QuestionProfile.correct_is_longest,
        )
        .join(QuestionProfile, QuestionProfile.question_id == Question.id)
        .where(
            Question.id.in_(question_ids(scope)),
            QuestionProfile.correct_label.is_not(None),
        )
        .order_by(Question.year, Question.id)
    )
    meta = (await session.execute(stmt)).all()
    if not meta:
        return []

    ids = [m[0] for m in meta]
    options = (
        await session.execute(
            select(QuestionOption).where(QuestionOption.question_id.in_(ids))
        )
    ).scalars().all()
    by_question: dict[int, list[QuestionOption]] = defaultdict(list)
    for option in options:
        by_question[option.question_id].append(option)

    rows = []
    for qid, year, archetype, correct_label, is_longest in meta:
        opts = sorted(by_question.get(qid, []), key=lambda o: o.option_label)
        if len(opts) < 3:
            continue
        # One language for the whole question. Falling back per option is what made the
        # inherited overlap statistic compare Devanagari tokens against Latin ones.
        lang = option_language(
            [
                OptionInput(o.option_label, o.option_text_en, o.option_text_hi, o.is_correct)
                for o in opts
            ]
        )
        texts = {
            o.option_label: ((o.option_text_en if lang == "en" else o.option_text_hi) or "")
            for o in opts
        }
        lengths = sorted(len(t) for t in texts.values())
        longest_label = None
        if len(lengths) >= 2 and lengths[-1] != lengths[-2]:
            longest_label = max(texts, key=lambda lab: len(texts[lab]))
        rows.append(
            _Row(
                question_id=qid,
                year=year,
                archetype=archetype.value if archetype else "unknown",
                correct_label=correct_label,
                labels=[o.option_label for o in opts],
                texts=texts,
                correct_is_longest=is_longest,
                longest_label=longest_label,
                catch_all_labels=[
                    lab for lab, t in texts.items() if NONE_OF_ABOVE_RE.search(t)
                ],
                dated_labels=[
                    lab for lab, t in texts.items() if YEAR_IN_OPTION_RE.search(t)
                ],
            )
        )
    return rows


def h_wording_overlap(rows: list[_Row], alpha: float) -> Hypothesis:
    """H1: does the correct option share more wording with a sibling than a wrong one?"""
    usable = [r for r in rows if len(r.texts) >= 3]
    if not usable:
        return Hypothesis("wording_overlap", "Correct option echoes a sibling option",
                          0, 0, 0.0, 0.0, "permutation", None, "underpowered")

    def best_overlap(row: _Row, label: str) -> float:
        return max(
            (_overlap(row.texts[label], row.texts[other])
             for other in row.texts if other != label),
            default=0.0,
        )

    observed = sum(best_overlap(r, r.correct_label) for r in usable) / len(usable)
    # Null: the correct option is any of this question's options with equal chance.
    all_scores = [[best_overlap(r, lab) for lab in r.texts] for r in usable]
    null = sum(sum(s) / len(s) for s in all_scores) / len(all_scores)

    # Express as a rate so the shared verdict/report machinery applies: how often the
    # correct option is the one with the highest sibling overlap.
    hits = sum(
        1 for r in usable
        if r.correct_label == max(r.texts, key=lambda lab: best_overlap(r, lab))
    )
    n = len(usable)
    baseline = stratified_permutation_rate(
        _strata(usable, lambda r: max(r.texts, key=lambda lab: best_overlap(r, lab))),
        iterations=PERMUTATION_ITERATIONS,
    )
    p = binomial_sf_two_sided(hits, n, baseline) if baseline > 0 else None
    return Hypothesis(
        key="wording_overlap",
        title_en="Correct option echoes a sibling option",
        n=n, hits=hits, rate=hits / n,
        baseline=baseline, baseline_basis="archetype-permutation",
        p_value=p, verdict=verdict(hits / n, baseline, n, p, alpha),
        note=f"mean sibling overlap: correct {observed:.3f} vs any-option {null:.3f}",
    )


def _strata(rows: list[_Row], flag) -> dict[str, list[tuple[str, str]]]:
    """(flagged_label, correct_label) pairs grouped by option archetype."""
    strata: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for row in rows:
        flagged = flag(row)
        if flagged is not None:
            strata[row.archetype].append((flagged, row.correct_label))
    return strata


def h_catch_all(rows: list[_Row], alpha: float) -> Hypothesis:
    """H2: when an escape-hatch option is offered, is it the answer?

    "None of the above" and the subset family's "Neither 1 nor 2" are the same tell in
    different words, so both count. Restricting to the literal phrase left n=5 in the
    recent era — a question the data could not answer either way.
    """
    usable = [r for r in rows if r.catch_all_labels]
    n = len(usable)
    hits = sum(1 for r in usable if r.correct_label in r.catch_all_labels)
    if n == 0:
        return Hypothesis("catch_all", "Escape-hatch option is the answer", 0, 0, 0.0,
                          0.25, "uniform", None, "underpowered")
    # A question may print more than one catch-all, so the null is the average share of
    # options that are catch-alls, not a flat 1/4.
    probabilities = [len(r.catch_all_labels) / len(r.texts) for r in usable]
    baseline = sum(probabilities) / n
    _, p = poisson_binomial_p(hits, probabilities)
    return Hypothesis(
        key="catch_all",
        title_en="Escape-hatch option ('none of the above' / 'Neither 1 nor 2') is the answer",
        n=n, hits=hits, rate=hits / n, baseline=baseline,
        baseline_basis="share-of-options", p_value=p,
        verdict=verdict(hits / n, baseline, n, p, alpha),
    )


def h_length_outlier(rows: list[_Row], alpha: float) -> Hypothesis:
    """H3: is the longest option the answer?

    Ties are excluded rather than counted as hits. Counting them is what produced a
    "33.4% against a 25% baseline" claim where the honest figure is 22.5% — below chance.
    """
    usable = [r for r in rows if r.longest_label is not None]
    n = len(usable)
    if n == 0:
        return Hypothesis("length_outlier", "Longest option is the answer", 0, 0, 0.0,
                          0.25, "uniform", None, "underpowered")
    hits = sum(1 for r in usable if r.correct_label == r.longest_label)
    baseline = stratified_permutation_rate(
        _strata(usable, lambda r: r.longest_label), iterations=PERMUTATION_ITERATIONS
    )
    p = binomial_sf_two_sided(hits, n, baseline) if baseline > 0 else None
    return Hypothesis(
        key="length_outlier",
        title_en="Longest option is the answer",
        n=n, hits=hits, rate=hits / n, baseline=baseline,
        baseline_basis="archetype-permutation", p_value=p,
        verdict=verdict(hits / n, baseline, n, p, alpha),
        note="ties excluded — a tie is the absence of a signal, not a weak one",
    )


def h_dated_options(rows: list[_Row], alpha: float) -> Hypothesis:
    """H4: are options carrying a specific year disproportionately wrong?

    Counted per question, not per option: options within a question are not independent,
    since exactly one is correct, and a per-option binomial over ~4,000 options would be
    anticonservative.
    """
    usable = [r for r in rows if r.dated_labels]
    n = len(usable)
    if n == 0:
        return Hypothesis("dated_options", "A dated option is the answer", 0, 0, 0.0,
                          0.25, "share-of-options", None, "underpowered")
    hits = sum(1 for r in usable if r.correct_label in r.dated_labels)
    probabilities = [len(r.dated_labels) / len(r.texts) for r in usable]
    baseline = sum(probabilities) / n
    _, p = poisson_binomial_p(hits, probabilities)
    return Hypothesis(
        key="dated_options",
        title_en="A dated option (containing a specific year) is the answer",
        n=n, hits=hits, rate=hits / n, baseline=baseline,
        baseline_basis="share-of-options", p_value=p,
        verdict=verdict(hits / n, baseline, n, p, alpha),
    )


def h_label_position(rows: list[_Row], alpha: float) -> Hypothesis:
    """H5: is any answer letter over-represented?"""
    counts = Counter(r.correct_label for r in rows)
    labels = sorted(counts)
    stat, _, p = chi_square_uniform([counts[label] for label in labels])
    n = len(rows)
    top = max(counts, key=lambda label: counts[label]) if counts else "-"
    baseline = 1 / len(labels) if labels else 0.25
    rate = counts[top] / n if n else 0.0
    return Hypothesis(
        key="label_position",
        title_en="One answer letter is over-represented",
        n=n, hits=counts[top] if counts else 0, rate=rate, baseline=baseline,
        baseline_basis="uniform-over-labels", p_value=p,
        verdict=verdict(rate, baseline, n, p, alpha),
        note=f"chi-square {stat:.2f}, most frequent letter {top}",
    )


async def option_pattern_report(
    session: AsyncSession, scope: QuestionScope | None = None
) -> OptionPatternReport:
    scope = scope or QuestionScope()
    rows = await load_rows(session, scope)
    counts = Counter(r.correct_label for r in rows)
    labels = sorted(counts)
    years = [r.year for r in rows]
    return OptionPatternReport(
        scope_note=scope.describe(),
        keyed_questions=len(rows),
        year_from=min(years) if years else None,
        year_to=max(years) if years else None,
        alpha=FAMILYWISE_ALPHA,
        label_distribution={label: counts[label] for label in labels},
        label_chi2=chi_square_uniform([counts[label] for label in labels]),
        hypotheses=[
            h_wording_overlap(rows, FAMILYWISE_ALPHA),
            h_catch_all(rows, FAMILYWISE_ALPHA),
            h_length_outlier(rows, FAMILYWISE_ALPHA),
            h_dated_options(rows, FAMILYWISE_ALPHA),
            h_label_position(rows, FAMILYWISE_ALPHA),
        ],
    )


async def archetype_mix(
    session: AsyncSession, scope: QuestionScope
) -> dict[str, int]:
    """How the option sets are built, for the era comparison the report leads with."""
    rows = (
        await session.execute(
            select(QuestionProfile.option_archetype, QuestionProfile.question_id)
            .join(Question, Question.id == QuestionProfile.question_id)
            .where(Question.id.in_(question_ids(scope)))
        )
    ).all()
    counts = Counter(a.value if a else "unknown" for a, _ in rows)
    return dict(counts.most_common())


async def format_mix(session: AsyncSession, scope: QuestionScope) -> dict[str, int]:
    """Regex-detected question format. Roughly 23% carry no marker; that bucket is
    reported rather than hidden, because the model classification is what fills it in."""
    rows = (
        await session.execute(
            select(QuestionProfile.regex_format)
            .join(Question, Question.id == QuestionProfile.question_id)
            .where(Question.id.in_(question_ids(scope)))
        )
    ).all()
    counts = Counter(
        f.value if isinstance(f, QuestionFormat) else "(no printed marker)"
        for (f,) in rows
    )
    return dict(counts.most_common())


VERDICT_LABELS = {
    "signal": "USABLE SIGNAL",
    "inverse_signal": "USABLE INVERSE SIGNAL",
    "noise": "not a usable signal",
    "underpowered": "too few questions to conclude anything",
}


def render_markdown(
    reports: list[tuple[str, OptionPatternReport]],
    *,
    archetypes: dict[str, dict[str, int]] | None = None,
) -> str:
    """One section per era. The recent era comes first because it is the one that
    describes the exam a candidate is about to sit."""
    lines = [
        "# Prelims MCQ Option-Pattern Analysis",
        "",
        "Does the *construction* of the options leak the answer? Pure statistics over",
        "questions with an official answer key loaded — no model involved.",
        "",
        "Three things to read before the numbers:",
        "",
        "- **The baseline is not 25%.** In roughly half these questions the options are",
        '  "1 only / 2 only / Both 1 and 2 / Neither 1 nor 2", where "Both 1 and 2" is',
        "  mechanically the longest string. Length-based rates are therefore compared",
        "  against a null built by permuting which option is correct *within each option",
        "  archetype*, not against a flat quarter.",
        "- **Five hypotheses are tested**, so the threshold is Bonferroni-corrected to",
        f"  alpha = {FAMILYWISE_ALPHA:.3f}. At a nominal 0.05 one false positive per report",
        "  is expected by construction.",
        "- **A verdict of 'not a usable signal' is the useful answer**, not a failure. A",
        "  pattern that fires at chance is worth knowing does not work.",
        "",
    ]

    for era_name, report in reports:
        lines += [
            f"## {era_name}",
            "",
            f"*{report.keyed_questions} keyed questions · {report.year_from}–{report.year_to}"
            f" · scope: {report.scope_note}*",
            "",
        ]
        if report.keyed_questions == 0:
            lines += ["No keyed questions in scope.", ""]
            continue

        stat, df, p = report.label_chi2
        dist = " · ".join(f"{k} {v}" for k, v in report.label_distribution.items())
        lines += [
            f"Answer-letter distribution: {dist}",
            f"(chi-square {stat:.2f}, df {df}, p {p:.3f})",
            "",
            "| Hypothesis | n | rate | baseline | basis | p | verdict |",
            "|---|---:|---:|---:|---|---:|---|",
        ]
        for h in report.hypotheses:
            p_text = "—" if h.p_value is None else f"{h.p_value:.4f}"
            lines.append(
                f"| {h.title_en} | {h.n} | {h.rate:.1%} | {h.baseline:.1%} | "
                f"{h.baseline_basis} | {p_text} | {VERDICT_LABELS[h.verdict]} |"
            )
        lines.append("")
        for h in report.hypotheses:
            if h.note:
                lines.append(f"- *{h.title_en}*: {h.note}")
        lines.append("")

        if archetypes and era_name in archetypes:
            total = sum(archetypes[era_name].values()) or 1
            lines += ["Option-set construction in this era:", ""]
            lines += [
                f"- {name}: {n} ({n / total:.0%})"
                for name, n in archetypes[era_name].items()
            ]
            lines.append("")

    return "\n".join(lines)
