"""Embedding provider interface + Voyage AI implementation.

Voyage multilingual embeddings put Hindi and English in one vector space, so
cross-lingual retrieval (Hindi query → English question and vice versa) works
without translation. Swappable behind the protocol (BGE-M3 is the documented
self-hosted escape hatch).
"""

import hashlib
import logging
import math
import re
from typing import Literal, Protocol

import voyageai

from kasauti_api.domain.llm.provider import LlmUsage
from kasauti_api.settings import get_settings

logger = logging.getLogger(__name__)


class EmbeddingProvider(Protocol):
    model_name: str

    async def embed(
        self, texts: list[str], *, input_type: Literal["document", "query"]
    ) -> tuple[list[list[float]], LlmUsage]: ...


class VoyageProvider:
    def __init__(self, client: voyageai.AsyncClient | None = None):
        s = get_settings()
        self.model_name = s.embedding_model
        self._client = client or voyageai.AsyncClient(api_key=s.voyage_api_key)

    async def embed(
        self, texts: list[str], *, input_type: Literal["document", "query"]
    ) -> tuple[list[list[float]], LlmUsage]:
        result = await self._client.embed(
            texts=texts, model=self.model_name, input_type=input_type
        )
        usage = LlmUsage(
            provider="voyage",
            model=self.model_name,
            input_tokens=result.total_tokens,
            output_tokens=0,
        )
        return result.embeddings, usage


_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


class HashingDevProvider:
    """Offline stand-in for Voyage — dev only, never selected in prod.

    Hashes tokens into the same 1024-dim space so the *plumbing* (embed job,
    pgvector index, hybrid search, rerank) can be exercised without an API key.
    It carries no semantics: matches are lexical-overlap only and it cannot do
    cross-lingual retrieval, which is the whole point of the real provider.
    Anything selecting this provider is demo data, not product output.
    """

    def __init__(self, dim: int | None = None):
        self.model_name = "hashing-dev-v1"
        self._dim = dim or get_settings().embedding_dim

    def _vector(self, text: str) -> list[float]:
        vec = [0.0] * self._dim
        for token in _TOKEN_RE.findall(text.lower()):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            idx = int.from_bytes(digest[:4], "big") % self._dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vec[idx] += sign
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0:  # empty/punctuation-only text — park it on a fixed axis
            vec[0] = 1.0
            return vec
        return [v / norm for v in vec]

    async def embed(
        self, texts: list[str], *, input_type: Literal["document", "query"]
    ) -> tuple[list[list[float]], LlmUsage]:
        usage = LlmUsage(
            provider="dev",
            model=self.model_name,
            input_tokens=0,  # no billable call — keeps the cost ledger honest
            output_tokens=0,
        )
        return [self._vector(t) for t in texts], usage


def get_embedding_provider() -> EmbeddingProvider:
    """Real provider whenever a key exists; the offline stand-in only in dev.

    Without this, every search/embed path is hard-blocked on a Voyage key, which
    makes the app undemoable before the first paper is ingested.
    """
    settings = get_settings()
    if settings.voyage_api_key:
        return VoyageProvider()
    if settings.env != "dev":
        raise RuntimeError(
            "KASAUTI_VOYAGE_API_KEY is not set — refusing to serve embeddings "
            f"with the dev stand-in in env={settings.env!r}."
        )
    logger.warning(
        "No KASAUTI_VOYAGE_API_KEY — using %s. Retrieval results are lexical "
        "placeholders, not real semantic or cross-lingual matches.",
        HashingDevProvider().model_name,
    )
    return HashingDevProvider()
