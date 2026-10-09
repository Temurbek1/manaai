from datetime import UTC, datetime
from decimal import ROUND_CEILING, Decimal
from enum import StrEnum

from pydantic import Field, field_validator

from app.mana_operation_ai.domain.models import DomainModel


class ProductScope(StrEnum):
    MANA = "mana"
    REC360 = "360rec"
    UNVERIFIED = "unverified"


class ResourceUsage(DomainModel):
    """Conservative admission units, not a replacement for provider billing."""

    document_reads: int = Field(default=0, ge=0)
    response_bytes: int = Field(default=0, ge=0)
    provider_requests: int = Field(default=0, ge=0)
    llm_calls: int = Field(default=0, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    data_microusd: int = Field(default=0, ge=0)
    llm_microusd: int = Field(default=0, ge=0)

    def plus(self, other: "ResourceUsage") -> "ResourceUsage":
        return ResourceUsage.model_validate(
            {key: value + getattr(other, key) for key, value in self.model_dump().items()},
        )

    def minus(self, other: "ResourceUsage") -> "ResourceUsage":
        return ResourceUsage.model_validate(
            {key: value - getattr(other, key) for key, value in self.model_dump().items()},
        )

    def exceeds(self, limit: "ResourceUsage") -> list[str]:
        return [key for key, value in self.model_dump().items() if value > getattr(limit, key)]


class CostLimits(DomainModel):
    daily: ResourceUsage
    monthly: ResourceUsage


class CostAttribution(DomainModel):
    product: ProductScope
    source: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9_.-]+$")
    agent_id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9_.-]+$")
    capability_key: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9_.-]+$")


class CostReservation(DomainModel):
    reservation_id: str
    reserved_at: datetime
    usage: ResourceUsage
    attribution: CostAttribution

    @field_validator("reserved_at")
    @classmethod
    def require_aware_time(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("Cost accounting requires a timezone-aware clock")
        return value.astimezone(UTC)


class CostPeriod(DomainModel):
    period_key: str
    usage: ResourceUsage


class DataRateCard(DomainModel):
    """Explicit regional assumptions; provider invoices remain authoritative."""

    document_usd_per_100k: Decimal = Field(default=Decimal("0"), ge=0)
    response_usd_per_gib: Decimal = Field(default=Decimal("0"), ge=0)

    def microusd(self, *, documents: int, response_bytes: int) -> int:
        if min(documents, response_bytes) < 0:
            raise ValueError("Data usage cannot be negative")
        amount = (
            Decimal(documents) * self.document_usd_per_100k / 100_000
            + Decimal(response_bytes) * self.response_usd_per_gib / (1024**3)
        ) * 1_000_000
        return int(amount.to_integral_value(rounding=ROUND_CEILING))


class LlmRateCard(DomainModel):
    model: str
    input_usd_per_million: Decimal = Field(ge=0)
    cached_input_usd_per_million: Decimal = Field(ge=0)
    cache_write_usd_per_million: Decimal = Field(ge=0)
    output_usd_per_million: Decimal = Field(ge=0)

    def reserve_microusd(self, *, input_tokens: int, output_tokens: int) -> int:
        worst_input = max(
            self.input_usd_per_million,
            self.cached_input_usd_per_million,
            self.cache_write_usd_per_million,
        )
        return self._round(input_tokens * worst_input + output_tokens * self.output_usd_per_million)

    def actual_microusd(
        self, *, input_tokens: int, output_tokens: int, cached_tokens: int, cache_write_tokens: int
    ) -> int:
        if min(input_tokens, output_tokens, cached_tokens, cache_write_tokens) < 0:
            raise ValueError("Provider usage cannot be negative")
        ordinary = input_tokens - cached_tokens - cache_write_tokens
        if ordinary < 0:
            raise ValueError("Provider cache counts exceed total input tokens")
        return self._round(
            ordinary * self.input_usd_per_million
            + cached_tokens * self.cached_input_usd_per_million
            + cache_write_tokens * self.cache_write_usd_per_million
            + output_tokens * self.output_usd_per_million,
        )

    @staticmethod
    def _round(value: Decimal) -> int:
        # USD per million tokens == micro-USD per token.
        return int(value.to_integral_value(rounding=ROUND_CEILING))
