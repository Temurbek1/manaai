"""A family page changes only its actual children; old/unknown admissions never upgrade."""

from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import httpx

from app.mana_ai.domain.family_day_usage import DAY_USAGE_SOURCE
from app.mana_ai.domain.family_sources import FamilySourceLimits
from app.mana_ai.domain.source_reviews import SourceAnalysisOwner, SourceReviewPolicy
from app.mana_ai.domain.source_safety import SourceSafetyPolicy
from app.services.day_review_cache import SqliteDayReviewCache
from app.services.day_usage_cache import SqliteDayUsageCache
from tests.test_day_usage_cache import service, target
from tests.test_family_day_usage import DAY, NOW, Provider


def cache(path: Path, *, enabled: bool = True) -> SqliteDayReviewCache:
    return SqliteDayReviewCache(
        path,
        binding="fictional-cache",
        limits=FamilySourceLimits(),
        policy=SourceSafetyPolicy(),
        review_policy=SourceReviewPolicy(coalesce_seconds=0),
        enabled=True,
        dated_reviews_enabled=enabled,
    )


async def test_sibling_native_read_consumes_only_its_exact_pending_day_context(
    tmp_path: Path,
) -> None:
    store = cache(tmp_path / "source.sqlite3")
    await store.initialize()
    provider = Provider()
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        reads = service(store, client, [NOW])
        first = await reads.read_for_analysis(target())
        assert first.status == "completed"
        with store._connection() as db:
            assert (
                db.execute("SELECT COUNT(*) FROM review_events WHERE phase='queued'").fetchone()[0]
                == 2
            )
        owner = SourceAnalysisOwner(parent_id="4", job_id=uuid4())
        await reads.read_for_analysis(target(), owner)
        assert len(provider.requests) == 4
        work = await store.claim_next_review(NOW)
        assert work and work.bundle.child_id == 12
        assert work.bundle.snapshots[0].source == DAY_USAGE_SOURCE
        assert work.bundle.snapshots[0].requested_day == DAY
        with store._connection() as db:
            assert db.execute(
                "SELECT owner_job_id FROM review_events WHERE child_id=11 AND phase='native'"
            ).fetchone()[0] == str(owner.job_id)


async def test_changed_sibling_does_not_reanalyse_unchanged_child_in_same_page(
    tmp_path: Path,
) -> None:
    store = cache(tmp_path / "source.sqlite3")
    await store.initialize()
    provider = Provider()
    clock = [NOW]
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        reads = service(store, client, clock)
        await reads.read_for_analysis(target())
        provider.payload["results"][1]["app_usage_statistics"]["results"][0]["daily_usage"][0][
            "total_time"
        ] = "02:00:00"
        clock[0] += timedelta(hours=6)
        await reads.read_for_analysis(target())
    with store._connection() as db:
        rows = db.execute("SELECT child_id,phase FROM review_events ORDER BY rowid").fetchall()
        assert [tuple(r) for r in rows] == [(11, "queued"), (12, "superseded"), (12, "queued")]
        assert db.execute("SELECT COUNT(*) FROM day_usage_snapshots").fetchone()[0] == 2


async def test_v5_inflight_day_read_cannot_acquire_new_review_capture_on_upgrade(
    tmp_path: Path,
) -> None:
    path = tmp_path / "source.sqlite3"
    legacy = SqliteDayUsageCache(
        path,
        binding="fictional-cache",
        limits=FamilySourceLimits(),
        policy=SourceSafetyPolicy(),
        review_policy=SourceReviewPolicy(coalesce_seconds=0),
        enabled=True,
    )
    await legacy.initialize()
    original = target()
    await legacy.claim_day(original, NOW)
    current = cache(path)
    await current.initialize()
    provider = Provider()
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        reads = service(current, client, [NOW])
        lookup = await reads._identities.read_usage_lookup("4")
        page = await reads._source.read_verified(lookup, DAY)
        result = await current.complete_day(original, page, NOW)
        assert result.status == "completed"
    assert await current.claim_next_review(NOW) is None
    with current._connection() as db:
        assert not db.execute("SELECT 1 FROM day_review_captures").fetchone()


async def test_disabled_reader_keeps_original_review_but_cannot_dispatch_it(tmp_path: Path) -> None:
    path = tmp_path / "source.sqlite3"
    store = cache(path)
    await store.initialize()
    async with httpx.AsyncClient(transport=httpx.MockTransport(Provider())) as client:
        await service(store, client, [NOW]).read_for_analysis(target())
    work = await store.claim_next_review(NOW)
    assert work and work.phase == "preparing"
    stopped = cache(path, enabled=False)
    await stopped.initialize()
    assert await stopped.claim_next_review(NOW) is None
    saved = await stopped.reviews("4")
    assert saved[0].phase == "skipped" and saved[0].bundle == work.bundle
    assert saved[0].reason == "dated_reviews_disabled"


def test_query_day_is_part_of_fingerprint_even_for_an_empty_counter_page() -> None:
    from app.mana_ai.domain.family_day_usage import day_child_fingerprint
    from app.mana_ai.domain.family_sources import ChildAppUsageFacts

    facts = ChildAppUsageFacts(
        child_id=11,
        status="missing",
        entries=(),
        returned_apps=0,
        total_apps=0,
        complete=True,
        collected_at=NOW,
    )
    assert day_child_fingerprint(facts, DAY) != day_child_fingerprint(
        facts, DAY - timedelta(days=1)
    )
