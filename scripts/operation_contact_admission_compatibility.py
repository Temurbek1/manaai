"""Synthetic-only populated admission fixture for the networkless rollback audit."""

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Literal
from uuid import uuid4

TABLES = (
    "operation_contact_preparation_gate",
    "operation_contact_preparations",
    "operation_retention_contacts",
    "operation_retention_contact_events",
    "operation_retention_contact_guards",
)


def ledger_fingerprint(path: Path) -> str:
    """Use only stdlib so the actual old image need not know the new contracts."""
    with sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True) as connection:
        data = {
            table: sorted(connection.execute(f"SELECT * FROM {table}").fetchall(), key=repr)
            for table in TABLES
        }
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


async def check_admissions(path: Path, *, stage: str, owner: str, topic_id: str) -> None:
    from app.mana_operation_ai.application.admin_service import ActorContext
    from app.mana_operation_ai.application.retention.contact import RetentionContactService
    from app.mana_operation_ai.application.retention.preparation_errors import (
        ContactPreparationError,
    )
    from app.mana_operation_ai.application.runtime import SystemClock, UuidGenerator
    from app.mana_operation_ai.domain.enums import AgentStatus, UserRole
    from app.mana_operation_ai.domain.models import AgentDefinition
    from app.mana_operation_ai.domain.retention_contact import (
        RetentionContactParameters,
        RetentionContactPrepare,
        RetentionContactTarget,
    )
    from app.mana_operation_ai.domain.workspace_retention_contacts import SandboxRecipient
    from app.mana_operation_ai.infrastructure.persistence.chat_repository import (
        SqlAlchemyChatRepository,
    )
    from app.mana_operation_ai.infrastructure.persistence.database import OperationDatabase
    from app.mana_operation_ai.infrastructure.persistence.repository import (
        SqlAlchemyOperationRepository,
    )
    from app.mana_operation_ai.infrastructure.persistence.retention_contact import (
        SqlAlchemyRetentionContacts,
    )
    from app.mana_operation_ai.infrastructure.retention.contact_catalog import (
        FakeRetentionContactCatalog,
        sandbox_account_ref,
    )

    class LostTargetCatalog(FakeRetentionContactCatalog):
        async def target(self, account_ref: str) -> RetentionContactTarget:
            if account_ref == sandbox_account_ref("sample_uz"):
                # The admitted lookup was attempted; an unknown outcome cannot expire.
                await super().target(account_ref)
                raise TimeoutError("Synthetic lost target response")
            return await super().target(account_ref)

    manifest = path.with_suffix(".admissions.json")
    database = OperationDatabase(f"sqlite+aiosqlite:///{path}")
    clock = SystemClock()
    catalog = LostTargetCatalog(clock)
    controls = SqlAlchemyOperationRepository(database)
    store = SqlAlchemyRetentionContacts(database)
    service = RetentionContactService(
        store=store,
        executor=catalog,
        chats=SqlAlchemyChatRepository(database, hourly_limit=20, daily_limit=200),
        clock=clock,
        ids=UuidGenerator(),
        enabled=True,
        allow_self_approval=False,
        controls=controls,
        global_kill_switch_default=False,
    )
    actor = ActorContext(actor_id=owner, role=UserRole.ADMIN)
    try:
        if stage == "setup":
            await controls.register_agent(
                AgentDefinition(
                    agent_id="retention-agent",
                    display_name="Synthetic contact owner",
                    description="Local fake-only admission rollback fixture.",
                    version="synthetic",
                    status=AgentStatus.ENABLED,
                    capabilities=[],
                    default_capability_key="retention.engagement.analyze",
                    configuration_schema={},
                    registered_at=clock.now(),
                )
            )
            recipients: tuple[tuple[SandboxRecipient, Literal["ru", "uz"]], ...] = (
                ("sample_ru", "ru"),
                ("sample_uz", "uz"),
            )
            requests = [
                RetentionContactPrepare(
                    request_id=uuid4(),
                    parameters=RetentionContactParameters(
                        account_ref=sandbox_account_ref(recipient),
                        template="onboarding_help",
                        language=language,
                    ),
                )
                for recipient, language in recipients
            ]
            recorded = await service.prepare(actor, topic_id, requests[0])
            assert recorded.status == "proposed"
            try:
                await service.prepare(actor, topic_id, requests[1])
            except ContactPreparationError as exc:
                assert exc.code == "contact_preparation_pending"
            else:
                raise AssertionError("A lost target response must retain its durable hold")
            assert sum(executor.target_reads for executor in catalog.executors.values()) == 2
            assert sum(executor.dispatch_count for executor in catalog.executors.values()) == 0
            manifest.write_text(
                json.dumps(
                    {
                        "fingerprint": ledger_fingerprint(path),
                        "requests": [request.model_dump(mode="json") for request in requests],
                        "action": recorded.model_dump(mode="json"),
                    }
                )
            )
        else:
            expected = json.loads(manifest.read_text())
            requests = [
                RetentionContactPrepare.model_validate(item) for item in expected["requests"]
            ]
            assert ledger_fingerprint(path) == expected["fingerprint"]
            recorded = await service.prepare(actor, topic_id, requests[0])
            assert recorded.model_dump(mode="json") == expected["action"]
            try:
                await service.prepare(actor, topic_id, requests[1])
            except ContactPreparationError as exc:
                assert exc.code == "contact_preparation_pending"
            else:
                raise AssertionError("Restart/rollback must not re-admit an unknown lookup")
            assert sum(executor.target_reads for executor in catalog.executors.values()) == 0
            assert sum(executor.dispatch_count for executor in catalog.executors.values()) == 0
            assert ledger_fingerprint(path) == expected["fingerprint"]
    finally:
        await database.dispose()


def check_legacy_admissions(path: Path) -> None:
    expected = json.loads(path.with_suffix(".admissions.json").read_text())
    assert ledger_fingerprint(path) == expected["fingerprint"]
    with sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True) as connection:
        assert connection.execute(
            "SELECT status, COUNT(*) FROM operation_contact_preparations "
            "GROUP BY status ORDER BY status"
        ).fetchall() == [("pending", 1), ("recorded", 1)]
