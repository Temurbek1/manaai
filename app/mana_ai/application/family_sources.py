"""Autonomous bounded reads, durable replay and exact family ownership."""

import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Protocol

from pydantic import ValidationError

from app.mana_ai.application.chat_ports import ParentChatError, ParentChildrenSource
from app.mana_ai.domain.chat import ParentChildContext
from app.mana_ai.domain.family_sources import (
    ChildAppUsageFacts,
    ChildBatteryFacts,
    ChildSourceFacts,
    FamilySourceClaim,
    FamilySourceReceipt,
    FamilySourceTarget,
    source_facts,
)
from app.mana_ai.domain.source_reviews import SourceAnalysisOwner


class ChildBatterySource(Protocol):
    async def read(self, child_id: int) -> ChildBatteryFacts: ...


class ChildAppUsageSource(Protocol):
    async def read(self, child_id: int) -> ChildAppUsageFacts: ...


class FamilySourceStore(Protocol):
    async def claim_for_analysis(
        self, target: FamilySourceTarget, owner: SourceAnalysisOwner, now: datetime
    ) -> FamilySourceClaim: ...

    async def claim(self, target: FamilySourceTarget, now: datetime) -> FamilySourceClaim: ...

    async def complete(
        self, target: FamilySourceTarget, facts: ChildSourceFacts, now: datetime
    ) -> FamilySourceReceipt: ...

    async def fail(
        self,
        target: FamilySourceTarget,
        now: datetime,
        *,
        code: str,
        unknown: bool,
        close_source: bool,
    ) -> FamilySourceReceipt: ...


class FamilySourceService:
    def __init__(
        self,
        store: FamilySourceStore,
        children: ParentChildrenSource,
        battery: ChildBatterySource,
        *,
        clock: Callable[[], datetime],
        app_usage: ChildAppUsageSource | None = None,
    ) -> None:
        self._store, self._children, self._battery, self._clock = store, children, battery, clock
        self._app_usage = app_usage

    async def read_child_battery(self, target: FamilySourceTarget) -> FamilySourceReceipt:
        if target.source != "firebase.child_battery.v1":
            raise ParentChatError("family_source_request_conflict", 409)
        return await self.read(target)

    async def read_child_app_usage(self, target: FamilySourceTarget) -> FamilySourceReceipt:
        if target.source != "manakids.child_app_usage.v1":
            raise ParentChatError("family_source_request_conflict", 409)
        return await self.read(target)

    async def read(self, target: FamilySourceTarget) -> FamilySourceReceipt:
        return await self._read(target)

    async def read_for_analysis(
        self, target: FamilySourceTarget, owner: SourceAnalysisOwner
    ) -> FamilySourceReceipt:
        return await self._read(target, owner=owner)

    async def _read(
        self, target: FamilySourceTarget, *, owner: SourceAnalysisOwner | None = None
    ) -> FamilySourceReceipt:
        target = FamilySourceTarget.model_validate(target.model_dump())
        if target.source == "manakids.child_app_usage.v1" and self._app_usage is None:
            raise ParentChatError("family_source_not_enabled", 503)
        if int(target.parent_id) > 2**63 - 1:
            raise ParentChatError("parent_profile_id_required", 422)
        claim = (
            await self._store.claim_for_analysis(target, owner, self._clock())
            if owner is not None
            else await self._store.claim(target, self._clock())
        )
        if not claim.admitted:
            return claim.receipt  # Exact SQL observation, including lost/unknown calls.
        submitted = False
        try:
            result_context = await self._children.read(target.parent_id)
            context = ParentChildContext.model_validate(result_context.model_dump())
            now = self._clock()
            if (
                context.parent_id != target.parent_id
                or len({child.child_id for child in context.children}) != len(context.children)
                or not now - timedelta(seconds=180) <= context.collected_at <= now
                or not any(
                    child.child_id == target.child_id and child.connected
                    for child in context.children
                )
            ):
                raise ParentChatError("family_source_ownership_denied", 403)
            if claim.read_provider:
                submitted = True
                adapter: ChildBatterySource | ChildAppUsageSource = self._battery
                if target.source == "manakids.child_app_usage.v1":
                    assert self._app_usage is not None
                    adapter = self._app_usage
                result = await adapter.read(target.child_id)
                facts = source_facts(result.model_dump(), target.source)
                if facts.child_id != target.child_id or not (
                    now - timedelta(seconds=5) <= facts.collected_at <= self._clock()
                ):
                    raise ValueError("Invalid family source observation")
            else:
                assert claim.receipt.facts is not None
                facts = claim.receipt.facts
            return await self._store.complete(target, facts, self._clock())
        except asyncio.CancelledError:
            # No expiry/new day/restart turns a lost submitted source into a retry.
            await asyncio.shield(
                self._store.fail(
                    target,
                    self._clock(),
                    code="family_source_cancelled",
                    unknown=submitted,
                    close_source=False,
                )
            )
            raise
        except ParentChatError as exc:
            code = (
                "family_source_auth_denied" if exc.code == "child_source_auth_denied" else exc.code
            )
            permanent = code in {
                "family_source_auth_denied",
                "family_source_query_invalid",
                "family_source_invalid",
            }
            return await self._store.fail(
                target,
                self._clock(),
                code=code if permanent else "family_source_unavailable",
                unknown=submitted and not permanent,
                close_source=permanent,
            )
        except (ValidationError, TypeError, ValueError):
            return await self._store.fail(
                target,
                self._clock(),
                code="family_source_invalid",
                unknown=False,
                close_source=submitted,
            )
        except Exception:
            return await self._store.fail(
                target,
                self._clock(),
                code="family_source_unavailable",
                unknown=submitted,
                close_source=False,
            )
