"""Blocked providers must not serialize unrelated family workflows or repeat claims."""

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.mana_ai.application.chat_ports import ChatModelReceipt, ChatPrompt, ParentChatError
from app.mana_ai.domain.child_safety import ChildSafetyLimits
from app.mana_ai.domain.family_agents import AgentQuestionRequest, ParentTouchMessageRequest
from app.mana_ai.domain.parent_notifications import ParentPushMessage, ParentPushReceipt
from app.mana_ai.domain.proactive_parent import ParentContactContext
from app.services import parent_chat_runtime as runtime_module
from app.services.family_agent_worker import FamilyAgentWorker
from app.services.mana_chat_lab import ChatLab, LabOptions, SimulatedModel
from tests.test_child_safety_store import analysis, target
from tests.test_family_source_runtime import config, make_credential_file
from tests.test_parent_chat import NOW, Children


class Clock:
    def now(self) -> datetime:
        return NOW


class GateModel(SimulatedModel):
    def __init__(self) -> None:
        super().__init__("safety")
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = 0

    async def respond(self, prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
        self.calls += 1
        self.started.set()
        await self.release.wait()
        return await super().respond(prompt, max_output_tokens=max_output_tokens)


class Push:
    def __init__(self) -> None:
        self.sent = asyncio.Event()
        self.calls = 0

    async def send(self, message: ParentPushMessage) -> ParentPushReceipt:
        self.calls += 1
        self.sent.set()
        return ParentPushReceipt(queued_devices=1)


def options(path: Path) -> LabOptions:
    return LabOptions(
        path,
        clock=Clock(),
        worker_enabled=False,
        parallel_worker=True,
        native_sources=True,
        native_observations=True,
        source_reviews=True,
        reminders=True,
        retention=True,
        upsell=True,
        tariff_context=True,
        expiry=True,
        manager=True,
        expiry_fixture_days=30,
    )


async def setup(path: Path) -> tuple[ChatLab, GateModel, FamilyAgentWorker]:
    lab = ChatLab(options(path))
    await lab.start()
    # Two declared fictional families, never a real family or provider. The
    # browser lab itself continues to refuse any parent except its single fixture.
    children = Children()
    lab.touch._children = lab.safety._children = children
    gate = GateModel()
    lab.safety._model = gate
    worker = lab._worker
    assert worker is not None and worker._parallel_enabled
    worker._interval = 0.01
    return lab, gate, worker


async def wait_for_message(lab: ChatLab, request: ParentTouchMessageRequest) -> None:
    async with asyncio.timeout(3):
        while (await lab.touch.message_state(request.parent_id, request.request_id)).phase not in {
            "completed",
            "failed",
            "unknown",
        }:
            await asyncio.sleep(0.01)


async def test_slow_safety_does_not_block_other_family_chat_or_saved_push_and_claims_once(
    tmp_path: Path,
) -> None:
    lab, gate, worker = await setup(tmp_path / "responsive")
    other = FamilyAgentWorker(
        lab.safety, lab.touch, clock=Clock().now, interval=0.01, parallel_enabled=True
    )
    try:
        job = await lab.safety.admit(target(), analysis(percent=12))
        worker.start()
        other.start()
        await asyncio.wait_for(gate.started.wait(), timeout=3)
        request = ParentTouchMessageRequest(parent_id="456", request_id=uuid4(), message="Привет")
        await lab.touch.admit_message(request)
        await wait_for_message(lab, request)
        state = await lab.touch.message_state("456", request.request_id)
        assert state.phase == "completed" and state.response
        assert state.response.quota.used_tokens == 150
        assert not gate.release.is_set() and gate.calls == 1
        assert (await lab.safety.assessment("123", job.job_id)).status == "submitted"
        assert len((await lab.touch.read_touch_history("123", before=None, limit=30)).messages) == 0
        with pytest.raises(ParentChatError, match="not_found"):
            await lab.touch.message_state("123", request.request_id)

        # A separate permitted push for an already saved assistant question must
        # also pass while another family's model response remains in flight.
        lab.store._push_enabled = True
        assert lab.touch.proactive
        push = Push()
        lab.touch.proactive._gateway = push
        await lab.touch.proactive.register(
            ParentContactContext(
                parent_id="456",
                event_id=uuid4(),
                revision=1,
                observed_at=NOW,
                valid_until=NOW + timedelta(days=1),
                language="ru",
                timezone="Asia/Tashkent",
                safety_chat_consent=True,
                safety_push_consent=True,
                marketing_push_consent=False,
            )
        )
        await lab.touch.request_question(
            AgentQuestionRequest(
                parent_id="456",
                child_id=457,
                agent_id="child-safety",
                request_id=uuid4(),
                information_key="routine.sleep",
                question="Во сколько ребёнок ложится спать?",
                reason="Fictional routine clarification",
                source_revision="parallel-fixture-v1",
                priority=1,
                observed_at=NOW,
                expires_at=NOW + timedelta(hours=1),
            )
        )
        await asyncio.wait_for(push.sent.wait(), timeout=3)
        assert push.calls == 1 and gate.calls == 1 and not gate.release.is_set()
        history = await lab.touch.read_touch_history("456", before=None, limit=30)
        assert history.active_question
        assert [message.role for message in history.messages] == ["user", "assistant", "assistant"]
        gate.release.set()
        async with asyncio.timeout(3):
            while (await lab.safety.assessment("123", job.job_id)).status not in {
                "completed",
                "failed",
                "unknown",
            }:
                await asyncio.sleep(0.01)
        assert (await lab.safety.assessment("123", job.job_id)).status == "completed"
        assert gate.calls == 1
        assert (await lab.safety.budget("123")).server_used_tokens == 150
        assert await lab.touch.admit_message(request) == state
    finally:
        gate.release.set()
        await other.close()
        await lab.close()


async def test_same_family_still_waits_for_safety_and_shutdown_preserves_unknown_hold(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "unknown"
    lab, gate, worker = await setup(directory)
    try:
        job = await lab.safety.admit(target(), analysis())
        worker.start()
        await asyncio.wait_for(gate.started.wait(), timeout=3)
        request = ParentTouchMessageRequest(parent_id="123", request_id=uuid4(), message="Привет")
        admitted = await lab.touch.admit_message(request)
        assert admitted.phase == "awaiting_review"
        reserved = (await lab.safety.budget("123")).server_reserved_tokens
        assert reserved > 0
        # Exercise the real five-second graceful shutdown and group cancellation.
        await worker.close()
        assert (await lab.safety.assessment("123", job.job_id)).status == "unknown"
        assert (await lab.safety.budget("123")).server_reserved_tokens == reserved
        assert (await lab.touch.message_state("123", request.request_id)).response is None
        assert gate.calls == 1
    finally:
        await lab.close()
    restarted, new_model, new_worker = await setup(directory)
    try:
        new_worker.start()
        await asyncio.sleep(0.05)
        assert (await restarted.safety.assessment("123", job.job_id)).status == "unknown"
        assert (await restarted.safety.budget("123")).server_reserved_tokens == reserved
        assert new_model.calls == 0
        assert await restarted.touch.admit_message(request) == await restarted.touch.message_state(
            "123", request.request_id
        )
    finally:
        await restarted.close()


async def test_default_serial_mode_retains_its_original_ordering(tmp_path: Path) -> None:
    lab, gate, _ = await setup(tmp_path / "serial")
    worker = FamilyAgentWorker(lab.safety, lab.touch, clock=Clock().now, interval=0.01)
    try:
        await lab.safety.admit(target(), analysis())
        worker.start()
        await asyncio.wait_for(gate.started.wait(), timeout=3)
        request = ParentTouchMessageRequest(parent_id="456", request_id=uuid4(), message="Привет")
        await lab.touch.admit_message(request)
        await asyncio.sleep(0.04)
        assert (await lab.touch.message_state("456", request.request_id)).response is None
        gate.release.set()
        await wait_for_message(lab, request)
        assert (await lab.touch.message_state("456", request.request_id)).phase == "completed"
    finally:
        gate.release.set()
        await worker.close()
        await lab.close()


async def test_uncaught_lane_failure_cancels_siblings_without_logging_provider_text_or_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    lab, gate, worker = await setup(tmp_path / "failure")
    calls = 0

    async def fail() -> None:
        nonlocal calls
        calls += 1
        await gate.started.wait()
        raise RuntimeError("synthetic-secret-do-not-log")

    monkeypatch.setattr(lab.source_safety, "process_one", fail)
    try:
        job = await lab.safety.admit(target(), analysis())
        worker.start()
        assert worker._task
        await asyncio.wait_for(asyncio.shield(worker._task), timeout=3)
        assert not lab.safety.worker_available
        assert (await lab.safety.assessment("123", job.job_id)).status == "unknown"
        assert (await lab.safety.budget("123")).server_reserved_tokens > 0
        with pytest.raises(ParentChatError, match="worker_unavailable"):
            await lab.touch.admit_message(
                ParentTouchMessageRequest(parent_id="456", request_id=uuid4(), message="Привет")
            )
        await asyncio.sleep(0.03)
        assert calls == gate.calls == 1
        assert "synthetic-secret-do-not-log" not in caplog.text
        assert "lane=sources" in caplog.text
        with pytest.raises(RuntimeError, match="already started"):
            worker.start()
    finally:
        await lab.close()


def test_parallel_mode_is_explicit_and_requires_a_working_reviewed_chat_profile() -> None:
    assert not Settings(_env_file=None).mana_family_parallel_worker_enabled
    with pytest.raises(ValidationError, match="Parallel family processing requires"):
        Settings(_env_file=None, mana_family_parallel_worker_enabled=True)
    assert not replace(options(Path("fictional")), parallel_worker=False).parallel_worker


async def test_independently_cancelled_lane_cannot_silently_leave_a_live_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lab, gate, worker = await setup(tmp_path / "cancelled-lane")

    async def cancelled(prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
        raise asyncio.CancelledError

    monkeypatch.setattr(gate, "respond", cancelled)
    try:
        job = await lab.safety.admit(target(), analysis())
        worker.start()
        assert worker._task
        await asyncio.wait_for(asyncio.shield(worker._task), timeout=3)
        assert not lab.safety.worker_available
        assert (await lab.safety.assessment("123", job.job_id)).status == "unknown"
        assert (await lab.safety.budget("123")).server_reserved_tokens > 0
    finally:
        await lab.close()


async def test_actual_runtime_selects_parallel_mode_without_idle_provider_requests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    requests: list[str] = []
    workers: list[FamilyAgentWorker] = []

    def deny(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.host or "")
        raise AssertionError("Idle SQL observation cannot authorize external I/O")

    class ObservedWorker(FamilyAgentWorker):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            workers.append(self)

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", lambda **kwargs: httpx.MockTransport(deny))
    monkeypatch.setattr(runtime_module, "FamilyAgentWorker", ObservedWorker)
    settings = config(
        tmp_path,
        make_credential_file(tmp_path),
        mana_parent_touch_review_first_enabled=True,
        mana_child_safety_enabled=True,
        mana_family_parallel_worker_enabled=True,
        mana_child_safety_limits=ChildSafetyLimits(
            server_daily_tokens=2000, parent_daily_tokens=2000, job_tokens=2000
        ),
    )
    async with runtime_module.parent_chat_runtime(settings):
        await asyncio.sleep(0.05)
        assert len(workers) == 1 and workers[0]._parallel_enabled
        assert workers[0]._task and not workers[0]._task.done()
        names = {task.get_name() for task in asyncio.all_tasks() if not task.done()}
        assert {"mana-family-safety", "mana-family-conversation", "mana-family-push"} <= names
        assert not requests
    assert workers[0]._task.done() and not requests
