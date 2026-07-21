from app.schemas.marketing import (
    MarketingAnalysisEvidenceBundleResponse,
    MarketingAnalysisReportSummary,
    MarketingAnalysisResponse,
)
from app.services.marketing_repository import MarketingRepository


class MarketingReportService:
    def __init__(self, *, repository: MarketingRepository) -> None:
        self._repository = repository

    async def list_reports(
        self,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[MarketingAnalysisReportSummary], int]:
        return await self._repository.list_analysis_reports(limit=limit, offset=offset)

    async def get_report(self, report_id: str) -> MarketingAnalysisResponse | None:
        return await self._repository.get_analysis_report(report_id)

    async def build_evidence_bundle(
        self,
        report_id: str,
    ) -> MarketingAnalysisEvidenceBundleResponse | None:
        report = await self._repository.get_analysis_report(report_id)
        if report is None:
            return None

        evidence_record_ids = collect_report_evidence_record_ids(report)
        raw_records = await self._repository.get_raw_records_by_ids(evidence_record_ids)
        found_record_ids = {record.id for record in raw_records}
        missing_record_ids = [
            record_id for record_id in evidence_record_ids if record_id not in found_record_ids
        ]

        return MarketingAnalysisEvidenceBundleResponse(
            report=report,
            raw_records=raw_records,
            missing_record_ids=missing_record_ids,
        )


def collect_report_evidence_record_ids(report: MarketingAnalysisResponse) -> list[str]:
    record_ids: list[str] = []
    _extend_unique(record_ids, report.source_record_ids)
    _extend_unique(record_ids, [row.record_id for row in report.kpis])

    for pattern in report.patterns:
        _extend_unique(record_ids, pattern.evidence_record_ids)

    for node in report.graph.nodes:
        _extend_unique(record_ids, node.source_record_ids)

    for edge in report.graph.edges:
        _extend_unique(record_ids, edge.source_record_ids)

    return record_ids


def _extend_unique(target: list[str], values: list[str]) -> None:
    seen = set(target)
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        target.append(value)
