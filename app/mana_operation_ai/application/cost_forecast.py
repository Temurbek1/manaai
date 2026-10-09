from decimal import Decimal

from pydantic import Field

from app.mana_operation_ai.domain.cost_control import LlmRateCard
from app.mana_operation_ai.domain.models import DomainModel


class ForecastWorkload(DomainModel):
    """Capacity assumptions, not enabled schedules or measured production usage."""

    products: int = Field(default=2, ge=1, le=2)
    shared_refreshes_per_day: int = Field(default=4, ge=0, le=4)
    analyses_per_product_refresh: int = Field(default=4, ge=0, le=4)
    firestore_reads_per_day: int = Field(default=50_000, ge=0)
    average_response_bytes_per_document: int = Field(default=5120, ge=0)
    chat_calls_per_day: int = Field(default=20, ge=0)
    complex_calls_per_day: int = Field(default=1, ge=0)
    scheduled_input_tokens: int = Field(default=6000, ge=0)
    scheduled_output_tokens: int = Field(default=2000, ge=0)
    chat_input_tokens: int = Field(default=8000, ge=0)
    chat_output_tokens: int = Field(default=2000, ge=0)
    complex_input_tokens: int = Field(default=8000, ge=0)
    complex_output_tokens: int = Field(default=4000, ge=0)
    goals_per_day: int = Field(default=0, ge=0)
    goal_steps_per_goal: int = Field(default=6, ge=3, le=12)
    goal_input_tokens_per_step: int = Field(default=8000, ge=0, le=272_000)
    goal_output_tokens_per_step: int = Field(default=4096, ge=0, le=8192)
    goal_budget_microusd: int = Field(default=500_000, ge=50_000, le=2_000_000)
    document_usd_per_100k: Decimal = Field(default=Decimal("0.06"), ge=0)
    response_usd_per_gib: Decimal = Field(default=Decimal("0.12"), ge=0)
    reserve_fraction: Decimal = Field(default=Decimal("0.25"), ge=0)
    full_scan_documents: int = Field(default=1_537_582, ge=0)


def forecast(
    workload: ForecastWorkload,
    *,
    ordinary_rate_card: LlmRateCard | None = None,
    goal_rate_card: LlmRateCard | None = None,
) -> dict[str, object]:
    # Prices fetched from the official standard short-context pricing page on
    # 2026-10-09. Forecasting these models does NOT choose or configure them.
    ordinary = ordinary_rate_card or _sol_rate_card()
    goal_model = goal_rate_card or _sol_rate_card()
    complex_model = LlmRateCard(
        model="gpt-6-astra",
        input_usd_per_million="10",
        cached_input_usd_per_million="1",
        cache_write_usd_per_million="12.50",
        output_usd_per_million="50",
    )
    calls = (
        workload.products
        * workload.shared_refreshes_per_day
        * workload.analyses_per_product_refresh
    )
    data_reads = (
        Decimal(workload.firestore_reads_per_day) * workload.document_usd_per_100k / 100_000
    )
    data_transfer = (
        Decimal(workload.firestore_reads_per_day * workload.average_response_bytes_per_document)
        / (1024**3)
        * workload.response_usd_per_gib
    )
    goal_calls = workload.goals_per_day * workload.goal_steps_per_goal
    goal_per_step = goal_model.reserve_microusd(
        input_tokens=workload.goal_input_tokens_per_step,
        output_tokens=workload.goal_output_tokens_per_step,
    )
    goal_per_goal = goal_per_step * workload.goal_steps_per_goal
    entries = {
        "firestore_document_reads": data_reads,
        "firestore_payload_transfer": data_transfer,
        "ga4_standard_aggregate_api": Decimal("0"),
        "scheduled_analysis_capacity": Decimal(calls)
        * ordinary.reserve_microusd(
            input_tokens=workload.scheduled_input_tokens,
            output_tokens=workload.scheduled_output_tokens,
        )
        / 1_000_000,
        "interactive_analysis_capacity": Decimal(workload.chat_calls_per_day)
        * ordinary.reserve_microusd(
            input_tokens=workload.chat_input_tokens,
            output_tokens=workload.chat_output_tokens,
        )
        / 1_000_000,
        "complex_analysis_capacity": Decimal(workload.complex_calls_per_day)
        * complex_model.reserve_microusd(
            input_tokens=workload.complex_input_tokens,
            output_tokens=workload.complex_output_tokens,
        )
        / 1_000_000,
        "goal_analysis_capacity": Decimal(goal_calls * goal_per_step) / 1_000_000,
    }
    total = sum(entries.values(), Decimal("0"))
    reserve = total * workload.reserve_fraction
    data_only = data_reads + data_transfer
    full_scan_daily = (
        Decimal(workload.full_scan_documents * workload.shared_refreshes_per_day)
        * workload.document_usd_per_100k
        / 100_000
    )
    return {
        "schema_version": "operation-cost-forecast-v2",
        "pricing_checked_on": "2026-10-09",
        "ordinary_rate_card_basis": "explicit_input_not_independently_verified"
        if ordinary_rate_card is not None
        else "documented_capacity_default",
        "live_provider_calls": 0,
        "status": "conditional_capacity_forecast_not_invoice_or_enabled_runtime",
        "assumptions": workload.model_dump(mode="json"),
        "rate_cards_not_runtime_configuration": {
            "ordinary": ordinary.model_dump(mode="json"),
            "complex": complex_model.model_dump(mode="json"),
            "goals": goal_model.model_dump(mode="json"),
        },
        "goal_rate_card_basis": "explicit_input_not_independently_verified"
        if goal_rate_card is not None
        else "documented_capacity_default",
        "llm_calls_per_day_capacity": calls
        + workload.chat_calls_per_day
        + workload.complex_calls_per_day
        + goal_calls,
        "goal_capacity": {
            "calls_per_day": goal_calls,
            "cost_per_step_microusd": goal_per_step,
            "cost_per_goal_microusd": goal_per_goal,
            "fits_per_goal_admission_budget": goal_per_goal <= workload.goal_budget_microusd,
            "goal_admission_envelope_usd": _periods(
                Decimal(workload.goals_per_day * workload.goal_budget_microusd) / 1_000_000
            ),
            "input_tokens_per_day": goal_calls * workload.goal_input_tokens_per_step,
            "output_tokens_per_day": goal_calls * workload.goal_output_tokens_per_step,
        },
        "line_items_usd": {name: _periods(amount) for name, amount in entries.items()},
        "total_without_reserve_usd": _periods(total),
        "reserve_usd": _periods(reserve),
        "total_with_reserve_usd": _periods(total + reserve),
        "data_only_usd": _periods(data_only),
        "data_only_with_reserve_usd": _periods(data_only * (1 + workload.reserve_fraction)),
        "baseline_full_scans_document_reads_only_usd": _periods(full_scan_daily),
        "planning_references_usd_per_30_days": {"data": "2", "data_and_ai": "90"},
        "planning_reference_comparison": {
            "data_with_reserve_fits_2_usd": data_only * (1 + workload.reserve_fraction)
            <= Decimal("2") / 30,
            "total_with_reserve_fits_90_usd": total + reserve <= Decimal("90") / 30,
        },
        "limitations": [
            "50,000 reads/day and 5 KiB/document are assumptions, not measured change volume.",
            "Firestore automatic historical/prefix collection is disabled pending "
            "a verified delta contract.",
            f"{calls} scheduled analyses/day are capacity assumptions, "
            "not implemented agent handlers or enabled schedules.",
            "Current operational chat model remains gpt-5.4-nano; planned models require "
            "quality evaluation before selection.",
            "Goals use a separate model/rate card. One goal is multiple calls, not one "
            "interactive call. Do not count the same work as both chat and Goals.",
            "Goal input/output are per-step assumptions, including reasoning output. "
            "The single synthetic quality check is not a production workload average.",
            "Nominal goal cost is not clipped to its admission budget: if it exceeds "
            "that budget, the planned steps may stop before delivering the result.",
            "Goal admission envelopes are separate ceilings, not extra line items. "
            "Shared daily/monthly limits, byte-based reservations, other consumers and "
            "unknown holds may refuse this workload even when the nominal forecast fits.",
            "Goals reuse saved reports by default. Additional explicitly confirmed source "
            "reads must be included in the total data assumptions; no free extra reads.",
            "No cache-hit discounts or shared Firebase free allowance are assumed.",
            "Retries and uncertain charges must fit capacity limits; "
            "they are not free additional calls.",
            "Annual values use 365 days; monthly values use 30 days, "
            "not twelve equal calendar months.",
        ],
        "excluded_costs": [
            "Existing servers, Firestore storage and writes, index/rules-dependent reads",
            "Backend database work, upstream subscription fees, taxes and network headers",
            "Audio moderation, marketing actions, BigQuery exports, "
            "tools and other client services",
        ],
        "sources": [
            "https://developers.openai.com/api/docs/pricing",
            "https://firebase.google.com/docs/firestore/billing-example",
            "https://firebase.google.com/docs/firestore/pricing",
            "https://developers.google.com/analytics/devguides/reporting/data/v1/quotas",
        ],
    }


def _sol_rate_card() -> LlmRateCard:
    return LlmRateCard(
        model="gpt-6.1-sol",
        input_usd_per_million="2",
        cached_input_usd_per_million="0.10",
        cache_write_usd_per_million="2.50",
        output_usd_per_million="10",
    )


def _periods(daily: Decimal) -> dict[str, str]:
    return {
        "daily": str(daily.quantize(Decimal("0.000001"))),
        "monthly_30_days": str((daily * 30).quantize(Decimal("0.000001"))),
        "yearly_365_days": str((daily * 365).quantize(Decimal("0.000001"))),
    }
