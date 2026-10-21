import base64
from typing import TypeVar

from anthropic import AsyncAnthropic
from pydantic import BaseModel

from kasauti_api.domain.llm.provider import DocumentInput, LlmUsage
from kasauti_api.settings import get_settings

T = TypeVar("T", bound=BaseModel)

# Tier → model. The approved plan tiers ingestion calls for cost discipline:
# light for page-level OCR/segmentation, standard for math/Devanagari-heavy work.
TIER_MODELS = {
    "light": "claude-haiku-4-5",
    "standard": "claude-sonnet-5",
}


class ClaudeProvider:
    def __init__(self, client: AsyncAnthropic | None = None):
        self._client = client or AsyncAnthropic(api_key=get_settings().anthropic_api_key)

    async def parse_structured(
        self,
        *,
        prompt: str,
        schema: type[T],
        documents: list[DocumentInput] | None = None,
        system: str | None = None,
        tier: str = "standard",
        max_tokens: int = 16000,
    ) -> tuple[T, LlmUsage]:
        model = TIER_MODELS[tier]

        content: list[dict] = []
        for doc in documents or []:
            block_type = "document" if doc.media_type == "application/pdf" else "image"
            content.append(
                {
                    "type": block_type,
                    "source": {
                        "type": "base64",
                        "media_type": doc.media_type,
                        "data": base64.standard_b64encode(doc.data).decode("ascii"),
                    },
                }
            )
        content.append({"type": "text", "text": prompt})

        kwargs: dict = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": content}],
            "output_format": schema,
        }
        if system is not None:
            kwargs["system"] = system

        response = await self._client.messages.parse(**kwargs)
        usage = LlmUsage(
            provider="anthropic",
            model=model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )
        return response.parsed_output, usage
