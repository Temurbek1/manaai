"""New native protocol2 never recaptures prior protocol1 manager turns."""

from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from app.mana_ai.application.chat_ports import ChatModelReceipt, ChatPrompt, ParentChatError
from app.mana_ai.domain.family_agents import ParentTouchMessageRequest, ParentTouchReviewedTurn
from app.services.compact_manager_decision_store import (
    SqliteClosedCompactManagerDecisionStore,
    SqliteCompactManagerDecisionStore,
)
from app.services.mana_chat_lab import LAB_PARENT, ChatLab
from tests.test_compact_manager_native import setup
from tests.test_mana_chat_lab import Clock
from tests.test_saved_observations import snapshot


def store(lab: ChatLab) -> SqliteCompactManagerDecisionStore:
    assert isinstance(lab.store, SqliteCompactManagerDecisionStore)
    return lab.store


def seed_prior_v1_capture(lab: ChatLab, turn_id: int) -> None:
    """Recreate the exact prior44 pair, before its original scope was captured."""
    with store(lab)._transaction() as db:
        original = db.execute(
            "SELECT binding FROM parent_touch_manager_turns WHERE turn_id=?", (turn_id,)
        ).fetchone()[0]
        current = db.execute(
            "SELECT binding,scope,scope_hash FROM compact_manager_admissions WHERE turn_id=?",
            (turn_id,),
        ).fetchone()
        assert tuple(current) == ("native-manager-v2:" + original, None, None)
        db.execute(
            "UPDATE compact_manager_admissions SET binding=? WHERE turn_id=?",
            (original, turn_id),
        )
        db.execute(
            "UPDATE parent_publication_captures SET manager_binding=? WHERE turn_id=?",
            ("native-manager-v1:" + original, turn_id),
        )


def captured_pair(lab: ChatLab, turn_id: int) -> tuple[object, ...]:
    with store(lab)._connect() as db:
        row = db.execute(
            "SELECT a.binding,a.request_hash,a.scope,a.scope_hash,p.manager_binding "
            "FROM compact_manager_admissions a JOIN parent_publication_captures p "
            "ON p.turn_id=a.turn_id AND p.parent_id=a.parent_id WHERE a.turn_id=?",
            (turn_id,),
        ).fetchone()
        assert row is not None
        return tuple(row)


def forbid_inference(lab: ChatLab, monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    calls = {"count": 0, "respond": 0}

    async def count(prompt: ChatPrompt) -> int:
        calls["count"] += 1
        raise AssertionError("Compatibility observation must not count model input")

    async def respond(prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
        calls["respond"] += 1
        raise AssertionError("Compatibility observation must not invoke a model")

    monkeypatch.setattr(lab.touch._model, "count_input", count)
    monkeypatch.setattr(lab.touch._model, "respond", respond)
    return calls


async def test_prior_v1_scope_survives_restart_rearm_and_new_v2_turn_in_same_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lab = await setup(tmp_path / "mixed-protocols")
    try:
        calls = forbid_inference(lab, monkeypatch)
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT, request_id=uuid4(), message="Привет"
        )
        admitted = await lab.touch.admit_message(request)
        seed_prior_v1_capture(lab, admitted.turn_id)
        assert isinstance(lab.options.clock, Clock)
        claimed = await store(lab).claim_reviewed_response(lab.options.clock.now())
        assert claimed and claimed[0].turn.turn_id == admitted.turn_id
        original_scope = await store(lab).manager_scope(LAB_PARENT, admitted.turn_id)
        assert original_scope and original_scope.compact_decision_protocol == 1
        original_pair = captured_pair(lab, admitted.turn_id)
        assert original_pair[0] == store(lab)._manager_binding
        assert original_pair[4] == "native-manager-v1:" + original_pair[0]
        assert '"compact_decision_protocol"' not in str(original_pair[2])
        before_restart = snapshot(store(lab)._path)
        options = lab.options
        await lab.close()
        lab = ChatLab(options)
        await lab.start()
        assert snapshot(store(lab)._path) == before_restart
        restart_calls = forbid_inference(lab, monkeypatch)
        assert await store(lab).manager_scope(LAB_PARENT, admitted.turn_id) == original_scope
        store(lab)._compact_decisions_enabled = False
        with pytest.raises(ParentChatError, match="compact_manager_disabled"):
            await store(lab).manager_scope(LAB_PARENT, admitted.turn_id)
        assert snapshot(store(lab)._path) == before_restart
        store(lab)._compact_decisions_enabled = True
        assert await store(lab).manager_scope(LAB_PARENT, admitted.turn_id) == original_scope
        assert captured_pair(lab, admitted.turn_id) == original_pair
        # Another fictional parent avoids changing or finishing the first pending
        # turn. Direct SQL admission grants no source or family ownership access.
        newer = ParentTouchReviewedTurn(parent_id="456", request_id=uuid4(), message="Привет")
        new_admission = await store(lab).admit_reviewed(newer, options.clock.now(), allow_new=True)
        new_claim = await store(lab).claim_reviewed_response(options.clock.now())
        assert new_claim and new_claim[0].turn.turn_id == new_admission.turn.turn_id
        new_scope = await store(lab).manager_scope("456", new_admission.turn.turn_id)
        assert new_scope and new_scope.compact_decision_protocol == 2
        new_pair = captured_pair(lab, new_admission.turn.turn_id)
        assert new_pair[0] == new_pair[4] == "native-manager-v2:" + store(lab)._manager_binding
        assert '"compact_decision_protocol"' not in str(new_pair[2])
        assert await store(lab).manager_scope(LAB_PARENT, admitted.turn_id) == original_scope
        assert captured_pair(lab, admitted.turn_id) == original_pair
        assert calls == restart_calls == {"count": 0, "respond": 0}
    finally:
        await lab.close()


@pytest.mark.parametrize("changed", ["publication_only_v1", "admission_only_plain_v1"])
async def test_mixed_v1_v2_pairing_fails_before_input_count_or_inference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, changed: str
) -> None:
    lab = await setup(tmp_path / changed)
    try:
        calls = forbid_inference(lab, monkeypatch)
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT, request_id=uuid4(), message="Привет"
        )
        admitted = await lab.touch.admit_message(request)
        with store(lab)._transaction() as db:
            original = db.execute(
                "SELECT binding FROM parent_touch_manager_turns WHERE turn_id=?",
                (admitted.turn_id,),
            ).fetchone()[0]
            if changed == "publication_only_v1":
                db.execute(
                    "UPDATE parent_publication_captures SET manager_binding=? WHERE turn_id=?",
                    ("native-manager-v1:" + original, admitted.turn_id),
                )
            else:
                db.execute(
                    "UPDATE compact_manager_admissions SET binding=? WHERE turn_id=?",
                    (original, admitted.turn_id),
                )
        assert not await lab.touch.process_reviewed_message()
        state = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert state.phase == "failed" and state.error_code == "compact_manager_capture_invalid"
        assert state.response is None
        quota = (await lab.state()).history.quota
        assert quota.used_tokens == quota.reserved_tokens == 0
        with store(lab)._connect() as db:
            assert not db.execute("SELECT 1 FROM compact_manager_decisions").fetchone()
        assert calls == {"count": 0, "respond": 0}
    finally:
        await lab.close()


async def test_unknown_v1_hold_and_pair_survive_closed44_restart_rearm_and_next_day(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lab = await setup(tmp_path / "unknown-v1")
    try:
        calls = forbid_inference(lab, monkeypatch)
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT, request_id=uuid4(), message="Привет"
        )
        admitted = await lab.touch.admit_message(request)
        seed_prior_v1_capture(lab, admitted.turn_id)
        assert isinstance(lab.options.clock, Clock)
        now = lab.options.clock.now()
        claimed = await store(lab).claim_reviewed_response(now)
        assert claimed and claimed[0].turn.turn_id == admitted.turn_id
        scope = await store(lab).manager_scope(LAB_PARENT, admitted.turn_id)
        assert scope and scope.compact_decision_protocol == 1
        original_pair = captured_pair(lab, admitted.turn_id)
        # Simulate a submitted invocation with no terminal receipt, without any
        # provider/model call or invented priced usage.
        await store(lab).submit(claimed[0].turn, reserved_tokens=612, now=now)
        await store(lab).fail(claimed[0].turn, code="model_receipt_unknown", unknown=True)
        with store(lab)._connect() as db:
            original_hold = tuple(
                db.execute(
                    "SELECT status,reserved,input_tokens,output_tokens,request_digest "
                    "FROM parent_chat_turns WHERE id=?",
                    (admitted.turn_id,),
                ).fetchone()
            )
        assert original_hold[:4] == ("unknown", 612, None, None)
        store(lab)._compact_decisions_enabled = False
        assert await store(lab).claim_reviewed_response(now) is None
        before = snapshot(store(lab)._path)
        await SqliteClosedCompactManagerDecisionStore(
            store(lab)._path, history_only=True, daily_limit=2000, timezone="Asia/Samarkand"
        ).initialize()
        assert snapshot(store(lab)._path) == before
        options = lab.options
        await lab.close()
        lab = ChatLab(options)
        await lab.start()
        assert snapshot(store(lab)._path) == before
        restart_calls = forbid_inference(lab, monkeypatch)
        assert store(lab)._compact_decisions_enabled
        assert isinstance(options.clock, Clock)
        options.clock.value += timedelta(days=1)
        assert not await lab.touch.process_reviewed_message()
        history = await lab.touch.read_touch_history(LAB_PARENT, before=None, limit=100)
        assert history.quota.blocked_by_unresolved_request
        with store(lab)._connect() as db:
            assert (
                tuple(
                    db.execute(
                        "SELECT status,reserved,input_tokens,output_tokens,request_digest "
                        "FROM parent_chat_turns WHERE id=?",
                        (admitted.turn_id,),
                    ).fetchone()
                )
                == original_hold
            )
        assert captured_pair(lab, admitted.turn_id) == original_pair
        assert calls == restart_calls == {"count": 0, "respond": 0}
    finally:
        await lab.close()
