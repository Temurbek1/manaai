"""Account-only source port, deliberately separate from child ownership reads."""

import asyncio
from collections.abc import Callable
from datetime import datetime
from typing import Protocol
from uuid import UUID

from pydantic import ValidationError

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.domain.conversion import ConversionAdmission, ConversionSnapshot
from app.mana_ai.domain.conversion_accounts import ConversionAccountFacts, ConversionAccountRead


class ConversionAccountSource(Protocol):
    async def read(self, parent_id: str) -> ConversionAccountFacts:
        """One explicit read; callers own durable admission and idempotency."""
        ...


class ConversionAccountReadStore(Protocol):
    async def claim_account_read(
        self, snapshot: ConversionSnapshot, now: datetime
    ) -> tuple[ConversionAdmission | None, bool]: ...

    async def finish_account_read(
        self,
        snapshot: ConversionSnapshot,
        now: datetime,
        *,
        status: str,
        facts: ConversionAccountFacts | None,
    ) -> None: ...

    async def account_read(self, parent_id: str, event_id: UUID) -> ConversionAccountRead: ...

    async def ingest_conversion(
        self, snapshot: ConversionSnapshot, now: datetime
    ) -> ConversionAdmission: ...


class ConversionAccountVerifier:
    """Only a committed, new SQL claim may dispatch the account source."""

    def __init__(
        self,
        store: ConversionAccountReadStore,
        source: ConversionAccountSource | None,
        *,
        clock: Callable[[], datetime],
    ) -> None:
        self._store, self._source, self._clock = store, source, clock

    async def observe(self, snapshot: ConversionSnapshot) -> ConversionAdmission:
        snapshot = ConversionSnapshot.model_validate(snapshot.model_dump(warnings=False))
        if int(snapshot.parent_id) > 2**63 - 1:
            raise ParentChatError("parent_profile_id_required", 422)
        known, dispatch = await self._store.claim_account_read(snapshot, self._clock())
        if known is not None:
            return known
        if dispatch:
            facts = None
            status = "unknown"
            try:
                if self._source is None:
                    raise ParentChatError("conversion_account_source_disabled", 503)
                result = await self._source.read(snapshot.parent_id)
                # Revalidate an adapter's annotation, including unchecked model_copy.
                facts = ConversionAccountFacts.model_validate(vars(result))
                if facts.parent_id != snapshot.parent_id:
                    facts = None
                    status = "refused"
                else:
                    status = "verified"
            except ParentChatError as exc:
                status = (
                    "refused"
                    if exc.code
                    in {
                        "conversion_account_invalid",
                        "conversion_account_owner_mismatch",
                        "conversion_account_auth_unavailable",
                        "conversion_account_auth_cooling_down",
                        "parent_not_found",
                    }
                    else "unknown"
                )
            except (ValidationError, TypeError, ValueError):
                status = "refused"
            except asyncio.CancelledError:
                await asyncio.shield(
                    self._store.finish_account_read(
                        snapshot, self._clock(), status="unknown", facts=None
                    )
                )
                raise
            except Exception:
                # Preserve an unknown read, never raw upstream error text or retry.
                status = "unknown"
            await self._store.finish_account_read(
                snapshot, self._clock(), status=status, facts=facts
            )
        # This resumes SQL-only finalization after a lost acknowledgement or
        # crash between verified observation and admission. It cannot reread.
        return await self._store.ingest_conversion(snapshot, self._clock())

    async def observation(self, parent_id: str, event_id: UUID) -> ConversionAccountRead:
        return await self._store.account_read(parent_id, event_id)
