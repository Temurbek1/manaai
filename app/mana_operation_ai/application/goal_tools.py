"""Saved-evidence tools. Every lookup stays inside a verified application scope."""

import json

from app.mana_operation_ai.application.admin_service import OperationAdminService
from app.mana_operation_ai.application.chat_ports import ChatError
from app.mana_operation_ai.application.chat_service import _report_source, _verified_report_product
from app.mana_operation_ai.application.goal_ports import GoalRepository
from app.mana_operation_ai.application.ports import Clock
from app.mana_operation_ai.domain.goals import GoalEvidence, OperationGoal
from app.mana_operation_ai.domain.models import AgentReport


class GoalEvidenceTools:
    def __init__(self, admin: OperationAdminService, clock: Clock, tasks: GoalRepository) -> None:
        self._admin = admin
        self._clock = clock
        self._tasks = tasks

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
        report = await self._admin.get_report(report_id)
        allowed_agents = (
            {"growth-agent", "marketing-agent", "retention-agent"}
            if goal.agent_id == "operations-orchestrator"
            else {goal.agent_id}
        )
        if (
            report is None
            or report.agent_id not in allowed_agents
            or _verified_report_product(report) != goal.product
        ):
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

    async def find_tasks(
        self,
        owner: str,
        goal: OperationGoal,
        *,
        query: str,
        cursor: str | None,
    ) -> str:
        page = await self._tasks.find_saved_tasks(
            owner,
            goal.topic_id,
            goal.product,
            before=goal.created_at,
            query=query,
            cursor=cursor,
        )
        return json.dumps(
            {
                "product": goal.product,
                "tasks": [
                    {
                        "task_id": item.goal_id,
                        "objective": item.request.objective[:160],
                        "objective_shortened": len(item.request.objective) > 160,
                        "status": item.status,
                        "updated_at": item.updated_at.isoformat(),
                    }
                    for item in page.goals
                ],
                "next_cursor": page.next_cursor,
                "historical_context_only": True,
                "notes": [
                    "No fresh measurement, source-read approval or action grant is inherited."
                ],
            },
            ensure_ascii=False,
        )

    async def read_task(self, owner: str, goal: OperationGoal, task_id: str, offset: int) -> str:
        past = await self._tasks.saved_task(
            owner,
            goal.topic_id,
            goal.product,
            task_id,
            before=goal.created_at,
        )
        if offset > len(past.result):
            raise ChatError("Смещение выходит за сохранённый результат задачи.")
        text = past.result[offset : offset + 4000]
        payload = {
            "task_id": past.goal_id,
            "product": past.product,
            "status": past.status,
            "updated_at": past.updated_at.isoformat(),
            "offset": offset,
            "result": text,
            "result_total_characters": len(past.result),
            "next_offset": offset + len(text) if offset + len(text) < len(past.result) else None,
            "result_shortened": offset != 0 or len(text) != len(past.result),
            "historical_context_only": True,
            "source_references": [
                {
                    "report_id": item.report_id,
                    "capability": item.capability_key,
                    "collected_at": item.collected_at.isoformat() if item.collected_at else None,
                    "fresh_until": item.fresh_until.isoformat() if item.fresh_until else None,
                    "shortened": item.shortened,
                }
                for item in past.evidence
                if item.product == goal.product
            ],
            "notes": [
                "This is a historical public analysis, not new evidence or permission.",
                "Read original saved reports separately before using their facts.",
                "Budgets, approvals, instructions and provider work are not inherited.",
            ],
        }
        while len(json.dumps(payload, ensure_ascii=False)) > 7800:
            if len(text) <= 1:
                raise ChatError("Ссылки прошлой задачи превышают безопасный размер контекста.")
            text = text[: len(text) // 2]
            payload.update(result=text, next_offset=offset + len(text), result_shortened=True)
        return json.dumps(payload, ensure_ascii=False)
