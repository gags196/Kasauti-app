"""FileQueueProvider round trip: queue a request, answer it off-line, replay it.

No database and no network — this is the seam that lets the whole pipeline run with no
Anthropic key, so it needs to hold on its own.
"""

import json
from pathlib import Path

import pytest
from kasauti_api.domain.llm.provider import DocumentInput
from kasauti_api.domain.llm.queue_provider import (
    FileQueueProvider,
    LlmRequestPending,
    schema_registry,
    script_profile,
)
from kasauti_api.domain.llm.schemas import TopicTagResult

VALID_ANSWER = {"tags": [{"topic_path": "gs2.constitution.federalism", "confidence": 0.9}]}


async def _call(provider: FileQueueProvider, prompt: str = "Tag this question."):
    return await provider.parse_structured(
        prompt=prompt, schema=TopicTagResult, system="You tag questions.", tier="light"
    )


@pytest.mark.asyncio
async def test_first_call_queues_and_raises(tmp_path):
    provider = FileQueueProvider(tmp_path)

    with pytest.raises(LlmRequestPending) as excinfo:
        await _call(provider)

    request_id = excinfo.value.request_id
    request = json.loads(
        (tmp_path / "requests" / f"{request_id}.json").read_text(encoding="utf-8")
    )
    assert request["schema"] == "TopicTagResult"
    assert request["tier"] == "light"
    # The JSON Schema travels with the request so an answer can be validated against
    # exactly what the API would have been constrained to.
    assert "properties" in request["schema_json"]
    assert not (tmp_path / "responses" / f"{request_id}.json").exists()


@pytest.mark.asyncio
async def test_answered_request_replays_from_cache(tmp_path):
    provider = FileQueueProvider(tmp_path)
    with pytest.raises(LlmRequestPending) as excinfo:
        await _call(provider)
    request_id = excinfo.value.request_id

    (tmp_path / "responses" / f"{request_id}.json").write_text(
        json.dumps(VALID_ANSWER), encoding="utf-8"
    )

    result, usage = await _call(provider)
    assert isinstance(result, TopicTagResult)
    assert result.tags[0].topic_path == "gs2.constitution.federalism"
    # Zero-token manual usage: no API call happened, so the ledger must not imply spend.
    assert (usage.provider, usage.input_tokens, usage.output_tokens) == ("manual", 0, 0)


@pytest.mark.asyncio
async def test_malformed_answer_is_rejected(tmp_path):
    """A bad answer must fail at the provider boundary, not corrupt rows downstream."""
    provider = FileQueueProvider(tmp_path)
    with pytest.raises(LlmRequestPending) as excinfo:
        await _call(provider)

    (tmp_path / "responses" / f"{excinfo.value.request_id}.json").write_text(
        json.dumps({"tags": [{"topic_path": "x", "confidence": 5.0}]}),  # confidence > 1
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="does not satisfy TopicTagResult"):
        await _call(provider)


@pytest.mark.asyncio
async def test_request_id_is_stable_and_input_sensitive(tmp_path):
    """Re-running a job must hit the same id (cache hit), while a different question
    must get its own request."""
    provider = FileQueueProvider(tmp_path)

    with pytest.raises(LlmRequestPending) as first:
        await _call(provider)
    with pytest.raises(LlmRequestPending) as repeat:
        await _call(provider)
    with pytest.raises(LlmRequestPending) as different:
        await _call(provider, prompt="A different question.")

    assert first.value.request_id == repeat.value.request_id
    assert first.value.request_id != different.value.request_id


@pytest.mark.asyncio
async def test_documents_are_saved_and_measured(tmp_path):
    provider = FileQueueProvider(tmp_path)
    pdf = b"%PDF-1.4\n/Type /Page \n/Type /Page \ntrailer"

    with pytest.raises(LlmRequestPending) as excinfo:
        await provider.parse_structured(
            prompt="Extract.",
            schema=TopicTagResult,
            documents=[DocumentInput(data=pdf, media_type="application/pdf")],
        )

    measurement = json.loads(
        (tmp_path / "measurements" / f"{excinfo.value.request_id}.json").read_text(
            encoding="utf-8"
        )
    )
    doc = measurement["documents"][0]
    assert doc["bytes"] == len(pdf)
    assert doc["page_count_hint"] == 2
    assert Path(doc["path"]).exists()


def test_script_profile_separates_devanagari():
    """Devanagari vs Latin is the main driver of token cost in a bilingual corpus."""
    profile = script_profile("Federalism संघवाद 2026")
    assert profile["latin_chars"] == 10
    assert profile["devanagari_chars"] == 6
    assert profile["digit_chars"] == 4


def test_schema_registry_exposes_pipeline_schemas():
    registry = schema_registry()
    for name in ("ScanExtraction", "TopicTagResult", "TopicAnalysisResult", "OnePagerResult"):
        assert name in registry
