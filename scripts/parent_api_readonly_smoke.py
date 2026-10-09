"""Explicit two-request parent API smoke; no database writes, model or Firestore calls."""

import asyncio
import logging
import os

import httpx

from app.core.config import get_settings
from app.mana_operation_ai.application.ports import ProviderOperationError
from app.mana_operation_ai.application.runtime import SystemClock
from app.mana_operation_ai.infrastructure.retention.manakids import ManakidsAdminActivityAdapter
from app.mana_operation_ai.infrastructure.retention.parents import ManakidsParentSummaryAdapter


async def main() -> None:
    if os.getenv("MANA_PARENT_LIVE_SMOKE") != "1":
        raise SystemExit("Set MANA_PARENT_LIVE_SMOKE=1 for one explicit, one-row read-only check")
    settings = get_settings()
    if not settings.manakids_api_username or settings.manakids_api_password is None:
        raise SystemExit("Configure MANAKIDS_API_USERNAME and MANAKIDS_API_PASSWORD")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    clock = SystemClock()
    async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
        reader = ManakidsAdminActivityAdapter(
            client=client,
            base_url=settings.manakids_api_base_url,
            username=settings.manakids_api_username,
            password=settings.manakids_api_password.get_secret_value(),
            clock=clock,
            max_pages=1,
            max_retries=0,
            retry_backoff_seconds=0.5,
            max_response_bytes=1_048_576,
        )
        try:
            facts = await ManakidsParentSummaryAdapter(reader, clock, 1).collect_summary()
        except ProviderOperationError as exc:
            raise SystemExit(str(exc)) from None
    print(facts.model_dump_json(indent=2))


if __name__ == "__main__":
    asyncio.run(main())
