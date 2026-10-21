"""Do the elimination techniques the coaching circuit teaches actually work?

Fifteen rules, taken from a synthesis of seven
YouTube sources, each tested against the fourteen-year Prelims corpus. Pure statistics
over the answer keys — no model, no opinion, and no rule is allowed into the product
without a measured rate attached to it.

The rules are **pre-registered from the document**, not mined from the data. That matters
more here than in any other analysis in this repo: with enough freedom to define a
"marker", something always comes out significant. The regex for each rule encodes what the
document says and nothing that was learned by looking at the answer.

How each family is judged:

**Statement rules** ask "does this wording mark a statement as false?" and are scored
against a **hypergeometric** null, per question. Under "the marker is unrelated to truth",
the marked statements are a random draw from that question's statements, whose true-count
the answer key has already fixed. Scoring against a flat 50% would instead measure UPSC's
habit of writing more true statements than false ones (the corpus rate is ~59%), and every
rule would look like a discovery.

**Option rules** ask "does this option shape mark an option as the answer?" and reuse A2's
permutation null, which preserves the printing convention rather than assuming 25%.

**One rule is already dead on arrival and stays in the report anyway.** "Chinese Checkers"
— the correct option mirrors wording from its siblings — is A2's H1, measured at p=0.79.
It is cross-referenced rather than re-run, because a reader of this report should not have
to discover that the docx's structural centrepiece was tested elsewhere and failed.

**The verdict to expect is 'not a usable signal'.** The document asserts rates like "~1% to
5% correct" for extreme modifiers. A rule that is right 43% of the time when the document
promises 97% is not a weaker version of the same advice — it is advice that destroys marks,
and saying so with a number is the entire point of this file.
"""

import re
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kasauti_api.db.models import Question, QuestionOption, QuestionProfile
from kasauti_api.domain.intelligence.scope import QuestionScope, question_ids
from kasauti_api.domain.intelligence.statements import (
    StatementRecord,
    decode_question,
)
from kasauti_api.domain.intelligence.statistics import (
    binomial_sf_two_sided,
    hypergeometric_pooled_p,
    stratified_permutation_rate,
    verdict,
)

PERMUTATION_ITERATIONS = 5000

TOKEN_RE = re.compile(r"\w+", re.UNICODE)


@dataclass(frozen=True)
class RuleResult:
    key: str
    title_en: str
    # What the source document claims, quoted so the gap between claim and measurement is
    # in the artifact rather than in a conversation about it.
    docx_claim: str
    family: str  # "statement" | "question" | "option"
    n: int
    hits: int
    rate: float
    baseline: float
    baseline_basis: str
    p_value: float | None
    verdict: str
    note: str | None = None

    @property
    def is_usable(self) -> bool:
        return self.verdict in ("signal", "inverse_signal")


@dataclass(frozen=True)
class EliminationReport:
    scope_note: str
    year_from: int | None
    year_to: int | None
    alpha: float
    statements: int
    claim_statements: int
    claim_true_rate: float
    questions_decoded: int
    coverage: dict[str, int]
    results: list[RuleResult] = field(default_factory=list)


# --- statement rules ------------------------------------------------------------------
# The regexes are deliberately literal readings of the document; a rule that needs a
# cleverer regex than the document describes is a different rule and would not be a test
# of the document.


@dataclass(frozen=True)
class StatementRule:
    key: str
    title_en: str
    docx_claim: str
    # What the document tells the candidate to *do* when the marker fires. Without this a
    # report can say a rule is significant but never whether following it would have
    # earned or cost a mark, which is the only question a learner is asking.
    claims_true: bool
    pattern: re.Pattern


STATEMENT_RULES: list[StatementRule] = [
    StatementRule(
        "extreme_modifier",
        "Statement contains an extreme modifier (only, all, never, any, no, must)",
        "~1% to 5% correct — 'heavily incorrect'",
        pattern=re.compile(
            r"\b(only|all|every|always|never|none|any|entirely|exclusively|solely"
            r"|must|cannot|no)\b",
            re.IGNORECASE,
        ),
        claims_true=False,
    ),
    StatementRule(
        "moderate_modifier",
        "Statement contains a moderate modifier (some, may, generally, one of the)",
        "~95% to 99% correct",
        pattern=re.compile(
            r"\b(some|may|might|can be|could|generally|broadly|often|usually"
            r"|one of the|several)\b",
            re.IGNORECASE,
        ),
        claims_true=True,
    ),
    StatementRule(
        "absolute_negation",
        "Statement asserts an absolute absence ('there is no …')",
        "'almost universally incorrect'",
        pattern=re.compile(
            r"\bthere (is|are|was|were) no\b|\bhas no\b|\bhave no\b|\bnot at all\b"
            r"|\bno (known|such|separate|specific|statutory|constitutional) \w+",
            re.IGNORECASE,
        ),
        claims_true=False,
    ),
    StatementRule(
        "milestone_first",
        "Statement claims a first ('world's first', 'first time')",
        "~90% to 95% correct — the counter-intuitive exception",
        pattern=re.compile(r"\b(first|foremost|maiden)\b", re.IGNORECASE),
        claims_true=True,
    ),
    StatementRule(
        "conjunction_contrast",
        "Statement joins two clauses with but / yet / whereas",
        "'overwhelmingly incorrect' — the error hides in the second clause",
        pattern=re.compile(r"\b(but|yet|whereas|however|although|though)\b", re.IGNORECASE),
        claims_true=False,
    ),
    StatementRule(
        "passive_attribution",
        "Statement attributes something in the passive ('developed by …')",
        "~90%+ incorrect — names and ministries are swapped",
        pattern=re.compile(
            r"\b(developed|launched|introduced|established|set up|manufactured"
            r"|created|designed|implemented|released|constituted|notified)\s+by\b",
            re.IGNORECASE,
        ),
        claims_true=False,
    ),
    StatementRule(
        "hard_number",
        "Statement carries a rigid number (a percentage or a statutory count)",
        "'usually altered and incorrect'",
        pattern=re.compile(
            r"\b\d+(\.\d+)?\s*(%|per cent|percent)\b|\b\d+(st|nd|rd|th)\b"
            r"|\b\d{1,3}(,\d{2,3})+\b",
            re.IGNORECASE,
        ),
        claims_true=False,
    ),
    StatementRule(
        "rounded_target",
        "Statement carries a rounded or tapered target ('nearly', 'net zero by 2070')",
        "'generally correct' — flexible targets are not tampered with",
        pattern=re.compile(
            r"\b(nearly|about|around|approximately|roughly|net zero|more than|over)\b",
            re.IGNORECASE,
        ),
        claims_true=True,
    ),
    StatementRule(
        "dated_statement",
        "Statement names a specific year",
        "milestone years are 'intentionally tampered with'",
        pattern=re.compile(r"\b(1[89]\d{2}|20\d{2})\b"),
        claims_true=False,
    ),
    StatementRule(
        "recency_framing",
        "Statement is framed as recent ('recently', 'in the news')",
        "'almost always correct' — verified current affairs",
        pattern=re.compile(
            r"\b(recently|currently|in the news|at present|as of)\b", re.IGNORECASE
        ),
        claims_true=True,
    ),
    StatementRule(
        "imperative_tone",
        "Statement uses an imposing tone (must adopt, shall replace, mandate)",
        "'almost always incorrect'; enabling language is correct",
        pattern=re.compile(
            r"\b(must|shall|mandate[sd]?|mandatory|compulsor(y|ily)|prohibit(s|ed)?"
            r"|banned|replace[sd]?)\b",
            re.IGNORECASE,
        ),
        claims_true=False,
    ),
]

# Length is the one statement rule with no regex: the docx's "verbosity shield" claim is
# about the longest statement in a question, which is a per-question comparison.
LONGEST_STATEMENT_RULE = (
    "longest_statement",
    "The longest statement in the question",
    "verbosity is a time-drain device, not a truth signal",
)

DICHOTOMY_RULE = (
    "similar_theme_dichotomy",
    "Two statements on the same theme are never both true",
    "'they are never both true' — a 1-correct, 1-incorrect pair by construction",
)

COMPOUND_OPTION_RULE = (
    "compound_nomenclature",
    "Option joins two entities with a hyphen ('Jaipur-Atroli Gharana')",
    "'usually the correct answer'",
)

OUTLIER_OPTION_RULE = (
    "thematic_outlier",
    "The option least like its siblings is the answer",
    "the thematic outlier 'is determinative'",
)

# A pair of statements counts as "same theme" above this Jaccard overlap. The docx
# describes the case in prose ("Statement 1 on arable land vs Statement 2 on irrigated
# land"); wording overlap is the only mechanical stand-in, and it is a weak one — a
# generous threshold is deliberate, so the rule gets its best shot rather than being
# refuted by an unfairly strict definition.
SAME_THEME_OVERLAP = 0.25


def _tokens(text: str) -> set[str]:
    return set(TOKEN_RE.findall(text.lower()))


def _overlap(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def claims_by_question(
    records: list[StatementRecord],
) -> dict[int, list[StatementRecord]]:
    """Decoded statements that a lexical rule can apply to, grouped by question."""
    grouped: dict[int, list[StatementRecord]] = defaultdict(list)
    for record in records:
        if record.is_claim:
            grouped[record.question_id].append(record)
    return grouped


def evaluate_statement_rule(
    rule: StatementRule, records: list[StatementRecord], alpha: float
) -> RuleResult:
    """Rate at which statements carrying the marker are *true*.

    Reported as a true-rate throughout, never flipped to a "how often eliminating works"
    figure, so every row in the report is on one scale and a rule that fires in the
    unexpected direction is visible instead of absorbed.
    """
    by_question = claims_by_question(records)

    hits = marked = 0
    trials: list[tuple[int, int, int]] = []
    for group in by_question.values():
        flagged = [r for r in group if rule.pattern.search(r.text)]
        if not flagged:
            continue
        marked += len(flagged)
        hits += sum(1 for r in flagged if r.is_true)
        first = group[0]
        trials.append((first.statement_count, first.true_count, len(flagged)))

    if marked == 0:
        return RuleResult(rule.key, rule.title_en, rule.docx_claim, "statement", 0, 0,
                          0.0, 0.0, "hypergeometric", None, "underpowered")

    _, baseline, p = hypergeometric_pooled_p(hits, trials)
    rate = hits / marked
    return RuleResult(
        key=rule.key, title_en=rule.title_en, docx_claim=rule.docx_claim,
        family="statement",
        n=marked, hits=hits, rate=rate, baseline=baseline,
        baseline_basis="hypergeometric", p_value=p,
        verdict=verdict(rate, baseline, marked, p, alpha),
        note=f"in {len(trials)} questions",
    )


def evaluate_longest_statement(
    records: list[StatementRecord], alpha: float
) -> RuleResult:
    """Is the longest statement in a question more or less likely to be true?"""
    key, title, claim = LONGEST_STATEMENT_RULE
    by_question = claims_by_question(records)

    hits = marked = 0
    trials: list[tuple[int, int, int]] = []
    for group in by_question.values():
        if len(group) < 2:
            continue
        lengths = sorted((len(r.text) for r in group), reverse=True)
        if lengths[0] == lengths[1]:
            continue  # a tie is the absence of a signal, as everywhere else here
        longest = max(group, key=lambda r: len(r.text))
        marked += 1
        hits += 1 if longest.is_true else 0
        trials.append((group[0].statement_count, group[0].true_count, 1))

    if marked == 0:
        return RuleResult(key, title, claim, "statement", 0, 0, 0.0, 0.0,
                          "hypergeometric", None, "underpowered")
    _, baseline, p = hypergeometric_pooled_p(hits, trials)
    rate = hits / marked
    return RuleResult(
        key=key, title_en=title, docx_claim=claim, family="statement",
        n=marked, hits=hits, rate=rate, baseline=baseline,
        baseline_basis="hypergeometric", p_value=p,
        verdict=verdict(rate, baseline, marked, p, alpha),
        note="ties excluded",
    )


def evaluate_dichotomy(records: list[StatementRecord], alpha: float) -> RuleResult:
    """In a two-statement question whose statements share wording, is exactly one true?

    The baseline is the same quantity measured over *every* two-statement question, so
    what is tested is the docx's actual claim — that shared theme is what forces the
    split — rather than the unremarkable fact that split answers are common.
    """
    key, title, claim = DICHOTOMY_RULE
    by_question = claims_by_question(records)
    pairs = [g for g in by_question.values() if len(g) == 2]
    if not pairs:
        return RuleResult(key, title, claim, "question", 0, 0, 0.0, 0.0,
                          "all-two-statement-questions", None, "underpowered")

    def exactly_one(group: list[StatementRecord]) -> bool:
        return sum(1 for r in group if r.is_true) == 1

    baseline = sum(1 for g in pairs if exactly_one(g)) / len(pairs)
    same_theme = [g for g in pairs if _overlap(g[0].text, g[1].text) >= SAME_THEME_OVERLAP]
    n = len(same_theme)
    if n == 0:
        return RuleResult(key, title, claim, "question", 0, 0, 0.0, baseline,
                          "all-two-statement-questions", None, "underpowered")
    hits = sum(1 for g in same_theme if exactly_one(g))
    p = binomial_sf_two_sided(hits, n, baseline) if 0 < baseline < 1 else None
    rate = hits / n
    return RuleResult(
        key=key, title_en=title, docx_claim=claim, family="question",
        n=n, hits=hits, rate=rate, baseline=baseline,
        baseline_basis="all-two-statement-questions", p_value=p,
        verdict=verdict(rate, baseline, n, p, alpha),
        note=(
            f"{len(pairs)} two-statement questions, "
            f"{n} of them sharing wording at Jaccard >= {SAME_THEME_OVERLAP}"
        ),
    )


# --- option rules ---------------------------------------------------------------------

# "Jaipur-Atroli Gharana", "HCL-Foxconn" — two capitalised names joined. A plain hyphen
# would match "well-being" and every other ordinary compound word.
COMPOUND_RE = re.compile(r"[A-Z][\w']+\s*[-–]\s*[A-Z][\w']+")


@dataclass
class _OptionRow:
    question_id: int
    year: int
    archetype: str
    correct_label: str
    texts: dict[str, str]


async def load_option_rows(
    session: AsyncSession, scope: QuestionScope
) -> list[_OptionRow]:
    """Keyed questions whose options name real things.

    Restricted to `entity_choice`: the docx's option rules are about the *content* of an
    option ("a hyphenated name", "the odd one out"), and "1 only / 2 only / Both / Neither"
    has no content to be odd about. Running them over the subset family would measure the
    printing convention, which is the mistake A2 exists to avoid.
    """
    meta = (
        await session.execute(
            select(
                Question.id,
                Question.year,
                QuestionProfile.option_archetype,
                QuestionProfile.correct_label,
            )
            .join(QuestionProfile, QuestionProfile.question_id == Question.id)
            .where(
                Question.id.in_(question_ids(scope)),
                QuestionProfile.correct_label.is_not(None),
            )
            .order_by(Question.year, Question.id)
        )
    ).all()
    wanted = {
        qid: (year, archetype.value if archetype else "unknown", label)
        for qid, year, archetype, label in meta
        if archetype is not None and archetype.value == "entity_choice"
    }
    if not wanted:
        return []

    options = (
        await session.execute(
            select(QuestionOption).where(QuestionOption.question_id.in_(wanted))
        )
    ).scalars().all()
    by_question: dict[int, list[QuestionOption]] = defaultdict(list)
    for option in options:
        by_question[option.question_id].append(option)

    rows = []
    for qid, (year, archetype, label) in wanted.items():
        texts = {
            o.option_label: (o.option_text_en or "").strip()
            for o in by_question.get(qid, [])
        }
        # English only, and only where every option has it: a rule about English wording
        # cannot be scored on a question half of whose options are missing that language.
        if len(texts) < 3 or not all(texts.values()) or label not in texts:
            continue
        rows.append(_OptionRow(qid, year, archetype, label, texts))
    return rows


def _permutation_baseline(pairs: list[tuple[str, str]]) -> float:
    return stratified_permutation_rate(
        {"entity_choice": pairs}, iterations=PERMUTATION_ITERATIONS
    )


def evaluate_compound_option(rows: list[_OptionRow], alpha: float) -> RuleResult:
    key, title, claim = COMPOUND_OPTION_RULE
    pairs, hits = [], 0
    for row in rows:
        flagged = [lab for lab, text in row.texts.items() if COMPOUND_RE.search(text)]
        # Exactly one flagged option, or the rule gives the candidate no instruction.
        if len(flagged) != 1:
            continue
        pairs.append((flagged[0], row.correct_label))
        hits += 1 if flagged[0] == row.correct_label else 0
    n = len(pairs)
    if n == 0:
        return RuleResult(key, title, claim, "option", 0, 0, 0.0, 0.0,
                          "permutation", None, "underpowered")
    baseline = _permutation_baseline(pairs)
    p = binomial_sf_two_sided(hits, n, baseline) if baseline > 0 else None
    rate = hits / n
    return RuleResult(
        key=key, title_en=title, docx_claim=claim, family="option",
        n=n, hits=hits, rate=rate, baseline=baseline, baseline_basis="permutation",
        p_value=p, verdict=verdict(rate, baseline, n, p, alpha),
        note="questions printing exactly one hyphenated-name option",
    )


def evaluate_thematic_outlier(rows: list[_OptionRow], alpha: float) -> RuleResult:
    """The option with the least wording in common with its siblings.

    The inverse of A2's H1, which asked whether the correct option *echoes* a sibling and
    came back at p=0.79. Both directions are in the document, and a null result on one
    does not settle the other.
    """
    key, title, claim = OUTLIER_OPTION_RULE
    pairs, hits = [], 0
    for row in rows:
        scores = {
            label: sum(_overlap(text, other) for lab2, other in row.texts.items()
                       if lab2 != label) / (len(row.texts) - 1)
            for label, text in row.texts.items()
        }
        ordered = sorted(scores.values())
        if ordered[0] == ordered[1]:
            continue  # tie: no instruction
        outlier = min(scores, key=lambda label: scores[label])
        pairs.append((outlier, row.correct_label))
        hits += 1 if outlier == row.correct_label else 0
    n = len(pairs)
    if n == 0:
        return RuleResult(key, title, claim, "option", 0, 0, 0.0, 0.0,
                          "permutation", None, "underpowered")
    baseline = _permutation_baseline(pairs)
    p = binomial_sf_two_sided(hits, n, baseline) if baseline > 0 else None
    rate = hits / n
    return RuleResult(
        key=key, title_en=title, docx_claim=claim, family="option",
        n=n, hits=hits, rate=rate, baseline=baseline, baseline_basis="permutation",
        p_value=p, verdict=verdict(rate, baseline, n, p, alpha),
        note="ties excluded",
    )


# 11 statement rules + longest-statement + dichotomy + two option rules.
RULE_COUNT = len(STATEMENT_RULES) + 4
FAMILYWISE_ALPHA = 0.05 / RULE_COUNT


async def load_statement_records(
    session: AsyncSession, scope: QuestionScope
) -> tuple[list[StatementRecord], dict[str, int], int]:
    """Decode every question in scope. Returns (records, coverage, questions decoded)."""
    questions = (
        await session.execute(
            select(Question.id, Question.year, Question.question_number,
                   Question.question_text_en)
            .where(Question.id.in_(question_ids(scope)))
            .order_by(Question.year, Question.id)
        )
    ).all()
    if not questions:
        return [], {}, 0

    ids = [q[0] for q in questions]
    options = (
        await session.execute(
            select(QuestionOption).where(QuestionOption.question_id.in_(ids))
        )
    ).scalars().all()
    by_question: dict[int, list[QuestionOption]] = defaultdict(list)
    for option in options:
        by_question[option.question_id].append(option)

    records: list[StatementRecord] = []
    coverage: dict[str, int] = defaultdict(int)
    decoded = 0
    for qid, year, number, stem in questions:
        result = decode_question(
            question_id=qid, year=year, question_number=number, stem_en=stem,
            options=[
                (o.option_label, o.option_text_en, o.is_correct)
                for o in sorted(by_question.get(qid, []), key=lambda o: o.option_label)
            ],
        )
        if result.records:
            decoded += 1
            coverage[f"decoded ({result.records[0].source})"] += 1
            records.extend(result.records)
        else:
            coverage[result.skipped or "unknown"] += 1
    return records, dict(sorted(coverage.items(), key=lambda kv: -kv[1])), decoded


async def elimination_report(
    session: AsyncSession, scope: QuestionScope | None = None
) -> EliminationReport:
    scope = scope or QuestionScope()
    records, coverage, decoded = await load_statement_records(session, scope)
    option_rows = await load_option_rows(session, scope)

    claims = [r for r in records if r.is_claim]
    years = [r.year for r in records] or [row.year for row in option_rows]
    results = [
        evaluate_statement_rule(rule, records, FAMILYWISE_ALPHA)
        for rule in STATEMENT_RULES
    ]
    results.append(evaluate_longest_statement(records, FAMILYWISE_ALPHA))
    results.append(evaluate_dichotomy(records, FAMILYWISE_ALPHA))
    results.append(evaluate_compound_option(option_rows, FAMILYWISE_ALPHA))
    results.append(evaluate_thematic_outlier(option_rows, FAMILYWISE_ALPHA))

    return EliminationReport(
        scope_note=scope.describe(),
        year_from=min(years) if years else None,
        year_to=max(years) if years else None,
        alpha=FAMILYWISE_ALPHA,
        statements=len(records),
        claim_statements=len(claims),
        claim_true_rate=(sum(1 for r in claims if r.is_true) / len(claims))
        if claims
        else 0.0,
        questions_decoded=decoded,
        coverage=coverage,
        results=results,
    )


VERDICT_LABELS = {
    "signal": "USABLE SIGNAL",
    "inverse_signal": "USABLE INVERSE SIGNAL",
    "noise": "not a usable signal",
    "underpowered": "too few to conclude anything",
}


def render_markdown(reports: list[tuple[str, EliminationReport]]) -> str:
    """One section per era, all-time first: the statement-level evidence is thinnest in
    the recent era (the subset family fell from 56% of questions to 45%), so leading with
    2022+ would report 'underpowered' for most of the document and answer nothing. The
    recent section follows, and a rule whose direction reverses there is a rule the
    product must not ship."""
    lines = [
        "# Prelims Elimination-Technique Verification",
        "",
        "Fifteen elimination rules, taken from the coaching-circuit elimination-rule list, tested",
        "against every Prelims Paper 1 question with an official answer key. No model is",
        "involved: in the 'Consider the following statements' family the correct option",
        "*enumerates which statements are true*, so the key is a per-statement truth label.",
        "",
        "Read these before the table:",
        "",
        "- **The baseline is not 50%.** UPSC writes more true statements than false ones,",
        "  and each question's true-count is fixed by its key. Every statement rule is",
        "  scored against a hypergeometric null built per question, so a marker that fires",
        "  on nothing in particular lands on the baseline instead of looking like a find.",
        f"- **{RULE_COUNT} rules means a Bonferroni threshold of alpha = "
        f"{FAMILYWISE_ALPHA:.4f}.** At a nominal 0.05, testing {RULE_COUNT} rules",
        "  produces a 'pattern' every run by construction.",
        "- **The rate reported is the rate at which the marked statement is TRUE.** A rule",
        "  that works for elimination shows a rate *below* its baseline — that is the",
        "  'usable inverse signal' verdict, and it is the good one.",
        "- **'Not a usable signal' is a finding.** The document's own confidence figures",
        "  are quoted in the table so the gap is visible rather than argued about.",
        "",
        "Not tested, because nothing in the corpus can decide them: the examiner-psychology",
        "claims ('fear of the unknown'), the cognitive-overload claims, and the bilingual",
        "etymology decoding. They are opinions about intent, not measurable properties of a",
        "printed paper. The 'Chinese Checkers' keyword-mirroring rule is measured in the",
        "option-pattern report instead, where it came back at p = 0.79.",
        "",
    ]

    for era_name, report in reports:
        lines += [
            f"## {era_name}",
            "",
            f"*{report.questions_decoded} questions decoded · {report.statements} statements"
            f" ({report.claim_statements} of them claims) · {report.year_from}–{report.year_to}"
            f" · scope: {report.scope_note}*",
            "",
            f"Base rate: **{report.claim_true_rate:.1%}** of decoded claim statements are true.",
            "",
            f"**Usable rules in this era: {sum(1 for r in report.results if r.is_usable)}"
            f" of {len(report.results)}.**",
            "",
            "| Rule | family | n | true rate | baseline | p | verdict | the document claims |",
            "|---|---|---:|---:|---:|---:|---|---|",
        ]
        for result in report.results:
            p_text = "—" if result.p_value is None else f"{result.p_value:.4f}"
            lines.append(
                f"| {result.title_en} | {result.family} | {result.n} | {result.rate:.1%} |"
                f" {result.baseline:.1%} | {p_text} | {VERDICT_LABELS[result.verdict]} |"
                f" {result.docx_claim} |"
            )
        lines.append("")
        notes = [r for r in report.results if r.note]
        if notes:
            lines += [f"- *{r.title_en}*: {r.note}" for r in notes]
            lines.append("")
        if report.coverage:
            lines += ["What decoded, and what did not:", ""]
            lines += [f"- {name}: {count}" for name, count in report.coverage.items()]
            lines.append("")

    return "\n".join(lines)
