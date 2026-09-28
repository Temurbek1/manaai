import logging
import time
import uuid
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from app.mana_operation_ai.application.ports import ProviderPermanentError

logger = logging.getLogger(__name__)


class FirestoreReadBudgetExceeded(ProviderPermanentError):
    """A request was refused locally before it could exceed the run's read budget."""


@dataclass(frozen=True)
class FirestoreReadLimits:
    documents: int = 25_000
    pages: int = 30
    requests: int = 40

    def __post_init__(self) -> None:
        if min(self.documents, self.pages, self.requests) < 1:
            raise ValueError("Firestore read limits must be positive")


@dataclass
class ReadAttempt:
    status_code: int | None = None


class FirestoreReadBudget:
    """One explicitly passed budget shared by every Firestore source in a run.

    Reserve the requested page/query limit BEFORE each HTTP attempt. Reservations
    are never refunded: a cancelled/timed-out request may still have been billed.
    These bounds exclude index/rules-dependent reads, storage and network charges;
    observed documents are not a substitute for Cloud Billing measurements.
    """

    def __init__(self, limits: FirestoreReadLimits, *, run_id: str | None = None) -> None:
        self.limits = limits
        self.run_id = run_id or str(uuid.uuid4())
        self.pages = 0
        self.requests = 0
        self.reserved_document_reads = 0
        self.observed_documents = 0
        self.retries = 0
        self.by_endpoint: Counter[str] = Counter()
        self.stop_reason: str | None = None
        self._started = time.monotonic()

    def _reject(self, reason: str) -> None:
        self.stop_reason = reason
        raise FirestoreReadBudgetExceeded(f"Firestore run budget exhausted: {reason}")

    def begin_page(self) -> None:
        if self.pages >= self.limits.pages:
            self._reject("pages")
        self.pages += 1

    def observe_documents(self, count: int) -> None:
        self.observed_documents += count

    @contextmanager
    def request(
        self,
        *,
        provider: str,
        endpoint: str,
        document_limit: int,
        retry: bool,
    ) -> Iterator[ReadAttempt]:
        if self.requests >= self.limits.requests:
            self._reject("requests")
        charge = max(1, document_limit)
        if self.reserved_document_reads + charge > self.limits.documents:
            self._reject("document_reads")
        # No await between checking and reserving: concurrent siblings share the
        # same totals, without any global state or per-collection budget loophole.
        self.requests += 1
        self.reserved_document_reads += charge
        self.retries += int(retry)
        self.by_endpoint[f"{provider}:{endpoint}"] += 1
        attempt = ReadAttempt()
        started = time.monotonic()
        try:
            yield attempt
        finally:
            logger.info(
                "Retention provider request",
                extra={
                    "run_id": self.run_id,
                    "provider": provider,
                    "endpoint": endpoint,
                    "request_count": 1,
                    "retry_count": int(retry),
                    "reserved_document_reads": charge,
                    "http_status": attempt.status_code,
                    "duration_ms": round((time.monotonic() - started) * 1000),
                },
            )

    def log_summary(self, reason: str) -> None:
        logger.info(
            "Retention Firestore budget summary",
            extra={
                "run_id": self.run_id,
                "provider": "firestore",
                "request_count": self.requests,
                "page_count": self.pages,
                "observed_documents": self.observed_documents,
                "reserved_document_reads": self.reserved_document_reads,
                "retry_count": self.retries,
                "requests_by_endpoint": dict(self.by_endpoint),
                "stop_reason": self.stop_reason or reason,
                "duration_ms": round((time.monotonic() - self._started) * 1000),
            },
        )
