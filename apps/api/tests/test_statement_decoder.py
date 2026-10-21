"""Statement-level truth decoding — pure functions, no database.

Every stem below is pasted from the real corpus. The decoder turns an answer key into
per-statement truth labels, and a bug here does not fail loudly: it silently relabels
statements and every elimination-rule verdict downstream inherits the error. These tests
are the only thing standing between a regex tweak and a report that is confidently wrong.
"""

from kasauti_api.domain.intelligence.statements import (
    decode_question,
    is_negative_polarity,
    parse_count_option,
    parse_subset_option,
    roman_to_int,
    split_stem,
)

MONEY_BILL = """Consider the following statements:
1. Article 109 mentions special procedure in respect of Money Bills.
2. A Money Bill shall not be introduced in the Council of States.
3. The Rajya Sabha can either approve the Bill or suggest changes, but cannot reject it.
4. Amendments to a Money Bill suggested by the Rajya Sabha have to be accepted.
Which of the statements given above are correct?
"""

ROMAN_STEM = """Which of the following are the sources of income for the Reserve Bank?
I. Buying and selling Government bonds
II. Buying and selling foreign currency
III. Pension fund management
IV. Lending to private companies
V. Printing and distributing currency notes
Select the correct answer using the code given below.
"""

COUNT_STEM = """Consider the following statements:
1. Jhelum River passes through Wular Lake.
2. Krishna River directly feeds Kolleru Lake.
3. Meandering of Gandak River formed Kanwar Lake.
How many of the statements given above are correct?
"""


def _options(*pairs: tuple[str, str], correct: str):
    return [(label, text, label == correct) for label, text in pairs]


def test_roman_numerals_decode():
    assert roman_to_int("I") == 1
    assert roman_to_int("IV") == 4
    assert roman_to_int("VIII") == 8
    assert roman_to_int("X") == 10
    assert roman_to_int("India") is None


def test_trailing_question_is_stripped_from_the_last_statement():
    """Without this the last statement absorbs "Which of the statements given above are
    correct?" — and every length or wording rule then measures UPSC's boilerplate."""
    items, interrogative = split_stem(MONEY_BILL)
    assert len(items) == 4
    assert items[4].endswith("have to be accepted.")
    assert "Which of the statements" in interrogative
    assert "Consider the following" in interrogative


def test_subset_options_parse_in_both_numbering_styles():
    assert parse_subset_option("1 only") == {1}
    assert parse_subset_option("2 and 3 only") == {2, 3}
    assert parse_subset_option("Both 1 and 2") == {1, 2}
    assert parse_subset_option("Neither 1 nor 2") == set()
    assert parse_subset_option("I and II only") == {1, 2}
    assert parse_subset_option("II, III and IV") == {2, 3, 4}
    assert parse_subset_option("None of the above statements is correct") == set()


def test_an_option_naming_a_thing_is_refused_rather_than_mangled():
    """`entity_choice` options must decode to nothing. Reading "Article 356" as a
    reference to statement 356 is the failure mode that would put junk truth labels into
    the corpus without any test noticing."""
    assert parse_subset_option("Article 356 of the Constitution") is None
    assert parse_subset_option("India") is None
    assert parse_subset_option("") is None
    assert parse_subset_option(None) is None


def test_count_options_parse():
    assert parse_count_option("Only one") == 1
    assert parse_count_option("All three") == 3
    assert parse_count_option("All the four") == 4  # 2025's wording
    assert parse_count_option("None") == 0
    assert parse_count_option("1 only") is None


def test_negative_polarity_is_read_from_the_question_not_the_statements():
    """The regression this guards: statements say "is not available to", "is not
    mandatory" and "cannot reject it" constantly. Searching the whole stem for a negation
    would throw away most of the corpus as negative-polarity."""
    _, interrogative = split_stem(MONEY_BILL)
    assert not is_negative_polarity(interrogative)
    assert is_negative_polarity("Which of the above pairs is/are not correctly matched?")
    assert is_negative_polarity("Which of the statements given above is incorrect?")


def test_subset_key_becomes_per_statement_truth():
    result = decode_question(
        question_id=1, year=2024, question_number="68", stem_en=MONEY_BILL,
        options=_options(
            ("A", "1 and 2 only"), ("B", "3 and 4 only"),
            ("C", "1, 2 and 3 only"), ("D", "1, 2, 3 and 4"), correct="C",
        ),
    )
    truth = {r.index: r.is_true for r in result.records}
    assert truth == {1: True, 2: True, 3: True, 4: False}
    assert all(r.statement_count == 4 and r.true_count == 3 for r in result.records)


def test_roman_numbered_statements_decode():
    """All 42 of 2025's subset questions print Roman numerals. Before DERIVED_REV 3 they
    were archetyped `entity_choice` and the whole year was invisible here."""
    result = decode_question(
        question_id=2, year=2025, question_number="2", stem_en=ROMAN_STEM,
        options=_options(
            ("A", "I and II only"), ("B", "II, III and IV"),
            ("C", "I, III, IV and V"), ("D", "I, II and V"), correct="A",
        ),
    )
    assert result.skipped is None
    assert {r.index: r.is_true for r in result.records} == {
        1: True, 2: True, 3: False, 4: False, 5: False
    }


def test_an_option_referencing_an_unprinted_statement_is_refused():
    """One real 2025 question does this. Trusting the option would label a statement
    that is not on the page, so the whole question is dropped instead."""
    result = decode_question(
        question_id=7, year=2025, question_number="2", stem_en=ROMAN_STEM,
        options=_options(("A", "I and II only"), ("B", "II and III only"),
                         ("C", "IV and VI only"), ("D", "I, II and IV"), correct="A"),
    )
    assert result.records == ()
    assert result.skipped == "options reference a statement that is not printed"


def test_count_question_decodes_only_at_the_extremes():
    """"None" and "All three" pin every statement. "Only two" pins how many, never
    which — and a guess there would invent exactly the labels being measured."""
    options = [("A", "Only one"), ("B", "Only two"), ("C", "All three"), ("D", "None")]

    none_correct = decode_question(
        question_id=3, year=2023, question_number="1", stem_en=COUNT_STEM,
        options=_options(*options, correct="D"),
    )
    assert [r.is_true for r in none_correct.records] == [False, False, False]
    assert none_correct.records[0].source == "count_extreme"

    all_correct = decode_question(
        question_id=3, year=2023, question_number="1", stem_en=COUNT_STEM,
        options=_options(*options, correct="C"),
    )
    assert [r.is_true for r in all_correct.records] == [True, True, True]

    partial = decode_question(
        question_id=3, year=2023, question_number="1", stem_en=COUNT_STEM,
        options=_options(*options, correct="B"),
    )
    assert partial.records == ()
    assert partial.skipped == "count question, partial information"


def test_dropped_question_yields_nothing():
    """A dropped question has `is_correct` NULL throughout. It must not be read as one
    where every option is wrong."""
    result = decode_question(
        question_id=4, year=2024, question_number="52", stem_en=MONEY_BILL,
        options=[("A", "1 only", None), ("B", "2 only", None),
                 ("C", "Both 1 and 2", None), ("D", "Neither 1 nor 2", None)],
    )
    assert result.records == ()
    assert result.skipped == "unkeyed or dropped"


def test_negative_polarity_questions_are_excluded_not_inverted():
    stem = """Consider the following pairs:
1. Chola : Uraiyur
2. Pandya : Madurai
Which of the above pairs is/are not correctly matched?
"""
    result = decode_question(
        question_id=5, year=2022, question_number="10", stem_en=stem,
        options=_options(("A", "1 only"), ("B", "2 only"),
                         ("C", "Both 1 and 2"), ("D", "Neither 1 nor 2"), correct="A"),
    )
    assert result.records == ()
    assert result.skipped == "negative polarity"


def test_list_entries_are_labelled_but_not_counted_as_claims():
    """"Italy" is true or false like any statement, but no rule about modifiers or
    attribution can apply to it, so it must not sit in the baseline's denominator."""
    stem = """Consider the following countries:
1. Italy
2. Japan
3. Nigeria
Which of the above are frequently mentioned for their ageing population?
"""
    result = decode_question(
        question_id=6, year=2024, question_number="67", stem_en=stem,
        options=_options(("A", "1 and 2 only"), ("B", "2 only"),
                         ("C", "1 and 3 only"), ("D", "1, 2 and 3"), correct="A"),
    )
    assert [r.is_true for r in result.records] == [True, True, False]
    assert not any(r.is_claim for r in result.records)
    assert all(r.statement_count == 0 for r in result.records)
