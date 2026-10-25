"""Real SQL/cache/application/HTTP boundaries with fictional family responses only."""

import asyncio
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from pytest import MonkeyPatch

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.application.day_usage_service import FamilyDayUsageService
from app.mana_ai.domain.family_day_usage import DayUsageReceipt, DayUsageTarget, FamilyDayUsagePage
from app.mana_ai.domain.family_sources import FamilySourceLimits, FamilySourceTarget
from app.mana_ai.domain.source_reviews import SourceAnalysisOwner, SourceReviewPolicy
from app.mana_ai.domain.source_safety import SourceSafetyPolicy
from app.services.day_usage_cache import SqliteDayUsageCache
from app.services.manakids_family_day_usage import ManakidsFamilyDayUsageSource
from app.services.parent_chat_children import ManakidsChatChildrenSource
from app.services.source_review_cache import SqliteSourceReviewCache
from tests.test_family_day_usage import DAY, NOW, Provider


def cache(path: Path, requests: int = 100) -> SqliteDayUsageCache:
    return SqliteDayUsageCache(
        path,
        binding="fictional-cache",
        limits=FamilySourceLimits(requests_per_24h=requests),
        policy=SourceSafetyPolicy(),
        review_policy=SourceReviewPolicy(),
    )


def target(child: int = 11) -> DayUsageTarget:
    return DayUsageTarget(parent_id="4", child_id=child, request_id=uuid4(), requested_day=DAY)


def service(
    store: SqliteDayUsageCache, client: httpx.AsyncClient, clock: list[datetime]
) -> FamilyDayUsageService:
    identities = ManakidsChatChildrenSource(
        client=client,
        base_url="https://api.manakids.uz",
        username="fake",
        password="fake",
        clock=lambda: clock[0],
    )
    source = ManakidsFamilyDayUsageSource(
        client, identities, identities, base_url="https://api.manakids.uz", clock=lambda: clock[0]
    )
    return FamilyDayUsageService(store, identities, source, clock=lambda: clock[0])


async def test_siblings_share_one_page_but_each_freshly_verifies_ownership(tmp_path: Path) -> None:
    store, provider, clock = cache(tmp_path / "source.sqlite3"), Provider(), [NOW]
    await store.initialize()
    first, second = target(), target(12)
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        reads = service(store, client, clock)
        a = await reads.read_for_analysis(first)
        b = await reads.read_for_analysis(second)
        assert a.status == b.status == "completed"
        assert not a.cache_hit and b.cache_hit
        assert a.family_snapshot_id == b.family_snapshot_id and a.snapshot_id != b.snapshot_id
        assert len(provider.requests) == 4  # login/profile/page, then only fresh profile
        assert sum(r.url.path.endswith("/app-usage-statistics/") for r in provider.requests) == 1
        clock[0] += timedelta(days=40)
        assert await reads.read_for_analysis(first) == a
        assert await reads.read_for_analysis(second) == b
        assert len(provider.requests) == 4
    with store._connection() as db:
        assert db.execute("SELECT COUNT(*),SUM(units) FROM source_reads").fetchone()[:] == (2, 0)
        assert not db.execute("SELECT 1 FROM review_events").fetchone()
        assert db.execute("SELECT COUNT(*) FROM day_usage_snapshots").fetchone()[0] == 1


@pytest.mark.parametrize("offset", [0, -1, 32])
async def test_invalid_query_day_is_refused_without_admission_or_io(
    tmp_path: Path, offset: int
) -> None:
    store = cache(tmp_path / "source.sqlite3")
    await store.initialize()
    with pytest.raises(ParentChatError, match="family_day_usage_day_outside_window"):
        await store.claim_day(
            target().model_copy(update={"requested_day": NOW.date() - timedelta(days=offset)}), NOW
        )
    with store._connection() as db:
        assert not db.execute("SELECT 1 FROM source_reads").fetchone()


async def test_absent_child_is_unavailable_not_a_zero_counter(tmp_path: Path) -> None:
    store, provider = cache(tmp_path / "source.sqlite3"), Provider()
    await store.initialize()
    provider.payload["results"] = provider.payload["results"][:1]
    provider.payload["total_count"] = 1
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        reads = service(store, client, [NOW])
        first = await reads.read_for_analysis(target(12))
        second = await reads.read_for_analysis(target(12))
    assert first.status == second.status == "unavailable"
    assert first.facts is second.facts is None
    assert first.child_returned is second.child_returned is False
    assert first.family_snapshot_id == second.family_snapshot_id and second.cache_hit
    assert len(provider.requests) == 4


async def test_equal_recollection_retains_original_facts_and_snapshot_time(tmp_path: Path) -> None:
    store, provider, clock = cache(tmp_path / "source.sqlite3"), Provider(), [NOW]
    await store.initialize()
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        reads = service(store, client, clock)
        a = await reads.read_for_analysis(target())
        clock[0] += timedelta(hours=6)
        b = await reads.read_for_analysis(target())
    assert a.family_snapshot_id == b.family_snapshot_id and a.facts == b.facts
    assert b.facts and b.facts.collected_at == NOW and not b.cache_hit
    with store._connection() as db:
        assert (
            db.execute("SELECT checked_at FROM day_usage_heads").fetchone()[0]
            == clock[0].isoformat()
        )
        assert db.execute("SELECT COUNT(*) FROM day_usage_snapshots").fetchone()[0] == 1


@pytest.mark.parametrize("phase", ["ownership", "usage"])
async def test_lost_external_receipt_blocks_siblings_and_days_across_restart(
    tmp_path: Path, phase: str
) -> None:
    path = tmp_path / "source.sqlite3"
    store, provider = cache(path), Provider()
    await store.initialize()

    def response(request: httpx.Request) -> httpx.Response:
        if (
            phase == "ownership"
            and request.url.path.endswith("/parent-list/")
            or phase == "usage"
            and request.url.path.endswith("/app-usage-statistics/")
        ):
            provider.requests.append(request)
            raise httpx.ReadTimeout("fictional lost response")
        return provider(request)

    original = target()
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        result = await service(store, client, [NOW]).read_for_analysis(original)
        assert result.status == "unknown"
        count = len(provider.requests)
        restored = cache(path)
        await restored.initialize()
        later = service(restored, client, [NOW + timedelta(days=2)])
        assert await later.read_for_analysis(original) == result
        with pytest.raises(ParentChatError, match="family_source_read_unresolved"):
            await later.read_for_analysis(
                target(12).model_copy(update={"requested_day": DAY + timedelta(days=1)})
            )
        assert len(provider.requests) == count


async def test_pending_parent_claim_fences_concurrent_sibling_reads(tmp_path: Path) -> None:
    store = cache(tmp_path / "source.sqlite3")
    await store.initialize()
    results = await asyncio.gather(
        store.claim_day(target(), NOW), store.claim_day(target(12), NOW), return_exceptions=True
    )
    assert sum(isinstance(r, ParentChatError) for r in results) == 1
    with store._connection() as db:
        assert db.execute("SELECT COUNT(*) FROM source_reads").fetchone()[0] == 1


async def test_new_day_does_not_bypass_parent_provider_cooldown(tmp_path: Path) -> None:
    store, provider = cache(tmp_path / "source.sqlite3"), Provider()
    await store.initialize()
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        await service(store, client, [NOW]).read_for_analysis(target())
        with pytest.raises(ParentChatError, match="family_source_read_cooldown"):
            await service(store, client, [NOW]).read_for_analysis(
                target(12).model_copy(update={"requested_day": DAY - timedelta(days=1)})
            )
    assert len(provider.requests) == 3


async def test_cache_hit_still_refuses_disconnected_child_without_usage_read(
    tmp_path: Path,
) -> None:
    store, provider = cache(tmp_path / "source.sqlite3"), Provider()
    await store.initialize()
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        reads = service(store, client, [NOW])
        first = await reads.read_for_analysis(target())
        provider.parent["results"][0]["children"][0]["is_connected"] = False
        refused = await reads.read_for_analysis(target())
    assert first.status == "completed" and refused.status == "failed"
    assert refused.error_code == "family_source_ownership_denied" and refused.facts is None
    assert len(provider.requests) == 4


async def test_lost_local_completion_ack_observes_committed_result_without_retry(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    store, provider = cache(tmp_path / "source.sqlite3"), Provider()
    await store.initialize()
    complete = store.complete_day

    async def lost(
        target: DayUsageTarget, page: FamilyDayUsagePage | None, now: datetime
    ) -> DayUsageReceipt:
        await complete(target, page, now)
        raise RuntimeError("fictional lost local acknowledgement")

    monkeypatch.setattr(store, "complete_day", lost)
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        result = await service(store, client, [NOW]).read_for_analysis(target())
    assert result.status == "completed" and len(provider.requests) == 3


async def test_shared_budget_and_cross_source_uuid_conflicts_are_controlled(tmp_path: Path) -> None:
    store, provider = cache(tmp_path / "source.sqlite3", requests=1), Provider()
    await store.initialize()
    original = target()
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        await service(store, client, [NOW]).read_for_analysis(original)
    with pytest.raises(ParentChatError, match="family_source_request_limit"):
        await store.claim(FamilySourceTarget(parent_id="4", child_id=12, request_id=uuid4()), NOW)
    with pytest.raises(ParentChatError, match="family_source_request_conflict"):
        await store.claim(
            FamilySourceTarget(parent_id="4", child_id=11, request_id=original.request_id), NOW
        )
    with pytest.raises(ParentChatError, match="family_source_request_conflict"):
        await store.claim_day(
            original.model_copy(update={"requested_day": DAY - timedelta(days=1)}), NOW
        )


async def test_native_owner_cannot_be_replaced_on_known_replay(tmp_path: Path) -> None:
    store = cache(tmp_path / "source.sqlite3")
    await store.initialize()
    original = target()
    owner = SourceAnalysisOwner(parent_id="4", job_id=uuid4())
    claim = await store.claim_day(original, NOW, owner)
    assert (await store.claim_day(original, NOW, owner)).receipt == claim.receipt
    with pytest.raises(ParentChatError, match="source_review_owner_mismatch"):
        await store.claim_day(original, NOW)


async def test_old_reader_refuses_v5_without_changing_existing_rows(tmp_path: Path) -> None:
    path = tmp_path / "source.sqlite3"
    store = cache(path)
    await store.initialize()
    await store.claim_day(target(), NOW)
    with sqlite3.connect(path) as db:
        original = list(db.iterdump())
    old = SqliteSourceReviewCache(
        path,
        binding="fictional-cache",
        limits=FamilySourceLimits(),
        policy=SourceSafetyPolicy(),
        review_policy=SourceReviewPolicy(),
    )
    with pytest.raises(ValueError):
        await old.initialize()
    with sqlite3.connect(path) as db:
        assert list(db.iterdump()) == original


async def test_cancelled_ownership_call_retains_parent_hold(tmp_path: Path) -> None:
    store, provider = cache(tmp_path / "source.sqlite3"), Provider()
    await store.initialize()
    entered, release = asyncio.Event(), asyncio.Event()

    async def response(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/parent-list/"):
            entered.set()
            await release.wait()
        return provider(request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        reads = service(store, client, [NOW])
        request = target()
        task = asyncio.create_task(reads.read_for_analysis(request))
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert (await store.observe_day(request)).status == "unknown"
        with pytest.raises(ParentChatError, match="family_source_read_unresolved"):
            await reads.read_for_analysis(target(12))


async def test_auth_denial_closes_only_day_source_and_preserves_old_receipt(tmp_path: Path) -> None:
    store, provider = cache(tmp_path / "source.sqlite3"), Provider()
    await store.initialize()
    provider.usage_status = 403
    original = target()
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        reads = service(store, client, [NOW])
        result = await reads.read_for_analysis(original)
        assert result.status == "failed" and result.error_code == "family_source_auth_denied"
        assert await reads.read_for_analysis(original) == result
        with pytest.raises(ParentChatError, match="family_source_circuit_open"):
            await reads.read_for_analysis(target(12))
    other = await store.claim(
        FamilySourceTarget(parent_id="4", child_id=11, request_id=uuid4()), NOW
    )
    assert other.admitted and other.read_provider
    assert len(provider.requests) == 3
