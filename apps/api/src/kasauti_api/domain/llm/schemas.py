"""Structured-output schemas for all LLM calls. No free-form parsing anywhere."""

from pydantic import BaseModel, Field


class ExtractedOption(BaseModel):
    """One MCQ option (Prelims papers only)."""

    label: str = Field(description="Option label as printed: 'A', 'B', 'C' or 'D'")
    text_en: str | None = Field(default=None, description="English option text, verbatim")
    text_hi: str | None = Field(default=None, description="Hindi option text, verbatim")


class TableCell(BaseModel):
    """One cell, in both languages where the paper prints both."""

    text_en: str | None = Field(default=None, description="English cell text, verbatim")
    text_hi: str | None = Field(default=None, description="Hindi cell text, verbatim")


class ExtractedTable(BaseModel):
    """A table printed inside a question.

    UPSC uses these constantly — 'Match List I with List II' appears in most Prelims
    papers, alongside plain data tables. Flattening them into the question text loses
    the row/column relationship the question is actually testing, which makes the
    corpus unusable for any analysis of matching-type questions and forces the
    frontend to render a wall of text.
    """

    caption_en: str | None = Field(default=None, description="e.g. 'List I (Country)'")
    caption_hi: str | None = Field(default=None)
    headers: list[TableCell] = Field(
        default_factory=list,
        description="Column headers, left to right. Empty if the table has none.",
    )
    rows: list[list[TableCell]] = Field(
        default_factory=list,
        description="Rows top to bottom; each row is cells left to right, "
        "including any printed row label such as 'A.' or '1.'",
    )


class ExtractedStimulus(BaseModel):
    """A block printed once above several items, which those items are answered from.

    Prelims Paper II prints a comprehension passage above two to five items, and one
    option key above a run of data-sufficiency items. Repeating either inside every
    item's text would store the same 400 words five times; instead each item carries
    the `stimulus_ref` naming the block it belongs to.
    """

    ref: str = Field(
        description="A short key unique within this extraction, e.g. 'passage-1' or "
        "'directions-1'. The items that use this block repeat it in stimulus_ref."
    )
    kind: str = Field(
        description="'passage' for a comprehension text, 'directions' for a shared "
        "instruction block such as a data-sufficiency option key"
    )
    text_en: str | None = Field(default=None, description="English block text, verbatim")
    text_hi: str | None = Field(default=None, description="Hindi block text, verbatim")


class ExtractedQuestion(BaseModel):
    """One question extracted from a scanned UPSC paper page.

    UPSC papers print Hindi and English side-by-side, so both texts usually
    come from a single extraction pass.
    """

    question_number: str = Field(description="Question number as printed, e.g. '1(a)' or 'Q5'")
    marks: float | None = Field(default=None, description="Marks as printed, if visible")
    text_en: str | None = Field(default=None, description="English question text, verbatim")
    text_hi: str | None = Field(default=None, description="Hindi question text, verbatim")
    math_latex: str | None = Field(
        default=None,
        description="Mathematical content as LaTeX, if the question contains notation",
    )
    options: list[ExtractedOption] = Field(
        default_factory=list,
        description="MCQ options for Prelims questions; empty for Mains free-text questions",
    )
    tables: list[ExtractedTable] = Field(
        default_factory=list,
        description="Any tables printed in the question, including 'Match List I with "
        "List II' pairs. Keep the table OUT of text_en/text_hi and put it here.",
    )
    stimulus_ref: str | None = Field(
        default=None,
        description="The `ref` of the stimulus this item is answered from, if it sits "
        "under a shared passage or directions block. Null for a self-contained item.",
    )
    confidence: float = Field(ge=0, le=1, description="Extraction confidence for this question")


class ScanExtraction(BaseModel):
    """Full structured extraction of one scanned paper."""

    questions: list[ExtractedQuestion]
    stimuli: list[ExtractedStimulus] = Field(
        default_factory=list,
        description="Passages and shared directions blocks printed in this slice. Empty "
        "for a paper whose items all stand alone.",
    )
    year_seen: int | None = Field(
        default=None, description="Exam year if printed on the paper, else null"
    )
    paper_title_seen: str | None = Field(
        default=None, description="Paper title as printed, else null"
    )
    overall_confidence: float = Field(ge=0, le=1)
    issues: list[str] = Field(
        default_factory=list,
        description="Legibility or layout problems that reduce confidence",
    )


class PredictedAngle(BaseModel):
    angle_en: str = Field(description="A likely future question angle, in English")
    angle_hi: str = Field(description="The same angle in Hindi")
    rationale_en: str = Field(description="Why the corpus suggests this angle is live")


class TopicAnalysisResult(BaseModel):
    """Feature A1: recurring-pattern synthesis + prediction for one topic."""

    pattern_summary_en: str = Field(
        description="How UPSC has framed this topic over the years: recurring patterns, "
        "framing evolution, exhausted vs live territory. English."
    )
    pattern_summary_hi: str = Field(description="The same summary in Hindi")
    predicted_angles: list[PredictedAngle] = Field(
        description="2-5 likely future angles, most likely first"
    )


class OnePagerSection(BaseModel):
    heading: str
    points: list[str] = Field(description="Concise revision points, one fact/idea each")


class OnePagerContent(BaseModel):
    title: str
    overview: str = Field(description="2-3 sentence orientation for the topic")
    sections: list[OnePagerSection] = Field(
        description="Typed revision sections: anchor facts, key articles/theorems/cases, "
        "recurring PYQ angles, common traps"
    )
    keywords: list[str] = Field(description="Terms an examiner expects to see")


class OnePagerResult(BaseModel):
    """Feature B: Mains one-pager, both locales generated together."""

    content_en: OnePagerContent
    content_hi: OnePagerContent


class UncertainSpan(BaseModel):
    """A stretch of handwriting the reader is not confident it read correctly.

    This field is the whole reason the transcription stage is a structured call rather
    than "return the text". On handwritten mathematics, 87% of grading errors traced to
    transcription failure rather than rubric misapplication, **skewed 2.5:1 toward
    inventing a correct reading out of unclear handwriting** — and the probe reproduced
    that instinct on the very first booklet, wanting to read a smudged place-name as the
    historically correct state. A reader with nowhere to put doubt resolves it silently.
    """

    text: str = Field(
        description="The reading committed to in the page text, verbatim, so it can be "
        "located there by string search"
    )
    readings: list[str] = Field(
        default_factory=list,
        description="Other plausible readings of the same marks, most likely first. "
        "Empty when the span is simply unreadable.",
    )
    confidence: float = Field(
        ge=0, le=1, description="Confidence in the committed reading, not in the page"
    )
    note: str | None = Field(
        default=None, description="Optionally, what makes it doubtful — one short phrase"
    )


class TranscribedPage(BaseModel):
    page_number: int = Field(description="1-based, as supplied")
    text: str = Field(
        description="Everything the candidate wrote on this page, verbatim: their "
        "spelling, their grammar, their abbreviations, uncorrected and untranslated. "
        "Struck-through text is omitted — it is not part of the answer."
    )


class HandwrittenAnswer(BaseModel):
    """A learner's handwritten answer, read into text.

    Deliberately *not* a judgement: this stage decides what the candidate wrote and
    nothing about whether it is right. Keeping the two calls apart is what makes the
    transcript confirmable by the learner before anything is judged from it, which
    removes the dominant error class rather than scoring around it.
    """

    language: str = Field(description="'en', 'hi', or 'mixed' — what the answer is in")
    pages: list[TranscribedPage] = Field(description="One entry per supplied page, in order")
    uncertain_spans: list[UncertainSpan] = Field(
        default_factory=list,
        description="Every span you are not confident of. Listing one costs the learner "
        "a glance; guessing one silently costs them a rubric point, in whichever "
        "direction the guess falls.",
    )

    @property
    def text(self) -> str:
        """The whole answer, pages joined — what the judge reads."""
        return "\n\n".join(page.text for page in self.pages)


class ContentPointVerdict(BaseModel):
    """Whether one rubric content point is present in one Mains answer.

    The unit of the whole evaluator. No mark is predicted anywhere — UPSC has never
    released an evaluated booklet, so a predicted score has no observable truth to be
    right or wrong about, while "did this answer state X" is adjudicable by one competent
    reader. That is what makes this measurable at all.

    `quote` is required whenever `present` is true, and is what stops a claimed hit from
    being indistinguishable from a hallucination: the model must point at the learner's
    own words, verbatim, so the claim can be checked against the transcript by string
    search rather than trusted.
    """

    present: bool = Field(
        description="True only if the answer actually states this point. Absence of "
        "evidence is absence: do not infer the point from adjacent or implied content."
    )
    quote: str | None = Field(
        default=None,
        description="The learner's own words evidencing the point, copied verbatim from "
        "the answer including any spelling errors. Required when present is true; null "
        "otherwise. Never paraphrase, correct or translate it.",
    )
    partial: bool = Field(
        default=False,
        description="True when the point is gestured at but incomplete — named without "
        "explanation, or asserted without the required specificity. Set present=true and "
        "say what is missing in `comment`.",
    )
    comment: str = Field(
        description="One sentence for the learner. When present, what they did well; "
        "when absent, what specifically was missing. Never a score or a grade."
    )


class ContentPointBatch(BaseModel):
    """Verdicts for every content point of one rubric against one answer."""

    verdicts: dict[str, ContentPointVerdict] = Field(
        description="Keyed by the rubric step/point id, exactly as given. Every id "
        "supplied must appear; do not invent ids."
    )
    illegible_spans: list[str] = Field(
        default_factory=list,
        description="Passages of the transcript too garbled to judge, quoted verbatim. "
        "Surfacing these is how a transcription failure stays visible instead of being "
        "silently scored as a missing point.",
    )


class TopicTag(BaseModel):
    topic_path: str = Field(description="ltree path of the matched topic, from the provided list")
    confidence: float = Field(ge=0, le=1)


class TopicTagResult(BaseModel):
    """Topic assignments for one question against the provided taxonomy slice."""

    tags: list[TopicTag] = Field(description="1-3 best-matching topics, most specific first")


class QuestionTags(BaseModel):
    """Tags for one question inside a batch, keyed by its printed number."""

    question_number: str = Field(description="The question's printed number, exactly as given")
    tags: list[TopicTag] = Field(description="1-3 best-matching topics, most specific first")


class BatchTopicTagResult(BaseModel):
    """Tags for several questions from a single call.

    The candidate topic list dominates the tagging prompt — 124 topics is ~17.7k
    characters, and sending it per question costs ~1.8M characters for a 100-question
    paper. Batching sends it once per call instead, which is the single largest cost
    saving available in the pipeline.
    """

    results: list[QuestionTags] = Field(description="One entry per question, in the order given")
