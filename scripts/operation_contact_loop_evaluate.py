"""One opt-in synthetic native contact loop; no sources, application startup or send.

Default execution prints an offline plan. An attempted paid party is never resumed;
existing output directories are refused. Two calls share a new $0.50 SQL ledger.
The first context is assembled here, not admitted through the HTTP/chat service.
Continuation uses the actual owning preparation, SQL and application/model path.
"""

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import SecretStr
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import Settings, get_settings  # noqa: E402
from app.mana_operation_ai.application.admin_service import ActorContext  # noqa: E402
from app.mana_operation_ai.application.chat_service import (  # noqa: E402
    SESSION_INSTRUCTIONS,
    WORKSPACE_INSTRUCTIONS,
    chat_card_purposes,
)
from app.mana_operation_ai.application.contact_result_continuation import (  # noqa: E402
    ContactResultContinuationService,
)
from app.mana_operation_ai.application.inference_errors import InferenceProviderError  # noqa: E402
from app.mana_operation_ai.application.retention.contact import (
    RetentionContactService,  # noqa: E402
)
from app.mana_operation_ai.application.runtime import SystemClock, UuidGenerator  # noqa: E402
from app.mana_operation_ai.application.session_context import OperationSessionContext  # noqa: E402
from app.mana_operation_ai.application.workspace_retention_contacts import (  # noqa: E402
    WorkspaceRetentionContacts,
)
from app.mana_operation_ai.domain.chat import (  # noqa: E402
    ChatNextAction,
    MessageCreate,
    TopicCreate,
)
from app.mana_operation_ai.domain.contact_continuation import (  # noqa: E402
    BoundContactWindow,
    ContactContinueRequest,
    verify_window_request,
)
from app.mana_operation_ai.domain.contact_preparation import (  # noqa: E402
    CONTACT_TOOL_CONTINUATION_CONTRACT,
    ContactToolRequest,
    contact_selection_fingerprint,
)
from app.mana_operation_ai.domain.cost_control import CostLimits, ResourceUsage  # noqa: E402
from app.mana_operation_ai.domain.enums import UserRole  # noqa: E402
from app.mana_operation_ai.domain.workspace_retention_contacts import (  # noqa: E402
    WorkspaceContactPrepare,
)
from app.mana_operation_ai.infrastructure.chat_model import OpenAIConversationModel  # noqa: E402
from app.mana_operation_ai.infrastructure.persistence.chat_repository import (  # noqa: E402
    SqlAlchemyChatRepository,
)
from app.mana_operation_ai.infrastructure.persistence.cost_ledger import (  # noqa: E402
    SqlAlchemyCostLedger,
)
from app.mana_operation_ai.infrastructure.persistence.database import (
    OperationDatabase,  # noqa: E402
)
from app.mana_operation_ai.infrastructure.persistence.goal_repository import (  # noqa: E402
    SqlAlchemyGoalRepository,
)
from app.mana_operation_ai.infrastructure.persistence.models import CostReservationRow  # noqa: E402
from app.mana_operation_ai.infrastructure.persistence.repository import (  # noqa: E402
    SqlAlchemyOperationRepository,
)
from app.mana_operation_ai.infrastructure.persistence.retention_contact import (  # noqa: E402
    SqlAlchemyRetentionContacts,
)
from app.mana_operation_ai.infrastructure.retention.contact_catalog import (  # noqa: E402
    FakeRetentionContactCatalog,
    sandbox_account_ref,
)

MODEL: Literal["gpt-6.1-sol"] = "gpt-6.1-sol"
CAP_MICROUSD = 500_000
OWNER = "synthetic-contact-loop"
MESSAGE = (
    "Проверь только вымышленный контактный sandbox MANA: попроси подготовить помощь "
    "с настройкой для sample_uz. Ответ мне нужен на русском, само тестовое сообщение "
    "на узбекском. Не отправляй сообщение, не согласовывай его и не читай внешние данные."
)
CONDITION = (
    "Дополнение после запроса: не предлагай скидки или другие сообщения. "
    "Объясни текущее состояние тестовой подготовки и следующий отдельный шаг человека."
)


@dataclass(frozen=True)
class FixtureClock:
    at: datetime

    def now(self) -> datetime:
        return self.at


def plan() -> dict[str, object]:
    return {
        "model": MODEL,
        "reasoning": "low",
        "max_calls": 2,
        "max_output_tokens_per_call": 2048,
        "cap_microusd": CAP_MICROUSD,
        "source_attempts": 0,
        "real_contacts": 0,
        "fake_sends": 0,
        "approval_or_deployment": False,
        "automatic_retry_or_resume": False,
        "initial_context": "synthetic assembly using actual workspace instructions",
        "quality_status": "manual_review_required",
    }


def diagnostic_settings(key: SecretStr) -> Settings:
    return Settings(
        _env_file=None,
        openai_api_key=key,
        operation_model_selection_enabled=True,
        operation_chat_max_output_tokens=2048,
        operation_chat_model=MODEL,
        operation_chat_reasoning_effort="low",
        operation_chat_rate_model=MODEL,
        operation_chat_input_usd_per_million="2.00",
        operation_chat_cached_input_usd_per_million="0.10",
        operation_chat_cache_write_usd_per_million="2.50",
        operation_chat_output_usd_per_million="10.00",
        openai_max_output_tokens=2048,
        operation_chat_max_input_tokens=64000,
        operation_workspace_contact_tool_proposals_enabled=True,
        operation_workspace_contact_tool_continuations_enabled=True,
    )


async def run(directory: Path) -> dict[str, object]:
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    (directory / "plan.json").write_text(json.dumps(plan(), indent=2))
    database = OperationDatabase(f"sqlite+aiosqlite:///{directory.resolve() / 'isolated.db'}")
    await database.create_schema()
    clock = SystemClock()
    # A dated fictional fixture clock, never a changed application/policy clock.
    fixture_clock = FixtureClock((clock.now() - timedelta(days=1)).replace(hour=12))
    limits = ResourceUsage(
        llm_calls=2,
        provider_requests=2,
        input_tokens=128000,
        output_tokens=4096,
        response_bytes=524288,
        llm_microusd=CAP_MICROUSD,
    )
    ledger = SqlAlchemyCostLedger(
        database, clock=clock, limits=CostLimits(daily=limits, monthly=limits)
    )
    gateway: OpenAIConversationModel | None = None
    result: dict[str, object] = {
        "plan": plan(),
        "status": "failed",
        "phase": "configuration",
        "fixture_at": fixture_clock.now().isoformat(),
        "quality_status": "manual_review_pending",
    }
    catalog = FakeRetentionContactCatalog(fixture_clock)
    try:
        # Select only the inference secret; never pass deployment/source URLs or keys.
        gateway = OpenAIConversationModel(
            diagnostic_settings(get_settings().openai_api_key), ledger=ledger
        )
        if str(gateway._client.base_url).rstrip("/") != "https://api.openai.com/v1":
            raise ValueError("Only the official API endpoint is allowed")
        chats = SqlAlchemyChatRepository(database, hourly_limit=10, daily_limit=10)
        await chats.initialize()
        topic = await chats.create(
            OWNER, TopicCreate(agent_id="retention-agent", product="mana", title="Synthetic loop")
        )
        origin, _ = await chats.reserve(
            OWNER,
            topic.topic_id,
            MessageCreate(
                request_id=uuid4(),
                message=MESSAGE,
                execution_mode="agent",
                response_language="ru",
                model_choice=MODEL,
                reasoning="low",
            ),
        )
        allowed: list[ChatNextAction] = ["none", "start_goal", "retention_contacts"]
        context = json.dumps(
            {
                "topic": topic.model_dump(mode="json"),
                "message": MESSAGE,
                "evaluation_time": clock.now().isoformat(),
                "response_language": "ru",
                "inference": {"model_choice": MODEL, "reasoning": "low"},
                "contact_tool_contract": CONTACT_TOOL_CONTINUATION_CONTRACT,
                "allowed_next_actions": allowed,
                "card_purposes": chat_card_purposes(allowed, default_capability_key=None),
                "shared_goals_enabled": True,
                "parent_summary_enabled": False,
                "history": [],
                "saved_reports": [],
                "session_memory": None,
                "older_turns_omitted": 0,
                "report_text_shortened": False,
            },
            ensure_ascii=False,
        )
        result["phase"] = "native_choice"
        async with asyncio.timeout(180):
            output = await gateway.reply(
                instructions=WORKSPACE_INSTRUCTIONS + SESSION_INSTRUCTIONS,
                context=context,
                owner=OWNER,
            )
        if (
            output.contact_selection is None
            or output.contact_call_sha256 is None
            or output.contact_model_window is None
            or output.next_action != "retention_contacts"
            or output.contact_selection.recipient != "sample_uz"
            or output.contact_selection.template != "onboarding_help"
        ):
            raise ValueError("The requested fictional native choice was not returned")
        selection = ContactToolRequest(
            **output.contact_selection.model_dump(),
            contract=CONTACT_TOOL_CONTINUATION_CONTRACT,
            provider_call_sha256=output.contact_call_sha256,
            selection_fingerprint=contact_selection_fingerprint(
                OWNER,
                topic.topic_id,
                origin.turn_id,
                output.contact_selection,
                output.contact_call_sha256,
                contract=CONTACT_TOOL_CONTINUATION_CONTRACT,
            ),
        )
        verify_window_request(
            output.contact_model_window,
            selection,
            topic_id=topic.topic_id,
            message=MESSAGE,
            response_language="ru",
        )
        await chats.update(
            origin.model_copy(
                update={
                    "status": "completed",
                    "answer": output.answer,
                    "next_action": output.next_action,
                    "contact_tool_contract": CONTACT_TOOL_CONTINUATION_CONTRACT,
                    "contact_preparation": selection,
                    "contact_model_window": BoundContactWindow(
                        selection_fingerprint=selection.selection_fingerprint,
                        window=output.contact_model_window,
                    ),
                }
            )
        )
        condition, _ = await chats.reserve(
            OWNER,
            topic.topic_id,
            MessageCreate(request_id=uuid4(), message=CONDITION, execution_mode="agent"),
        )
        await chats.update(condition.model_copy(update={"status": "completed"}))
        store = SqlAlchemyRetentionContacts(database)
        contacts = RetentionContactService(
            store=store,
            executor=catalog,
            chats=chats,
            clock=fixture_clock,
            ids=UuidGenerator(),
            enabled=True,
            allow_self_approval=False,
            controls=SqlAlchemyOperationRepository(database),
            global_kill_switch_default=False,
        )
        bridge = WorkspaceRetentionContacts(
            chats=chats,
            contacts=contacts,
            store=store,
            enabled=True,
            allow_self_approval=False,
            recipients=catalog.recipients,
            account_refs={item.key: sandbox_account_ref(item.key) for item in catalog.recipients},
            continuations_enabled=True,
        )
        actor = ActorContext(actor_id=OWNER, role=UserRole.OPERATOR)
        result["phase"] = "human_preparation"
        action = await bridge.prepare(
            actor,
            topic.topic_id,
            origin.turn_id,
            WorkspaceContactPrepare(
                request_id=uuid4(),
                confirmed=True,
                recipient=selection.recipient,
                template=selection.template,
                selection_fingerprint=selection.selection_fingerprint,
            ),
        )
        result["prepared_status"] = action.status
        service = ContactResultContinuationService(
            chats=chats,
            contacts=bridge,
            model=gateway,
            context=OperationSessionContext(
                chats, SqlAlchemyGoalRepository(database, clock), contacts=bridge
            ),
            enabled=True,
        )
        request = ContactContinueRequest(
            request_id=uuid4(),
            confirmed=True,
            action_id=action.action_id,
            action_fingerprint=action.fingerprint,
            revision=action.revision,
        )
        result["phase"] = "result_continuation"
        child = await service.continue_with_result(actor, topic.topic_id, origin.turn_id, request)
        observed = await service.continue_with_result(
            actor,
            topic.topic_id,
            origin.turn_id,
            request.model_copy(update={"request_id": uuid4()}),
        )
        result.update(
            status=child.status,
            phase="stored_result",
            answer=child.answer,
            response_language=child.response_language,
            selection=output.contact_selection.model_dump(),
            replay_same_turn=observed.turn_id == child.turn_id,
        )
    except InferenceProviderError as exc:
        result.update(failure_kind=exc.kind, http_status=exc.http_status)
    except Exception:
        # Do not log provider prose, credentials, encrypted items or raw exceptions.
        result["failure_kind"] = "unclassified"
    finally:
        if gateway is not None:
            await gateway.close()
        async with database.session_factory() as session:
            rows = list((await session.scalars(select(CostReservationRow))).all())
        result["accounting"] = {
            "calls": len(rows),
            "known_microusd": sum(
                ResourceUsage.model_validate(row.actual).llm_microusd
                for row in rows
                if row.actual is not None
            ),
            "unknown_hold_microusd": sum(
                ResourceUsage.model_validate(row.usage).llm_microusd
                for row in rows
                if row.actual is None
            ),
        }
        result["fake_target_reads"] = sum(item.target_reads for item in catalog.executors.values())
        result["fake_sends"] = sum(item.dispatch_count for item in catalog.executors.values())
        result["finished_at"] = datetime.now(UTC).isoformat()
        (directory / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
        await database.dispose()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-paid", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not args.confirm_paid:
        print(json.dumps(plan(), indent=2))
        return
    if args.output is None:
        parser.error("A fresh output directory is required; no previous attempt can be resumed")
    os.umask(0o077)
    print(json.dumps(asyncio.run(run(args.output)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
