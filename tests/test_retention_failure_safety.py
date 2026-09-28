import asyncio
import logging
from collections import Counter
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.mana_operation_ai.application.concurrency import gather_or_cancel
from app.mana_operation_ai.application.ports import ProviderPermanentError
from app.mana_operation_ai.application.read_budget import (
    FirestoreReadBudget,
    FirestoreReadBudgetExceeded,
    FirestoreReadLimits,
)
from app.mana_operation_ai.application.runtime import SystemClock
from app.mana_operation_ai.infrastructure.retention.firestore import FirestoreMobileActivityAdapter
from app.mana_operation_ai.infrastructure.retention.firestore_operational import (
    FirestoreOperationalTelemetryAdapter,
)
from app.mana_operation_ai.infrastructure.retention.manakids import ManakidsAdminActivityAdapter


def adapter(client: httpx.AsyncClient) -> ManakidsAdminActivityAdapter:
    return ManakidsAdminActivityAdapter(
        client=client,
        base_url="https://manakids.test",
        username="test-user",
        password="test-password",
        clock=SystemClock(),
        max_retries=3,
        retry_backoff_seconds=0.001,
        max_pages=2,
    )


@pytest.mark.parametrize("status", [401, 403])
@pytest.mark.parametrize("same_token", [False, True])
async def test_rejected_token_refresh_is_single_flight(status: int, same_token: bool) -> None:
    logins = 0
    reads = 0
    initial_wave = asyncio.Event()
    by_endpoint: Counter[str] = Counter()

    async def handle(request: httpx.Request) -> httpx.Response:
        nonlocal logins, reads
        if request.method == "POST":
            logins += 1
            return httpx.Response(200, json={"access": "same" if same_token else str(logins)})
        reads += 1
        key = str(request.url)
        by_endpoint[key] += 1
        if by_endpoint[key] == 1:
            if reads == 5:
                initial_wave.set()
            await initial_wave.wait()
            return httpx.Response(status)
        return httpx.Response(200, json={"count": 0, "results": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        now = datetime(2026, 9, 28, tzinfo=UTC)
        facts = await asyncio.wait_for(
            adapter(client).collect_activity(
                period_start=now - timedelta(days=1),
                period_end=now,
            ),
            timeout=2,
        )
    assert facts.total_children == 0
    assert logins == 2
    assert reads == 10


@pytest.mark.parametrize("status", [401, 403])
async def test_second_auth_rejection_is_permanent_without_network_retry(status: int) -> None:
    counts: Counter[str] = Counter()

    def handle(request: httpx.Request) -> httpx.Response:
        counts[request.method] += 1
        if request.method == "POST":
            return httpx.Response(200, json={"access": "same-test-token"})
        return httpx.Response(status)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(ProviderPermanentError, match=f"HTTP {status}"):
            await adapter(client)._authorized_json("/api/v1/account/", params={})
    assert counts == {"POST": 2, "GET": 2}


async def test_rejected_login_does_not_start_collection_or_retry() -> None:
    requests: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request.method)
        return httpx.Response(403)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        now = datetime(2026, 9, 28, tzinfo=UTC)
        with pytest.raises(ProviderPermanentError, match="authentication.*403"):
            await adapter(client).collect_activity(
                period_start=now - timedelta(days=1),
                period_end=now,
            )
    assert requests == ["POST"]


async def test_failed_refresh_is_not_repeated_by_concurrent_rejections() -> None:
    logins = 0
    reads = 0
    all_readers = asyncio.Event()

    async def handle(request: httpx.Request) -> httpx.Response:
        nonlocal logins, reads
        if request.method == "POST":
            logins += 1
            if logins == 1:
                return httpx.Response(200, json={"access": "expired"})
            return httpx.Response(403)
        reads += 1
        if reads == 5:
            all_readers.set()
        await all_readers.wait()
        return httpx.Response(403)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        now = datetime(2026, 9, 28, tzinfo=UTC)
        with pytest.raises(ProviderPermanentError, match="authentication.*403"):
            await asyncio.wait_for(
                adapter(client).collect_activity(
                    period_start=now - timedelta(days=1),
                    period_end=now,
                ),
                timeout=2,
            )
    assert logins == 2
    assert reads == 5


async def test_provider_metrics_count_auth_retry_without_secrets(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)

    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"access": "sensitive-test-token"})
        return httpx.Response(403, json={"private_child": "sensitive-test-child"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(ProviderPermanentError):
            await adapter(client)._authorized_json("/api/v1/account/", params={})
    records = [r for r in caplog.records if r.message == "Retention provider request"]
    assert len(records) == 4
    assert sum(r.__dict__["request_count"] for r in records) == 4
    assert sum(r.__dict__["retry_count"] for r in records) == 1
    assert all(r.__dict__["duration_ms"] >= 0 for r in records)
    exported = str([r.__dict__ for r in records])
    assert "test-password" not in exported
    assert "sensitive-test-token" not in exported
    assert "sensitive-test-child" not in exported


@pytest.mark.parametrize("external_cancel", [False, True])
async def test_failure_cancels_and_drains_nested_firestore_batches(external_cancel: bool) -> None:
    all_started = asyncio.Event()
    started = 0
    drained: list[int] = []

    async def firestore_page(index: int) -> None:
        nonlocal started
        started += 1
        if started == 5:
            all_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0)
            drained.append(index)

    async def mandatory_backend() -> None:
        await all_started.wait()
        if external_cancel:
            await asyncio.Event().wait()
        raise ProviderPermanentError("Manakids rejected the read")

    task = asyncio.create_task(
        gather_or_cancel(
            mandatory_backend(),
            gather_or_cancel(*(firestore_page(index) for index in range(5))),
        )
    )
    await all_started.wait()
    if external_cancel:
        task.cancel()
    with pytest.raises(asyncio.CancelledError if external_cancel else ProviderPermanentError):
        await task
    assert sorted(drained) == list(range(5))


def firestore(
    client: httpx.AsyncClient, *, per_collection: int = 1
) -> FirestoreOperationalTelemetryAdapter:
    return FirestoreOperationalTelemetryAdapter(
        client=client,
        project_id="test-project",
        database_id="(default)",
        token_provider=None,
        clock=SystemClock(),
        max_documents_per_collection=per_collection,
        max_retries=3,
        retry_backoff_seconds=0.001,
    )


@pytest.mark.parametrize("limit_kind", ["documents", "requests"])
async def test_firestore_global_budget_is_enforced_before_dispatch(limit_kind: str) -> None:
    sent = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal sent
        sent += 1
        return httpx.Response(200, json={"documents": [{"fields": {}}]})

    limits = FirestoreReadLimits(
        documents=2 if limit_kind == "documents" else 10,
        pages=10,
        requests=2 if limit_kind == "requests" else 10,
    )
    budget = FirestoreReadBudget(limits)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(FirestoreReadBudgetExceeded):
            await firestore(client).collect_telemetry(read_budget=budget)
    assert sent == budget.requests == budget.observed_documents == 2
    assert budget.reserved_document_reads == 2


async def test_firestore_transient_retries_consume_document_budget() -> None:
    sent = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal sent
        sent += 1
        return httpx.Response(503)

    budget = FirestoreReadBudget(FirestoreReadLimits(documents=2, pages=10, requests=10))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(FirestoreReadBudgetExceeded, match="document_reads"):
            await firestore(client)._list_collection("battery", read_budget=budget)
    assert sent == budget.requests == budget.reserved_document_reads == 2
    assert budget.retries == 1
    assert budget.observed_documents == 0


@pytest.mark.parametrize("repeated_token", [False, True])
async def test_firestore_empty_pages_cannot_loop_forever(repeated_token: bool) -> None:
    sent = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal sent
        sent += 1
        return httpx.Response(
            200,
            json={
                "documents": [],
                "nextPageToken": "repeat" if repeated_token else str(sent),
            },
        )

    budget = FirestoreReadBudget(FirestoreReadLimits(documents=10, pages=2, requests=10))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(ProviderPermanentError, match="pagination token|pages"):
            await firestore(client)._list_collection("battery", read_budget=budget)
    assert sent == budget.pages == budget.requests == 2


async def test_mobile_and_operational_sources_share_one_firestore_budget() -> None:
    sent = 0

    class Token:
        async def access_token(self) -> str:
            return "test-token"

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal sent
        sent += 1
        return httpx.Response(200, json=[] if request.method == "POST" else {"documents": []})

    budget = FirestoreReadBudget(FirestoreReadLimits(documents=5, pages=10, requests=10))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        mobile = FirestoreMobileActivityAdapter(
            client=client,
            project_id="test-project",
            database_id="(default)",
            collection_id="events",
            token_provider=Token(),
            clock=SystemClock(),
            max_documents=1,
            max_retries=3,
            retry_backoff_seconds=0.001,
        )
        now = datetime(2026, 9, 28, tzinfo=UTC)
        await mobile.collect_activity(
            period_start=now - timedelta(days=1),
            period_end=now,
            read_budget=budget,
        )
        with pytest.raises(FirestoreReadBudgetExceeded, match="document_reads"):
            await firestore(client).collect_telemetry(read_budget=budget)
    assert sent == budget.requests == budget.reserved_document_reads == 5


async def test_firestore_failure_drains_in_flight_http_requests() -> None:
    all_started = asyncio.Event()
    started = 0
    finished = 0

    async def handle(request: httpx.Request) -> httpx.Response:
        nonlocal started, finished
        started += 1
        if started == 5:
            all_started.set()
        try:
            await all_started.wait()
            if request.url.path.endswith("/battery"):
                return httpx.Response(403)
            await asyncio.Event().wait()
            raise AssertionError("The sibling should have been cancelled")
        finally:
            await asyncio.sleep(0)
            finished += 1

    budget = FirestoreReadBudget(FirestoreReadLimits(documents=5, pages=5, requests=5))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(ProviderPermanentError, match="403"):
            await asyncio.wait_for(
                firestore(client).collect_telemetry(read_budget=budget), timeout=2
            )
    assert started == finished == budget.requests == 5
    assert budget.reserved_document_reads == 5
    assert budget.observed_documents == 0
