"""Stage 2 of the PYQ pipeline: scanned PDF → structured bilingual questions."""

from kasauti_api.domain.llm.provider import DocumentInput, LLMProvider, LlmUsage
from kasauti_api.domain.llm.schemas import ScanExtraction
from kasauti_api.settings import get_settings

# Prompt history — old versions are kept so rows extracted under them keep honest
# provenance in prompt_ref:
#   v1  claimed the two languages are printed "side-by-side or one above the other".
#       Wrong for UPSC, which prints a Hindi page then the English page for the same
#       questions, so pairing must happen by question number across page boundaries.
#   v2  fixed that, and added page-slice and marks guidance.
#   v3  adds table capture. Match-the-list items appear in most Prelims papers; before
#       this they were flattened into the question text, destroying the row/column
#       relationship the question actually tests.
#   v4  adds shared blocks. Prelims Paper II prints a comprehension passage above a run
#       of items, and prints one option key above a run of data-sufficiency items; v3
#       had nowhere to put either, so a passage would have been duplicated into five
#       stems and the data-sufficiency items would have arrived with no options at all.
#       A paper without such blocks just returns an empty `stimuli`, so v4 supersedes
#       v3 for every paper rather than only for Paper II.
EXTRACTION_PROMPT_REF = "prompts/extraction/pyq_scan_v4.md"

# Optional-subject papers carry math notation; route them to the standard tier.
MATH_SUBJECT_CODES = {"maths"}


def load_prompt(ref: str) -> str:
    """Load a versioned prompt from content/ by its repo-relative ref."""
    return (get_settings().content_dir / ref).read_text(encoding="utf-8")


async def extract_scan(
    provider: LLMProvider,
    pdf_bytes: bytes,
    *,
    optional_subject_code: str | None,
) -> tuple[ScanExtraction, LlmUsage]:
    tier = "standard" if optional_subject_code in MATH_SUBJECT_CODES else "light"
    prompt = load_prompt(EXTRACTION_PROMPT_REF)
    return await provider.parse_structured(
        prompt="Extract all questions from this paper.",
        system=prompt,
        schema=ScanExtraction,
        documents=[DocumentInput(data=pdf_bytes, media_type="application/pdf")],
        tier=tier,
        max_tokens=32000,
    )
