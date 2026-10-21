"""Every versioned prompt reference must resolve to a real file.

A typo'd or renamed ref currently fails only at runtime, part-way through a pipeline
run that has already spent money on earlier stages. Cheap to catch here instead.
"""

import pytest
from kasauti_api.domain.ingestion.extract import EXTRACTION_PROMPT_REF, load_prompt
from kasauti_api.domain.ingestion.tag import TAGGING_PROMPT_REF
from kasauti_api.domain.intelligence.generation import (
    ONE_PAGER_PROMPT_REF,
    TOPIC_ANALYSIS_PROMPT_REF,
)

ALL_REFS = [
    EXTRACTION_PROMPT_REF,
    TAGGING_PROMPT_REF,
    TOPIC_ANALYSIS_PROMPT_REF,
    ONE_PAGER_PROMPT_REF,
]


@pytest.mark.parametrize("ref", ALL_REFS)
def test_prompt_ref_resolves(ref):
    text = load_prompt(ref)
    assert text.strip(), f"{ref} is empty"


def test_extraction_prompt_describes_the_real_bilingual_layout():
    """v1 claimed the two languages sit side by side. They do not: UPSC prints a Hindi
    page then the English page for the same questions, so pairing happens across pages.
    Getting this wrong silently halves recall or duplicates every question."""
    text = load_prompt(EXTRACTION_PROMPT_REF).lower()
    # The exact v1 claim, which was wrong for Prelims papers.
    assert "usually side-by-side or one above the other" not in text
    assert "separate pages" in text, "must state that the languages are on different pages"
    assert "question number" in text, "must tell the model to pair by printed number"
    assert "never guess" in text, "must forbid inferring the correct option"


def test_batch_tagging_prompt_exists_and_pairs_by_question_number():
    """Batching is the pipeline's biggest cost saving, but it only works if the model
    keys its answers by printed question number — otherwise tags land on the wrong
    questions, silently."""
    from kasauti_api.domain.ingestion.tag import BATCH_TAGGING_PROMPT_REF

    text = load_prompt(BATCH_TAGGING_PROMPT_REF).lower()
    assert "question_number" in text
    assert "do not skip" in text


def test_every_rubric_judging_prompt_loads_through_the_engine_path():
    """Rubric YAML stores `evaluation/gs_content_point_v1.md` (relative to
    content/prompts/) while `load_prompt` wants it relative to content/. The engine
    bridges the two; get that wrong and every rubric validates in CI and then fails at
    judge time, part-way through an answer."""
    from kasauti_api.domain.rubric import iter_rubric_paths, load_rubric_path
    from kasauti_api.domain.rubric.loader import VerificationMethod

    checked = 0
    for path in iter_rubric_paths():
        for point in load_rubric_path(path).points:
            if point.verification.method is not VerificationMethod.llm_judged:
                continue
            assert load_prompt(point.verification.prompt_ref).strip()
            checked += 1
    assert checked, "no llm-judged rubric points found"


def test_the_judging_prompt_forbids_producing_a_mark():
    """The evaluator's whole reframe. No UPSC-marked script has ever been released, so a
    predicted score is unfalsifiable — the contract has no field for one and the prompt
    must not invite one anyway. It must also demand verbatim evidence, which is what the
    engine checks by string search."""
    text = load_prompt("prompts/evaluation/gs_content_point_v1.md").lower()
    assert "you are not marking" in text
    assert "do not award, estimate, or imply a score" in text
    assert "verbatim" in text
    assert "illegible_spans" in text, "must give the model somewhere to put unreadable text"


def test_extraction_prompt_keeps_shared_passages_out_of_the_stems():
    """Prelims Paper II prints one passage above several items. If the prompt does not
    say to factor it out AND to still copy the shared option key onto every item, the
    two failure modes are a passage duplicated into five stems, and data-sufficiency
    items arriving with zero options — which cannot be scored at all."""
    text = load_prompt(EXTRACTION_PROMPT_REF).lower()
    assert "stimulus_ref" in text, "must tell the model how items point at a shared block"
    assert "out of the items" in text, "must forbid repeating the passage in each stem"
    assert "four options for every multiple-choice item" in text
