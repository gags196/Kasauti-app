"""Read a learner's handwritten answer into text.

Deliberately a separate call from judging, and deliberately the first one. The dominant
error class in machine grading of handwritten work is transcription, not rubric
misapplication — 87% of errors on handwritten mathematics, skewed about 2.5:1 toward
inventing a correct reading out of unclear handwriting. A pipeline that reads and judges
in one call can never show the learner what it thought they wrote, so that error is
unfalsifiable from the outside and invisible from the inside.

Splitting it makes the transcript an artifact: confirmable by the learner before anything
is judged from it, scoreable against a reference (`scripts/score_transcription.py`), and
carrying its own doubts forward as `uncertain_spans`, which the evaluator uses to flag a
verdict resting on words nobody is sure of.

The tier is a parameter rather than a policy because "can the cheap tier read Devanagari
handwriting" is precisely the open question — and the answer is a number nobody has yet.
"""

from kasauti_api.domain.ingestion.extract import load_prompt
from kasauti_api.domain.llm.provider import DocumentInput, LLMProvider, LlmUsage
from kasauti_api.domain.llm.schemas import HandwrittenAnswer

TRANSCRIPTION_PROMPT_REF = "prompts/transcription/handwritten_answer_v1.md"

# A dense handwritten Mains page is ~250 words. Devanagari tokenizes far denser than
# Latin, so the budget is set from the Hindi case and is generous for the English one.
TOKENS_PER_PAGE = 1400
TOKENS_OVERHEAD = 1000


def language_instruction(language_hint: str | None) -> str:
    """What the caller already knows about the script, if anything.

    Passed as a hint and never as an assertion: a Hindi-medium candidate writing
    `Doctrine of Lapse` in Latin inside a Devanagari sentence is normal, and a hint that
    hardened into a rule would have the reader transliterating one of them.
    """
    if language_hint in {"en", "hi"}:
        script = "Devanagari" if language_hint == "hi" else "Latin script"
        return (
            f"\n\nThe booklet is expected to be written mainly in {script}, but transcribe "
            "whatever is actually on the page — including words in the other script."
        )
    return ""


async def transcribe_answer(
    provider: LLMProvider,
    documents: list[DocumentInput],
    *,
    page_count: int,
    language_hint: str | None = None,
    tier: str = "standard",
) -> tuple[HandwrittenAnswer, LlmUsage]:
    """Transcribe one candidate's answer booklet (or the pages of it supplied).

    `page_count` sizes the output budget and is the caller's count, not the model's — a
    model that loses track of how many pages it was given would otherwise silently
    truncate at whatever token limit it was handed.
    """
    if not documents:
        raise ValueError("no pages supplied to transcribe")

    return await provider.parse_structured(
        prompt=(
            f"Transcribe this handwritten answer. {page_count} page(s) are supplied; "
            f"return one entry per page, in order."
            + language_instruction(language_hint)
        ),
        system=load_prompt(TRANSCRIPTION_PROMPT_REF),
        schema=HandwrittenAnswer,
        documents=documents,
        tier=tier,
        max_tokens=TOKENS_PER_PAGE * page_count + TOKENS_OVERHEAD,
    )
