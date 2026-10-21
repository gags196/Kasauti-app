"""Handwriting transcription: the stage, its error metrics, and the link into judging.

The metrics are hand-rolled (no jiwer, no python-Levenshtein), so each is pinned here
against a value computed by hand — the same bargain domain/intelligence/statistics.py
makes for its chi-square.
"""

import pytest
import yaml
from kasauti_api.domain.extraction.accuracy import (
    character_error_rate,
    combine,
    edit_distance,
    flag_quality,
    normalise,
    word_error_rate,
)
from kasauti_api.domain.extraction.handwriting import (
    TRANSCRIPTION_PROMPT_REF,
    transcribe_answer,
)
from kasauti_api.domain.ingestion.extract import load_prompt
from kasauti_api.domain.llm.provider import DocumentInput, LlmUsage
from kasauti_api.domain.llm.schemas import (
    ContentPointBatch,
    ContentPointVerdict,
    HandwrittenAnswer,
    TranscribedPage,
    UncertainSpan,
)
from kasauti_api.domain.rubric import PointStatus, judge_answer, load_rubric
from kasauti_api.settings import REPO_ROOT

FAKE_USAGE = LlmUsage(provider="fake", model="fake-standard", input_tokens=0, output_tokens=0)


# --- metrics -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("a", "b", "distance"),
    [
        ("kitten", "sitting", 3),  # the textbook value: k->s, e->i, +g
        ("", "abc", 3),
        ("abc", "abc", 0),
        ("Wellesley", "Welleslay", 1),  # one substitution: the 'e' before the 'y'
        # Plain Levenshtein has no transposition edit, so a swap costs two. That is the
        # right convention here: a reader that swaps two letters made two mistakes on the
        # page, and CER is meant to count marks misread, not keystrokes to repair.
        ("form", "from", 2),
    ],
)
def test_edit_distance_matches_hand_computed_values(a, b, distance):
    assert edit_distance(a, b) == distance
    assert edit_distance(b, a) == distance  # symmetric


def test_character_error_rate_is_errors_over_reference_length():
    rate = character_error_rate("abcdefghij", "abcdefghXj")
    assert rate.errors == 1
    assert rate.length == 10
    assert rate.rate == pytest.approx(0.1)


def test_word_error_rate_counts_words_not_characters():
    rate = word_error_rate("the state could not have an army", "the state could not keep an army")
    assert (rate.errors, rate.length) == (1, 7)


def test_devanagari_is_compared_after_unicode_normalisation():
    """The same syllable composes several ways. Comparing raw codepoints would report an
    error rate largely made of encoding differences — and would bias it against Hindi,
    which is the exact conclusion this measurement must not reach by accident."""
    composed = "सेना"  # से + ना, precomposed matras
    decomposed = "सेना"
    assert normalise(composed) == normalise(decomposed)
    # A real difference still counts: व and ब are a documented confusion pair.
    assert character_error_rate("वह", "बह").errors == 1


def test_a_rate_may_exceed_one_rather_than_being_clamped():
    """A reader that invents a page of text into an empty one is worse than 100% wrong;
    clamping would hide the failure with the largest consequence."""
    rate = character_error_rate("ab", "abcdefgh")
    assert rate.rate > 1


def test_pooling_is_by_totals_not_by_averaging_rates():
    """A one-word page and a three-hundred-word page are not equal evidence."""
    small = character_error_rate("ab", "xb")  # 1/2 = 50%
    large = character_error_rate("a" * 100, "a" * 100)  # 0/100
    pooled = combine([small, large])
    assert pooled.rate == pytest.approx(1 / 102)
    assert pooled.rate < (small.rate + large.rate) / 2


def test_flag_quality_separates_flagged_errors_from_silent_ones():
    reference = "Hyderabad Bharatpur Satara fell prey"
    candidate = "Hyderabad Bhagatpur Satara fell prey"
    # The reader flagged the word it actually got wrong.
    good = flag_quality(reference, candidate, ["Bhagatpur"])
    assert (good.flagged, good.flagged_wrong, good.unflagged_wrong) == (1, 1, 0)
    assert good.recall == 1.0
    assert good.precision == 1.0

    # The same error, resolved silently — the documented failure mode.
    silent = flag_quality(reference, candidate, [])
    assert (silent.flagged, silent.flagged_wrong, silent.unflagged_wrong) == (0, 0, 1)
    assert silent.recall == 0.0
    assert silent.precision is None

    # A flag on a word that was read correctly is a false alarm, not a hit.
    noisy = flag_quality(reference, reference, ["Satara"])
    assert (noisy.flagged, noisy.flagged_wrong) == (1, 0)
    assert noisy.precision == 0.0


# --- the stage ---------------------------------------------------------------------


class FakeTranscriber:
    def __init__(self):
        self.calls: list[dict] = []

    async def parse_structured(self, *, prompt, schema, documents=None, system=None,
                               tier="standard", max_tokens=16000):
        assert schema is HandwrittenAnswer
        self.calls.append(
            {"prompt": prompt, "system": system, "documents": documents,
             "tier": tier, "max_tokens": max_tokens}
        )
        return (
            HandwrittenAnswer(
                language="hi",
                pages=[
                    TranscribedPage(page_number=1, text="राज्य अपनी सेना नहीं रख सकते थे।"),
                    TranscribedPage(page_number=2, text="यह नीति वेलेजली ने चलाई।"),
                ],
                uncertain_spans=[
                    UncertainSpan(text="वेलेजली", readings=["वेलेस्ली"], confidence=0.6)
                ],
            ),
            FAKE_USAGE,
        )


@pytest.mark.asyncio
async def test_transcription_sends_the_pages_and_sizes_the_budget_by_page_count():
    provider = FakeTranscriber()
    documents = [DocumentInput(data=b"%PDF-1", media_type="application/pdf")] * 2

    answer, usage = await transcribe_answer(
        provider, documents, page_count=2, language_hint="hi", tier="light"
    )

    call = provider.calls[0]
    assert call["documents"] == documents
    assert call["tier"] == "light"
    assert call["max_tokens"] > 2000  # scaled by pages, not a fixed budget
    assert "Devanagari" in call["prompt"]
    # The hint is a hint: it must not tell the reader to force one script.
    assert "whatever is actually on the page" in call["prompt"]
    assert answer.text.startswith("राज्य")
    assert "वेलेजली" in answer.text
    assert usage is FAKE_USAGE


@pytest.mark.asyncio
async def test_transcription_refuses_an_empty_page_list():
    with pytest.raises(ValueError, match="no pages"):
        await transcribe_answer(FakeTranscriber(), [], page_count=0)


def test_the_transcription_prompt_forbids_correcting_and_demands_flagged_doubt():
    """The prompt is the artifact being measured. These clauses are the ones that stand
    between a faithful transcript and a plausible one."""
    text = load_prompt(TRANSCRIPTION_PROMPT_REF).lower()
    assert "verbatim" in text
    assert "their spelling, including mistakes" in text
    assert "never translate" in text
    assert "uncertain_spans" in text
    # The specific instinct the probe caught on its very first booklet.
    assert "bharatpur" in text, "must name the smoothing failure concretely"
    assert "struck through" in text or "struck-through" in text


def test_the_schema_has_somewhere_to_put_doubt():
    """A reader with no field for uncertainty resolves it silently — which is the whole
    reason this call is structured rather than 'return the text'."""
    assert "uncertain_spans" in HandwrittenAnswer.model_fields
    assert "confidence" in UncertainSpan.model_fields
    assert "readings" in UncertainSpan.model_fields


# --- the link into judging ----------------------------------------------------------


class OneHitProvider:
    def __init__(self, point_id: str, quote: str):
        self.point_id, self.quote = point_id, quote

    async def parse_structured(self, *, prompt, schema, documents=None, system=None,
                               tier="standard", max_tokens=16000):
        assert schema is ContentPointBatch
        return (
            ContentPointBatch(
                verdicts={
                    self.point_id: ContentPointVerdict(
                        present=True, quote=self.quote, comment="Stated."
                    )
                },
                illegible_spans=[],
            ),
            FAKE_USAGE,
        )


@pytest.mark.asyncio
async def test_a_transcribers_doubt_reaches_the_verdict_that_rests_on_it():
    """The two stages see different things: only the transcriber saw the ink, only the
    judge knows which words a point turns on. A hit evidenced by a span the transcriber
    was unsure of must arrive flagged, not clean."""
    rubric = load_rubric("gs1-2024-q2-subsidiary-alliance-v1")
    answer = "Hyderabad, Bhagatpur, Satara and more states fell prey to this policy."

    report, _ = await judge_answer(
        OneHitProvider("names-annexed-states", "Hyderabad, Bhagatpur, Satara"),
        rubric,
        question_text="Evaluate the role of subsidiary alliance policy.",
        answer_text=answer,
        uncertain_spans=["Bhagatpur"],
    )

    outcome = next(o for o in report.outcomes if o.point_id == "names-annexed-states")
    assert outcome.status is PointStatus.hit
    assert outcome.evidence_uncertain, "a hit resting on doubtful ink must say so"
    assert "Bhagatpur" in report.illegible_spans

    # A hit whose evidence sits nowhere near the doubtful span is not flagged.
    clean, _ = await judge_answer(
        OneHitProvider("names-annexed-states", "Hyderabad, Bhagatpur, Satara"),
        rubric,
        question_text="Evaluate the role of subsidiary alliance policy.",
        answer_text=answer,
        uncertain_spans=["fell prey to this policy"],
    )
    assert not next(
        o for o in clean.outcomes if o.point_id == "names-annexed-states"
    ).evidence_uncertain


# --- the collection spec -------------------------------------------------------------


def test_the_handwriting_set_is_a_spec_until_the_booklets_exist():
    """A manifest with no samples must not be scoreable. Scoring an empty set would
    print a clean report describing nothing, which is worse than no report."""
    manifest = yaml.safe_load(
        (REPO_ROOT / "content" / "benchmark_sets" / "handwriting_ocr_v1.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["status"] == "awaiting_source"
    assert manifest["samples"] == []
    # Both arms, or there is no parity number to compute.
    assert manifest["collection_spec"]["minimum"].keys() == {"hi", "en"}
