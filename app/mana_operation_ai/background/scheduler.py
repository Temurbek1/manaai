import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.mana_operation_ai.application.admin_service import ActorContext, OperationAdminService
from app.mana_operation_ai.application.agent_service import (
    AgentRunLockedError,
    AgentRunTimeoutError,
)
from app.mana_operation_ai.application.maintenance import OperationMaintenanceService
from app.mana_operation_ai.application.ports import (
    Clock,
    OperationRepository,
    ProviderPermanentError,
    ProviderTransientError,
)
from app.mana_operation_ai.application.scheduling import next_cron_occurrence
from app.mana_operation_ai.domain.enums import AgentRunStatus, AuditEventType, TriggerType, UserRole
from app.mana_operation_ai.domain.models import AgentSchedule, AuditEvent

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _OccurrenceOutcome:
    reason: str
    permanent: bool = False


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
        max_attempts: int = 3,
        permanent_failure_threshold: int = 3,
    ) -> None:
        self._repository = repository
        self._admin = admin
        self._maintenance = maintenance
        self._clock = clock
        self._poll_seconds = poll_seconds
        self._job_timeout_seconds = job_timeout_seconds
        if max_attempts < 1 or permanent_failure_threshold < 1:
            raise ValueError("Scheduler attempt and circuit-breaker limits must be positive")
        self._max_attempts = max_attempts
        self._permanent_failure_threshold = permanent_failure_threshold
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
            if scheduled_at is None or schedule.circuit_open:
                continue
            occurrence_lock = (
                f"schedule-occurrence:{schedule.schedule_id}:{scheduled_at.isoformat()}"
            )
            owner_id = str(uuid.uuid4())
            acquired = await self._repository.acquire_lock(
                key=occurrence_lock,
                owner_id=owner_id,
                now=now,
                expires_at=now
                + timedelta(
                    seconds=self._max_attempts * self._job_timeout_seconds
                    + 2**self._max_attempts
                    + 60,
                ),
            )
            if not acquired:
                continue
            try:
                # Consume the occurrence atomically BEFORE any provider I/O. A stale
                # due-list or a crashed worker cannot replay it after its lease expires.
                # Missed historical slots are skipped, not backfilled as costly scans.
                reserved = schedule.model_copy(
                    update={
                        "next_run_at": next_cron_occurrence(
                            schedule.cron_expression,
                            schedule.timezone,
                            max(scheduled_at, self._clock.now()),
                        ),
                    }
                )
                if not await self._repository.claim_schedule(current=schedule, advanced=reserved):
                    continue
                await self._audit(reserved, "claimed", scheduled_at)
                started = time.monotonic()
                outcome = await self._run_with_retries(reserved, scheduled_at)
                await self._finish_occurrence(reserved, scheduled_at, outcome, started)
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

    async def _finish_occurrence(
        self,
        schedule: AgentSchedule,
        scheduled_at: datetime,
        outcome: _OccurrenceOutcome,
        started: float,
    ) -> None:
        failures = schedule.consecutive_permanent_failures + 1 if outcome.permanent else 0
        circuit_open = failures >= self._permanent_failure_threshold
        completed_at = self._clock.now()
        advanced = schedule.model_copy(
            update={
                "last_run_at": completed_at,
                "next_run_at": next_cron_occurrence(
                    schedule.cron_expression,
                    schedule.timezone,
                    completed_at,
                ),
                "consecutive_permanent_failures": failures,
                "circuit_open": circuit_open,
                "enabled": not circuit_open,
            }
        )
        # Respect an administrator's intervening disable/reschedule.
        persisted = await self._repository.claim_schedule(current=schedule, advanced=advanced)
        logger.log(
            logging.ERROR if circuit_open and persisted else logging.INFO,
            "Retention/operation circuit opened; schedule disabled; operator intervention required"
            if circuit_open and persisted
            else "Scheduled occurrence finished",
            extra={
                "agent_id": schedule.agent_id,
                "capability_key": schedule.capability_key,
                "schedule_id": schedule.schedule_id,
                "scheduled_at": scheduled_at.isoformat(),
                "stop_reason": outcome.reason,
                "circuit_open": circuit_open and persisted,
                "consecutive_permanent_failures": failures,
                "duration_ms": round((time.monotonic() - started) * 1000),
                "schedule_update_applied": persisted,
            },
        )
        await self._audit(
            advanced if persisted else schedule,
            outcome.reason,
            scheduled_at,
        )

    async def _audit(self, schedule: AgentSchedule, reason: str, scheduled_at: datetime) -> None:
        await self._repository.save_audit_event(
            AuditEvent(
                event_id=str(uuid.uuid4()),
                correlation_id=schedule.schedule_id,
                agent_id=schedule.agent_id,
                capability_key=schedule.capability_key,
                event_type=AuditEventType.SCHEDULE_CHANGED,
                actor_id="scheduler",
                actor_role=UserRole.ADMIN,
                occurred_at=self._clock.now(),
                summary="Circuit breaker opened; capability requires operator recovery"
                if schedule.circuit_open
                else "Scheduled occurrence state changed",
                details={
                    "schedule_id": schedule.schedule_id,
                    "scheduled_at": scheduled_at.isoformat(),
                    "stop_reason": reason,
                    "circuit_open": schedule.circuit_open,
                    "consecutive_permanent_failures": schedule.consecutive_permanent_failures,
                    "enabled": schedule.enabled,
                    "next_run_at": schedule.next_run_at.isoformat()
                    if schedule.next_run_at
                    else None,
                },
            )
        )

    async def _run_with_retries(
        self,
        schedule: AgentSchedule,
        scheduled_at: datetime,
    ) -> _OccurrenceOutcome:
        actor = ActorContext(actor_id="scheduler", role=UserRole.ADMIN)
        occurrence_key = f"schedule:{schedule.schedule_id}:{scheduled_at.isoformat()}"
        for attempt in range(self._max_attempts):
            current = next(
                (
                    item
                    for item in await self._repository.list_schedules(
                        schedule.agent_id,
                        schedule.capability_key,
                    )
                    if item.schedule_id == schedule.schedule_id
                ),
                None,
            )
            if (
                current is None
                or not current.enabled
                or current.circuit_open
                or current.next_run_at != schedule.next_run_at
                or current.cron_expression != schedule.cron_expression
                or current.timezone != schedule.timezone
            ):
                return _OccurrenceOutcome("schedule_changed_or_disabled")
            try:
                async with asyncio.timeout(self._job_timeout_seconds):
                    result = await self._admin.run_now(
                        agent_id=schedule.agent_id,
                        capability_key=schedule.capability_key,
                        job_type=schedule.job_type,
                        actor=actor,
                        correlation_id=str(uuid.uuid4()),
                        idempotency_key=f"{occurrence_key}:attempt:{attempt + 1}",
                        trigger=TriggerType.SCHEDULE,
                    )
                if result.status in {AgentRunStatus.FAILED, AgentRunStatus.CANCELLED}:
                    # Existing terminal runs are not reopened by an idempotent request.
                    return _OccurrenceOutcome("existing_terminal_run", permanent=True)
                return _OccurrenceOutcome("success")
            except ProviderPermanentError:
                return _OccurrenceOutcome("provider_permanent_error", permanent=True)
            except (
                ProviderTransientError,
                AgentRunLockedError,
                AgentRunTimeoutError,
                TimeoutError,
            ):
                if attempt + 1 == self._max_attempts:
                    return _OccurrenceOutcome("transient_retries_exhausted")
                logger.warning(
                    "Scheduled occurrence transient retry",
                    extra={"schedule_id": schedule.schedule_id, "retry_count": attempt + 1},
                )
                await asyncio.sleep(2**attempt)
            except Exception as exc:
                # Unknown errors are never permission for an automatic provider replay.
                logger.error(
                    "Scheduled occurrence stopped without retry",
                    extra={"schedule_id": schedule.schedule_id, "error_code": type(exc).__name__},
                )
                return _OccurrenceOutcome("non_retryable_error", permanent=True)
        raise AssertionError("Scheduler retry loop exited unexpectedly")
