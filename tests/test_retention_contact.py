"""Private application → SQL → fake receiver; never calls model or customer providers."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.mana_operation_ai.application.admin_service import ActorContext
from app.mana_operation_ai.application.chat_ports import ChatError
from app.mana_operation_ai.application.retention.contact import RetentionContactService
from app.mana_operation_ai.application.retention.contact_policy import evaluate_contact
from app.mana_operation_ai.application.runtime import UuidGenerator
from app.mana_operation_ai.domain.chat import TopicCreate
from app.mana_operation_ai.domain.enums import AgentStatus, UserRole
from app.mana_operation_ai.domain.models import AgentDefinition
from app.mana_operation_ai.domain.retention_contact import (
    RetentionContactDecision,
    RetentionContactParameters,
    RetentionContactPrepare,
    RetentionContactTarget,
)
from app.mana_operation_ai.infrastructure.persistence.chat_repository import (
    SqlAlchemyChatRepository,
)
from app.mana_operation_ai.infrastructure.persistence.database import OperationDatabase
from app.mana_operation_ai.infrastructure.persistence.models import (
    ActionProposalRow,
    RecommendationRow,
    RetentionContactEventRow,
    RetentionContactGuardRow,
    RetentionContactRow,
)
from app.mana_operation_ai.infrastructure.persistence.repository import (
    SqlAlchemyOperationRepository,
)
from app.mana_operation_ai.infrastructure.persistence.retention_contact import (
    SqlAlchemyRetentionContacts,
)
from app.mana_operation_ai.infrastructure.retention.contact_fake import FakeRetentionContactExecutor
from tests.test_retention_risk import facts_payload

NOW = datetime(2026, 9, 29, 12, tzinfo=UTC)
ADMIN = ActorContext(actor_id="alice", role=UserRole.ADMIN)


async def test_uzbek_contact_requires_explicit_recipient_language_and_exact_review(system):  # type: ignore[no-untyped-def]
    _, _, topic, _, executor, _, service = system
    req = request()
    req.parameters.language = "uz"
    denied = await service.prepare(ADMIN, topic.topic_id, req)
    assert denied.status == "refused" and executor.dispatch_count == 0
    source = target_payload()
    source["preferred_language"] = "uz"
    executor.replace_target(RetentionContactTarget.model_validate(source))
    req = request()
    req.parameters.language = "uz"
    proposal = await service.prepare(ADMIN, topic.topic_id, req)
    assert proposal.status == "proposed"
    assert proposal.message.version == "retention-contact-uz-v1"
    assert proposal.message.language == "uz"
    assert (
        proposal.message.text
        == "MANA: sozlashda yordam kerakmi? Ilovadagi yordam bo‘limini oching."
    )
    verified = await service.decide(ADMIN, proposal.action_id, decision(proposal.fingerprint))
    assert verified.status == "verified" and executor.dispatch_count == 1
    assert executor.accepted_messages == [proposal.message.text]


class Clock:
    def __init__(self) -> None:
        self.current = NOW

    def now(self) -> datetime:
        return self.current


async def register_contact_owner(db: OperationDatabase, clock: Clock) -> None:
    await SqlAlchemyOperationRepository(db).register_agent(
        AgentDefinition(
            agent_id="retention-agent",
            display_name="Fictional Retention owner",
            description="Explicit owner for the isolated contact foundation fixture.",
            version="synthetic",
            status=AgentStatus.ENABLED,
            capabilities=[],
            default_capability_key="retention.engagement.analyze",
            configuration_schema={},
            registered_at=clock.now(),
        )
    )


def target_payload() -> dict[str, Any]:
    facts = facts_payload()
    facts["activity"].update(
        last_open_at=NOW - timedelta(days=6), active_days=1, distinct_features=2, push_opens=0
    )
    return {
        "facts": facts,
        "observed_at": NOW,
        "consent": True,
        "consent_channel": "push",
        "consent_purpose": "retention_support",
        "consent_evidence_ref": "fake_contact_consent_01",
        "preferred_language": "ru",
        "consent_observed_at": NOW,
        "consent_expires_at": NOW + timedelta(days=10),
        "suppressed": False,
        "timezone": "UTC",
        "contact_history_complete": True,
    }


def target() -> RetentionContactTarget:
    return RetentionContactTarget.model_validate(target_payload())


def request() -> RetentionContactPrepare:
    return RetentionContactPrepare(
        request_id=uuid4(),
        parameters=RetentionContactParameters(
            account_ref=target().facts.account_ref, template="onboarding_help"
        ),
    )


def decision(fingerprint: str, *, approve: bool = True) -> RetentionContactDecision:
    return RetentionContactDecision(
        request_id=uuid4(),
        confirmed=True,
        approve=approve,
        reason="Explicit fictional receiver review",
        fingerprint=fingerprint,
    )


@pytest.fixture
async def system(tmp_path: Path):  # type: ignore[no-untyped-def]
    db = OperationDatabase(f"sqlite+aiosqlite:///{tmp_path / 'contacts.db'}")
    await db.create_schema()
    chats = SqlAlchemyChatRepository(db, hourly_limit=100, daily_limit=100)
    topic = await chats.create(
        "alice",
        TopicCreate(agent_id="retention-agent", product="mana", title="Fictional contact review"),
    )
    clock = Clock()
    await register_contact_owner(db, clock)
    executor = FakeRetentionContactExecutor(clock=clock, target=target())
    store = SqlAlchemyRetentionContacts(db)
    service = RetentionContactService(
        store=store,
        executor=executor,
        chats=chats,
        clock=clock,
        ids=UuidGenerator(),
        enabled=True,
        allow_self_approval=True,
        controls=SqlAlchemyOperationRepository(db),
        global_kill_switch_default=False,
    )
    try:
        yield db, chats, topic, clock, executor, store, service
    finally:
        await db.dispose()


async def test_full_private_lifecycle_exact_replay_and_isolated_old_tables(system):  # type: ignore[no-untyped-def]
    db, _, topic, _, executor, _, service = system
    req = request()
    action = await service.prepare(ADMIN, topic.topic_id, req)
    assert action.status == "proposed" and not action.policy.customer_action_authorized
    assert executor.dispatch_count == 0
    reads = executor.target_reads
    assert await service.prepare(ADMIN, topic.topic_id, req) == action
    assert executor.target_reads == reads
    command = decision(action.fingerprint)
    completed = await service.decide(ADMIN, action.action_id, command)
    assert completed.status == "verified" and completed.business_outcome == "not_measured"
    assert completed.delivery and completed.delivery.state == "sandbox_accepted"
    assert executor.dispatch_count == 1 and len(executor.accepted_messages) == 1
    for _ in range(2):
        assert await service.decide(ADMIN, action.action_id, command) == completed
        assert await service.get(ADMIN, action.action_id) == completed
    assert executor.dispatch_count == 1
    async with db.session_factory() as session:
        assert (await session.scalars(select(ActionProposalRow))).all() == []
        assert (await session.scalars(select(RecommendationRow))).all() == []
        events = (
            await session.scalars(
                select(RetentionContactEventRow).order_by(RetentionContactEventRow.revision)
            )
        ).all()
        assert [e.payload["status"] for e in events] == ["proposed", "dispatching", "verified"]
        guard = await session.get(RetentionContactGuardRow, req.parameters.account_ref)
        assert guard and guard.expires_at is not None


async def test_lost_ack_uses_exact_receipt_without_second_write(system):  # type: ignore[no-untyped-def]
    _, _, topic, _, executor, _, service = system
    action = await service.prepare(ADMIN, topic.topic_id, request())
    executor.lose_ack = True
    result = await service.decide(ADMIN, action.action_id, decision(action.fingerprint))
    assert result.status == "verified" and executor.dispatch_count == 1


async def test_unknown_survives_restart_blocks_recipient_and_only_observes_on_replay(system):  # type: ignore[no-untyped-def]
    db, chats, topic, clock, executor, _, service = system
    action = await service.prepare(ADMIN, topic.topic_id, request())
    executor.lose_ack = executor.receipt_unavailable = True
    command = decision(action.fingerprint)
    result = await service.decide(ADMIN, action.action_id, command)
    assert result.status == "uncertain" and executor.dispatch_count == 1
    replacement = FakeRetentionContactExecutor(clock=clock, target=target())
    restarted = RetentionContactService(
        store=SqlAlchemyRetentionContacts(db),
        executor=replacement,
        chats=chats,
        clock=clock,
        ids=UuidGenerator(),
        enabled=True,
        allow_self_approval=True,
        controls=SqlAlchemyOperationRepository(db),
        global_kill_switch_default=False,
    )
    assert await restarted.decide(ADMIN, action.action_id, command) == result
    assert replacement.target_reads == replacement.receipt_reads == replacement.dispatch_count == 0
    assert (await restarted.reconcile(ADMIN, action.action_id)).status == "uncertain"
    new = await restarted.prepare(ADMIN, topic.topic_id, request())
    with pytest.raises(ChatError, match="частоты"):
        await restarted.decide(ADMIN, new.action_id, decision(new.fingerprint))
    assert replacement.dispatch_count == 0
    # Even long after the original approval expires, an unknown delivery never unlocks.
    clock.current += timedelta(days=30)
    async with db.session_factory() as session:
        guard = await session.get(RetentionContactGuardRow, action.request.parameters.account_ref)
        assert guard and guard.expires_at is None and guard.action_id == action.action_id
    # Recovering a real exact fake receipt is observation, not renewed approval.
    clock.current = NOW
    executor.receipt_unavailable = False
    repaired = await service.reconcile(ADMIN, action.action_id)
    assert repaired.status == "verified" and executor.dispatch_count == 1


async def test_current_consent_withdrawal_blocks_dispatch_and_releases_only_unused_slot(system):  # type: ignore[no-untyped-def]
    db, _, topic, _, executor, _, service = system
    action = await service.prepare(ADMIN, topic.topic_id, request())
    changed = target_payload()
    changed["consent"] = False
    executor.replace_target(RetentionContactTarget.model_validate(changed))
    result = await service.decide(ADMIN, action.action_id, decision(action.fingerprint))
    assert result.status == "refused" and executor.dispatch_count == 0
    async with db.session_factory() as session:
        assert (
            await session.get(RetentionContactGuardRow, action.request.parameters.account_ref)
            is None
        )


async def test_rejection_expiry_roles_owner_and_self_approval(system):  # type: ignore[no-untyped-def]
    _, chats, topic, clock, executor, store, service = system
    action = await service.prepare(ADMIN, topic.topic_id, request())
    with pytest.raises(ChatError) as denied:
        await service.get(ActorContext(actor_id="bob", role=UserRole.ADMIN), action.action_id)
    assert denied.value.status == 404
    with pytest.raises(ChatError) as denied:
        await service.decide(
            ActorContext(actor_id="alice", role=UserRole.OPERATOR),
            action.action_id,
            decision(action.fingerprint),
        )
    assert denied.value.status == 403
    no_self = RetentionContactService(
        store=store,
        executor=executor,
        chats=chats,
        clock=clock,
        ids=UuidGenerator(),
        enabled=True,
        allow_self_approval=False,
        controls=SqlAlchemyOperationRepository(system[0]),
        global_kill_switch_default=False,
    )
    with pytest.raises(ChatError, match="собственного"):
        await no_self.decide(ADMIN, action.action_id, decision(action.fingerprint))
    rejected = await service.decide(
        ADMIN, action.action_id, decision(action.fingerprint, approve=False)
    )
    assert rejected.status == "rejected" and executor.dispatch_count == 0
    other = await service.prepare(ADMIN, topic.topic_id, request())
    clock.current += timedelta(hours=1)
    expired = await service.decide(ADMIN, other.action_id, decision(other.fingerprint))
    assert expired.status == "refused" and expired.result_code == "proposal_expired"


async def test_two_runtime_instances_cannot_repeat_one_human_intent(system):  # type: ignore[no-untyped-def]
    db, chats, topic, clock, executor, _, service = system
    action = await service.prepare(ADMIN, topic.topic_id, request())
    command = decision(action.fingerprint)
    second = RetentionContactService(
        store=SqlAlchemyRetentionContacts(db),
        executor=executor,
        chats=chats,
        clock=clock,
        ids=UuidGenerator(),
        enabled=True,
        allow_self_approval=True,
        controls=SqlAlchemyOperationRepository(db),
        global_kill_switch_default=False,
    )
    values = await asyncio.gather(
        service.decide(ADMIN, action.action_id, command),
        second.decide(ADMIN, action.action_id, command),
        return_exceptions=True,
    )
    assert any(getattr(value, "status", None) == "verified" for value in values)
    assert executor.dispatch_count == 1
    assert (await service.get(ADMIN, action.action_id)).status == "verified"


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("consent", False, "contact_consent_missing_or_expired"),
        ("consent", None, "contact_consent_missing_or_expired"),
        ("suppressed", True, "contact_suppressed_or_unknown"),
        ("suppressed", None, "contact_suppressed_or_unknown"),
        ("contact_history_complete", False, "contact_history_incomplete"),
        ("timezone", "not/a_timezone", "recipient_timezone_unknown"),
    ],
)
def test_contact_permission_is_independent_of_risk(field: str, value: object, reason: str) -> None:
    payload = target_payload()
    payload[field] = value
    policy = evaluate_contact(
        request().parameters, RetentionContactTarget.model_validate(payload), now=NOW
    )
    assert not policy.eligible_for_review and reason in policy.reasons
    assert not policy.customer_action_authorized


@pytest.mark.parametrize("value", [1, 1.0, "true", False, None])
def test_human_confirmation_is_never_coerced(value: object) -> None:
    with pytest.raises(ValidationError):
        RetentionContactDecision.model_validate(
            {
                "request_id": str(uuid4()),
                "confirmed": value,
                "approve": True,
                "reason": "human",
                "fingerprint": "a" * 64,
            }
        )


def test_no_arbitrary_message_financial_payload_real_product_or_child_facts() -> None:
    params = request().parameters.model_dump(mode="json")
    changes: list[dict[str, object]] = [
        {"body": "send this"},
        {"discount": 20},
        {"product": "360rec"},
        {"mode": "live"},
        {"channel": "email"},
    ]
    for change in changes:
        with pytest.raises(ValidationError):
            RetentionContactParameters.model_validate({**params, **change})
    source = target_payload()
    source["facts"]["subject_type"] = "child"
    with pytest.raises(ValidationError):
        RetentionContactTarget.model_validate(source)
    source = target_payload()
    source["facts"]["mode"] = "live"
    with pytest.raises(ValidationError):
        RetentionContactTarget.model_validate(source)


def test_partial_activity_tariff_like_unknown_billing_and_renewal_do_not_grant_contact() -> None:
    for path, change in [
        ("activity", {"coverage": "partial"}),
        ("subscription", {"status": "unknown"}),
        ("feedback", {"open_complaints": 1}),
    ]:
        source = target_payload()
        source["facts"][path].update(change)
        assert not evaluate_contact(
            request().parameters, RetentionContactTarget.model_validate(source), now=NOW
        ).eligible_for_review
    renewal = request().parameters.model_copy(update={"template": "renewal_reminder"})
    assert "renewal_not_confirmed" in evaluate_contact(renewal, target(), now=NOW).reasons


async def test_tampered_sql_and_changed_idempotent_request_fail_closed(system):  # type: ignore[no-untyped-def]
    db, _, topic, _, executor, _, service = system
    req = request()
    action = await service.prepare(ADMIN, topic.topic_id, req)
    changed = req.model_copy(
        update={"parameters": req.parameters.model_copy(update={"template": "renewal_reminder"})}
    )
    with pytest.raises(ChatError):
        await service.prepare(ADMIN, topic.topic_id, changed)
    async with db.session_factory() as session, session.begin():
        row = await session.get(RetentionContactRow, action.action_id)
        assert row
        row.payload = {**row.payload, "owner": "bob"}
    with pytest.raises(ChatError) as exc:
        await service.get(ADMIN, action.action_id)
    assert exc.value.status == 503 and executor.dispatch_count == 0


@pytest.mark.parametrize(
    "key",
    [
        "global_kill_switch",
        "agent_kill_switch:retention-agent",
        "capability_kill_switch:retention-agent:retention.contact.sandbox",
    ],
)
async def test_each_scoped_kill_switch_is_rechecked_after_human_review(system, key: str):  # type: ignore[no-untyped-def]
    db, _, topic, _, executor, _, service = system
    action = await service.prepare(ADMIN, topic.topic_id, request())
    await SqlAlchemyOperationRepository(db).set_control(
        key=key, enabled=True, updated_at=NOW, updated_by="admin"
    )
    result = await service.decide(ADMIN, action.action_id, decision(action.fingerprint))
    assert result.status == "refused" and executor.dispatch_count == 0
    reads = executor.target_reads
    with pytest.raises(ChatError) as exc:
        await service.prepare(ADMIN, topic.topic_id, request())
    assert exc.value.status == 423 and executor.target_reads == reads


async def test_exact_message_body_is_bound_to_human_fingerprint_and_delivery(system):  # type: ignore[no-untyped-def]
    db, _, topic, _, executor, _, service = system
    import hashlib

    action = await service.prepare(ADMIN, topic.topic_id, request())
    changed = action.message.model_dump(mode="json")
    changed["text"] = "An unapproved replacement"
    changed["sha256"] = hashlib.sha256(changed["text"].encode()).hexdigest()
    with pytest.raises(ValidationError, match="fingerprint"):
        type(action).model_validate({**action.model_dump(mode="json"), "message": changed})
    result = await service.decide(ADMIN, action.action_id, decision(action.fingerprint))
    assert result.status == "verified" and executor.accepted_messages == [action.message.text]
    assert action.message.version == "retention-contact-ru-v1"
    # A changed decision or confirmed payload never triggers another dispatch.
    with pytest.raises(ChatError):
        await service.decide(ADMIN, action.action_id, decision(action.fingerprint))
    assert executor.dispatch_count == 1


@pytest.mark.parametrize(
    "field", ["consent_channel", "consent_purpose", "consent_evidence_ref", "preferred_language"]
)
def test_push_permission_alone_is_not_contact_consent(field: str) -> None:
    source = target_payload()
    source[field] = None
    assert not evaluate_contact(
        request().parameters, RetentionContactTarget.model_validate(source), now=NOW
    ).eligible_for_review


@pytest.mark.parametrize(
    "timezone,allowed",
    [("Etc/GMT+4", False), ("Etc/GMT+3", True), ("Etc/GMT-8", True), ("Etc/GMT-9", False)],
)
def test_quiet_hours_use_the_explicit_recipient_timezone(timezone: str, allowed: bool) -> None:
    source = target_payload()
    source["timezone"] = timezone
    assert (
        evaluate_contact(
            request().parameters, RetentionContactTarget.model_validate(source), now=NOW
        ).eligible_for_review
        == allowed
    )


async def test_known_acceptance_cooldown_survives_an_empty_provider_restart(system):  # type: ignore[no-untyped-def]
    db, chats, topic, clock, executor, _, service = system
    action = await service.prepare(ADMIN, topic.topic_id, request())
    assert (
        await service.decide(ADMIN, action.action_id, decision(action.fingerprint))
    ).status == "verified"
    replacement = FakeRetentionContactExecutor(clock=clock, target=target())
    restarted = RetentionContactService(
        store=SqlAlchemyRetentionContacts(db),
        executor=replacement,
        chats=chats,
        clock=clock,
        ids=UuidGenerator(),
        enabled=True,
        allow_self_approval=True,
        controls=SqlAlchemyOperationRepository(db),
        global_kill_switch_default=False,
    )
    new = await restarted.prepare(ADMIN, topic.topic_id, request())
    with pytest.raises(ChatError, match="частоты"):
        await restarted.decide(ADMIN, new.action_id, decision(new.fingerprint))
    assert replacement.dispatch_count == 0 and executor.dispatch_count == 1


async def test_populated_contact_migration_cannot_downgrade_or_delete_audit(system, monkeypatch):  # type: ignore[no-untyped-def]
    import importlib

    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext

    db, _, topic, _, _, _, service = system
    action = await service.prepare(ADMIN, topic.topic_id, request())
    module = importlib.import_module(
        "migrations.versions.b47ea6c9130d_add_private_retention_contact_state"
    )

    def attempt(connection):  # type: ignore[no-untyped-def]
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(connection)))
        with pytest.raises(RuntimeError, match="populated retention contact"):
            module.downgrade()

    async with db.engine.begin() as connection:
        await connection.run_sync(attempt)
    assert (await service.get(ADMIN, action.action_id)).status == "proposed"
    async with db.session_factory() as session:
        assert len((await session.scalars(select(RetentionContactEventRow))).all()) == 1
