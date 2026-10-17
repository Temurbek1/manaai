"""Native v3 private metadata retention; synthetic SQL only, never provider I/O."""

import hashlib
import json
import sqlite3
from pathlib import Path
from uuid import uuid4


def fingerprint(path: Path) -> str:
    expected = json.loads(path.with_suffix(".loop.json").read_text())
    with sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True) as connection:
        rows = connection.execute(
            "SELECT * FROM operation_chat_turns WHERE topic_id=? ORDER BY turn_id",
            (expected["topic_id"],),
        ).fetchall()
    return hashlib.sha256(json.dumps(rows).encode()).hexdigest()


def check_legacy(path: Path) -> None:
    expected = json.loads(path.with_suffix(".loop.json").read_text())
    assert fingerprint(path) == expected["fingerprint"]


async def check_loop(path: Path, *, owner: str, setup: bool = False) -> None:
    from datetime import UTC, datetime

    from app.mana_operation_ai.application.retention.contact_templates import contact_message
    from app.mana_operation_ai.domain.chat import MessageCreate, TopicCreate
    from app.mana_operation_ai.domain.contact_continuation import (
        BoundContactWindow,
        ContactPreparationResult,
    )
    from app.mana_operation_ai.domain.contact_loop import ContactLoopState, verify_loop_window
    from app.mana_operation_ai.domain.contact_preparation import (
        CONTACT_TOOL_LOOP_CONTRACT,
        ContactToolRequest,
        ContactToolSelection,
        contact_selection_fingerprint,
    )
    from app.mana_operation_ai.domain.retention_contact import RetentionContactParameters
    from app.mana_operation_ai.infrastructure.contact_loop_model import (
        capture_loop_append,
        loop_input,
    )
    from app.mana_operation_ai.infrastructure.contact_model_continuation import (
        capture_contact_window,
    )
    from app.mana_operation_ai.infrastructure.persistence.chat_repository import (
        SqlAlchemyChatRepository,
    )
    from app.mana_operation_ai.infrastructure.persistence.database import OperationDatabase
    from app.mana_operation_ai.infrastructure.retention.contact_catalog import sandbox_account_ref

    db = OperationDatabase(f"sqlite+aiosqlite:///{path}")
    repo = SqlAlchemyChatRepository(db, hourly_limit=20, daily_limit=200)
    manifest = path.with_suffix(".loop.json")
    try:
        if setup:
            topic = await repo.create(
                owner,
                TopicCreate(
                    agent_id="retention-agent", product="mana", title="Native contact loop"
                ),
            )
            turn, admitted = await repo.reserve(
                owner,
                topic.topic_id,
                MessageCreate(
                    request_id=uuid4(),
                    message="Synthetic two-contact loop; no real contact.",
                    execution_mode="agent",
                    response_language="uz",
                ),
            )
            assert admitted
            loop = ContactLoopState(root_turn_id=turn.turn_id)
            context = json.dumps(
                {
                    "topic": topic.model_dump(mode="json"),
                    "message": turn.message,
                    "response_language": "uz",
                    "contact_tool_contract": CONTACT_TOOL_LOOP_CONTRACT,
                    "contact_loop": loop.model_dump(mode="json"),
                }
            )
            window = None
            for index, recipient in enumerate(("sample_uz", "sample_ru")):
                selection = ContactToolSelection.model_validate(
                    {"recipient": recipient, "template": "onboarding_help"}
                )
                call_id = f"call_compat_loop_{index}"
                call_hash = hashlib.sha256(call_id.encode()).hexdigest()
                output = [
                    {
                        "type": "function_call",
                        "name": "request_retention_contact_preparation",
                        "call_id": call_id,
                        "arguments": selection.model_dump_json(),
                    }
                ]
                if window is None:
                    window = capture_contact_window(
                        model="compatibility-fake",
                        effort="medium",
                        instructions="Synthetic pairing; never a real send grant.",
                        context=context,
                        output=output,
                    )
                else:
                    window = capture_loop_append(
                        window, input_items=loop_input(window, loop, None), output=output
                    )
                request = ContactToolRequest(
                    **selection.model_dump(),
                    contract=CONTACT_TOOL_LOOP_CONTRACT,
                    provider_call_sha256=call_hash,
                    selection_fingerprint=contact_selection_fingerprint(
                        owner,
                        topic.topic_id,
                        turn.turn_id,
                        selection,
                        call_hash,
                        contract=CONTACT_TOOL_LOOP_CONTRACT,
                    ),
                )
                assert await repo.update(
                    turn.model_copy(
                        update={
                            "status": "completed",
                            "next_action": "retention_contacts",
                            "contact_tool_contract": CONTACT_TOOL_LOOP_CONTRACT,
                            "contact_loop": loop,
                            "contact_preparation": request,
                            "contact_model_window": BoundContactWindow(
                                protocol="contact-model-continuation-v2",
                                window=window,
                                selection_fingerprint=request.selection_fingerprint,
                            ),
                        }
                    )
                )
                result = ContactPreparationResult(
                    origin_turn_id=turn.turn_id,
                    selection_fingerprint=request.selection_fingerprint,
                    action_id=f"synthetic-loop-action-{index}",
                    action_fingerprint=str(index + 1) * 64,
                    revision=2,
                    observed_at=datetime.now(UTC),
                    template="onboarding_help",
                    message=contact_message(
                        RetentionContactParameters(
                            account_ref=sandbox_account_ref(selection.recipient),
                            template="onboarding_help",
                            language="uz" if recipient == "sample_uz" else "ru",
                        )
                    ),
                    status="verified",
                    result_code="sandbox_accepted",
                )
                turn, admitted = await repo.reserve(
                    owner,
                    topic.topic_id,
                    MessageCreate(
                        request_id=uuid4(),
                        message="Continue exact synthetic SQL result.",
                        execution_mode="agent",
                        response_language="uz",
                    ),
                    contact_result=result,
                )
                assert admitted and turn.contact_loop is not None
                loop = turn.contact_loop
            assert await repo.update(
                turn.model_copy(
                    update={
                        "status": "failed",
                        "answer": "Synthetic unknown model result; never replay.",
                    }
                )
            )
            manifest.write_text(json.dumps({"topic_id": topic.topic_id}))
            manifest.write_text(
                json.dumps({"topic_id": topic.topic_id, "fingerprint": fingerprint(path)})
            )
        else:
            check_legacy(path)
            expected = json.loads(manifest.read_text())
            turns = await repo.turns(owner, expected["topic_id"])
            assert len(turns) == 3
            root = await repo.turn(owner, expected["topic_id"], turns[0].turn_id)
            for item in turns[:2]:
                restored = await repo.turn(owner, expected["topic_id"], item.turn_id)
                assert restored.contact_model_window and restored.contact_preparation
                assert restored.contact_loop and restored.contact_reply_turn_id
                verify_loop_window(
                    restored.contact_model_window.window,
                    restored.contact_preparation,
                    restored.contact_loop,
                    owner=owner,
                    topic_id=expected["topic_id"],
                    turn_id=restored.turn_id,
                    root_message=root.message,
                    response_language="uz",
                )
            final = await repo.turn(owner, expected["topic_id"], turns[-1].turn_id)
            assert final.status == "failed" and final.contact_loop
            assert (
                len(final.contact_loop.receipts) == 2
                and not final.contact_loop.allowed_recipients()
            )
            check_legacy(path)
    finally:
        await db.dispose()
