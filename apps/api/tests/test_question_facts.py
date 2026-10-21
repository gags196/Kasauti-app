"""Deterministic question facts — pure functions, no database, no fixtures.

The regexes are the risky part of the whole intelligence layer: they decide what a
question "is" for every downstream statistic. Stems below are pasted verbatim from the
real corpus rather than invented, so a rule change that breaks a real paper fails here.
"""

from kasauti_api.db.models.profiles import OptionArchetype, QuestionFormat
from kasauti_api.domain.intelligence.facts import (
    OptionInput,
    detect_format,
    is_passage,
    option_facts,
    option_language,
    stem_facts,
)


def _opts(*texts: str, correct: str | None = None) -> list[OptionInput]:
    labels = "ABCD"
    return [
        OptionInput(labels[i], t, None, (labels[i] == correct) if correct else None)
        for i, t in enumerate(texts)
    ]


def _format(text: str, options: list[OptionInput] | None = None) -> QuestionFormat | None:
    options = options if options is not None else _opts("Alpha", "Beta", "Gamma", "Delta")
    stem = stem_facts(text_en=text, text_hi=None, tables=None)
    return detect_format(text, stem, option_facts(options))


# --- format detection -----------------------------------------------------------------

def test_count_form_beats_statement_form():
    """2023 Q1. Both markers are present; the count form must win, because eliminating
    one statement earns nothing here where it halves the field in a subset question."""
    text = (
        "Consider the following statements :\n"
        "1. Jhelum River passes through Wular Lake.\n"
        "2. Krishna River directly feeds Kolleru Lake.\n"
        "3. Meandering of Gandak River formed Kanwar Lake.\n"
        "How many of the statements given above are correct?"
    )
    assert _format(text) is QuestionFormat.how_many_correct


def test_count_form_beats_pairs_form():
    """The count form also overlaps 'correctly matched' — 22 questions in the corpus."""
    text = (
        "Consider the following pairs :\n1. A : B\n2. C : D\n"
        "In how many of the above rows is the given information correctly matched?"
    )
    assert _format(text) is QuestionFormat.how_many_correct


def test_count_archetype_alone_identifies_the_count_form():
    """Even with no 'how many' wording, an "Only one / Only two / All three / None"
    answer set is unambiguous."""
    options = _opts("Only one", "Only two", "All three", "None")
    assert option_facts(options).archetype is OptionArchetype.count_of_correct
    assert _format("Consider the following :\n1. A\n2. B\n3. C", options) is (
        QuestionFormat.how_many_correct
    )


def test_statement_pair_is_not_matched_by_the_word_statement_is():
    """`statement i\\b` matches "statement is" and once inflated this count from 14 to
    31. Only the hyphenated/colon forms may match."""
    assert _format("Which one of the following statements is correct?") is (
        QuestionFormat.single_fact
    )
    text = (
        "Consider the following statements :\nStatement-I :\nMarsupials are not "
        "naturally found in India.\nStatement-II :\nMarsupials can thrive only in "
        "montane grasslands."
    )
    assert _format(text) is QuestionFormat.assertion_reason


def test_numbered_list_without_a_count_question_is_statement_evaluation():
    text = (
        "Consider the following statements :\n1. Alpha is true.\n2. Beta is false.\n"
        "Which of the statements given above is/are correct?"
    )
    assert _format(text) is QuestionFormat.statement_evaluation


def test_unmarked_question_returns_none_rather_than_guessing():
    """47% of the corpus carries no marker. `None` is the honest answer — the model's
    classification is what fills those in, and a regex guess would poison the
    disagreement check that exists to audit it."""
    assert _format("The 'Miyawaki method' is well known for the :") is None


# --- passages -------------------------------------------------------------------------

def test_quoted_term_is_not_a_passage():
    """These are ordinary single-fact items. Without a length floor the passage count
    came out at 46 against a true 7."""
    for stem in (
        "'SWAYAM', an initiative of the Government of India, aims at",
        "“Biorock technology” is talked about in which one of the following situations ?",
        "'Rashtriya Garima Abhiyaan' is a national campaign to",
    ):
        assert not is_passage(stem), stem


def test_quoted_paragraph_is_a_passage():
    """2013 Q65, verbatim."""
    assert is_passage(
        '"Climate is extreme, rainfall is scanty and the people used to be nomadic '
        'herders."\nThe above statement best describes which of the following regions?'
    )


# --- statement counting ---------------------------------------------------------------

def test_statement_count_counts_distinct_numbered_items():
    facts = stem_facts(
        text_en="Consider the following :\n1. Aerosols\n2. Foam agents\n3. Fire retardants",
        text_hi=None,
        tables=None,
    )
    assert facts.statement_count == 3


def test_statement_count_accepts_roman_numerals():
    """2025 numbered its statements I./II./III. throughout — 59 questions, zero Arabic —
    before 2026 reverted to a mix. Matching digits only made every 2025 statement
    question invisible to the format taxonomy, inside the era the product leads with.
    Verbatim from 2025 Q6."""
    text = (
        "Consider the following statements :\n"
        "I. India has joined the Minerals Security Partnership as a member.\n"
        "II. India is a resource-rich country in all the 30 critical minerals.\n"
        "III. The Parliament in 2023 amended the Act.\n"
        "Which of the statements given above is/are correct?"
    )
    assert stem_facts(text_en=text, text_hi=None, tables=None).statement_count == 3
    assert _format(text) is QuestionFormat.statement_evaluation


def test_statement_count_handles_the_statement_pair_form():
    facts = stem_facts(
        text_en="Statement-I :\nAlpha.\nStatement-II :\nBeta.", text_hi=None, tables=None
    )
    assert facts.statement_count == 2


# --- option geometry ------------------------------------------------------------------

def test_equal_length_options_give_no_longest_signal():
    """A tie is the absence of a signal, not a weak one. Recording False here would
    invent a finding — and counting ties as hits is exactly what made a naive pass
    report 33.4% where the honest figure is 22.5%."""
    facts = option_facts(_opts("aaaa", "bbbb", "cccc", "dddd", correct="A"))
    assert facts.correct_is_longest is None
    assert facts.longest_margin is None


def test_longest_option_signal_and_margin():
    facts = option_facts(_opts("a" * 20, "b" * 10, "c" * 5, "d" * 4, correct="A"))
    assert facts.correct_is_longest is True
    assert facts.longest_margin == 1.0  # 20 vs 10
    facts = option_facts(_opts("a" * 20, "b" * 10, "c" * 5, "d" * 4, correct="B"))
    assert facts.correct_is_longest is False


def test_unkeyed_question_has_no_longest_signal():
    """A dropped question carries no correct option; it must not contribute."""
    facts = option_facts(_opts("a" * 20, "bb", "cc", "dd"))
    assert facts.correct_label is None
    assert facts.correct_is_longest is None


def test_subset_archetype_and_catch_alls():
    facts = option_facts(_opts("1 only", "2 only", "Both 1 and 2", "Neither 1 nor 2"))
    assert facts.archetype is OptionArchetype.subset_of_numbered
    assert facts.has_all_of_above and facts.has_none_of_above


def test_entity_archetype():
    facts = option_facts(
        _opts("Bhitarkanika Mangroves", "Marakkanam Salt Pans", "Naupada Swamp",
              "Rann of Kutch")
    )
    assert facts.archetype is OptionArchetype.entity_choice
    assert not facts.has_all_of_above and not facts.has_none_of_above


def test_dated_options():
    facts = option_facts(_opts("In 1947", "In 1950", "Much later", "Never", correct="B"))
    assert facts.dated_option_count == 2
    assert facts.dated_correct is True


def test_language_is_chosen_once_per_question():
    """Falling back per option is what made the inherited overlap statistic compare
    Devanagari against Latin and score a guaranteed zero."""
    mixed = [
        OptionInput("A", "English text", "हिन्दी पाठ", None),
        OptionInput("B", None, "केवल हिन्दी", None),
    ]
    assert option_language(mixed) == "hi"
    assert option_language([OptionInput("A", "x", "य", None)]) == "en"
