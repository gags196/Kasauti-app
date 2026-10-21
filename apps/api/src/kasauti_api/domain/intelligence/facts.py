"""Deterministic per-question facts: what shape the question is, how its options are built.

Pure functions over text — no ORM types, no database, no LLM — so the regexes, which are
the risky part, are testable without Postgres. `scripts/derive_question_facts.py` is the
only writer; bump `DERIVED_REV` whenever a rule below changes and re-run it with
`--rebuild`.

Two rules here are worth knowing before reading the code:

**The count form wins over everything it overlaps.** "In how many of the above rows is the
information correctly matched?" is both a pairs question and a count question; 22 such
questions overlap with the pairs markers and 28 with the statement markers. It is
classified `how_many_correct` because that is what changes the candidate's task —
eliminating one row earns nothing, where in a subset question it halves the field. The
count form did not exist in Prelims before 2022 and is the clearest single marker of the
pattern change.

**A tie is the absence of a signal, not a weak one.** When two options share the longest
length, `correct_is_longest` is None rather than False. Recording False there would invent
a finding, and the "correct option is longest" statistic is already fragile enough — see
`option_patterns` on why its baseline cannot be 25%.
"""

import re
from dataclasses import dataclass
from typing import NamedTuple

from kasauti_api.db.models.profiles import OptionArchetype, QuestionFormat

# Bump on any rule change below, then re-run derive_question_facts.py.
# 2: statement numbering accepts Roman numerals (2025 prints them exclusively).
# 3: *option* subset markers accept them too. Rev 2 fixed the stem side and left the
#    option side digit-only, so all 42 of 2025's "I and II only" questions were archetyped
#    `entity_choice` — the archetype that means "the options name real things". It cost
#    the A2 baseline its stratification for a whole year and hid 2025 entirely from the
#    statement decoder. Half a fix reads exactly like no bug at all.
DERIVED_REV = 3

# --- stem markers ---------------------------------------------------------------------
# "how many of the above/given above" — Hindi prints "उपर्युक्त में से कितने".
HOW_MANY_RE = re.compile(r"how many of the|कितने", re.IGNORECASE)
# `statement\s*-\s*i` deliberately, never `statement i\b` — the latter matches
# "statement is" and inflated this count from 14 to 31 when first tried.
STATEMENT_PAIR_RE = re.compile(
    r"statement\s*[-–—]\s*(i{1,3})\b|statement\s+(i{1,3})\s*:|\bassertion\b",
    re.IGNORECASE,
)
MATCH_LIST_RE = re.compile(r"match\s+list|सूची", re.IGNORECASE)
PAIRS_RE = re.compile(r"following pairs|correctly matched|युग्म", re.IGNORECASE)
CHRONO_RE = re.compile(
    r"chronological|correct sequence|correct order|कालानुक्रम", re.IGNORECASE
)
# UPSC numbers its statements "1. 2. 3." in every year except **2025**, which used Roman
# numerals throughout (59 questions, zero Arabic) before 2026 reverted to a mix (72 Arabic,
# 5 Roman). Matching digits only made every 2025 statement question invisible to the format
# taxonomy — inside the era the product leads with. House style drifts per year here; the
# ingestion runbook says the same about page layout.
NUMBERED_ITEM_RE = re.compile(r"^\s*(\d+|[IVX]{1,4})\s*[.)]\s", re.MULTILINE)
QUOTED_START_RE = re.compile(r"^\s*([\"“”'‘’])(.*?)([\"“”'‘’])", re.DOTALL)
# A passage item quotes a *paragraph* and then asks about it. Far more questions merely
# open with a quoted term — 'SWAYAM', "Biorock technology", 'Triclosan' — and those are
# ordinary single-fact items. Length is what separates them: without this floor the
# passage count came out at 46 when the corpus holds a handful.
PASSAGE_MIN_QUOTED_CHARS = 80
SINGLE_CHOICE_RE = re.compile(r"which (one )?of the following|निम्नलिखित", re.IGNORECASE)

# --- option markers -------------------------------------------------------------------
ALL_OF_ABOVE_RE = re.compile(
    r"all of the above|both\b|उपर्युक्त सभी|दोनों", re.IGNORECASE
)
NONE_OF_ABOVE_RE = re.compile(
    r"none of the above|neither\b|^\s*none\s*$|उपर्युक्त में से कोई|कोई (भी )?नहीं",
    re.IGNORECASE | re.MULTILINE,
)
YEAR_RE = re.compile(r"\b(1[89]\d{2}|20\d{2})\b")

# "Only one" / "Only two" / "All three" / "All four" / "None" — the answer set of the
# count format, and the surest confirmation of it.
COUNT_WORD_RE = re.compile(
    r"^\s*(only\s+)?(one|two|three|four|five|six)\s*$"
    # "All the four" is 2025's wording; "All four" is everyone else's.
    r"|^\s*all\s+(the\s+)?(two|three|four|five|six)\s*$"
    r"|^\s*none\s*$"
    r"|^\s*केवल\s+(एक|दो|तीन|चार)\s*$|^\s*सभी\s+(तीन|चार)\s*$|^\s*कोई\s+नहीं\s*$",
    re.IGNORECASE,
)
# "1 only", "2 and 3", "Both 1 and 2", "Neither 1 nor 2", "1, 3 and 4 only" — and the
# same forms in Roman numerals, which is how 2025 prints all 42 of its subset questions
# ("I and II only"). The item token is spelled once here and reused by the statement
# decoder, so the two can never drift apart on what counts as an item reference.
ITEM_TOKEN = r"(?:\d+|[IVX]{1,4})"
SUBSET_RE = re.compile(
    rf"^\s*(both\s+|neither\s+)?{ITEM_TOKEN}"
    rf"(\s*(,|and|&|nor|तथा|और)\s*{ITEM_TOKEN})*"
    r"(\s+(only|अकेले|केवल))?\s*$",
    re.IGNORECASE,
)
# "1-2-3-4" / "2, 4, 1, 3" — a permutation, i.e. an ordering answer
ORDERING_RE = re.compile(r"^\s*\d+(\s*[-–,]\s*\d+){2,}\s*$")
NUMERIC_RE = re.compile(r"^\s*[₹$]?\s*[\d.,]+\s*(%|per cent|crore|lakh|km|kg|m|years?)?\s*$",
                        re.IGNORECASE)


class OptionInput(NamedTuple):
    label: str
    text_en: str | None
    text_hi: str | None
    is_correct: bool | None


@dataclass(frozen=True)
class StemFacts:
    statement_count: int | None
    stem_chars_en: int | None
    # Never compared against stem_chars_en: Devanagari tokenizes far denser, so the two
    # are not on one scale and must not share an axis or be averaged.
    stem_chars_hi: int | None
    has_table: bool


@dataclass(frozen=True)
class OptionFacts:
    option_count: int
    archetype: OptionArchetype | None
    has_all_of_above: bool
    has_none_of_above: bool
    correct_label: str | None
    correct_is_longest: bool | None
    longest_margin: float | None
    dated_option_count: int
    dated_correct: bool | None


def option_language(options: list[OptionInput]) -> str:
    """Pick one language for the whole question and stick to it.

    Falling back per option — English if present, else Hindi — is what made the inherited
    H1 overlap statistic compare Devanagari tokens against Latin ones and score a
    guaranteed zero. One language per question, or the numbers are meaningless.
    """
    return "en" if all((o.text_en or "").strip() for o in options) else "hi"


def _text(option: OptionInput, lang: str) -> str:
    return ((option.text_en if lang == "en" else option.text_hi) or "").strip()


def stem_facts(
    *, text_en: str | None, text_hi: str | None, tables: list | None
) -> StemFacts:
    text = text_en or text_hi or ""
    # Distinct tokens, so a stem repeating "1." in a quoted passage counts it once.
    numbered = {m.upper() for m in NUMBERED_ITEM_RE.findall(text)}
    if numbered:
        count = len(numbered)
    elif STATEMENT_PAIR_RE.search(text):
        # Statement-I / Statement-II items print no numbered list.
        count = len({m.lower() for pair in STATEMENT_PAIR_RE.findall(text) for m in pair if m})
        count = count or None
    else:
        count = None
    return StemFacts(
        statement_count=count,
        stem_chars_en=len(text_en) if text_en else None,
        stem_chars_hi=len(text_hi) if text_hi else None,
        has_table=bool(tables),
    )


def option_facts(options: list[OptionInput], *, lang: str | None = None) -> OptionFacts:
    if not options:
        return OptionFacts(0, None, False, False, None, None, None, 0, None)

    lang = lang or option_language(options)
    texts = {o.label: _text(o, lang) for o in options}
    joined = "\n".join(texts.values())

    correct = [o for o in options if o.is_correct]
    correct_label = correct[0].label if len(correct) == 1 else None

    lengths = sorted((len(t) for t in texts.values()), reverse=True)
    if correct_label is None or len(lengths) < 2 or lengths[1] == 0:
        is_longest, margin = None, None
    elif lengths[0] == lengths[1]:
        # A tie is not a weak signal — it is no signal. Never record False here.
        is_longest, margin = None, None
    else:
        is_longest = len(texts[correct_label]) == lengths[0]
        margin = (lengths[0] - lengths[1]) / lengths[1]

    dated = [o for o in options if YEAR_RE.search(texts[o.label])]
    dated_correct = None
    if dated and correct_label is not None:
        dated_correct = any(o.label == correct_label for o in dated)

    return OptionFacts(
        option_count=len(options),
        archetype=_archetype(list(texts.values())),
        has_all_of_above=bool(ALL_OF_ABOVE_RE.search(joined)),
        has_none_of_above=bool(NONE_OF_ABOVE_RE.search(joined)),
        correct_label=correct_label,
        correct_is_longest=is_longest,
        longest_margin=margin,
        dated_option_count=len(dated),
        dated_correct=dated_correct,
    )


def _archetype(texts: list[str]) -> OptionArchetype | None:
    """Classify the option set by shape. Majority rules, because a set is often three
    of a kind plus a catch-all ("1 only / 2 only / Both / None of the above")."""
    if not texts:
        return None

    def share(pattern: re.Pattern) -> float:
        return sum(1 for t in texts if pattern.match(t)) / len(texts)

    if share(COUNT_WORD_RE) >= 0.75:
        return OptionArchetype.count_of_correct
    if share(ORDERING_RE) >= 0.75:
        return OptionArchetype.ordering
    if share(SUBSET_RE) >= 0.5:
        return OptionArchetype.subset_of_numbered
    if share(NUMERIC_RE) >= 0.75:
        return OptionArchetype.numeric
    if all(t for t in texts):
        return OptionArchetype.entity_choice
    return OptionArchetype.other


def is_passage(text: str) -> bool:
    """True when the stem opens with a quotation long enough to be a passage.

    A quoted *term* at the start is common and means nothing; a quoted paragraph is the
    passage format (2015 Q80's climate-regime description is the corpus's first).
    """
    match = QUOTED_START_RE.match(text)
    return bool(match) and len(match.group(2)) >= PASSAGE_MIN_QUOTED_CHARS


def detect_format(
    text: str | None, stem: StemFacts, options: OptionFacts
) -> QuestionFormat | None:
    """Best-effort format from the printed text alone.

    This is a cross-check on the model's classification, not a replacement for it: 652 of
    the 1,400 questions match none of the obvious markers, so a regex-only taxonomy would
    misclassify roughly half the corpus. Where it does fire it is reliable, and a
    disagreement with the model's `format` is worth a human look.
    """
    if not text:
        return None

    # First, because it overlaps everything and changes the candidate's task.
    if HOW_MANY_RE.search(text) or options.archetype is OptionArchetype.count_of_correct:
        return QuestionFormat.how_many_correct
    if STATEMENT_PAIR_RE.search(text):
        return QuestionFormat.assertion_reason
    if MATCH_LIST_RE.search(text):
        return QuestionFormat.match_the_following
    if PAIRS_RE.search(text):
        return QuestionFormat.pairs_matched
    if CHRONO_RE.search(text) or options.archetype is OptionArchetype.ordering:
        return QuestionFormat.chronological_order
    if is_passage(text):
        return QuestionFormat.passage_based
    if (stem.statement_count or 0) >= 2:
        return QuestionFormat.statement_evaluation
    if SINGLE_CHOICE_RE.search(text):
        return QuestionFormat.single_fact
    return None
