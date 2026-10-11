"""Explicit human decisions delegate to the existing owning-domain action lifecycle."""

import hashlib
import json
from datetime import datetime
from uuid import uuid4

from pydantic import ValidationError

from app.mana_operation_ai.application.action_lifecycle import (
    ActionReconciliationRequiredError,
    ActionSafetyError,
    ApprovalPermissionError,
    StaleProposalError,
)
from app.mana_operation_ai.application.admin_service import ActorContext, OperationAdminService
from app.mana_operation_ai.application.chat_ports import ChatError, ChatRepository
from app.mana_operation_ai.application.evidence_freshness import evidence_freshness_failure
from app.mana_operation_ai.application.ports import Clock, ConcurrentOperationError
from app.mana_operation_ai.application.workspace_action_ports import WorkspaceActionStore
from app.mana_operation_ai.domain.enums import (
    ActionStatus,
    ApprovalStatus,
    ExecutionStatus,
    GrowthActionType,
    ProviderMode,
    UserRole,
    VerificationStatus,
)
from app.mana_operation_ai.domain.growth import GrowthFunnelSnapshot
from app.mana_operation_ai.domain.models import ActionProposal, CreateExperimentActionParameters
from app.mana_operation_ai.domain.workspace_actions import (
    SANDBOX_MANA_FUNNEL_SCOPE,
    WorkspaceActionDecision,
    WorkspaceActionHistory,
    WorkspaceActionPage,
    WorkspaceActionReceipt,
    WorkspaceActionView,
)


class WorkspaceActionService:
    def __init__(
        self,
        *,
        admin: OperationAdminService,
        chats: ChatRepository,
        store: WorkspaceActionStore,
        clock: Clock,
        enabled: bool,
        allow_self_approval: bool,
        evidence_max_age_seconds: int = 21_600,
    ) -> None:
        self._admin = admin
        self._chats = chats
        self._store = store
        self._clock = clock
        self._enabled = enabled
        self._allow_self_approval = allow_self_approval
        self._evidence_max_age_seconds = evidence_max_age_seconds

    async def _access(self, owner: str, topic_id: str, turn_id: str) -> None:
        if not self._enabled:
            raise ChatError("Согласование действий в рабочем режиме отключено.", 503)
        topic = await self._chats.topic(owner, topic_id)
        if topic.product != "mana" or topic.agent_id not in (
            "growth-agent",
            "operations-orchestrator",
        ):
            raise ChatError("Для этой темы нет подключённых исполнителей.", 403)
        turn = await self._chats.turn(owner, topic_id, turn_id)
        if (
            turn.execution_mode != "agent"
            or turn.status != "completed"
            or turn.next_action != "approvals"
        ):
            raise ChatError("Это сообщение не запрашивало согласование действий.", 403)

    @staticmethod
    def _supported(proposal: ActionProposal) -> bool:
        return (
            proposal.agent_id == "growth-agent"
            and proposal.capability_key == "growth.funnel.analyze"
            and proposal.action_family == "growth_experiment"
            and proposal.provider == "fake_experiments"
            and proposal.provider_mode == ProviderMode.FAKE_EXECUTABLE
            and not proposal.execution_forbidden
            and proposal.action_type == GrowthActionType.CREATE_EXPERIMENT
            and isinstance(proposal.parameters, CreateExperimentActionParameters)
            and proposal.object_type == "experiment"
            and proposal.provider_object_id == proposal.parameters.experiment_key
        )

    async def _scoped(self, proposal: ActionProposal, *, fresh: bool = False) -> bool:
        if not self._supported(proposal):
            return False
        run = await self._admin.repository.get_run(proposal.run_id)
        if run is None or (run.agent_id, run.capability_key) != (
            proposal.agent_id,
            proposal.capability_key,
        ):
            return False
        snapshots = await self._admin.repository.list_snapshots(proposal.run_id)
        if not snapshots:
            return False
        snapshot = snapshots[-1]
        refs = snapshot.evidence_refs
        if (
            snapshot.provider != "normalized_growth_funnel"
            or snapshot.agent_id != proposal.agent_id
            or snapshot.capability_key != proposal.capability_key
            or len(refs) != 3
            or {ref.source for ref in refs}
            != {"fake_product_analytics", "fake_billing", "fake_attribution"}
            or any(ref.subject_scope != SANDBOX_MANA_FUNNEL_SCOPE for ref in refs)
        ):
            return False
        canonical = json.dumps(snapshot.payload, sort_keys=True, separators=(",", ":"))
        if hashlib.sha256(canonical.encode()).hexdigest() != snapshot.checksum:
            return False
        try:
            normalized = GrowthFunnelSnapshot.model_validate(snapshot.payload)
        except ValidationError:
            return False
        if normalized.evidence_refs != refs:
            return False
        now = self._clock.now()
        return not (
            fresh
            and (
                proposal.expires_at <= now
                or evidence_freshness_failure(
                    [snapshot], now=now, maximum_age_seconds=self._evidence_max_age_seconds
                )
                is not None
            )
        )

    @staticmethod
    def _fingerprint(proposal: ActionProposal, topic_id: str, turn_id: str) -> str:
        value = {
            "topic_id": topic_id,
            "turn_id": turn_id,
            "product": "mana",
            "proposal": proposal.model_dump(mode="json", exclude={"status"}),
        }
        return hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    async def _view(
        self,
        owner: str,
        topic_id: str,
        turn_id: str,
        proposal: ActionProposal,
        receipt: WorkspaceActionReceipt | None = None,
    ) -> WorkspaceActionView:
        if not isinstance(proposal.parameters, CreateExperimentActionParameters):
            raise ChatError("Неподдерживаемый тип действия.", 422)
        if receipt is not None and (
            receipt.request.fingerprint != self._fingerprint(proposal, topic_id, turn_id)
            or receipt.parameters != proposal.parameters
        ):
            raise ChatError("Параметры сохранённого решения изменились. Требуется проверка.")
        approval = await self._admin.repository.get_approval_for_proposal(proposal.proposal_id)
        execution = await self._admin.repository.get_execution_for_proposal(proposal.proposal_id)
        verification = (
            (await self._admin.repository.get_verification_for_execution(execution.execution_id))
            if execution is not None
            else None
        )
        return WorkspaceActionView(
            proposal_id=proposal.proposal_id,
            status=proposal.status,
            parameters=proposal.parameters,
            reasoning=proposal.reasoning[:2000],
            expected_effect=proposal.expected_effect[:2000],
            risks=proposal.risks[:10],
            expires_at=proposal.expires_at,
            fingerprint=self._fingerprint(proposal, topic_id, turn_id),
            self_approval_forbidden=(
                not self._allow_self_approval
                and approval is not None
                and approval.requested_by == owner
            ),
            receipt=receipt,
            execution_status=execution.status if execution else None,
            verification_status=verification.status if verification else None,
        )

    async def page(self, owner: str, topic_id: str, turn_id: str) -> WorkspaceActionPage:
        await self._access(owner, topic_id, turn_id)
        receipts = await self._store.receipts(owner, topic_id, turn_id=turn_id)
        items: list[WorkspaceActionView] = []
        for receipt in receipts:
            proposal = await self._admin.repository.get_proposal(receipt.proposal_id)
            if proposal is not None and self._supported(proposal):
                items.append(await self._view(owner, topic_id, turn_id, proposal, receipt))
        candidates, total = await self._admin.repository.list_proposals(
            status=ActionStatus.AWAITING_APPROVAL, limit=20
        )
        saved = {item.proposal_id for item in items}
        for proposal in candidates:
            if proposal.proposal_id not in saved and await self._scoped(proposal, fresh=True):
                items.append(await self._view(owner, topic_id, turn_id, proposal))
        return WorkspaceActionPage(items=items[:3], more_omitted=len(items) > 3 or total > 20)

    async def decide(
        self,
        actor: ActorContext,
        topic_id: str,
        turn_id: str,
        proposal_id: str,
        request: WorkspaceActionDecision,
    ) -> WorkspaceActionView:
        if actor.role not in (UserRole.APPROVER, UserRole.ADMIN):
            raise ChatError("Нужны права согласования действий.", 403)
        await self._access(actor.actor_id, topic_id, turn_id)
        proposal = await self._admin.repository.get_proposal(proposal_id)
        if proposal is None:
            raise ChatError("Предложение не найдено.", 404)
        if not self._supported(proposal):
            raise ChatError("Источник или исполнитель не поддерживается в этой теме.", 403)
        saved = await self._store.get(actor.actor_id, topic_id, turn_id, proposal_id)
        if saved is not None:
            if saved.request != request:
                raise ChatError("Решение уже сохранено. Повторное выполнение запрещено.")
            return await self._view(actor.actor_id, topic_id, turn_id, proposal, saved)
        if not await self._scoped(proposal):
            raise ChatError("Привязка источника к приложению не подтверждена.", 403)
        if request.fingerprint != self._fingerprint(proposal, topic_id, turn_id):
            raise ChatError("Предложение изменилось. Обновите карточку перед решением.")
        approval = await self._admin.repository.get_approval_for_proposal(proposal_id)
        if (
            approval is None
            or approval.status != ApprovalStatus.PENDING
            or proposal.status != ActionStatus.AWAITING_APPROVAL
        ):
            raise ChatError("Нет ожидающего согласования. Обновите карточку.")
        if not self._allow_self_approval and approval.requested_by == actor.actor_id:
            raise ChatError("Нельзя согласовать собственное предложение.", 403)
        if approval.expires_at <= self._clock.now() or not await self._scoped(proposal, fresh=True):
            raise ChatError("Предложение или его данные устарели.")
        if not isinstance(proposal.parameters, CreateExperimentActionParameters):
            raise ChatError("Неподдерживаемый тип действия.", 422)
        receipt, admitted = await self._store.admit(
            actor.actor_id,
            WorkspaceActionReceipt(
                receipt_id=str(uuid4()),
                topic_id=topic_id,
                turn_id=turn_id,
                proposal_id=proposal_id,
                parameters=proposal.parameters,
                request=request,
                created_at=self._clock.now(),
            ),
        )
        if not admitted:
            current = await self._admin.repository.get_proposal(proposal_id)
            return await self._view(actor.actor_id, topic_id, turn_id, current or proposal, receipt)
        try:
            await self._admin.decide_approval(
                proposal_id=proposal_id,
                approve=request.approve,
                reason=request.reason,
                actor=actor,
                correlation_id=receipt.receipt_id,
            )
            state, message = "resolved", "Решение обработано. Результат исполнителя ниже."
        except ActionReconciliationRequiredError:
            state, message = (
                "unknown",
                "Результат неизвестен. Не повторяйте действие; нужна сверка.",
            )
        except (
            ApprovalPermissionError,
            StaleProposalError,
            ActionSafetyError,
            ConcurrentOperationError,
        ):
            state, message = "refused", "Исполнитель остановил действие. Проверьте статус ниже."
        except Exception:
            # The intent remains consumed even when the domain or its final report loses a reply.
            state, message = "unknown", "Ответ потерян. Решение сохранено; повтор запрещён."
        receipt = receipt.model_copy(update={"state": state, "message": message})
        await self._store.finish(actor.actor_id, receipt)
        current = await self._admin.repository.get_proposal(proposal_id)
        return await self._view(actor.actor_id, topic_id, turn_id, current or proposal, receipt)

    async def history(
        self, owner: str, topic_id: str, *, before: datetime
    ) -> list[WorkspaceActionHistory]:
        if not self._enabled:
            return []
        topic = await self._chats.topic(owner, topic_id)
        if topic.product != "mana":
            return []
        result: list[WorkspaceActionHistory] = []
        for receipt in await self._store.receipts(owner, topic_id, before=before):
            proposal = await self._admin.repository.get_proposal(receipt.proposal_id)
            if proposal is None or not self._supported(proposal):
                continue
            view = await self._view(owner, topic_id, receipt.turn_id, proposal, receipt)
            message = receipt.message
            if (
                view.execution_status == ExecutionStatus.SUCCEEDED
                and view.verification_status == VerificationStatus.VERIFIED
            ):
                message = "Создан и проверен sandbox-черновик. Влияние на конверсию не измерено."
            elif proposal.status == ActionStatus.REJECTED:
                message = "Администратор отклонил предложение; запись не выполнялась."
            result.append(
                WorkspaceActionHistory(
                    proposal_id=proposal.proposal_id,
                    at=receipt.created_at,
                    status=proposal.status,
                    execution_status=view.execution_status,
                    verification_status=view.verification_status,
                    message=message,
                )
            )
        return result
