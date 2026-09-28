import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

from app.mana_operation_ai.application.admin_service import OperationAdminService
from app.mana_operation_ai.application.maintenance import OperationMaintenanceService
from app.mana_operation_ai.application.ports import (
    ConcurrentOperationError,
    ProviderPermanentError,
    ProviderTransientError,
)
from app.mana_operation_ai.background.scheduler import InProcessScheduler
from app.mana_operation_ai.domain.enums import AgentRunStatus, AgentStatus
from app.mana_operation_ai.domain.models import AgentDefinition, AgentRunResult, AgentSchedule
from app.mana_operation_ai.infrastructure.persistence.database import OperationDatabase
from app.mana_operation_ai.infrastructure.persistence.repository import (
    SqlAlchemyOperationRepository,
)


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def now(self) -> datetime:
        return self.value


class RecordingAdmin:
    def __init__(self) -> None:
        self.run_count = 0
        self.idempotency_keys: list[str | None] = []
        self.failures: list[Exception] = []

    async def expire_approvals(self, now: datetime) -> int:
        del now
        return 0

    async def run_now(self, **kwargs: object) -> AgentRunResult:
        self.run_count += 1
        key = kwargs.get("idempotency_key")
        self.idempotency_keys.append(key if isinstance(key, str) else None)
        await asyncio.sleep(0)
        if self.failures:
            raise self.failures.pop(0)
        return AgentRunResult(run_id="test-run", status=AgentRunStatus.COMPLETED)


class NoopMaintenance:
    async def reconcile_actions(self) -> int:
        return 0

    async def cleanup(self) -> dict[str, int]:
        return {}


async def create_scheduler_fixture(
    database_path: Path,
) -> tuple[
    OperationDatabase,
    SqlAlchemyOperationRepository,
    AgentSchedule,
    MutableClock,
]:
    database = OperationDatabase(f"sqlite+aiosqlite:///{database_path}")
    await database.create_schema()
    repository = SqlAlchemyOperationRepository(database)
    now = datetime(2026, 7, 22, 12, tzinfo=UTC)
    clock = MutableClock(now)
    await repository.register_agent(
        AgentDefinition(
            agent_id="scheduler-agent",
            display_name="Scheduler Agent",
            description="Exercises durable occurrence leases",
            version="1.0.0",
            status=AgentStatus.ENABLED,
            capabilities=[],
            default_capability_key="scheduler.default",
            configuration_schema={"type": "object"},
            registered_at=now,
        ),
    )
    schedule = AgentSchedule(
        schedule_id="scheduler-analysis",
        agent_id="scheduler-agent",
        capability_key="scheduler.default",
        job_type="analysis",
        cron_expression="0 */6 * * *",
        timezone="UTC",
        enabled=True,
        next_run_at=now,
    )
    await repository.save_schedule(schedule)
    return database, repository, schedule, clock


def scheduler(
    *,
    repository: SqlAlchemyOperationRepository,
    admin: RecordingAdmin,
    clock: MutableClock,
) -> InProcessScheduler:
    return InProcessScheduler(
        repository=repository,
        admin=cast(OperationAdminService, admin),
        maintenance=cast(OperationMaintenanceService, NoopMaintenance()),
        clock=clock,
        poll_seconds=30,
        job_timeout_seconds=10,
    )


async def test_two_scheduler_instances_execute_one_occurrence_once(tmp_path: Path) -> None:
    database, repository, _, clock = await create_scheduler_fixture(
        tmp_path / "two-schedulers.db",
    )
    admin = RecordingAdmin()
    first = scheduler(repository=repository, admin=admin, clock=clock)
    second = scheduler(repository=repository, admin=admin, clock=clock)

    await asyncio.gather(first.tick(), second.tick())

    assert admin.run_count == 1
    assert len(set(admin.idempotency_keys)) == 1
    schedules = await repository.list_schedules("scheduler-agent")
    assert schedules[0].next_run_at == clock.now() + timedelta(hours=6)
    await database.dispose()


async def test_expired_occurrence_lease_recovers_after_worker_death(tmp_path: Path) -> None:
    database, repository, schedule, clock = await create_scheduler_fixture(
        tmp_path / "scheduler-recovery.db",
    )
    admin = RecordingAdmin()
    occurrence_lock = f"schedule-occurrence:{schedule.schedule_id}:{clock.now().isoformat()}"
    assert await repository.acquire_lock(
        key=occurrence_lock,
        owner_id="dead-worker",
        now=clock.now(),
        expires_at=clock.now() + timedelta(seconds=10),
    )

    runner = scheduler(repository=repository, admin=admin, clock=clock)
    await runner.tick()
    assert admin.run_count == 0

    clock.value += timedelta(seconds=11)
    await runner.tick()

    assert admin.run_count == 1
    advanced = (await repository.list_schedules("scheduler-agent"))[0]
    assert advanced.next_run_at == datetime(2026, 7, 22, 18, tzinfo=UTC)
    await database.dispose()


async def test_permanent_failure_consumes_slot_without_poll_replay(tmp_path: Path) -> None:
    database, repository, _, clock = await create_scheduler_fixture(tmp_path / "permanent.db")
    admin = RecordingAdmin()
    admin.failures = [ProviderPermanentError("HTTP 403")]
    runner = scheduler(repository=repository, admin=admin, clock=clock)
    await runner.tick()
    for _ in range(10):
        clock.value += timedelta(seconds=30)
        await runner.tick()
    saved = (await repository.list_schedules())[0]
    assert admin.run_count == 1
    assert saved.next_run_at == datetime(2026, 7, 22, 18, tzinfo=UTC)
    assert saved.consecutive_permanent_failures == 1
    assert not saved.circuit_open
    await database.dispose()


async def test_circuit_breaker_is_persisted_and_survives_worker_restart(tmp_path: Path) -> None:
    database, repository, _, clock = await create_scheduler_fixture(tmp_path / "circuit.db")
    admin = RecordingAdmin()
    admin.failures = [ProviderPermanentError("HTTP 403") for _ in range(3)]
    for _ in range(3):
        await scheduler(repository=repository, admin=admin, clock=clock).tick()
        clock.value += timedelta(hours=6)
    saved = (await repository.list_schedules())[0]
    assert saved.circuit_open
    assert not saved.enabled
    assert saved.consecutive_permanent_failures == 3
    events, _ = await repository.list_audit_events(correlation_id=saved.schedule_id)
    trips = [event for event in events if event.details.get("circuit_open") is True]
    assert len(trips) == 1
    assert trips[0].capability_key == saved.capability_key
    assert trips[0].details["enabled"] is False
    await scheduler(repository=repository, admin=admin, clock=clock).tick()
    assert admin.run_count == 3
    await database.dispose()


async def test_terminal_update_cannot_reenable_an_administrator_disabled_schedule(
    tmp_path: Path,
) -> None:
    database, repository, schedule_value, clock = await create_scheduler_fixture(
        tmp_path / "disable-during-run.db",
    )

    class DisablingAdmin(RecordingAdmin):
        async def run_now(self, **kwargs: object) -> AgentRunResult:
            claimed = (await repository.list_schedules())[0]
            await repository.save_schedule(claimed.model_copy(update={"enabled": False}))
            return await super().run_now(**kwargs)

    await scheduler(repository=repository, admin=DisablingAdmin(), clock=clock).tick()
    saved = (await repository.list_schedules())[0]
    assert not saved.enabled
    assert saved.next_run_at != schedule_value.next_run_at
    await database.dispose()


async def test_transient_retry_uses_distinct_finite_attempt_keys(tmp_path: Path) -> None:
    database, repository, _, clock = await create_scheduler_fixture(tmp_path / "transient.db")
    admin = RecordingAdmin()
    admin.failures = [ProviderTransientError("503") for _ in range(3)]
    runner = scheduler(repository=repository, admin=admin, clock=clock)
    await runner.tick()
    await runner.tick()
    saved = (await repository.list_schedules())[0]
    assert admin.run_count == 3
    assert len(set(admin.idempotency_keys)) == 3
    assert saved.next_run_at == clock.now() + timedelta(hours=6)
    assert saved.consecutive_permanent_failures == 0
    await database.dispose()


@pytest.mark.parametrize("failure", [None, RuntimeError("Unexpected failure")])
async def test_stale_due_snapshot_cannot_replay_consumed_occurrence(
    tmp_path: Path,
    failure: Exception | None,
) -> None:
    database, repository, stale, clock = await create_scheduler_fixture(tmp_path / "stale.db")
    admin = RecordingAdmin()
    if failure is not None:
        admin.failures = [failure]
    await scheduler(repository=repository, admin=admin, clock=clock).tick()
    # Emulate a second worker that fetched its due list before the first finished,
    # but acquired the occurrence lock only after the first released it.
    assert not await repository.claim_schedule(
        current=stale,
        advanced=stale.model_copy(update={"next_run_at": clock.now() + timedelta(hours=6)}),
    )
    assert admin.run_count == 1
    await database.dispose()


async def test_scheduler_skips_overdue_backlog_and_resets_failure_streak(tmp_path: Path) -> None:
    database, repository, schedule_value, clock = await create_scheduler_fixture(
        tmp_path / "backlog.db",
    )
    await repository.save_schedule(
        schedule_value.model_copy(
            update={
                "consecutive_permanent_failures": 2,
            }
        )
    )
    clock.value += timedelta(days=5, minutes=3)
    admin = RecordingAdmin()
    runner = scheduler(repository=repository, admin=admin, clock=clock)
    await runner.tick()
    await runner.tick()
    saved = (await repository.list_schedules())[0]
    assert saved.next_run_at is not None and saved.next_run_at > clock.now()
    assert saved.consecutive_permanent_failures == 0
    assert admin.run_count == 1
    await database.dispose()


async def test_disabling_schedule_between_attempts_prevents_more_provider_calls(
    tmp_path: Path,
) -> None:
    database, repository, _, clock = await create_scheduler_fixture(tmp_path / "disable-retry.db")

    class DisablingAdmin(RecordingAdmin):
        async def run_now(self, **kwargs: object) -> AgentRunResult:
            self.run_count += 1
            claimed = (await repository.list_schedules())[0]
            await repository.save_schedule(claimed.model_copy(update={"enabled": False}))
            raise ProviderTransientError("503")

    admin = DisablingAdmin()
    await scheduler(repository=repository, admin=admin, clock=clock).tick()
    assert admin.run_count == 1
    assert not (await repository.list_schedules())[0].enabled
    await database.dispose()


async def test_stale_configuration_write_cannot_reset_a_new_circuit_trip(tmp_path: Path) -> None:
    database, repository, stale, clock = await create_scheduler_fixture(tmp_path / "stale-trip.db")
    tripped = stale.model_copy(
        update={
            "enabled": False,
            "circuit_open": True,
            "consecutive_permanent_failures": 3,
            "next_run_at": clock.now() + timedelta(hours=6),
        }
    )
    assert await repository.claim_schedule(current=stale, advanced=tripped)
    with pytest.raises(ConcurrentOperationError, match="safety state changed"):
        await repository.save_schedule(stale)
    saved = (await repository.list_schedules())[0]
    assert saved.circuit_open and not saved.enabled
    await database.dispose()
