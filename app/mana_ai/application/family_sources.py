"""Autonomous bounded reads, durable replay and exact family ownership."""

import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Protocol

from pydantic import ValidationError

from app.mana_ai.application.chat_ports import ParentChatError, ParentChildrenSource
from app.mana_ai.domain.chat import ParentChildContext
from app.mana_ai.domain.family_sources import (
    ChildBatteryFacts,
    FamilySourceClaim,
    FamilySourceReceipt,
    FamilySourceTarget,
)


class ChildBatterySource(Protocol):
    async def read(self, child_id: int) -> ChildBatteryFacts: ...


class FamilySourceStore(Protocol):
    async def claim(self, target: FamilySourceTarget, now: datetime) -> FamilySourceClaim: ...

    async def complete(
        self, target: FamilySourceTarget, facts: ChildBatteryFacts, now: datetime
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
    ) -> None:
        self._store, self._children, self._battery, self._clock = store, children, battery, clock

    async def read_child_battery(self, target: FamilySourceTarget) -> FamilySourceReceipt:
        target = FamilySourceTarget.model_validate(target.model_dump())
        if int(target.parent_id) > 2**63 - 1:
            raise ParentChatError("parent_profile_id_required", 422)
        claim = await self._store.claim(target, self._clock())
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
                result = await self._battery.read(target.child_id)
                facts = ChildBatteryFacts.model_validate(result.model_dump())
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
