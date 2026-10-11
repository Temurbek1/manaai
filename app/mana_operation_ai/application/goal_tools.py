"""Saved-evidence tools. Every lookup stays inside a verified application scope."""

import json

from app.mana_operation_ai.application.admin_service import OperationAdminService
from app.mana_operation_ai.application.chat_ports import ChatError
from app.mana_operation_ai.application.chat_service import _report_source, _verified_report_product
from app.mana_operation_ai.application.ports import Clock
from app.mana_operation_ai.domain.goals import GoalEvidence, OperationGoal
from app.mana_operation_ai.domain.models import AgentReport


class GoalEvidenceTools:
    def __init__(self, admin: OperationAdminService, clock: Clock) -> None:
        self._admin = admin
        self._clock = clock

    async def reports(self, goal: OperationGoal) -> list[AgentReport]:
        agents = (
            ["growth-agent", "retention-agent"]
            if goal.agent_id == "operations-orchestrator"
            else [goal.agent_id]
        )
        result: list[AgentReport] = []
        for agent in agents:
            reports, _ = await self._admin.list_reports(
                agent_id=agent, capability_key=None, limit=20, offset=0
            )
            result.extend(
                report for report in reports if _verified_report_product(report) == goal.product
            )
        return result

    async def inspect(self, goal: OperationGoal, allowed_reads: list[str]) -> str:
        reports = await self.reports(goal)
        sources = [_report_source(report, now=self._clock.now()) for report in reports[:12]]
        return json.dumps(
            {
                "product": goal.product,
                "saved_reports": [
                    {
                        "report_id": report.report_id,
                        "capability": report.capability_key,
                        "title": report.report_type[:120],
                        "collected_at": source.collected_at.isoformat()
                        if source.collected_at
                        else None,
                        "freshness": source.refresh_status,
                    }
                    for report, source in zip(reports[:12], sources, strict=True)
                ],
                "catalog_bounded": True,
                "more_references_omitted": len(reports) > 12,
                "allowed_confirmed_reads": allowed_reads,
                "notes": [
                    "Saved reports are scoped; absence here does not prove an empty database.",
                    "Unverified live bindings are not available for collection.",
                    "Parent behavior is not child inventory; tariffs are not payments.",
                    "No payment-confirmed regional orders capability is implemented.",
                ],
            },
            ensure_ascii=False,
        )

    async def read(self, goal: OperationGoal, report_id: str) -> GoalEvidence:
        report = next(
            (item for item in await self.reports(goal) if item.report_id == report_id), None
        )
        if report is None:
            raise ChatError("Отчёт недоступен в проверенной области этого приложения.")
        source = _report_source(report, now=self._clock.now())
        shortened = (
            len(report.human_readable) > 5000
            or len(report.data_quality_notes) > 9
            or any(len(note) > 300 for note in report.data_quality_notes[:9])
        )
        return GoalEvidence(
            report_id=report.report_id,
            capability_key=report.capability_key,
            product=goal.product,
            collected_at=source.collected_at,
            fresh_until=source.fresh_until,
            refresh_status=source.refresh_status,
            shortened=shortened,
            summary=report.human_readable[:5000],
            limitations=[note[:300] for note in report.data_quality_notes[:9]]
            + (["Evidence shortened; complete coverage cannot be assumed."] if shortened else []),
        )
