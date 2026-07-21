import uuid
from collections import Counter
from datetime import UTC, datetime

from pydantic import JsonValue

from app.schemas.marketing import (
    MarketingEntityType,
    MetaSyncRequest,
    MetaSyncResponse,
    RawMarketingRecordInput,
)
from app.services.marketing_repository import MarketingRepository
from app.services.meta_marketing_client import MetaMarketingClient, normalize_ad_account_id


class MarketingSyncService:
    def __init__(
        self,
        *,
        meta_client: MetaMarketingClient,
        repository: MarketingRepository,
    ) -> None:
        self._meta_client = meta_client
        self._repository = repository

    async def sync_meta(self, request: MetaSyncRequest) -> MetaSyncResponse:
        collected_at = datetime.now(UTC)
        sync_id = str(uuid.uuid4())
        warnings: list[str] = []
        raw_inputs: list[RawMarketingRecordInput] = []

        app_payload = await self._meta_client.fetch_app()
        if app_payload is not None:
            raw_inputs.append(
                self._record_input(
                    entity_type="app",
                    payload=app_payload,
                    provider_record_id=_payload_id(app_payload),
                    observed_at=collected_at,
                ),
            )

        account_ids = await self._resolve_account_ids(request=request, raw_inputs=raw_inputs)
        if not account_ids:
            warnings.append("No Meta ad accounts were resolved from request or configuration.")

        for account_id in account_ids:
            if request.include_structure:
                raw_inputs.extend(
                    await self._fetch_structure(
                        account_id=account_id,
                        observed_at=collected_at,
                    ),
                )

            if request.include_insights:
                for level in request.levels:
                    insights = await self._meta_client.fetch_insights(
                        account_id=account_id,
                        level=level,
                        date_start=request.date_start,
                        date_stop=request.date_stop,
                    )
                    raw_inputs.extend(
                        self._record_input(
                            entity_type="insight",
                            payload={
                                **payload,
                                "_meta_level": level,
                            },
                            provider_record_id=_insight_provider_id(payload=payload, level=level),
                            account_id=account_id,
                            parent_id=_insight_parent_id(payload=payload, level=level),
                            observed_at=datetime.combine(
                                request.date_start,
                                datetime.min.time(),
                                tzinfo=UTC,
                            ),
                        )
                        for payload in insights
                    )

        inserted = await self._repository.insert_raw_records(raw_inputs) if raw_inputs else []
        counts = Counter(record.entity_type for record in inserted)

        return MetaSyncResponse(
            sync_id=sync_id,
            api_version=self._meta_client.api_version,
            collected_at=collected_at,
            account_ids=account_ids,
            inserted_count=len(inserted),
            records_by_entity_type=dict(counts),
            warnings=warnings,
        )

    async def _resolve_account_ids(
        self,
        *,
        request: MetaSyncRequest,
        raw_inputs: list[RawMarketingRecordInput],
    ) -> list[str]:
        if request.account_ids:
            return [normalize_ad_account_id(account_id) for account_id in request.account_ids]

        account_payloads = await self._meta_client.fetch_configured_ad_accounts()
        account_ids: list[str] = []
        for payload in account_payloads:
            account_id = _payload_id(payload)
            raw_inputs.append(
                self._record_input(
                    entity_type="ad_account",
                    payload=payload,
                    provider_record_id=account_id,
                    account_id=account_id,
                ),
            )
            if account_id:
                account_ids.append(normalize_ad_account_id(account_id))
        return account_ids

    async def _fetch_structure(
        self,
        *,
        account_id: str,
        observed_at: datetime,
    ) -> list[RawMarketingRecordInput]:
        campaigns = await self._meta_client.fetch_campaigns(account_id)
        adsets = await self._meta_client.fetch_adsets(account_id)
        ads = await self._meta_client.fetch_ads(account_id)

        records: list[RawMarketingRecordInput] = []
        records.extend(
            self._record_input(
                entity_type="campaign",
                payload=payload,
                provider_record_id=_payload_id(payload),
                account_id=account_id,
                observed_at=observed_at,
            )
            for payload in campaigns
        )
        records.extend(
            self._record_input(
                entity_type="adset",
                payload=payload,
                provider_record_id=_payload_id(payload),
                account_id=account_id,
                parent_id=_payload_str(payload, "campaign_id"),
                observed_at=observed_at,
            )
            for payload in adsets
        )
        records.extend(
            self._record_input(
                entity_type="ad",
                payload=payload,
                provider_record_id=_payload_id(payload),
                account_id=account_id,
                parent_id=_payload_str(payload, "adset_id"),
                observed_at=observed_at,
            )
            for payload in ads
        )
        return records

    def _record_input(
        self,
        *,
        entity_type: MarketingEntityType,
        payload: dict[str, JsonValue],
        provider_record_id: str | None,
        account_id: str | None = None,
        parent_id: str | None = None,
        observed_at: datetime | None = None,
    ) -> RawMarketingRecordInput:
        return RawMarketingRecordInput(
            source="meta_marketing_api",
            entity_type=entity_type,
            provider_record_id=provider_record_id,
            account_id=account_id,
            parent_id=parent_id,
            observed_at=observed_at,
            api_version=self._meta_client.api_version,
            payload=payload,
        )


def _payload_id(payload: dict[str, JsonValue]) -> str | None:
    return _payload_str(payload, "id")


def _payload_str(payload: dict[str, JsonValue], key: str) -> str | None:
    value = payload.get(key)
    return str(value) if value is not None else None


def _insight_provider_id(payload: dict[str, JsonValue], level: str) -> str | None:
    level_key = f"{level}_id"
    entity_id = _payload_str(payload, level_key) or _payload_str(payload, "account_id")
    date_start = _payload_str(payload, "date_start")
    date_stop = _payload_str(payload, "date_stop")
    if entity_id is None:
        return None
    return ":".join(part for part in [level, entity_id, date_start, date_stop] if part)


def _insight_parent_id(payload: dict[str, JsonValue], level: str) -> str | None:
    if level == "ad":
        return _payload_str(payload, "adset_id")
    if level == "adset":
        return _payload_str(payload, "campaign_id")
    if level == "campaign":
        return _payload_str(payload, "account_id")
    return None
