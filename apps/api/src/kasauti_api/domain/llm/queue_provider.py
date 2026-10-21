"""An LLMProvider that hands requests to a human/agent instead of calling an API.

Purpose: run the real pipeline with no Anthropic key. Each `parse_structured` call
either finds a previously written answer on disk and returns it, or records the request
(prompt, system prompt, JSON Schema, attached documents) and raises `LlmRequestPending`.

This is safe to re-run because every arq task commits only at the end — raising midway
rolls the session back, so no partial or duplicated rows survive. Re-running after an
answer is written is a cache hit, so earlier stages are not redone.

The answer is validated against the same Pydantic schema the API would have been
constrained to, so the "structured outputs everywhere" trust boundary is unchanged: a
malformed answer fails here, not three layers downstream.

Dev/testing only. It is slow, manual, and does not scale — see
benchmarks/reports/token-cost/ for what the API path costs instead.
"""

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from kasauti_api.domain.llm import schemas as llm_schemas
from kasauti_api.domain.llm.provider import DocumentInput, LlmUsage
from kasauti_api.settings import REPO_ROOT

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

MANUAL_PROVIDER = "manual"
MANUAL_MODEL = "claude-code"

# Deliberately not a Settings field: this is dev-only tooling, and keeping it out of
# Settings means the production config surface is untouched by it. gitignored.
DEFAULT_QUEUE_DIR = REPO_ROOT / "var" / "llm_queue"

# Devanagari block. Hindi tokenizes far denser than Latin, so the split is the single
# most important input to the cost estimate — see scripts/token_cost_report.py.
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_LATIN = re.compile(r"[A-Za-z]")
_DIGIT = re.compile(r"[0-9]")


def script_profile(text: str) -> dict[str, int]:
    """Character counts by script — the raw input to token estimation."""
    return {
        "total_chars": len(text),
        "devanagari_chars": len(_DEVANAGARI.findall(text)),
        "latin_chars": len(_LATIN.findall(text)),
        "digit_chars": len(_DIGIT.findall(text)),
    }


def schema_registry() -> dict[str, type[BaseModel]]:
    """Every structured-output schema, by class name — lets the CLI validate an answer
    against the exact schema its request was created with."""
    return {
        name: obj
        for name, obj in vars(llm_schemas).items()
        if isinstance(obj, type) and issubclass(obj, BaseModel) and obj is not BaseModel
    }


class LlmRequestPending(Exception):
    """Raised when a request has been queued but not yet answered.

    Callers should return without committing; the DB session rolls back cleanly.
    """

    def __init__(self, request_id: str, schema_name: str, request_path: Path):
        self.request_id = request_id
        self.schema_name = schema_name
        self.request_path = request_path
        super().__init__(
            f"LLM request {request_id} ({schema_name}) is queued and unanswered. "
            f"Answer it with: uv run python scripts/llm_queue.py show {request_id}"
        )


@dataclass(frozen=True)
class QueuePaths:
    root: Path

    @property
    def requests(self) -> Path:
        return self.root / "requests"

    @property
    def responses(self) -> Path:
        return self.root / "responses"

    @property
    def documents(self) -> Path:
        return self.root / "documents"

    @property
    def measurements(self) -> Path:
        return self.root / "measurements"

    def ensure(self) -> None:
        for path in (self.requests, self.responses, self.documents, self.measurements):
            path.mkdir(parents=True, exist_ok=True)


def _page_count_hint(pdf_bytes: bytes) -> int | None:
    """Best-effort page count without adding a PDF dependency.

    Returns None for PDFs using compressed object streams, which is common — the real
    count is then recorded by whoever reads the document. Never guess it: page count
    drives the whole image-token estimate.
    """
    matches = re.findall(rb"/Type\s*/Page[^s]", pdf_bytes)
    return len(matches) or None


class FileQueueProvider:
    def __init__(self, queue_dir: Path | None = None):
        self.paths = QueuePaths(queue_dir or DEFAULT_QUEUE_DIR)
        self.paths.ensure()

    def _request_id(
        self,
        *,
        schema_name: str,
        system: str | None,
        prompt: str,
        documents: list[DocumentInput],
    ) -> str:
        """Stable across runs, so re-running a job hits the cache instead of re-asking."""
        digest = hashlib.blake2b(digest_size=8)
        digest.update(schema_name.encode())
        digest.update((system or "").encode())
        digest.update(prompt.encode())
        for doc in documents:
            digest.update(doc.media_type.encode())
            digest.update(hashlib.blake2b(doc.data, digest_size=16).digest())
        return digest.hexdigest()

    def _write_request(
        self,
        request_id: str,
        *,
        schema: type[T],
        system: str | None,
        prompt: str,
        documents: list[DocumentInput],
        tier: str,
        max_tokens: int,
    ) -> Path:
        doc_records = []
        for index, doc in enumerate(documents, start=1):
            suffix = "pdf" if doc.media_type == "application/pdf" else doc.media_type.split("/")[-1]
            doc_path = self.paths.documents / f"{request_id}.{index}.{suffix}"
            doc_path.write_bytes(doc.data)
            doc_records.append(
                {
                    "path": str(doc_path),
                    "media_type": doc.media_type,
                    "bytes": len(doc.data),
                    "page_count_hint": (
                        _page_count_hint(doc.data)
                        if doc.media_type == "application/pdf"
                        else None
                    ),
                }
            )

        request_path = self.paths.requests / f"{request_id}.json"
        request_path.write_text(
            json.dumps(
                {
                    "id": request_id,
                    "schema": schema.__name__,
                    "schema_json": schema.model_json_schema(),
                    "system": system,
                    "prompt": prompt,
                    "tier": tier,
                    "max_tokens": max_tokens,
                    "documents": doc_records,
                    "created_at": datetime.now(UTC).isoformat(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        # Everything the cost report needs about the *input* side of this call.
        (self.paths.measurements / f"{request_id}.json").write_text(
            json.dumps(
                {
                    "id": request_id,
                    "schema": schema.__name__,
                    "tier": tier,
                    "max_tokens": max_tokens,
                    "system": script_profile(system or ""),
                    "prompt": script_profile(prompt),
                    "documents": doc_records,
                    "response": None,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return request_path

    def _record_response_measurement(self, request_id: str, raw: str) -> None:
        path = self.paths.measurements / f"{request_id}.json"
        if not path.exists():
            return
        data = json.loads(path.read_text(encoding="utf-8"))
        data["response"] = script_profile(raw)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

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
        docs = documents or []
        request_id = self._request_id(
            schema_name=schema.__name__, system=system, prompt=prompt, documents=docs
        )
        response_path = self.paths.responses / f"{request_id}.json"

        if response_path.exists():
            raw = response_path.read_text(encoding="utf-8")
            try:
                parsed = schema.model_validate_json(raw)
            except ValidationError as error:
                raise ValueError(
                    f"Queued answer {request_id} does not satisfy {schema.__name__}: "
                    f"{error}"
                ) from error
            self._record_response_measurement(request_id, raw)
            # Zero tokens is honest — no API call happened. It also means the /admin
            # cost dashboard reads $0 for manual runs; the projected cost of the same
            # work lives in benchmarks/reports/token-cost/ instead.
            usage = LlmUsage(
                provider=MANUAL_PROVIDER, model=MANUAL_MODEL, input_tokens=0, output_tokens=0
            )
            return parsed, usage

        request_path = self._write_request(
            request_id,
            schema=schema,
            system=system,
            prompt=prompt,
            documents=docs,
            tier=tier,
            max_tokens=max_tokens,
        )
        logger.info("Queued LLM request %s (%s)", request_id, schema.__name__)
        raise LlmRequestPending(request_id, schema.__name__, request_path)
