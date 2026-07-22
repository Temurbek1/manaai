import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

from app.mana_operation_ai.application.admin_service import OperationAdminService
from app.mana_operation_ai.application.maintenance import OperationMaintenanceService
from app.mana_operation_ai.background.scheduler import InProcessScheduler
from app.mana_operation_ai.domain.enums import AgentStatus
from app.mana_operation_ai.domain.models import AgentDefinition, AgentSchedule
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

    async def expire_approvals(self, now: datetime) -> int:
        del now
        return 0

    async def run_now(self, **kwargs: object) -> None:
        self.run_count += 1
        key = kwargs.get("idempotency_key")
        self.idempotency_keys.append(key if isinstance(key, str) else None)
        await asyncio.sleep(0)


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
            configuration_schema={"type": "object"},
            registered_at=now,
        ),
    )
    schedule = AgentSchedule(
        schedule_id="scheduler-analysis",
        agent_id="scheduler-agent",
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
