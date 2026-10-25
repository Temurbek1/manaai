"""One profile read, minimized account answers and no commercial facts in Child-Safety."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from pytest import MonkeyPatch

from app.mana_ai.application.chat_ports import ChatModelReceipt, ChatPrompt
from app.mana_ai.domain.family_agents import ParentTouchMessageRequest
from app.services.mana_chat_lab import LAB_PARENT, ChatLab, LabOptions
from app.services.parent_chat_children import ManakidsChatChildrenSource
from tests.test_mana_chat_lab import Clock
from tests.test_parent_chat_adapters import parent_payload


def tariff_row() -> dict[str, Any]:
    return {
        "tariff_name": "One Month",
        "is_paid": True,
        "valid_until": "2026-11-23T16:00:00+05:00",
        "payment_date": "2026-10-01T10:00:00+05:00",
        "created_at": "PRIVATE date with unconfirmed semantics",
        "agent_trial_used": True,
        "referral_code": "PRIVATE unverified field",
    }


@pytest.mark.parametrize("paid", [True, False, None])
async def test_tariff_fields_use_the_same_filtered_profile_read_without_extra_http(
    paid: bool | None,
) -> None:
    seen: list[httpx.Request] = []
    payload = deepcopy(parent_payload())
    row = payload["results"][0]
    row.update(tariff_row() | {"is_paid": paid})

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"access": "fake"} if request.method == "POST" else payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        source = ManakidsChatChildrenSource(
            client=client, base_url="https://mana.test", username="unit", password="unit"
        )
        result = await source.read("123")
    assert len(seen) == 2
    assert seen[1].url.path == "/api/v1/admin-panel-parent/parent-list/"
    assert dict(seen[1].url.params) == {"parent_id": "123", "limit": "1", "offset": "0"}
    assert result.tariff and result.tariff.is_paid is paid
    assert result.tariff.collected_at == result.collected_at
    assert result.tariff.valid_until and result.tariff.valid_until.utcoffset() == timedelta(hours=5)
    assert "PRIVATE" not in result.model_dump_json()
    assert result.children[0].child_id == 456


@pytest.mark.parametrize("change", ["missing", "bool", "naive", "number", "future", "name"])
async def test_optional_invalid_tariff_does_not_discard_child_ownership(change: str) -> None:
    payload = deepcopy(parent_payload())
    row = payload["results"][0]
    row.update(tariff_row())
    if change == "missing":
        del row["is_paid"]
    elif change == "bool":
        row["is_paid"] = 1
    elif change == "naive":
        row["valid_until"] = "2026-11-23T16:00:00"
    elif change == "number":
        row["payment_date"] = 1234
    elif change == "future":
        row["payment_date"] = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    elif change == "name":
        row["tariff_name"] = "x" * 101
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200, json={"access": "fake"} if r.method == "POST" else payload
            )
        )
    ) as client:
        result = await ManakidsChatChildrenSource(
            client=client, base_url="https://mana.test", username="unit", password="unit"
        ).read("123")
    assert result.children[0].child_id == 456 and result.children[0].connected
    assert result.tariff is None
    assert '"tariff"' not in result.model_dump_json()


@pytest.mark.parametrize("ticking", [False, True])
async def test_speaker_answers_account_question_but_child_review_never_receives_tariff(
    tmp_path: Path, monkeypatch: MonkeyPatch, ticking: bool
) -> None:
    class TickingClock(Clock):
        def now(self) -> datetime:
            self.value += timedelta(microseconds=1)
            return self.value

    clock = TickingClock() if ticking else Clock()
    lab = ChatLab(
        LabOptions(
            tmp_path / "profile",
            clock=clock,
            worker_enabled=False,
            native_sources=True,
            native_observations=True,
            source_reviews=True,
            reminders=True,
            retention=True,
            upsell=True,
            tariff_context=True,
        )
    )
    await lab.start()
    speaker, child = lab._models
    from app.services.lab_native_source_model import LabNativeSourceModel

    assert isinstance(child, LabNativeSourceModel)
    speaker_original, child_original = speaker.respond, child._fallback.respond
    speaker_inputs: list[ChatPrompt] = []
    child_inputs: list[ChatPrompt] = []

    async def speaking(prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
        speaker_inputs.append(prompt)
        return await speaker_original(prompt, max_output_tokens=max_output_tokens)

    async def reviewing(prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
        child_inputs.append(prompt)
        return await child_original(prompt, max_output_tokens=max_output_tokens)

    monkeypatch.setattr(speaker, "respond", speaking)
    monkeypatch.setattr(child._fallback, "respond", reviewing)
    request = ParentTouchMessageRequest(
        parent_id=LAB_PARENT,
        request_id=uuid4(),
        message="Какой у меня тариф и когда заканчивается?",
    )
    try:
        await lab.touch.admit_message(request)
        review = await lab.safety.process_one()
        assert review and review.status == "completed"
        assert await lab.touch.process_reviewed_message()
        state = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert state.phase == "completed" and state.response
        assert "2026-11-23 16:00" in state.response.answer
        assert "Fictional 1-Month" in speaker_inputs[0].messages[0][1]
        assert all(
            "Fictional 1-Month" not in str(p) and "parent_tariff" not in str(p)
            for p in child_inputs
        )
        assert (await lab.touch.admit_message(request)).phase == "completed"
        assert len(speaker_inputs) == len(child_inputs) == 1
        assert lab.catalog.calls == lab.battery.calls == lab.app_usage.calls == 0
        assert (await lab.state()).history.quota.used_tokens == 150
        assert not await lab.touch.process_upsell()
        assert lab.touch.proactive and lab.touch.proactive._gateway is None
    finally:
        await lab.close()


async def test_mismatched_collection_or_stale_tariff_is_not_shown(tmp_path: Path) -> None:
    from app.mana_ai.application.parent_touch import ParentTouchService
    from app.mana_ai.domain.chat import ParentTariffContext
    from app.mana_ai.domain.family_agents import ParentTouchRequest
    from tests.test_family_agent_queue import store
    from tests.test_parent_chat import NOW, Children, Model

    context = await Children().read("123")
    stale = ParentTariffContext(
        collected_at=NOW - timedelta(minutes=4),
        tariff_name="STALE",
        is_paid=True,
        valid_until=NOW + timedelta(days=1),
        payment_date=None,
        agent_trial_used=None,
    )
    context = context.model_copy(update={"tariff": stale})
    repository = await store(tmp_path / "chat.db")
    service = ParentTouchService(
        store=repository,
        children=Children(),
        model=Model(),
        clock=lambda: NOW,
        max_output_tokens=512,
        history_turn_limit=2,
    )
    request = ParentTouchRequest(parent_id="123", request_id=uuid4(), message="Мой тариф?")
    turn = await repository.admit(request, NOW)
    prompt = await service._prepare_prompt(
        turn,
        request,
        context,
        (("user", '{"profiles":[],"limitations":[]}'), ("user", request.message)),
    )
    assert "STALE" not in str(prompt)
    assert "parent_tariff" not in prompt.messages[0][1]
