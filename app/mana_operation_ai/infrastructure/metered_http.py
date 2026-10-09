from collections.abc import Mapping
from typing import Any

import httpx

from app.mana_operation_ai.application.cost_control import CostLedger
from app.mana_operation_ai.application.ports import ProviderPermanentError
from app.mana_operation_ai.domain.cost_control import (
    CostAttribution,
    DataRateCard,
    ResourceUsage,
)

# The pinned httpcore HTTP/1.1 and HTTP/2 transports read at most 64 KiB at a
# time. HTTPX's chunk_size only slices an already-received block; it does not
# reduce transport read-ahead. This reserve covers one final detection block,
# not headers/TLS or an arbitrary replacement transport's allocation policy.
_TRANSPORT_READ_AHEAD_BYTES = 64 * 1024


class MeteredReadHttp:
    """One bounded external attempt; retries belong to adapters and reserve again.

    Unknown Firestore charges keep the document reservation. Only supported,
    structurally valid successful document responses reconcile it. No response
    body, URL, token or request payload is stored in the ledger.
    """

    def __init__(
        self,
        *,
        ledger: CostLedger,
        attribution: CostAttribution,
        maximum_response_bytes: int,
        rates: DataRateCard,
    ) -> None:
        if maximum_response_bytes < 1:
            raise ValueError("HTTP response ceiling must be positive")
        self._ledger = ledger
        self._attribution = attribution
        self._maximum_bytes = maximum_response_bytes
        # One detection chunk may already be read before overflow is known. Admit
        # it too; bounded payload storage is not itself a transfer reservation.
        self._reserved_bytes = maximum_response_bytes + _TRANSPORT_READ_AHEAD_BYTES
        self._rates = rates

    async def request(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        *,
        document_limit: int = 0,
        **kwargs: Any,
    ) -> httpx.Response:
        if method not in {"GET", "POST"} or document_limit < 0:
            raise ValueError("Unsupported metered read attempt")
        reserved = ResourceUsage(
            document_reads=document_limit,
            response_bytes=self._reserved_bytes,
            provider_requests=1,
            data_microusd=self._rates.microusd(
                documents=document_limit, response_bytes=self._reserved_bytes
            ),
        )
        reservation = await self._ledger.reserve(reserved, attribution=self._attribution)
        # Avoid compressed-payload accounting ambiguity, redirects and transport
        # retry loops. Identity/raw streaming avoids decompression before bounds.
        headers = httpx.Headers(kwargs.pop("headers", {}))
        headers["Accept-Encoding"] = "identity"
        async with client.stream(
            method, url, headers=headers, follow_redirects=False, **kwargs
        ) as response:
            if response.headers.get("content-encoding", "identity").strip().lower() != "identity":
                # A provider ignoring identity negotiation must not trigger an
                # unbounded decoder allocation before the body ceiling is checked.
                raise ProviderPermanentError("Compressed provider responses are not permitted")
            body = bytearray()
            # MockTransport may provide an already-loaded identity response; real
            # streamed responses must remain raw to bypass automatic decoders.
            chunks = response.aiter_bytes() if response.is_stream_consumed else response.aiter_raw()
            received_bytes = 0
            async for chunk in chunks:
                received_bytes += len(chunk)
                if received_bytes > self._maximum_bytes:
                    # Abort without refund: the server may already have read all
                    # documents; neither usage nor transfer is known completely.
                    if received_bytes > self._reserved_bytes:
                        # A replaced/nonconforming transport must not hide known
                        # overrun behind the admitted estimate. Preserve all other
                        # uncertain charges and record the observed lower bound.
                        await self._ledger.settle(
                            reservation.reservation_id,
                            actual=ResourceUsage(
                                document_reads=document_limit,
                                response_bytes=received_bytes,
                                provider_requests=1,
                                data_microusd=self._rates.microusd(
                                    documents=document_limit, response_bytes=received_bytes
                                ),
                            ),
                        )
                    raise ProviderPermanentError("Provider response exceeded its byte ceiling")
                body.extend(chunk)
            complete = httpx.Response(
                response.status_code,
                headers={
                    name: value
                    for name, value in response.headers.items()
                    if name.lower() not in {"content-encoding", "content-length"}
                },
                content=bytes(body),
                request=response.request,
            )
        documents = document_limit
        if document_limit and 200 <= complete.status_code < 300:
            documents = _document_reads(complete, fallback=document_limit)
        actual = ResourceUsage(
            document_reads=documents,
            response_bytes=len(body),
            provider_requests=1,
            data_microusd=self._rates.microusd(documents=documents, response_bytes=len(body)),
        )
        await self._ledger.settle(reservation.reservation_id, actual=actual)
        if actual.exceeds(reserved):
            raise ProviderPermanentError("Provider usage exceeded its admitted request bound")
        # A redirect is not an authorized extra attempt or a successful read.
        if 300 <= complete.status_code < 400:
            raise ProviderPermanentError("Provider redirects are not permitted")
        return complete


def _document_reads(response: httpx.Response, *, fallback: int) -> int:
    try:
        payload = response.json()
    except ValueError:
        return fallback
    if isinstance(payload, list):
        if not all(isinstance(row, Mapping) for row in payload):
            return fallback
        documents = [row["document"] for row in payload if "document" in row]
        # runQuery metadata rows are valid but must not be mistaken for documents.
        if any(not isinstance(document, Mapping) for document in documents):
            return fallback
        if any(not ("document" in row or "readTime" in row) for row in payload):
            return fallback
        return max(1, len(documents))
    if isinstance(payload, Mapping) and "documents" in payload:
        documents = payload["documents"]
        if isinstance(documents, list) and all(isinstance(row, Mapping) for row in documents):
            return max(1, len(documents))
    # An empty listDocuments response can legitimately omit `documents`.
    if isinstance(payload, Mapping) and set(payload).issubset({"nextPageToken"}):
        return 1
    return fallback
