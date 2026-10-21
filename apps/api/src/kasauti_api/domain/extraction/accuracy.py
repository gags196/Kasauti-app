"""Character and word error rates for a handwriting transcript, and whether its own
doubts landed where its errors did.

Written here rather than pulled from `jiwer`/`python-Levenshtein` for the same reason
`domain/intelligence/statistics.py` hand-rolls its tests: three functions do not justify a
dependency, and each is pinned by a unit test against values computed by hand.

**Unicode normalisation is load-bearing, not hygiene.** Devanagari composes several ways —
`क` + `ि` and a precomposed form are the same syllable to a reader and different codepoints
to `==`. Comparing un-normalised text would report a Hindi error rate made largely of
encoding differences, which is exactly the direction of bias this measurement exists to
rule out: it would make Hindi look worse than it is and the conclusion ("Hindi is not
launchable") unfalsifiable.
"""

import re
import unicodedata
from dataclasses import dataclass

_WHITESPACE = re.compile(r"\s+")


def normalise(text: str) -> str:
    """NFC, collapsed whitespace, stripped. Case is *not* folded: a transcript that
    lowercases a candidate's proper nouns has changed what they wrote."""
    return _WHITESPACE.sub(" ", unicodedata.normalize("NFC", text)).strip()


def edit_distance(reference: list[str] | str, candidate: list[str] | str) -> int:
    """Levenshtein distance, two rows of memory rather than a full matrix.

    A dense Mains page is ~1,500 characters, so the full matrix would be ~2M cells per
    page for no reason; only the previous row is ever read.
    """
    if len(reference) < len(candidate):
        reference, candidate = candidate, reference
    previous = list(range(len(candidate) + 1))
    for i, ref_item in enumerate(reference, start=1):
        current = [i]
        for j, cand_item in enumerate(candidate, start=1):
            current.append(
                min(
                    previous[j] + 1,  # deletion
                    current[j - 1] + 1,  # insertion
                    previous[j - 1] + (ref_item != cand_item),  # substitution
                )
            )
        previous = current
    return previous[-1]


@dataclass(frozen=True)
class ErrorRate:
    errors: int
    length: int

    @property
    def rate(self) -> float:
        """Errors per reference unit. Can exceed 1.0 — a candidate that hallucinates a
        page of text into an empty one is not 100% wrong, it is worse, and clamping that
        to 1.0 would hide the failure mode with the largest consequence."""
        if self.length == 0:
            return 0.0 if self.errors == 0 else float("inf")
        return self.errors / self.length


def character_error_rate(reference: str, candidate: str) -> ErrorRate:
    ref, cand = normalise(reference), normalise(candidate)
    return ErrorRate(errors=edit_distance(ref, cand), length=len(ref))


def word_error_rate(reference: str, candidate: str) -> ErrorRate:
    ref = normalise(reference).split(" ") if normalise(reference) else []
    cand = normalise(candidate).split(" ") if normalise(candidate) else []
    return ErrorRate(errors=edit_distance(ref, cand), length=len(ref))


def combine(rates: list[ErrorRate]) -> ErrorRate:
    """Pool by totals, never by averaging rates — a one-word page and a 300-word page
    are not equal evidence, and averaging their rates would say they were."""
    return ErrorRate(
        errors=sum(r.errors for r in rates), length=sum(r.length for r in rates)
    )


@dataclass(frozen=True)
class FlagQuality:
    """Whether the transcriber's own `uncertain_spans` point at its actual mistakes.

    This decides whether gating a rubric verdict on transcription confidence is worth
    building at all. If flagged spans are no likelier to be wrong than unflagged ones,
    the flags carry no information and the gate would only add false alarms; if flagged
    spans capture most of the errors, the gate is the cheapest correctness win available.
    """

    flagged: int
    flagged_wrong: int
    #: Words that differ from the reference but sit in no flagged span.
    unflagged_wrong: int

    @property
    def precision(self) -> float | None:
        """Of the spans flagged, how many actually contained an error."""
        return self.flagged_wrong / self.flagged if self.flagged else None

    @property
    def recall(self) -> float | None:
        """Of the errors made, how many were flagged. The number that matters: an error
        the transcriber knew it might be making is one the learner can fix."""
        total = self.flagged_wrong + self.unflagged_wrong
        return self.flagged_wrong / total if total else None


def flag_quality(
    reference: str, candidate: str, uncertain_spans: list[str]
) -> FlagQuality:
    """Score the transcriber's doubts against its errors, at word granularity.

    Word granularity, not character: a flagged span is a word or phrase, and a reader
    confirming a transcript confirms words. A flagged span counts as hitting an error when
    any of its words is absent from the reference's word multiset — crude, but it does not
    require aligning two texts that may differ by whole inserted clauses, and it cannot
    credit a flag for an error somewhere else on the page.
    """
    ref_words = normalise(reference).split(" ") if normalise(reference) else []
    cand_words = normalise(candidate).split(" ") if normalise(candidate) else []

    remaining: dict[str, int] = {}
    for word in ref_words:
        remaining[word] = remaining.get(word, 0) + 1

    wrong: set[int] = set()
    for index, word in enumerate(cand_words):
        if remaining.get(word, 0) > 0:
            remaining[word] -= 1
        else:
            wrong.add(index)

    flagged_indices: set[int] = set()
    flagged_hits = 0
    for span in uncertain_spans:
        span_words = normalise(span).split(" ") if normalise(span) else []
        if not span_words:
            continue
        positions = _locate(cand_words, span_words)
        flagged_indices |= positions
        if positions & wrong:
            flagged_hits += 1

    return FlagQuality(
        flagged=sum(1 for s in uncertain_spans if normalise(s)),
        flagged_wrong=flagged_hits,
        unflagged_wrong=len(wrong - flagged_indices),
    )


def _locate(words: list[str], span: list[str]) -> set[int]:
    """Indices of every occurrence of `span` inside `words`."""
    found: set[int] = set()
    for start in range(len(words) - len(span) + 1):
        if words[start : start + len(span)] == span:
            found |= set(range(start, start + len(span)))
    return found
