import asyncio
import logging
import uuid
from datetime import datetime, timedelta

from app.mana_operation_ai.application.admin_service import ActorContext, OperationAdminService
from app.mana_operation_ai.application.maintenance import OperationMaintenanceService
from app.mana_operation_ai.application.ports import Clock, OperationRepository
from app.mana_operation_ai.application.scheduling import next_cron_occurrence
from app.mana_operation_ai.domain.enums import TriggerType, UserRole
from app.mana_operation_ai.domain.models import AgentSchedule

logger = logging.getLogger(__name__)


class InProcessScheduler:
    """Single-process scheduler with persisted due times and database-backed run locks."""

    def __init__(
        self,
        *,
        repository: OperationRepository,
        admin: OperationAdminService,
        maintenance: OperationMaintenanceService,
        clock: Clock,
        poll_seconds: float,
        job_timeout_seconds: int,
    ) -> None:
        self._repository = repository
        self._admin = admin
        self._maintenance = maintenance
        self._clock = clock
        self._poll_seconds = poll_seconds
        self._job_timeout_seconds = job_timeout_seconds
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._next_reconciliation = clock.now()
        self._next_cleanup = clock.now()

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop(), name="mana-operation-scheduler")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            await self._task
            self._task = None

    async def tick(self) -> None:
        now = self._clock.now()
        await self._admin.expire_approvals(now)
        for schedule in await self._repository.due_schedules(now):
            scheduled_at = schedule.next_run_at
            if scheduled_at is None:
                continue
            occurrence_lock = (
                f"schedule-occurrence:{schedule.schedule_id}:{scheduled_at.isoformat()}"
            )
            owner_id = str(uuid.uuid4())
            acquired = await self._repository.acquire_lock(
                key=occurrence_lock,
                owner_id=owner_id,
                now=now,
                expires_at=now + timedelta(seconds=self._job_timeout_seconds),
            )
            if not acquired:
                continue
            try:
                if await self._run_with_retries(schedule, scheduled_at):
                    completed_at = self._clock.now()
                    advanced = schedule.model_copy(
                        update={
                            "last_run_at": completed_at,
                            "next_run_at": next_cron_occurrence(
                                schedule.cron_expression,
                                schedule.timezone,
                                scheduled_at,
                            ),
                        },
                    )
                    await self._repository.claim_schedule(
                        current=schedule,
                        advanced=advanced,
                    )
            finally:
                await self._repository.release_lock(key=occurrence_lock, owner_id=owner_id)
        if now >= self._next_reconciliation:
            await self._maintenance.reconcile_actions()
            self._next_reconciliation = now + timedelta(hours=1)
        if now >= self._next_cleanup:
            await self._maintenance.cleanup()
            self._next_cleanup = now + timedelta(days=1)

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self.tick()
            except Exception:
                logger.exception("Operation scheduler tick failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._poll_seconds)
            except TimeoutError:
                continue

    async def _run_with_retries(self, schedule: AgentSchedule, scheduled_at: datetime) -> bool:
        actor = ActorContext(actor_id="scheduler", role=UserRole.ADMIN)
        idempotency_key = f"schedule:{schedule.schedule_id}:{scheduled_at.isoformat()}"
        for attempt in range(3):
            try:
                async with asyncio.timeout(self._job_timeout_seconds):
                    await self._admin.run_now(
                        agent_id=schedule.agent_id,
                        job_type=schedule.job_type,
                        actor=actor,
                        correlation_id=str(uuid.uuid4()),
                        idempotency_key=idempotency_key,
                        trigger=TriggerType.SCHEDULE,
                    )
                return True
            except Exception:
                if attempt == 2:
                    logger.exception(
                        "Scheduled job failed after retries",
                        extra={"schedule_id": schedule.schedule_id},
                    )
                    return False
                await asyncio.sleep(2**attempt)
        return False
