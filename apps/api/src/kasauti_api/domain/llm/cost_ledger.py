"""Per-feature token-cost ledger. Every LLM/embedding call records one row —
this feeds the founder cost dashboard (llm_cost_daily_by_feature) in /admin."""

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from kasauti_api.db.models.cost_ledger import LlmFeature, LlmUsageEvent
from kasauti_api.domain.llm.provider import LlmUsage

# USD per 1M tokens (input, output). Sonnet 5 uses the $3/$15 sticker price —
# the 2026 introductory discount is ignored so the ledger never understates cost.
PRICING_PER_MTOK: dict[str, tuple[Decimal, Decimal]] = {
    "claude-haiku-4-5": (Decimal("1.00"), Decimal("5.00")),
    "claude-sonnet-5": (Decimal("3.00"), Decimal("15.00")),
    "claude-opus-4-8": (Decimal("5.00"), Decimal("25.00")),
    "voyage-multilingual-2": (Decimal("0.12"), Decimal("0")),
}


def compute_cost_usd(usage: LlmUsage) -> Decimal:
    input_rate, output_rate = PRICING_PER_MTOK.get(usage.model, (Decimal("0"), Decimal("0")))
    return (
        input_rate * usage.input_tokens + output_rate * usage.output_tokens
    ) / Decimal(1_000_000)


async def record_usage(
    session: AsyncSession,
    *,
    feature: LlmFeature,
    usage: LlmUsage,
    related_entity_type: str | None = None,
    related_entity_id: str | None = None,
) -> None:
    session.add(
        LlmUsageEvent(
            feature=feature,
            provider=usage.provider,
            model=usage.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cost_usd=compute_cost_usd(usage),
            related_entity_type=related_entity_type,
            related_entity_id=related_entity_id,
        )
    )
