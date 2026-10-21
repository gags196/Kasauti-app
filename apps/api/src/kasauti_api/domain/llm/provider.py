"""Provider-agnostic LLM interface.

Everything upstream (ingestion, evaluation, benchmark) depends on this protocol,
never on a concrete SDK — swapping or adding a provider is a one-file change.
"""

from dataclasses import dataclass
from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class LlmUsage:
    provider: str
    model: str
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class DocumentInput:
    """A document or image passed to a vision-capable model."""

    data: bytes
    media_type: str  # "application/pdf" | "image/png" | "image/jpeg" | "image/webp"


class LLMProvider(Protocol):
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
        """Run a (possibly vision) request constrained to `schema`.

        `tier` selects a model class, not a specific model:
          "light"    — cheap/fast (page-level OCR, simple tagging)
          "standard" — the workhorse (math/Devanagari-heavy extraction, judging)
        """
        ...
