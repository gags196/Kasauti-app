"""Statement-level ground truth, decoded from the answer key alone.

Every elimination technique a coaching video teaches is a claim about a *statement*
("statements containing 'only' are almost never correct"), while everything the corpus
records is about an *option*. This module is the bridge, and it needs no model:

    Consider the following statements:          correct option = "1 only"
    1. <statement A>                     =>     statement 1 is TRUE
    2. <statement B>                            statement 2 is FALSE

In the `subset_of_numbered` family the correct option *enumerates exactly which numbered
statements are true*, so an official answer key is a per-statement truth label. That is
the only reason the docx's lexical rules can be tested at all, and it is why the
`elimination` report can exist without a labelling pass.

Three limits are structural, not fixable by better regexes, and every consumer must
report them rather than average over them:

**Only two option families decode.** `subset_of_numbered` gives a full assignment.
`count_of_correct` ("How many of the above are correct?") gives a count, which pins the
assignment only at the extremes — "None" makes every statement false, "All three" makes
every one true. A key of "Only two" out of three is genuinely undecidable and is dropped,
not guessed. `entity_choice` yields nothing at all.

**Negative-polarity questions are excluded, not inverted.** "Which of the above is/are
*not* correctly matched" inverts the mapping cleanly in principle, but a missed negation
does not lose a statement — it records the statement backwards, which is worse than
silence. Detection runs only over the question's interrogative lines, never over the
statement bodies, because statements say "is not available to" and "is not mandatory" all
the time without making the *question* negative.

**English only.** The rules being tested are lexical claims about English wording, so the
Hindi twin is not a second sample of the same statement — it is the same statement in a
language whose modifiers do not map one-to-one. Decoding Hindi to double the n would
double-count every question.
"""

import re
from dataclasses import dataclass

from kasauti_api.domain.intelligence.facts import ITEM_TOKEN

# A statement shorter than this is a list entry, not a claim: "Italy", "Japan",
# "Hedge Funds". They carry a truth label perfectly well (that country *is* one of the
# ageing ones) but no lexical rule about modifiers or attribution can apply to them, so
# rules run over claims and the rest are counted and set aside.
MIN_CLAIM_WORDS = 4

ROMAN_VALUES = {"I": 1, "V": 5, "X": 10}

# "1. body" / "IV) body", body running until the next marker or the end of the stem.
ITEM_RE = re.compile(
    rf"^[ \t]*({ITEM_TOKEN})[.)]\s+(.*?)(?=^[ \t]*{ITEM_TOKEN}[.)]\s|\Z)",
    re.MULTILINE | re.DOTALL,
)

# Lines that belong to the question rather than to the statement they trail. Without
# this the last statement absorbs "Select the correct answer using the code given below"
# and every length- or wording-based rule measures the boilerplate.
LEAD_OUT_RE = re.compile(
    r"^\s*("
    r"select\b|which\b|how many\b|in how many\b|choose\b|consider\b|"
    r"what\b|the correct answer\b|codes?\s*:|with reference to\b|identify\b"
    r")",
    re.IGNORECASE,
)

# Searched over the interrogative lines only — see the module docstring.
NEGATIVE_POLARITY_RE = re.compile(
    r"\bnot\b|\bincorrect(ly)?\b|\bexcept\b|\bfalse\b", re.IGNORECASE
)

NEITHER_RE = re.compile(r"\b(neither|none)\b", re.IGNORECASE)
COUNT_WORDS = {
    "none": 0, "zero": 0,
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
}
COUNT_OPTION_RE = re.compile(
    r"^\s*(?:only\s+|all\s+(?:the\s+)?)?(none|zero|one|two|three|four|five|six)\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class StatementRecord:
    """One numbered statement whose truth is known from the official key."""

    question_id: int
    year: int
    question_number: str
    index: int
    text: str
    is_true: bool
    is_claim: bool
    # Decidable statements in this question, and how many of them are true. Both are the
    # null model's parameters: under "the rule marks statements at random", hits follow a
    # hypergeometric draw of `marked` from `statement_count` containing `true_count`.
    statement_count: int
    true_count: int
    source: str  # "subset" | "count_extreme"


@dataclass(frozen=True)
class DecodeResult:
    records: tuple[StatementRecord, ...]
    # Why a question yielded nothing. Reported as a coverage table, never swallowed —
    # a decoder that silently drops a third of the corpus is indistinguishable from one
    # that works.
    skipped: str | None = None


def roman_to_int(token: str) -> int | None:
    """I, II, III, IV, V … up to X. Returns None for anything that is not one."""
    token = token.upper()
    if not token or any(c not in ROMAN_VALUES for c in token):
        return None
    total, previous = 0, 0
    for char in reversed(token):
        value = ROMAN_VALUES[char]
        total += -value if value < previous else value
        previous = max(previous, value)
    return total or None


def item_number(token: str) -> int | None:
    return int(token) if token.isdigit() else roman_to_int(token)


def split_stem(text: str) -> tuple[dict[int, str], str]:
    """Numbered statements, and the question's own interrogative text.

    The interrogative text is everything that is not a statement body: the lead-in
    ("Consider the following statements:") plus any trailing question or code line
    stripped off the last item.
    """
    items: dict[int, str] = {}
    trailing: list[str] = []
    first_match_start = len(text)

    for match in ITEM_RE.finditer(text):
        number = item_number(match.group(1))
        if number is None:
            continue
        first_match_start = min(first_match_start, match.start())
        body_lines, tail_lines = [], []
        for line in match.group(2).splitlines():
            if tail_lines or LEAD_OUT_RE.match(line):
                tail_lines.append(line)
            else:
                body_lines.append(line)
        body = " ".join(line.strip() for line in body_lines).strip()
        # A repeated number ("1." appearing inside a quoted passage) keeps the first.
        if body and number not in items:
            items[number] = body
        trailing.extend(tail_lines)

    lead_in = text[:first_match_start]
    return items, "\n".join([lead_in, *trailing])


def parse_subset_option(text: str | None) -> frozenset[int] | None:
    """"1 only" -> {1}; "Both I and II" -> {1, 2}; "Neither 1 nor 2" -> {}.

    Returns None when the option is not a reference to numbered items at all, which is
    how an `entity_choice` question is refused rather than mangled into a truth claim.
    """
    if not text:
        return None
    stripped = text.strip()
    if not stripped:
        return None
    if NEITHER_RE.search(stripped):
        return frozenset()
    tokens = re.findall(rf"\b{ITEM_TOKEN}\b", stripped)
    numbers = {n for n in (item_number(t) for t in tokens) if n is not None}
    if not numbers:
        return None
    # "1 only and nothing else" is fine; a sentence that merely mentions a number is not.
    residue = re.sub(rf"\b{ITEM_TOKEN}\b", "", stripped, flags=re.IGNORECASE)
    residue = re.sub(r"[,&]|\b(and|only|both|nor|or)\b", "", residue, flags=re.IGNORECASE)
    if residue.strip():
        return None
    return frozenset(numbers)


def parse_count_option(text: str | None) -> int | None:
    """"Only two" -> 2; "All the four" -> 4; "None" -> 0."""
    if not text:
        return None
    match = COUNT_OPTION_RE.match(text.strip())
    return COUNT_WORDS[match.group(1).lower()] if match else None


def is_negative_polarity(interrogative: str) -> bool:
    return bool(NEGATIVE_POLARITY_RE.search(interrogative))


def decode_question(
    *,
    question_id: int,
    year: int,
    question_number: str,
    stem_en: str | None,
    options: list[tuple[str, str | None, bool | None]],
) -> DecodeResult:
    """Statement truth labels for one question, or the reason there are none.

    `options` is (label, english text, is_correct). Exactly one option must be marked
    correct: a dropped question carries `is_correct` NULL throughout and says nothing
    about any statement.
    """
    if not stem_en:
        return DecodeResult((), "no English stem")

    items, interrogative = split_stem(stem_en)
    if len(items) < 2:
        return DecodeResult((), "no numbered statements")

    correct = [label for label, _, is_correct in options if is_correct]
    if len(correct) != 1:
        return DecodeResult((), "unkeyed or dropped")
    correct_label = correct[0]
    texts = {label: text for label, text, _ in options}

    if is_negative_polarity(interrogative):
        return DecodeResult((), "negative polarity")

    subsets = {label: parse_subset_option(text) for label, text in texts.items()}
    if all(value is not None for value in subsets.values()) and subsets:
        universe = frozenset().union(*subsets.values())
        if not universe:
            return DecodeResult((), "options reference no statement")
        if not universe <= set(items):
            return DecodeResult((), "options reference a statement that is not printed")
        true_set = subsets[correct_label]
        assert true_set is not None
        decidable = sorted(universe)
        return DecodeResult(
            _records(
                question_id, year, question_number, items,
                {n: n in true_set for n in decidable}, "subset",
            )
        )

    counts = {label: parse_count_option(text) for label, text in texts.items()}
    if all(value is not None for value in counts.values()) and counts:
        true_count = counts[correct_label]
        assert true_count is not None
        if true_count == 0:
            truth = dict.fromkeys(items, False)
        elif true_count == len(items):
            truth = dict.fromkeys(items, True)
        else:
            # "Only two of three" pins how many, never which. Guessing here would invent
            # exactly the labels the whole report is meant to measure.
            return DecodeResult((), "count question, partial information")
        return DecodeResult(
            _records(question_id, year, question_number, items, truth, "count_extreme")
        )

    return DecodeResult((), "options are not statement references")


def _records(
    question_id: int,
    year: int,
    question_number: str,
    items: dict[int, str],
    truth: dict[int, bool],
    source: str,
) -> tuple[StatementRecord, ...]:
    """Build records, counting `statement_count`/`true_count` over *claims* only.

    The null model is per question, so its parameters have to describe the same
    population the rules are evaluated over. Counting a one-word list entry in the
    denominator while no rule can ever mark it would bias every baseline downward.
    """
    claims = {n: t for n, t in truth.items() if _is_claim(items[n])}
    claim_total = len(claims)
    claim_true = sum(claims.values())
    return tuple(
        StatementRecord(
            question_id=question_id,
            year=year,
            question_number=question_number,
            index=n,
            text=items[n],
            is_true=is_true,
            is_claim=n in claims,
            statement_count=claim_total,
            true_count=claim_true,
            source=source,
        )
        for n, is_true in sorted(truth.items())
    )


def _is_claim(text: str) -> bool:
    return len(text.split()) >= MIN_CLAIM_WORDS
