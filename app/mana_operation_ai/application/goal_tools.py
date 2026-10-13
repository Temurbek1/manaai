"""Saved-evidence tools. Every lookup stays inside a verified application scope."""

import hashlib
import json
from typing import Literal

from app.mana_operation_ai.application.admin_service import OperationAdminService
from app.mana_operation_ai.application.analytics_scope import shared_mana_analytics
from app.mana_operation_ai.application.chat_ports import ChatError
from app.mana_operation_ai.application.chat_service import _report_source, _verified_report_product
from app.mana_operation_ai.application.goal_ports import GoalRepository
from app.mana_operation_ai.application.ports import Clock
from app.mana_operation_ai.application.report_catalog import (
    REPORT_CATALOG_PAGE_SIZE,
    SavedReportCatalogQuery,
    catalog_position,
    catalog_report_matches,
)
from app.mana_operation_ai.domain.goals import GoalEvidence, OperationGoal, ReportReadProgress
from app.mana_operation_ai.domain.models import AgentReport


class SavedToolInputError(ChatError):
    """A verified local paging mistake, never a policy denial or uncertain I/O."""

    def __init__(
        self,
        code: Literal["invalid_offset", "noncontiguous_page", "report_changed"],
        *,
        expected_offset: int,
    ) -> None:
        message = {
            "invalid_offset": "Смещение выходит за сохранённый текст. Используйте expected_offset.",
            "noncontiguous_page": (
                "Часть отчёта не загружена по порядку. Используйте expected_offset."
            ),
            "report_changed": "Сохранённый отчёт изменился. Для нового снимка начните с нуля.",
        }[code]
        super().__init__(message)
        self.code = code
        self.expected_offset = expected_offset

    def receipt(self) -> str:
        return json.dumps(
            {
                "code": self.code,
                "message": str(self),
                "expected_offset": self.expected_offset,
                "new_evidence_loaded": False,
                "local_saved_text_only": True,
                "permission_granted": False,
            },
            ensure_ascii=False,
        )


class GoalEvidenceTools:
    def __init__(self, admin: OperationAdminService, clock: Clock, tasks: GoalRepository) -> None:
        self._admin = admin
        self._clock = clock
        self._tasks = tasks

    async def reports(self, goal: OperationGoal) -> list[AgentReport]:
        agents = (
            ["growth-agent", "retention-agent"]
            if goal.agent_id == "operations-orchestrator"
            else list(dict.fromkeys([goal.agent_id, "retention-agent"]))
        )
        result: list[AgentReport] = []
        for agent in agents:
            reports, _ = await self._admin.list_reports(
                agent_id=agent, capability_key=None, limit=20, offset=0
            )
            result.extend(
                report
                for report in reports
                if _verified_report_product(report) == goal.product
                and (
                    report.agent_id == goal.agent_id
                    or goal.agent_id == "operations-orchestrator"
                    or shared_mana_analytics(report)
                )
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

    async def find_reports(
        self,
        goal: OperationGoal,
        *,
        query: str,
        cursor: str | None,
        capability_key: str | None = None,
    ) -> str:
        """SQL discovery foundation; not yet exposed as a native model tool."""
        if goal.request.execution_mode != "agent":
            raise ChatError("Поиск отчётов требует рабочей среды агента.")
        agents = (
            {"growth-agent", "retention-agent"}
            if goal.agent_id == "operations-orchestrator"
            else {goal.agent_id, "retention-agent"}
        )
        identifiers = sorted(
            {identifier for agent in agents for identifier in self._admin.agent_identifiers(agent)}
        )
        search = SavedReportCatalogQuery(
            scope_id=goal.goal_id,
            product=goal.product,
            agent_ids=tuple(identifiers),
            before=goal.created_at,
            query=query,
            capability_key=capability_key,
        )
        page = await self._admin.repository.page_report_candidates(search, cursor=cursor)
        if len(page.reports) > REPORT_CATALOG_PAGE_SIZE:
            raise ChatError("Страница сохранённого каталога превышает разрешённый размер.", 503)
        if page.next_cursor is not None:
            position = catalog_position(search, page.next_cursor)
            if not page.reports or (
                position.report_id != page.reports[-1].report_id
                or position.created_at != page.reports[-1].created_at
            ):
                raise ChatError("Курсор каталога не соответствует возвращённой странице.", 503)
        reports = [
            report
            for report in page.reports
            if catalog_report_matches(search, report)
            and _verified_report_product(report) == goal.product
            and (
                report.agent_id in self._admin.agent_identifiers(goal.agent_id)
                or goal.agent_id == "operations-orchestrator"
                or shared_mana_analytics(report)
            )
        ]
        payload = {
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
                for report in reports
                for source in [_report_source(report, now=self._clock.now())]
            ],
            "next_cursor": page.next_cursor,
            "created_before": goal.created_at.isoformat(),
            "references_only": True,
            "loaded_into_evidence": False,
            "permission_granted": False,
            "notes": [
                "An empty page is not an empty database; follow next_cursor when present.",
                "Read original reports separately; references do not prove freshness or coverage.",
                "No new source call, read grant, budget or action is created by discovery.",
            ],
        }
        result = json.dumps(payload, ensure_ascii=False)
        if len(result) > 7800:
            raise ChatError(
                "Метаданные каталога превышают безопасный размер; страница не обрезана."
            )
        return result

    async def read(self, goal: OperationGoal, report_id: str) -> GoalEvidence:
        report = await self._report(goal, report_id)
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

    async def _report(self, goal: OperationGoal, report_id: str) -> AgentReport:
        report = await self._admin.get_report(report_id)
        allowed_agents = (
            {"growth-agent", "marketing-agent", "retention-agent"}
            if goal.agent_id == "operations-orchestrator"
            else {goal.agent_id}
        )
        if (
            report is None
            or (report.agent_id not in allowed_agents and not shared_mana_analytics(report))
            or _verified_report_product(report) != goal.product
        ):
            raise ChatError("Отчёт недоступен в проверенной области этого приложения.")
        return report

    async def read_page(
        self, goal: OperationGoal, report_id: str, offset: int
    ) -> tuple[GoalEvidence, str]:
        if goal.request.execution_mode != "agent":
            raise ChatError("Чтение отчёта частями требует рабочей среды агента.")
        report = await self._report(goal, report_id)
        text = report.human_readable
        if len(text) > 32000:
            raise ChatError("Отчёт превышает лимит чтения: 32 000 символов. Текст не обрезан.")
        prior = next((item for item in goal.evidence if item.report_id == report_id), None)
        progress = prior.report_read_progress if prior is not None else None
        source = _report_source(report, now=self._clock.now())
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "report": report.model_dump(mode="json"),
                    "product": goal.product,
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode()
        ).hexdigest()
        if offset and progress is not None and progress.source_fingerprint != fingerprint:
            raise SavedToolInputError("report_changed", expected_offset=0)
        if offset > len(text):
            raise SavedToolInputError(
                "invalid_offset", expected_offset=progress.next_offset if progress else 0
            )
        if offset and (progress is None or progress.next_offset != offset):
            raise SavedToolInputError(
                "noncontiguous_page", expected_offset=progress.next_offset if progress else 0
            )
        page = text[offset : offset + 4000]
        payload = {
            "report_id": report_id,
            "offset": offset,
            "text": page,
            "total_characters": len(text),
            "next_offset": offset + len(page) if offset + len(page) < len(text) else None,
            "loaded_into_evidence": True,
            "reading_not_population_coverage": True,
        }
        while len(json.dumps(payload, ensure_ascii=False)) > 7800:
            page = page[: len(page) // 2]
            payload.update(text=page, next_offset=offset + len(page))
        summary = (prior.summary if offset and prior is not None else "") + page
        notes_complete = len(report.data_quality_notes) <= 9 and all(
            len(note) <= 300 for note in report.data_quality_notes
        )
        shortened = len(summary) != len(text) or not notes_complete
        item = GoalEvidence(
            report_id=report.report_id,
            capability_key=report.capability_key,
            product=goal.product,
            collected_at=source.collected_at,
            fresh_until=source.fresh_until,
            refresh_status=source.refresh_status,
            shortened=shortened,
            summary=summary,
            limitations=[note[:300] for note in report.data_quality_notes[:9]]
            + (["Evidence shortened; complete coverage cannot be assumed."] if shortened else []),
            report_read_progress=ReportReadProgress(
                source_fingerprint=fingerprint,
                full_text_sha256=hashlib.sha256(text.encode()).hexdigest(),
                loaded_text_sha256=hashlib.sha256(summary.encode()).hexdigest(),
                total_characters=len(text),
                next_offset=len(summary),
                quality_notes_complete=notes_complete,
            ),
        )
        return item, json.dumps(payload, ensure_ascii=False)

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
            raise SavedToolInputError("invalid_offset", expected_offset=0)
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
