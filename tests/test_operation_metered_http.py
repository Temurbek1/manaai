import asyncio
import json
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path

import httpx
import pytest

from app.mana_operation_ai.application.cost_control import CostBudgetExceeded
from app.mana_operation_ai.application.ports import ProviderPermanentError
from app.mana_operation_ai.domain.cost_control import (
    CostAttribution,
    CostLimits,
    DataRateCard,
    ProductScope,
    ResourceUsage,
)
from app.mana_operation_ai.infrastructure.metered_http import MeteredReadHttp
from app.mana_operation_ai.infrastructure.persistence.cost_ledger import SqlAlchemyCostLedger
from app.mana_operation_ai.infrastructure.persistence.database import OperationDatabase
from app.mana_operation_ai.infrastructure.retention.ga4 import Ga4MobileActivityAdapter
from tests.test_operation_cost_ledger import Clock
from tests.test_retention_sources import StaticTokenProvider


def limits(requests: int = 100) -> CostLimits:
    usage = ResourceUsage(
        provider_requests=requests,
        document_reads=1000,
        response_bytes=1_000_000,
        data_microusd=1_000_000,
    )
    return CostLimits(daily=usage, monthly=usage)


def meter(ledger: SqlAlchemyCostLedger, *, maximum: int = 8192) -> MeteredReadHttp:
    return MeteredReadHttp(
        ledger=ledger,
        attribution=CostAttribution(
            product=ProductScope.MANA,
            source="firestore",
            agent_id="retention-agent",
            capability_key="retention.engagement.analyze",
        ),
        maximum_response_bytes=maximum,
        rates=DataRateCard(document_usd_per_100k="0.06", response_usd_per_gib="0.12"),
    )


class ObservedStream(httpx.AsyncByteStream):
    def __init__(self, chunks: tuple[bytes, ...]) -> None:
        self.chunks = chunks
        self.chunks_read = 0
        self.bytes_read = 0
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self.chunks:
            self.chunks_read += 1
            self.bytes_read += len(chunk)
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


@pytest.fixture
async def accounting(tmp_path: Path) -> AsyncIterator[SqlAlchemyCostLedger]:
    db = OperationDatabase(f"sqlite+aiosqlite:///{tmp_path / 'stream.db'}")
    await db.create_schema()
    ledger = SqlAlchemyCostLedger(db, clock=Clock(), limits=limits())
    try:
        yield ledger
    finally:
        await db.dispose()


@pytest.mark.asyncio
async def test_raw_stream_overflow_closes_before_another_block(
    accounting: SqlAlchemyCostLedger,
) -> None:
    stream = ObservedStream((b"x" * 512, b"x" * 65_536, b"unread"))

    async def handle(request: httpx.Request) -> httpx.Response:
        assert request.headers["accept-encoding"] == "identity"
        assert (await accounting.periods())[0].usage.response_bytes == 512 + 65_536
        return httpx.Response(200, stream=stream)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(ProviderPermanentError, match="byte ceiling"):
            await meter(accounting, maximum=512).request(
                client,
                "GET",
                "https://read.test",
                document_limit=10,
                headers={"accept-encoding": "gzip"},
            )
    assert stream.closed and stream.chunks_read == 2
    usage = (await accounting.periods())[0].usage
    assert usage.response_bytes == stream.bytes_read == 512 + 65_536
    assert usage.document_reads == 10 and usage.provider_requests == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("encoding", ["gzip", "deflate", "br", "zstd"])
async def test_compressed_response_is_refused_before_body_iteration(
    accounting: SqlAlchemyCostLedger, encoding: str
) -> None:
    stream = ObservedStream((b"not-even-valid-compressed-data",))
    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, stream=stream, headers={"content-encoding": encoding})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(ProviderPermanentError, match="Compressed"):
            await meter(accounting, maximum=512).request(
                client, "GET", "https://read.test", document_limit=10
            )
    assert stream.closed and stream.chunks_read == 0 and calls == 1
    usage = (await accounting.periods())[0].usage
    # No receipt proving document usage or EOF: retain the full reservation.
    assert usage.response_bytes == 512 + 65_536 and usage.document_reads == 10


@pytest.mark.asyncio
async def test_known_identity_receipt_refunds_read_ahead_margin(
    accounting: SqlAlchemyCostLedger,
) -> None:
    stream = ObservedStream((b'{"documents":', b'[{"fields":{}}]}'))

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream, headers={"content-encoding": "identity"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        response = await meter(accounting, maximum=512).request(
            client, "GET", "https://read.test", document_limit=10
        )
    usage = (await accounting.periods())[0].usage
    assert stream.closed and response.json() == {"documents": [{"fields": {}}]}
    assert usage.response_bytes == stream.bytes_read == len(response.content)
    assert usage.document_reads == 1 and usage.provider_requests == 1


@pytest.mark.asyncio
async def test_nonconforming_transport_does_not_hide_observed_overrun(
    accounting: SqlAlchemyCostLedger,
) -> None:
    stream = ObservedStream((b"x" * 131_072, b"unread"))

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(ProviderPermanentError, match="byte ceiling"):
            await meter(accounting, maximum=512).request(
                client, "GET", "https://read.test", document_limit=10
            )
    usage = (await accounting.periods())[0].usage
    assert stream.closed and stream.chunks_read == 1
    assert usage.response_bytes == stream.bytes_read == 131_072
    assert usage.document_reads == 10 and usage.provider_requests == 1


@pytest.mark.asyncio
async def test_read_ahead_margin_is_admitted_before_dispatch(tmp_path: Path) -> None:
    db = OperationDatabase(f"sqlite+aiosqlite:///{tmp_path / 'byte-admission.db'}")
    await db.create_schema()
    usage = limits().daily.model_copy(update={"response_bytes": 512 + 65_536 - 1})
    ledger = SqlAlchemyCostLedger(db, clock=Clock(), limits=CostLimits(daily=usage, monthly=usage))

    def handle(request: httpx.Request) -> httpx.Response:
        raise AssertionError("The request exceeded its admitted transfer budget")

    try:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            with pytest.raises(CostBudgetExceeded):
                await meter(ledger, maximum=512).request(client, "GET", "https://read.test")
        assert all(period.usage.provider_requests == 0 for period in await ledger.periods())
    finally:
        await db.dispose()


@pytest.mark.asyncio
async def test_http_receipts_empty_queries_and_retry_attempts(tmp_path: Path) -> None:
    db = OperationDatabase(f"sqlite+aiosqlite:///{tmp_path / 'http.db'}")
    await db.create_schema()
    ledger = SqlAlchemyCostLedger(db, clock=Clock(), limits=limits())
    replies = [
        httpx.Response(200, json=[{"document": {"fields": {}}}, {"readTime": "receipt"}]),
        httpx.Response(200, json=[{"readTime": "receipt"}]),
        httpx.Response(503, json={"error": "temporary"}),
        httpx.Response(200, json={"documents": [{"fields": {}}]}),
    ]
    attempted = 0

    async def handle(request: httpx.Request) -> httpx.Response:
        nonlocal attempted
        assert request.headers["accept-encoding"] == "identity"
        attempted += 1
        assert (await ledger.periods())[0].usage.provider_requests == attempted
        return replies.pop(0)

    try:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            for _ in range(4):
                await meter(ledger).request(client, "POST", "https://read.test", document_limit=10)
        usage = (await ledger.periods())[0].usage
        assert usage.provider_requests == 4
        # Unknown 503 read charge retains ten; empty successful query charges one.
        assert usage.document_reads == 13
        assert 0 < usage.response_bytes < 8192
        assert usage.data_microusd > 0
    finally:
        await db.dispose()


@pytest.mark.asyncio
async def test_timeout_and_oversized_response_keep_full_reservation(tmp_path: Path) -> None:
    db = OperationDatabase(f"sqlite+aiosqlite:///{tmp_path / 'unknown.db'}")
    await db.create_schema()
    ledger = SqlAlchemyCostLedger(db, clock=Clock(), limits=limits(requests=2))
    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ReadTimeout("No receipt", request=request)
        return httpx.Response(200, content=b"x" * 1025)

    try:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            with pytest.raises(httpx.ReadTimeout):
                await meter(ledger, maximum=1024).request(
                    client, "GET", "https://read.test", document_limit=10
                )
            with pytest.raises(ProviderPermanentError, match="byte ceiling"):
                await meter(ledger, maximum=1024).request(
                    client, "GET", "https://read.test", document_limit=10
                )
            with pytest.raises(CostBudgetExceeded):
                await meter(ledger).request(client, "GET", "https://read.test")
        assert calls == 2
        usage = (await ledger.periods())[0].usage
        assert usage.document_reads == 20 and usage.response_bytes == 2 * (1024 + 65_536)
    finally:
        await db.dispose()


@pytest.mark.asyncio
async def test_cancelled_http_attempt_is_still_reserved(tmp_path: Path) -> None:
    db = OperationDatabase(f"sqlite+aiosqlite:///{tmp_path / 'cancel.db'}")
    await db.create_schema()
    ledger = SqlAlchemyCostLedger(db, clock=Clock(), limits=limits())
    started = asyncio.Event()

    async def handle(request: httpx.Request) -> httpx.Response:
        started.set()
        await asyncio.Event().wait()
        raise AssertionError("Cancelled")

    try:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            task = asyncio.create_task(
                meter(ledger).request(client, "GET", "https://read.test", document_limit=10)
            )
            await started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        usage = (await ledger.periods())[0].usage
        assert usage.provider_requests == 1 and usage.document_reads == 10
        assert usage.response_bytes == 8192 + 65_536
    finally:
        await db.dispose()


@pytest.mark.asyncio
async def test_ga4_every_report_is_stream_filtered_and_retries_are_metered(tmp_path: Path) -> None:
    db = OperationDatabase(f"sqlite+aiosqlite:///{tmp_path / 'ga4.db'}")
    await db.create_schema()
    clock = Clock()
    ledger = SqlAlchemyCostLedger(db, clock=clock, limits=limits())
    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        body = json.loads(request.content)
        assert body["dimensionFilter"] == {
            "filter": {
                "fieldName": "streamId",
                "inListFilter": {"values": ["123", "456"], "caseSensitive": True},
            }
        }
        if calls == 1:
            return httpx.Response(429, json={"error": "throttle"})
        return httpx.Response(200, json={"rows": []})

    try:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            adapter = Ga4MobileActivityAdapter(
                client=client,
                property_id="123456789",
                token_provider=StaticTokenProvider(),
                clock=clock,
                api_base_url="https://analytics.test/v1beta",
                dimension_limit=10,
                max_concurrency=2,
                max_retries=1,
                retry_backoff_seconds=0.001,
                metered_http=meter(ledger),
                stream_ids=("123", "456"),
            )
            await adapter.collect_activity(
                period_start=clock.now() - timedelta(days=7), period_end=clock.now()
            )
        assert calls == 15  # Fourteen report shapes plus one throttled attempt.
        assert (await ledger.periods())[0].usage.provider_requests == 15
    finally:
        await db.dispose()
