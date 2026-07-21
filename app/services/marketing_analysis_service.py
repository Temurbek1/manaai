import json
import uuid
from datetime import UTC, datetime

from app.schemas.marketing import (
    MarketingAnalysisReport,
    MarketingAnalysisRequest,
    MarketingAnalysisResponse,
    MarketingFinding,
    MarketingPatternsRequest,
)
from app.services.marketing_metrics import MarketingMetricsBuilder
from app.services.marketing_pattern_service import MarketingPatternService
from app.services.marketing_repository import MarketingRepository
from app.services.openai_service import OpenAIService

MARKETING_ANALYST_SYSTEM_PROMPT = """
You are a senior performance marketing analyst for Meta Ads data.

Use only the supplied KPI evidence and raw samples. Do not invent spend,
conversion, audience, creative, or attribution facts. When evidence is missing,
state what is missing and suggest the next raw-data pull or breakdown.

Return a concise analytics report for operators: explain what changed, what is
working, what is wasting budget, what should be tested next, and which raw data
would validate the recommendation.
"""


class MarketingAnalysisService:
    def __init__(
        self,
        *,
        repository: MarketingRepository,
        metrics_builder: MarketingMetricsBuilder,
        pattern_service: MarketingPatternService,
        openai_service: OpenAIService,
    ) -> None:
        self._repository = repository
        self._metrics_builder = metrics_builder
        self._pattern_service = pattern_service
        self._openai_service = openai_service

    async def analyze(self, request: MarketingAnalysisRequest) -> MarketingAnalysisResponse:
        records, total = await self._repository.list_raw_records(
            account_ids=request.account_ids,
            entity_types=["insight"],
            date_start=request.date_start,
            date_stop=request.date_stop,
            limit=request.max_records,
            offset=0,
        )
        kpis = self._metrics_builder.build_rows(records)
        kpi_summary = self._metrics_builder.summarize(kpis)
        pattern_response = await self._pattern_service.detect(
            MarketingPatternsRequest(
                account_ids=request.account_ids,
                date_start=request.date_start,
                date_stop=request.date_stop,
                max_records=request.max_records,
            ),
        )
        generated_at = datetime.now(UTC)

        if not records or not kpis:
            report = _empty_report(total=total)
            model = "deterministic"
        else:
            report = await self._openai_service.create_structured_response(
                text_format=MarketingAnalysisReport,
                system_prompt=MARKETING_ANALYST_SYSTEM_PROMPT,
                user_input=_analysis_context_json(
                    request=request,
                    total_matching_records=total,
                    response_record_limit=request.max_records,
                    kpi_summary=kpi_summary.model_dump(mode="json"),
                    kpis=[row.model_dump(mode="json") for row in kpis],
                    patterns=[
                        pattern.model_dump(mode="json") for pattern in pattern_response.patterns
                    ],
                    raw_samples=[
                        {
                            "id": record.id,
                            "entity_type": record.entity_type,
                            "provider_record_id": record.provider_record_id,
                            "account_id": record.account_id,
                            "payload": record.payload,
                        }
                        for record in records[:10]
                    ]
                    if request.include_raw_samples
                    else [],
                ),
            )
            model = self._openai_service.model_name

        response = MarketingAnalysisResponse(
            report_id=str(uuid.uuid4()),
            generated_at=generated_at,
            model=model,
            source_record_count=len(records),
            source_record_ids=[record.id for record in records],
            kpi_summary=kpi_summary,
            kpis=kpis,
            patterns=pattern_response.patterns,
            report=report,
        )
        await self._repository.save_analysis_report(request=request, response=response)
        return response


def _analysis_context_json(
    *,
    request: MarketingAnalysisRequest,
    total_matching_records: int,
    response_record_limit: int,
    kpi_summary: dict[str, object],
    kpis: list[dict[str, object]],
    patterns: list[dict[str, object]],
    raw_samples: list[dict[str, object]],
) -> str:
    top_kpis = sorted(kpis, key=_spend_sort_value, reverse=True)[:100]
    return json.dumps(
        {
            "request": request.model_dump(mode="json"),
            "total_matching_records": total_matching_records,
            "response_record_limit": response_record_limit,
            "kpi_summary": kpi_summary,
            "top_kpis_by_spend": top_kpis,
            "deterministic_patterns": patterns,
            "raw_samples": raw_samples,
            "analysis_rules": [
                "Use KPI rows as the source of truth.",
                "Use deterministic_patterns as precomputed evidence, not as final truth.",
                "Prefer recommendations with numeric evidence.",
                (
                    "Mention data quality gaps when conversion actions, values, "
                    "or breakdowns are missing."
                ),
                "Suggest raw-data follow-up queries for suspicious patterns.",
            ],
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _spend_sort_value(row: dict[str, object]) -> float:
    value = row.get("spend")
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return 0.0
    return 0.0


def _empty_report(*, total: int) -> MarketingAnalysisReport:
    return MarketingAnalysisReport(
        executive_summary="No Meta Ads insight records matched the requested filters.",
        health_score=0,
        key_findings=[
            MarketingFinding(
                type="next_step",
                title="Load marketing insight data",
                explanation=(
                    f"The storage query matched {total} raw records, but none contained usable "
                    "insight KPI payloads for analysis."
                ),
                evidence=["No insight KPI rows were built from the selected raw records."],
                confidence="high",
                recommended_action=(
                    "Run a Meta sync for the required ad accounts/date range or upload raw "
                    "insight exports through the raw ingestion endpoint."
                ),
            ),
        ],
        prioritized_actions=[
            "Sync Meta insights at campaign, adset, and ad levels.",
            "Verify conversion action mappings in MARKETING_CONVERSION_ACTION_TYPES.",
        ],
        data_quality_notes=[
            "No KPI-bearing insight rows are available for this analysis request.",
        ],
        raw_data_followups=[
            "Pull /insights with spend, impressions, clicks, actions, and action_values.",
        ],
    )
