"""One durably admitted family/day acquisition and selected-child observation."""

import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.application.family_day_usage import FamilyDayUsageSource, ParentUsageIdentitySource
from app.mana_ai.domain.family_day_usage import (
    DayUsageClaim,
    DayUsageReceipt,
    DayUsageTarget,
    FamilyDayUsagePage,
    ParentUsageLookup,
)
from app.mana_ai.domain.source_reviews import SourceAnalysisOwner


class DayUsageStore(Protocol):
    async def claim_day(
        self, target: DayUsageTarget, now: datetime, owner: SourceAnalysisOwner | None = None
    ) -> DayUsageClaim: ...
    async def complete_day(
        self, target: DayUsageTarget, page: FamilyDayUsagePage | None, now: datetime
    ) -> DayUsageReceipt: ...
    async def fail_day(
        self, target: DayUsageTarget, now: datetime, *, code: str, unknown: bool, close_source: bool
    ) -> DayUsageReceipt: ...


class FamilyDayUsageService:
    def __init__(
        self,
        store: DayUsageStore,
        identities: ParentUsageIdentitySource,
        source: FamilyDayUsageSource,
        *,
        clock: Callable[[], datetime],
    ) -> None:
        self._store, self._identities, self._source, self._clock = store, identities, source, clock

    async def read_for_analysis(
        self, target: DayUsageTarget, owner: SourceAnalysisOwner | None = None
    ) -> DayUsageReceipt:
        target = DayUsageTarget.model_validate(target.model_dump())
        now = self._clock()
        if now.utcoffset() is None:
            raise ValueError("A timezone-aware source clock is required")
        # Replays must observe their original receipt even after its day window closes.
        # New requests are range-checked again by the store before admission.
        claim = await self._store.claim_day(target, now, owner)
        if not claim.admitted:
            return claim.receipt
        submitted = False
        try:
            if (
                not 1
                <= (now.astimezone(ZoneInfo("Asia/Tashkent")).date() - target.requested_day).days
                <= 31
            ):
                raise ValueError("Only the preceding 31 completed calendar days are allowed")
            async with asyncio.timeout(60):
                submitted = True  # Ownership I/O is also a one-shot external attempt.
                raw = await self._identities.read_usage_lookup(target.parent_id)
                lookup = ParentUsageLookup.model_validate(vars(raw))
                current = self._clock()
                if (
                    lookup.parent_id != target.parent_id
                    or target.child_id not in lookup.connected_child_ids
                    or not current - timedelta(seconds=180) <= lookup.collected_at <= current
                ):
                    raise ParentChatError("family_source_ownership_denied", 403)
                page = (
                    await self._source.read_verified(lookup, target.requested_day)
                    if claim.read_provider
                    else None
                )
                if page is not None and (
                    page.ownership_collected_at != lookup.collected_at
                    or any(c.child_id not in lookup.connected_child_ids for c in page.children)
                ):
                    raise ParentChatError("family_source_ownership_denied", 403)
                return await self._store.complete_day(target, page, self._clock())
        except asyncio.CancelledError:
            await asyncio.shield(
                self._store.fail_day(
                    target,
                    self._clock(),
                    code="family_source_cancelled",
                    unknown=submitted,
                    close_source=False,
                )
            )
            raise
        except ParentChatError as exc:
            auth = exc.code in {
                "family_day_usage_auth_denied",
                "child_source_auth_denied",
                "chat_children_auth_denied",
            }
            invalid = exc.code in {
                "family_day_usage_invalid",
                "family_day_usage_query_invalid",
                "family_source_snapshot_mismatch",
            }
            denied = exc.code in {
                "family_source_ownership_denied",
                "family_day_usage_child_not_authorized",
                "family_day_usage_owner_or_date_invalid",
                "parent_not_found",
            }
            code = (
                "family_source_auth_denied"
                if auth
                else "family_source_invalid"
                if invalid
                else "family_source_ownership_denied"
                if denied
                else "family_source_unavailable"
            )
            return await self._store.fail_day(
                target,
                self._clock(),
                code=code,
                unknown=submitted and not (auth or invalid or denied),
                close_source=auth or invalid,
            )
        except (ValidationError, ValueError, TypeError):
            return await self._store.fail_day(
                target,
                self._clock(),
                code="family_source_invalid",
                unknown=False,
                close_source=submitted,
            )
        except Exception:
            return await self._store.fail_day(
                target,
                self._clock(),
                code="family_source_unavailable",
                unknown=submitted,
                close_source=False,
            )
