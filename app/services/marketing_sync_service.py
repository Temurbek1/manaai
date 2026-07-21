import uuid
from collections import Counter
from datetime import UTC, datetime

from pydantic import JsonValue

from app.schemas.marketing import (
    MarketingEntityType,
    MetaDiscoveryResponse,
    MetaInsightsAsyncJobCreateResponse,
    MetaInsightsAsyncJobIngestRequest,
    MetaInsightsAsyncJobIngestResponse,
    MetaInsightsAsyncJobRequest,
    MetaInsightsAsyncJobStatusResponse,
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

        if request.include_structure:
            raw_inputs.extend(await self._fetch_business_assets(observed_at=collected_at))

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

    async def discover_meta_assets(self) -> MetaDiscoveryResponse:
        collected_at = datetime.now(UTC)
        discovery_id = str(uuid.uuid4())
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

        raw_inputs.extend(await self._fetch_business_assets(observed_at=collected_at))

        ad_accounts = await self._meta_client.fetch_configured_ad_accounts()
        raw_inputs.extend(
            self._record_input(
                entity_type="ad_account",
                payload=payload,
                provider_record_id=_payload_id(payload),
                account_id=_payload_id(payload),
                observed_at=collected_at,
            )
            for payload in ad_accounts
        )
        for payload in ad_accounts:
            account_id = _payload_id(payload)
            if account_id is None:
                continue
            raw_inputs.extend(
                await self._fetch_custom_conversions(
                    account_id=account_id,
                    observed_at=collected_at,
                ),
            )
            raw_inputs.extend(
                await self._fetch_custom_audiences(
                    account_id=account_id,
                    observed_at=collected_at,
                ),
            )

        inserted = await self._repository.insert_raw_records(raw_inputs) if raw_inputs else []
        counts = Counter(record.entity_type for record in inserted)

        return MetaDiscoveryResponse(
            discovery_id=discovery_id,
            api_version=self._meta_client.api_version,
            collected_at=collected_at,
            app_collected=app_payload is not None,
            ad_account_count=len(ad_accounts),
            inserted_count=len(inserted),
            records_by_entity_type=dict(counts),
            record_ids=[record.id for record in inserted],
        )

    async def create_insights_async_job(
        self,
        request: MetaInsightsAsyncJobRequest,
    ) -> MetaInsightsAsyncJobCreateResponse:
        payload = await self._meta_client.create_insights_async_job(
            account_id=request.account_id,
            level=request.level,
            date_start=request.date_start,
            date_stop=request.date_stop,
            fields=request.fields,
            breakdowns=request.breakdowns,
            action_breakdowns=request.action_breakdowns,
            time_increment=request.time_increment,
        )
        report_run_id = _payload_str(payload, "report_run_id") or _payload_str(payload, "id")
        inserted_ids: list[str] = []
        if report_run_id is not None:
            inserted = await self._repository.insert_raw_records(
                [
                    RawMarketingRecordInput(
                        source="meta_marketing_api",
                        entity_type="insights_job",
                        provider_record_id=report_run_id,
                        account_id=normalize_ad_account_id(request.account_id),
                        observed_at=datetime.now(UTC),
                        api_version=self._meta_client.api_version,
                        payload=payload,
                    ),
                ],
            )
            inserted_ids = [record.id for record in inserted]

        if report_run_id is None:
            raise RuntimeError("Meta async insights job response did not include report_run_id")

        return MetaInsightsAsyncJobCreateResponse(
            report_run_id=report_run_id,
            account_id=normalize_ad_account_id(request.account_id),
            level=request.level,
            api_version=self._meta_client.api_version,
            raw_record_id=inserted_ids[0] if inserted_ids else None,
        )

    async def get_insights_async_job_status(
        self,
        report_run_id: str,
    ) -> MetaInsightsAsyncJobStatusResponse:
        payload = await self._meta_client.fetch_insights_async_job_status(report_run_id)
        status = _payload_str(payload, "async_status")
        percent = _payload_int(payload, "async_percent_completion")
        return MetaInsightsAsyncJobStatusResponse(
            report_run_id=report_run_id,
            async_status=status,
            async_percent_completion=percent,
            is_complete=status == "Job Completed" and percent == 100,
            raw_status=payload,
        )

    async def ingest_insights_async_job_results(
        self,
        *,
        report_run_id: str,
        request: MetaInsightsAsyncJobIngestRequest,
    ) -> MetaInsightsAsyncJobIngestResponse:
        insights = await self._meta_client.fetch_insights_async_job_results(
            report_run_id=report_run_id,
            limit=request.limit,
        )
        account_id = normalize_ad_account_id(request.account_id) if request.account_id else None
        level = request.level
        inserted = await self._repository.insert_raw_records(
            [
                self._record_input(
                    entity_type="insight",
                    payload={
                        **payload,
                        "_meta_level": level or payload.get("_meta_level") or "ad",
                        "_meta_report_run_id": report_run_id,
                    },
                    provider_record_id=_insight_provider_id(
                        payload=payload,
                        level=level or "ad",
                    ),
                    account_id=account_id or _payload_str(payload, "account_id"),
                    parent_id=_insight_parent_id(payload=payload, level=level or "ad"),
                    observed_at=datetime.now(UTC),
                )
                for payload in insights
            ],
        )
        return MetaInsightsAsyncJobIngestResponse(
            report_run_id=report_run_id,
            inserted_count=len(inserted),
            record_ids=[record.id for record in inserted],
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
        creatives = await self._meta_client.fetch_ad_creatives(account_id)
        custom_conversions = await self._meta_client.fetch_custom_conversions(account_id)
        custom_audiences = await self._meta_client.fetch_custom_audiences(account_id)

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
        records.extend(
            self._record_input(
                entity_type="creative",
                payload=payload,
                provider_record_id=_payload_id(payload),
                account_id=account_id,
                observed_at=observed_at,
            )
            for payload in creatives
        )
        records.extend(
            self._custom_conversion_record_input(
                payload=payload,
                account_id=account_id,
                observed_at=observed_at,
            )
            for payload in custom_conversions
        )
        records.extend(
            self._record_input(
                entity_type="custom_audience",
                payload=payload,
                provider_record_id=_payload_id(payload),
                account_id=account_id,
                observed_at=observed_at,
            )
            for payload in custom_audiences
        )
        return records

    async def _fetch_business_assets(
        self,
        *,
        observed_at: datetime,
    ) -> list[RawMarketingRecordInput]:
        business = await self._meta_client.fetch_business()
        pixels = await self._meta_client.fetch_business_owned_pixels()

        records: list[RawMarketingRecordInput] = []
        if business is not None:
            records.append(
                self._record_input(
                    entity_type="business",
                    payload=business,
                    provider_record_id=_payload_id(business),
                    observed_at=observed_at,
                ),
            )
        records.extend(
            self._record_input(
                entity_type="pixel",
                payload=payload,
                provider_record_id=_payload_id(payload),
                parent_id=_payload_id(business) if business is not None else None,
                observed_at=observed_at,
            )
            for payload in pixels
        )
        return records

    async def _fetch_custom_conversions(
        self,
        *,
        account_id: str,
        observed_at: datetime,
    ) -> list[RawMarketingRecordInput]:
        custom_conversions = await self._meta_client.fetch_custom_conversions(account_id)
        return [
            self._custom_conversion_record_input(
                payload=payload,
                account_id=account_id,
                observed_at=observed_at,
            )
            for payload in custom_conversions
        ]

    async def _fetch_custom_audiences(
        self,
        *,
        account_id: str,
        observed_at: datetime,
    ) -> list[RawMarketingRecordInput]:
        custom_audiences = await self._meta_client.fetch_custom_audiences(account_id)
        return [
            self._record_input(
                entity_type="custom_audience",
                payload=payload,
                provider_record_id=_payload_id(payload),
                account_id=account_id,
                observed_at=observed_at,
            )
            for payload in custom_audiences
        ]

    def _custom_conversion_record_input(
        self,
        *,
        payload: dict[str, JsonValue],
        account_id: str,
        observed_at: datetime,
    ) -> RawMarketingRecordInput:
        return self._record_input(
            entity_type="custom_conversion",
            payload=payload,
            provider_record_id=_payload_id(payload),
            account_id=account_id,
            parent_id=_custom_conversion_pixel_id(payload),
            observed_at=observed_at,
        )

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


def _custom_conversion_pixel_id(payload: dict[str, JsonValue]) -> str | None:
    pixel = payload.get("pixel")
    if isinstance(pixel, dict):
        pixel_id = pixel.get("id")
        if pixel_id is not None:
            return str(pixel_id)
    return _payload_str(payload, "pixel_id")


def _payload_int(payload: dict[str, JsonValue], key: str) -> int | None:
    value = payload.get(key)
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value:
        try:
            return int(float(value))
        except ValueError:
            return None
    return None


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
