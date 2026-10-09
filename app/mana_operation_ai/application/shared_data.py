import hashlib
import json
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Protocol

from app.mana_operation_ai.application.cost_control import CostBudgetExceeded
from app.mana_operation_ai.application.ports import ProviderPermanentError
from app.mana_operation_ai.application.read_budget import FirestoreReadBudgetExceeded
from app.mana_operation_ai.domain.cost_control import ProductScope
from app.mana_operation_ai.domain.shared_data import (
    CollectedAggregate,
    SavedAggregate,
    SourceAdmission,
    SourceBinding,
)


class SharedDataUnavailable(ProviderPermanentError):
    """No appropriately scoped saved facts exist; never substitute another app's data."""


class SharedDataStore(Protocol):
    async def admit(self, binding: SourceBinding, *, query_key: str) -> SourceAdmission: ...

    async def publish(self, admission: SourceAdmission, *, snapshot: SavedAggregate) -> None: ...

    async def fail(self, admission: SourceAdmission, *, permanent: bool) -> None: ...


class SharedDataReader:
    """Reuse typed, minimized aggregates, with durable single-flight per source/app.

    The source-wide cooldown cannot be bypassed with different lookback settings,
    by another agent, or by changing a chat topic. Config revisions must be explicit.
    """

    def __init__(self, store: SharedDataStore) -> None:
        self._store = store

    async def read[T: CollectedAggregate](
        self,
        *,
        binding: SourceBinding,
        parameters: dict[str, object],
        model: type[T],
        load: Callable[[], Awaitable[T]],
    ) -> T:
        if binding.product is ProductScope.UNVERIFIED:
            raise SharedDataUnavailable("Live data requires verified application ownership")
        key = query_fingerprint(binding, parameters)
        admission = await self._store.admit(binding, query_key=key)
        if admission.token is None:
            return _saved(model, admission, product=binding.product)
        try:
            facts = await load()
            if facts.product_scope not in {ProductScope.UNVERIFIED, binding.product}:
                raise SharedDataUnavailable(
                    "Collected aggregate belongs to a different application"
                )
            collected_at = facts.collected_at
            facts = facts.model_copy(
                update={
                    "product_scope": binding.product,
                    "fresh_until": collected_at
                    + timedelta(seconds=binding.minimum_interval_seconds),
                    "refresh_status": "live",
                }
            )
            await self._store.publish(
                admission,
                snapshot=SavedAggregate(
                    query_key=key,
                    collected_at=collected_at,
                    fresh_until=collected_at + timedelta(seconds=binding.minimum_interval_seconds),
                    payload=facts.model_dump(mode="json"),
                ),
            )
            return facts
        except BaseException as exc:
            # Cancellation leaves admission/cooldown durable too. A late publisher
            # cannot replace a newer source lease after a process restart.
            await self._store.fail(
                admission,
                permanent=isinstance(exc, ProviderPermanentError)
                and not isinstance(exc, CostBudgetExceeded | FirestoreReadBudgetExceeded),
            )
            if isinstance(exc, Exception) and admission.snapshot is not None:
                return _saved(model, admission, product=binding.product, failed=True)
            raise


def query_fingerprint(binding: SourceBinding, parameters: dict[str, object]) -> str:
    canonical = json.dumps(
        {
            "product": binding.product,
            "source": binding.source,
            "binding": binding.fingerprint,
            "parameters": parameters,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _saved[T: CollectedAggregate](
    model: type[T], admission: SourceAdmission, *, product: ProductScope, failed: bool = False
) -> T:
    if admission.snapshot is None:
        raise SharedDataUnavailable(f"Shared source refresh unavailable: {admission.reason}")
    facts = model.model_validate(admission.snapshot.payload)
    if facts.product_scope is not product:
        raise SharedDataUnavailable("Saved aggregate has no matching verified application scope")
    if admission.reason != "fresh" or failed:
        limitations = list(getattr(facts, "limitations", []))
        limitations.append(
            "Saved aggregate reused without a new external read; refresh is unavailable. "
            f"Original collection time: {admission.snapshot.collected_at.isoformat()}.",
        )
        facts = facts.model_copy(update={"limitations": limitations})
    return facts.model_copy(
        update={
            "fresh_until": admission.snapshot.fresh_until,
            "refresh_status": "stale" if admission.reason != "fresh" or failed else "cached",
        }
    )
