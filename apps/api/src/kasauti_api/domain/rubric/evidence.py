"""The deterministic half of the evaluator: does the learner's transcript actually
contain the words the model quoted?

The judging prompt promises the learner that every claimed hit is evidenced by their own
words, "checked against the transcript by string search". This module is that string
search. Without it the promise is decoration: a model that invents a plausible quote and a
model that found a real one produce identical output, and the whole design — which trades
an unfalsifiable predicted mark for a checkable presence claim — collapses back into
trust.

So a claimed hit whose quote cannot be located in the transcript is **not** downgraded to
a miss and it is **not** shown as a hit. It is reported as unsupported, because those are
three different things: the learner did not make the point, the learner made the point, and
the system said something it cannot back up. Only the third is a defect in us.

Matching is verbatim on substance and forgiving on form: Unicode is normalised (Devanagari
composes several ways), whitespace is collapsed (the transcript wraps where the page
wrapped), quotes and dashes are unified (typography drifts between a scan and a JSON
string), and case is folded. Nothing else. A paraphrase does not match, which is the point.
"""

import re
import unicodedata
from dataclasses import dataclass

# A judge quoting two separated stretches of one sentence joins them with an ellipsis —
# the worked example's `names-annexed-states` evidence does exactly this. Requiring the
# joined string verbatim would fail every such quote; ignoring the split would let
# "A ... B" match a transcript containing only B. Each fragment must appear, in order.
_ELLIPSIS = re.compile(r"\s*(?:\.\s*\.\s*\.|…)\s*")
_WHITESPACE = re.compile(r"\s+")

# Typographic variants that carry no meaning here. Kept explicit rather than stripping all
# punctuation: dropping punctuation wholesale would let a quote match across a sentence
# boundary it never crossed.
_UNIFY = str.maketrans(
    {
        "‘": "'", "’": "'", "‚": "'", "‛": "'",
        "“": '"', "”": '"', "„": '"',
        "‐": "-", "‑": "-", "‒": "-", "–": "-",
        "—": "-", "―": "-", "−": "-",
        " ": " ", "​": "", "‌": "", "‍": "",
    }
)

_WRAPPING_QUOTES = "\"'‘’“” "


@dataclass(frozen=True)
class QuoteMatch:
    """Where a verified quote sits in the *normalised* transcript.

    The offsets are into `normalise(transcript)`, not the raw text — they exist to test
    one span against another (does this evidence overlap a passage the judge itself
    flagged as illegible?), never to slice the learner's answer for display.
    """

    start: int
    end: int


def normalise(text: str) -> str:
    """Fold away everything that differs between a transcript and a quote of it
    without changing what was said."""
    folded = unicodedata.normalize("NFC", text).translate(_UNIFY)
    return _WHITESPACE.sub(" ", folded).strip().casefold()


def find_quote(quote: str, transcript: str) -> QuoteMatch | None:
    """Locate `quote` in `transcript`, or None if the words are not there.

    An ellipsis in the quote means "and later"; each fragment must appear after the
    previous one ends.
    """
    haystack = normalise(transcript)
    fragments = [
        normalise(fragment.strip(_WRAPPING_QUOTES))
        for fragment in _ELLIPSIS.split(quote)
    ]
    fragments = [f for f in fragments if f]
    if not fragments or not haystack:
        return None

    cursor = 0
    start: int | None = None
    for fragment in fragments:
        found = haystack.find(fragment, cursor)
        if found == -1:
            return None
        if start is None:
            start = found
        cursor = found + len(fragment)
    assert start is not None
    return QuoteMatch(start=start, end=cursor)


def quote_is_supported(quote: str | None, transcript: str) -> bool:
    return bool(quote) and find_quote(quote, transcript) is not None


def touches_illegible_span(
    match: QuoteMatch, illegible_spans: list[str], transcript: str
) -> bool:
    """True when the evidence overlaps a passage the judge itself called illegible.

    A hit resting on words the same call admitted it could not read is not a hit anyone
    should act on: the documented failure mode is a model smoothing unclear handwriting
    into the token that *ought* to be there and then crediting the point. Flagging the
    overlap is the cheap half of that guard; gating on per-span OCR confidence, for
    points that hang on a single name or figure, is the other half and is not built yet.
    """
    haystack = normalise(transcript)
    for span in illegible_spans:
        needle = normalise(span)
        if not needle:
            continue
        cursor = 0
        while (found := haystack.find(needle, cursor)) != -1:
            if found < match.end and match.start < found + len(needle):
                return True
            cursor = found + 1
    return False
