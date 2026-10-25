"""One public chat path into model-selected tariff needs and a metered shared fake catalog."""

from pathlib import Path
from uuid import uuid4

import pytest
from pytest import MonkeyPatch

from app.mana_ai.domain.chat import ParentChildContext
from app.mana_ai.domain.conversion_catalog import ConversionCatalogObservation
from app.mana_ai.domain.family_agents import ParentTouchMessageRequest
from app.services.mana_chat_lab import LAB_PARENT, ChatLab, LabOptions
from tests.test_mana_chat_lab import Clock


async def setup(path: Path) -> tuple[ChatLab, Clock]:
    clock = Clock()
    clock.value = Clock.value
    lab = ChatLab(
        LabOptions(
            path,
            clock=clock,
            worker_enabled=False,
            native_sources=True,
            native_observations=True,
            source_reviews=True,
            reminders=True,
            retention=True,
            upsell=True,
        )
    )
    await lab.start()
    return lab, clock


async def ask(lab: ChatLab, text: str = "Подбери тариф на 3 месяца") -> ParentTouchMessageRequest:
    request = ParentTouchMessageRequest(parent_id=LAB_PARENT, request_id=uuid4(), message=text)
    await lab.touch.admit_message(request)
    review = await lab.safety.process_one()
    assert review and review.status == "completed"
    assert await lab.touch.process_reviewed_message()
    result = await lab.touch.message_state(LAB_PARENT, request.request_id)
    assert result.phase == "completed", result
    return request


async def test_explicit_price_request_finishes_in_the_same_chat_without_payment(
    tmp_path: Path,
) -> None:
    lab, _ = await setup(tmp_path / "chat")
    try:
        request = await ask(lab)
        assert (await lab.state()).history.messages[
            -1
        ].content == "Проверю актуальные варианты в каталоге."
        assert await lab.touch.process_upsell()
        state = await lab.state()
        assert len(state.history.messages) == 3
        assert "90 дней — 162 000.00 UZS" in state.history.messages[-1].content
        assert state.history.quota.used_tokens == 150
        assert lab.catalog.calls == 1
        assert not await lab.touch.process_upsell()
        assert (await lab.touch.admit_message(request)).phase == "completed"
        assert len((await lab.state()).history.messages) == 3
        with lab.store._connect() as db:
            assert db.execute("SELECT status FROM upsell_intents").fetchone()[0] == "published"
            assert (
                db.execute(
                    "SELECT SUM(reserved_http_attempts) FROM upsell_catalog_reads"
                ).fetchone()[0]
                == 2
            )
            assert not db.execute("SELECT 1 FROM parent_push_outbox").fetchone()
            assert not db.execute("SELECT 1 FROM conversion_trial_grants").fetchone()
    finally:
        await lab.close()


async def test_another_enquiry_reuses_catalog_without_another_source_read(
    tmp_path: Path,
) -> None:
    lab, _ = await setup(tmp_path / "cache")
    try:
        await ask(lab)
        assert await lab.touch.process_upsell()
        await ask(lab, "3 oylik tarif tanlang")
        assert await lab.touch.process_upsell()
        assert lab.catalog.calls == 1
        state = await lab.state()
        assert "90 kun — 162 000.00 UZS" in state.history.messages[-1].content
        assert len(state.history.messages) == 6
    finally:
        await lab.close()


async def test_unknown_catalog_is_not_retried_by_next_request_or_restart(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    from datetime import timedelta

    lab, clock = await setup(tmp_path / "lost")
    calls = 0

    async def lost() -> object:
        nonlocal calls
        calls += 1
        raise TimeoutError("fictional lost catalog receipt")

    monkeypatch.setattr(lab.catalog, "read", lost)
    try:
        await ask(lab)
        assert await lab.touch.process_upsell()
        assert "не удалось подтвердить" in (await lab.state()).history.messages[-1].content
        await ask(lab)
        assert await lab.touch.process_upsell()
        assert calls == 1
        await lab.close()
        lab = ChatLab(lab.options)
        await lab.start()
        clock.value += timedelta(days=1)
        assert lab.touch.upsell
        admitted = await lab.touch.upsell._store.catalog_admission(clock.now())
        assert admitted.refusal == "blocked" and admitted.claim is None
    finally:
        await lab.close()


async def test_lost_catalog_commit_ack_uses_original_sql_receipt_without_reread(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    from datetime import datetime

    from app.mana_ai.domain.client_upsell import CatalogReadClaim
    from app.mana_ai.domain.conversion_catalog import ConversionCatalogObservation

    lab, _ = await setup(tmp_path / "ack")
    assert lab.touch.upsell
    store = lab.touch.upsell._store
    original = store.finish_catalog

    async def lose(
        claim: CatalogReadClaim, now: datetime, *, snapshot: ConversionCatalogObservation | None
    ) -> None:
        await original(claim, now, snapshot=snapshot)
        if snapshot is not None:
            raise OSError("fictional committed ack loss")

    monkeypatch.setattr(store, "finish_catalog", lose)
    try:
        await ask(lab)
        assert await lab.touch.process_upsell()
        assert lab.catalog.calls == 1
        assert "162 000.00 UZS" in (await lab.state()).history.messages[-1].content
        assert not await lab.touch.process_upsell()
    finally:
        await lab.close()


async def test_new_parent_message_during_profile_lookup_cancels_old_quote_without_catalog_call(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    from app.mana_ai.domain.chat import ParentChildContext

    lab, _ = await setup(tmp_path / "cancel")
    assert lab.touch.upsell
    children = lab.touch.upsell._children
    original = children.read

    async def cancelled(parent_id: str) -> ParentChildContext:
        context = await original(parent_id)
        await lab.touch.admit_message(
            ParentTouchMessageRequest(
                parent_id=LAB_PARENT, request_id=uuid4(), message="Нет, уже не нужно."
            )
        )
        return context

    try:
        await ask(lab)
        monkeypatch.setattr(children, "read", cancelled)
        assert await lab.touch.process_upsell()
        assert lab.catalog.calls == 0
        with lab.store._connect() as db:
            assert db.execute("SELECT status FROM upsell_intents").fetchone()[0] == "cancelled"
    finally:
        await lab.close()


def test_tariff_selection_uses_exact_currency_budget_and_duration() -> None:
    from datetime import UTC, datetime

    from app.mana_ai.application.client_upsell import select_tariffs
    from app.mana_ai.domain.client_upsell import UpsellChoice
    from app.mana_ai.domain.conversion_catalog import (
        ConversionCatalogObservation,
        ConversionTariffPrice,
    )

    now = datetime(2026, 10, 25, tzinfo=UTC)
    catalog = ConversionCatalogObservation(
        collected_at=now,
        tariffs=tuple(
            ConversionTariffPrice(
                tariff_id=identity, currency=currency, price_minor=price, duration_days=days
            )
            for identity, currency, price, days in [
                ("1", "UZS", 6000000, 30),
                ("2", "UZS", 16200000, 90),
                ("3", "USD", 1000, 90),
                ("4", "UZS", 59900000, 365),
            ]
        ),
    )
    choice = UpsellChoice(
        parent_quote="на 3 месяца",
        objective="lowest_total",
        currency="UZS",
        minimum_days=90,
        maximum_days=90,
        maximum_price_minor=17000000,
    )
    assert select_tariffs(choice, catalog, now=now).options[0].tariff_id == "2"
    assert not select_tariffs(
        choice.model_copy(update={"maximum_price_minor": 16000000}), catalog, now=now
    ).options
    year = choice.model_copy(
        update={
            "minimum_days": 1,
            "maximum_days": 366,
            "maximum_price_minor": None,
            "objective": "lowest_daily",
        }
    )
    assert select_tariffs(year, catalog, now=now).options[0].tariff_id == "4"


async def test_catalog_claim_is_shared_and_expired_unknown_blocks_after_restart(
    tmp_path: Path,
) -> None:
    import asyncio
    from datetime import timedelta

    lab, clock = await setup(tmp_path / "concurrent")
    try:
        assert lab.touch.upsell
        store = lab.touch.upsell._store
        claims = await asyncio.gather(*(store.catalog_admission(clock.now()) for _ in range(8)))
        assert sum(item.claim is not None for item in claims) == 1
        assert sum(item.refusal == "busy" for item in claims) == 7
        clock.value += timedelta(seconds=181)
        await lab.close()
        lab = ChatLab(lab.options)
        await lab.start()
        assert lab.touch.upsell
        assert (await lab.touch.upsell._store.catalog_admission(clock.now())).refusal == "blocked"
        assert lab.catalog.calls == 0
    finally:
        await lab.close()


async def test_changed_parent_during_catalog_io_fences_quote_but_retains_shared_receipt(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    lab, _ = await setup(tmp_path / "source-race")
    source = lab.catalog.read

    async def changed() -> ConversionCatalogObservation:
        snapshot = await source()
        await lab.touch.admit_message(
            ParentTouchMessageRequest(
                parent_id=LAB_PARENT, request_id=uuid4(), message="Больше не надо."
            )
        )
        return snapshot

    try:
        await ask(lab)
        monkeypatch.setattr(lab.catalog, "read", changed)
        assert await lab.touch.process_upsell()
        assert lab.catalog.calls == 1
        assert (await lab.state()).history.messages[-1].role == "user"
        with lab.store._connect() as db:
            assert db.execute("SELECT status FROM upsell_intents").fetchone()[0] == "cancelled"
            assert db.execute("SELECT status FROM upsell_catalog_reads").fetchone()[0] == "recorded"
        assert not await lab.touch.process_upsell()
    finally:
        await lab.close()


@pytest.mark.parametrize("mismatch", ["parent", "date"])
async def test_ownership_or_stale_profile_prevents_catalog_read(
    tmp_path: Path, monkeypatch: MonkeyPatch, mismatch: str
) -> None:
    from datetime import timedelta

    lab, clock = await setup(tmp_path / mismatch)
    assert lab.touch.upsell
    children = lab.touch.upsell._children
    original = children.read

    async def denied(parent: str) -> ParentChildContext:
        profile = await original(parent)
        return profile.model_copy(
            update={"parent_id": "123"}
            if mismatch == "parent"
            else {"collected_at": clock.now() - timedelta(minutes=4)}
        )

    try:
        await ask(lab)
        monkeypatch.setattr(children, "read", denied)
        assert await lab.touch.process_upsell()
        assert lab.catalog.calls == 0
        with lab.store._connect() as db:
            assert db.execute("SELECT status FROM upsell_intents").fetchone()[0] == "unknown"
            assert not db.execute("SELECT 1 FROM upsell_catalog_reads").fetchone()
        assert not await lab.touch.process_upsell()
    finally:
        await lab.close()


async def test_v15_queued_turn_is_not_upgraded_to_an_upsell_tool(tmp_path: Path) -> None:
    import sqlite3
    from dataclasses import replace

    from app.services.client_upsell_store import SqliteClientUpsellStore

    lab, _ = await setup(tmp_path / "old-source")
    old_options = replace(lab.options, upsell=False, directory=tmp_path / "old")
    await lab.close()
    old = ChatLab(old_options)
    await old.start()
    request = ParentTouchMessageRequest(
        parent_id=LAB_PARENT, request_id=uuid4(), message="Подбери тариф на 3 месяца"
    )
    admitted = await old.touch.admit_message(request)
    await old.close()
    target = tmp_path / "upgraded"
    current = ChatLab(replace(old_options, upsell=True, directory=target))
    await current.start()
    await current.close()
    with (
        sqlite3.connect(old_options.directory / "family.sqlite3") as source,
        sqlite3.connect(target / "family.sqlite3") as destination,
    ):
        source.backup(destination)
    try:
        await current.start()
        assert isinstance(current.store, SqliteClientUpsellStore)
        assert await current.store.upsell_scope(LAB_PARENT, admitted.turn_id) is None
        assert (await current.touch.admit_message(request)).turn_id == admitted.turn_id
        review = await current.safety.process_one()
        assert review and review.status == "completed"
        assert await current.touch.process_reviewed_message()
        assert not await current.touch.process_upsell()
        assert current.catalog.calls == 0
    finally:
        await current.close()
