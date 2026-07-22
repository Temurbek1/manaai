import asyncio
import hashlib
import json
from collections.abc import Iterable, Sequence
from dataclasses import asdict
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import cast

from pydantic import JsonValue

from app.core.config import Settings
from app.mana_operation_ai.application.marketing.metrics import build_metrics
from app.mana_operation_ai.application.ports import (
    Clock,
    ProviderObjectNotFoundError,
    ProviderPermanentError,
    ProviderTransientError,
    WriteOperationForbidden,
)
from app.mana_operation_ai.domain.enums import DataAvailability, IntegrationStatus, ProviderMode
from app.mana_operation_ai.domain.marketing import (
    AdAccount,
    AdEntity,
    AdEntityType,
    AdsCollectionRequest,
    AdsSnapshot,
    Audience,
    Breakdown,
    CompatibilityStatus,
    Creative,
    InsightRow,
    ProviderActionResult,
    ProviderCompatibilityCheck,
    ProviderDiagnostic,
    ProviderObjectState,
    ProviderObservability,
    ProviderRequestBudget,
)
from app.mana_operation_ai.domain.models import (
    ActionParameters,
    IntegrationHealth,
)
from app.services.meta_marketing_client import (
    MetaAPIError,
    MetaAuthenticationError,
    MetaConfigurationError,
    MetaMarketingClient,
    MetaMarketingError,
    MetaObjectNotFoundError,
    MetaPaginationLimitError,
    MetaPermissionError,
    MetaRequestBudgetExceeded,
    MetaRequestBudgetSnapshot,
    MetaRequestDiagnostic,
    MetaTransientAPIError,
    normalize_ad_account_id,
)

META_BREAKDOWN_PLANS: dict[Breakdown, tuple[str, ...]] = {
    Breakdown.PLACEMENT: ("publisher_platform", "platform_position"),
    Breakdown.REGION: ("region",),
    Breakdown.AGE: ("age", "gender"),
    Breakdown.GENDER: ("age", "gender"),
    Breakdown.HOUR: ("hourly_stats_aggregated_by_advertiser_time_zone",),
    Breakdown.DAY: (),
}


class MetaAdsAdapter:
    def __init__(
        self,
        *,
        client: MetaMarketingClient,
        settings: Settings,
        clock: Clock,
    ) -> None:
        self._client = client
        self._settings = settings
        self._clock = clock
        self._account_currencies: dict[str, str] = {}
        self._account_minimum_daily_budgets: dict[str, Decimal] = {}

    @property
    def provider_name(self) -> str:
        return "meta"

    @property
    def provider_mode(self) -> ProviderMode:
        return ProviderMode.LIVE_READ_ONLY

    async def collect(self, request: AdsCollectionRequest) -> AdsSnapshot:
        async with self._client.request_budget(
            run_id=request.run_id,
            correlation_id=request.correlation_id,
        ) as budget:
            snapshot = await self._collect_bounded(request)
            budget_snapshot = budget.snapshot()
        return snapshot.model_copy(
            update={
                "provider_mode": self.provider_mode,
                "api_version": self._client.api_version,
                "request_budget": ProviderRequestBudget.model_validate(
                    asdict(budget_snapshot),
                ),
                "observability": _observability(snapshot, budget_snapshot),
            },
        )

    async def _collect_bounded(self, request: AdsCollectionRequest) -> AdsSnapshot:
        self._client.consume_diagnostics()
        if request.date_stop >= self._clock.now().date():
            raise MetaConfigurationError(
                "Live Meta collection requires a completed reporting period",
            )
        account_payloads = await self._client.fetch_configured_ad_accounts()
        requested_accounts = (
            {normalize_ad_account_id(item) for item in request.account_ids}
            if request.account_ids
            else None
        )
        if requested_accounts is not None:
            account_payloads = [
                item for item in account_payloads if _text(item.get("id")) in requested_accounts
            ]
        if len(account_payloads) > self._settings.meta_live_max_accounts:
            raise MetaConfigurationError(
                "Multiple Meta ad accounts are accessible; explicitly select one account",
            )
        accounts = [_normalize_account(payload) for payload in account_payloads]
        self._account_currencies.update(
            {
                account.provider_id: account.currency
                for account in accounts
                if account.currency is not None
            },
        )
        self._account_minimum_daily_budgets.update(
            {
                account.provider_id: account.minimum_daily_budget
                for account in accounts
                if account.minimum_daily_budget is not None
            },
        )
        campaigns: list[AdEntity] = []
        ad_sets: list[AdEntity] = []
        ads: list[AdEntity] = []
        creatives: list[Creative] = []
        audiences: list[Audience] = []
        insights: list[InsightRow] = []
        compatibility: list[ProviderCompatibilityCheck] = []
        targeting_attributes: dict[str, set[str]] = {}
        data_quality_notes: list[str] = []

        for account in accounts:
            structures = await asyncio.gather(
                self._client.fetch_campaigns(account.provider_id),
                self._client.fetch_adsets(account.provider_id),
                self._client.fetch_ads(account.provider_id),
                self._client.fetch_ad_creatives(account.provider_id),
                self._client.fetch_custom_audiences(account.provider_id),
                return_exceptions=True,
            )
            structure_names = ("campaigns", "ad_sets", "ads", "creatives", "audiences")
            normalized_structures: list[list[dict[str, JsonValue]]] = []
            for operation, result in zip(structure_names, structures, strict=True):
                if isinstance(result, BaseException):
                    if not isinstance(result, Exception):
                        raise result
                    normalized_structures.append([])
                    compatibility.append(
                        _compatibility_error(operation=operation, error=result),
                    )
                    data_quality_notes.append(
                        f"Meta {operation} inventory is unavailable ({type(result).__name__}).",
                    )
                else:
                    normalized_structures.append(result)
                    compatibility.append(
                        ProviderCompatibilityCheck(
                            operation=operation,
                            status=(
                                CompatibilityStatus.SUPPORTED
                                if result
                                else CompatibilityStatus.EMPTY
                            ),
                            row_count=len(result),
                        ),
                    )
            (
                campaign_payloads,
                ad_set_payloads,
                ad_payloads,
                creative_payloads,
                audience_payloads,
            ) = normalized_structures
            campaigns.extend(
                _normalize_entity(item, AdEntityType.CAMPAIGN, account)
                for item in campaign_payloads
            )
            ad_sets.extend(
                _normalize_entity(item, AdEntityType.AD_SET, account) for item in ad_set_payloads
            )
            ads.extend(_normalize_entity(item, AdEntityType.AD, account) for item in ad_payloads)
            creatives.extend(
                _normalize_creative(item, account.provider_id) for item in creative_payloads
            )
            audiences.extend(
                _normalize_audience(item, account.provider_id) for item in audience_payloads
            )
            _extend_targeting_attributes(targeting_attributes, ad_set_payloads)
            audience_by_ad_set = _audience_by_ad_set(ad_set_payloads)
            creative_by_ad = _creative_by_ad(ad_payloads)

            for level in ("account", "campaign", "adset"):
                try:
                    level_payloads = await self._client.fetch_insights(
                        account_id=account.provider_id,
                        level=level,
                        date_start=request.date_start,
                        date_stop=request.date_stop,
                        time_increment=1,
                        attribution_windows=[request.attribution_window],
                    )
                except Exception as exc:
                    compatibility.append(
                        _compatibility_error(
                            operation="insights",
                            error=exc,
                            level=level,
                        ),
                    )
                    data_quality_notes.append(
                        f"Meta {level}-level Insights are unavailable ({type(exc).__name__}).",
                    )
                    if isinstance(exc, MetaRequestBudgetExceeded):
                        break
                else:
                    compatibility.append(
                        _compatibility_success(
                            operation="insights",
                            level=level,
                            rows=level_payloads,
                        ),
                    )

            for breakdowns in _query_plans(request.requested_breakdowns):
                try:
                    payloads = await self._client.fetch_insights(
                        account_id=account.provider_id,
                        level="ad",
                        date_start=request.date_start,
                        date_stop=request.date_stop,
                        breakdowns=list(breakdowns) or None,
                        time_increment=1,
                        attribution_windows=[request.attribution_window],
                    )
                except Exception as exc:
                    compatibility.append(
                        _compatibility_error(
                            operation="insights",
                            error=exc,
                            level="ad",
                            breakdowns=list(breakdowns),
                        ),
                    )
                    scope = "+".join(breakdowns) if breakdowns else "base"
                    data_quality_notes.append(
                        f"Meta ad-level Insights scope {scope} is unavailable "
                        f"({type(exc).__name__}).",
                    )
                    if isinstance(exc, MetaRequestBudgetExceeded):
                        break
                    continue
                compatibility.append(
                    _compatibility_success(
                        operation="insights",
                        level="ad",
                        breakdowns=list(breakdowns),
                        rows=payloads,
                    ),
                )
                insights.extend(
                    _normalize_insight(
                        payload=item,
                        account=account,
                        attribution_window=request.attribution_window,
                        query_scope="base" if not breakdowns else "+".join(breakdowns),
                        creative_by_ad=creative_by_ad,
                        audience_by_ad_set=audience_by_ad_set,
                        conversion_action_types=set(
                            self._settings.marketing_conversion_action_types,
                        ),
                        value_action_types=set(self._settings.marketing_value_action_types),
                    )
                    for item in payloads
                )

        if not accounts:
            data_quality_notes.append("No accessible Meta ad accounts were returned.")
        if any(account.currency is None for account in accounts):
            data_quality_notes.append(
                "One or more Meta ad accounts did not expose currency metadata.",
            )
        diagnostics = [_provider_diagnostic(item) for item in self._client.consume_diagnostics()]
        return AdsSnapshot(
            provider=self.provider_name,
            collected_at=self._clock.now(),
            period_start=datetime.combine(request.date_start, datetime.min.time(), tzinfo=UTC),
            period_end=datetime.combine(request.date_stop, datetime.max.time(), tzinfo=UTC),
            attribution_window=request.attribution_window,
            accounts=accounts,
            campaigns=campaigns,
            ad_sets=ad_sets,
            ads=ads,
            creatives=creatives,
            audiences=audiences,
            available_targeting_attributes={
                key: sorted(values) for key, values in targeting_attributes.items()
            },
            insights=_deduplicate_insights(insights),
            diagnostics=diagnostics,
            compatibility_matrix=compatibility,
            data_quality_notes=data_quality_notes,
        )

    async def health(self) -> IntegrationHealth:
        now = self._clock.now()
        if not self._settings.is_meta_configured:
            return IntegrationHealth(
                integration_id="meta",
                status=IntegrationStatus.UNCONFIGURED,
                checked_at=now,
                message="META_ACCESS_TOKEN is not configured",
            )
        started = self._clock.now()
        try:
            async with self._client.request_budget() as budget:
                token_debug = await self._client.fetch_token_debug()
                accounts = await self._client.fetch_configured_ad_accounts()
                budget_snapshot = budget.snapshot()
        except MetaConfigurationError as exc:
            return IntegrationHealth(
                integration_id="meta",
                status=IntegrationStatus.UNCONFIGURED,
                checked_at=now,
                message=str(exc),
            )
        except (MetaAPIError, MetaRequestBudgetExceeded) as exc:
            diagnostics = self._client.consume_diagnostics()
            request_id = next(
                (item.request_id for item in reversed(diagnostics) if item.request_id),
                None,
            )
            return IntegrationHealth(
                integration_id="meta",
                status=IntegrationStatus.UNHEALTHY,
                checked_at=self._clock.now(),
                message=f"Meta GET validation failed ({type(exc).__name__})",
                provider_request_id=request_id,
                diagnostics={
                    "request_failed": True,
                    "error_class": type(exc).__name__,
                    "provider_mode": self.provider_mode.value,
                    "api_version": self._client.api_version,
                    "write_operations_available": False,
                },
            )
        elapsed = self._clock.now() - started
        diagnostics = self._client.consume_diagnostics()
        request_id = next(
            (item.request_id for item in reversed(diagnostics) if item.request_id), None
        )
        safe_token = _safe_token_health(token_debug)
        account_alias = _account_alias(_text(accounts[0].get("id"))) if len(accounts) == 1 else None
        account_currency = _text(accounts[0].get("currency")) if len(accounts) == 1 else None
        account_timezone = _text(accounts[0].get("timezone_name")) if len(accounts) == 1 else None
        rate_limit_usage = max(
            (
                item.rate_limit_usage_percent
                for item in diagnostics
                if item.rate_limit_usage_percent is not None
            ),
            default=None,
        )
        account_limit_satisfied = len(accounts) <= self._settings.meta_live_max_accounts
        healthy = bool(accounts) and account_limit_satisfied and safe_token["is_valid"] is True
        return IntegrationHealth(
            integration_id="meta",
            status=IntegrationStatus.HEALTHY if healthy else IntegrationStatus.DEGRADED,
            checked_at=self._clock.now(),
            last_success_at=self._clock.now(),
            latency_ms=max(int(elapsed.total_seconds() * 1_000), 0),
            message=(f"Accessible ad accounts: {len(accounts)}; live read-only safeguards active"),
            provider_request_id=request_id,
            diagnostics={
                "account_count": len(accounts),
                "account_limit_satisfied": account_limit_satisfied,
                "selected_account_alias": account_alias,
                "currency": account_currency,
                "timezone": account_timezone,
                "provider_mode": self.provider_mode.value,
                "api_version": self._client.api_version,
                "write_operations_available": False,
                "token": safe_token,
                "last_error": None,
                "rate_limit_usage_percent": rate_limit_usage,
                "request_budget": asdict(budget_snapshot),
            },
        )

    async def get_object_state(
        self,
        object_type: str,
        provider_object_id: str,
    ) -> ProviderObjectState:
        try:
            payload = await self._client.fetch_object_state(provider_object_id)
            account_id = _text(payload.get("account_id"))
            currency = self._account_currencies.get(account_id or "")
            minimum_daily_budget = self._account_minimum_daily_budgets.get(account_id or "")
            if account_id is not None and (currency is None or minimum_daily_budget is None):
                account = _normalize_account(await self._client.fetch_ad_account(account_id))
                if account.currency is not None:
                    self._account_currencies[account.provider_id] = account.currency
                if account.minimum_daily_budget is not None:
                    self._account_minimum_daily_budgets[account.provider_id] = (
                        account.minimum_daily_budget
                    )
                currency = account.currency
                minimum_daily_budget = account.minimum_daily_budget
            return _normalize_state(
                payload,
                object_type,
                self.provider_name,
                currency=currency,
                minimum_daily_budget=minimum_daily_budget,
            )
        except MetaMarketingError as exc:
            raise _provider_error(exc) from exc

    async def execute(
        self,
        *,
        object_type: str,
        provider_object_id: str,
        parameters: ActionParameters,
        idempotency_key: str,
    ) -> ProviderActionResult:
        del object_type, provider_object_id, parameters, idempotency_key
        self._client.consume_diagnostics()
        raise WriteOperationForbidden(
            "LIVE Meta is read-only; no provider request was sent",
        )


def _provider_error(exc: MetaMarketingError) -> RuntimeError:
    if isinstance(exc, MetaObjectNotFoundError):
        return ProviderObjectNotFoundError(str(exc))
    if isinstance(exc, MetaTransientAPIError):
        return ProviderTransientError(str(exc))
    if isinstance(
        exc,
        MetaConfigurationError | MetaAuthenticationError | MetaPermissionError | MetaAPIError,
    ):
        return ProviderPermanentError(str(exc))
    return ProviderPermanentError("Meta provider operation failed")


def _account_alias(account_id: str | None) -> str | None:
    if account_id is None:
        return None
    return hashlib.sha256(account_id.encode()).hexdigest()[:10]


def _safe_token_health(payload: dict[str, JsonValue]) -> dict[str, JsonValue]:
    raw_data = payload.get("data")
    data = raw_data if isinstance(raw_data, dict) else {}
    raw_scopes = data.get("scopes")
    scopes = sorted(str(item) for item in raw_scopes) if isinstance(raw_scopes, list) else []
    raw_granular = data.get("granular_scopes")
    granular_scope_names = (
        sorted(
            {
                str(item.get("scope"))
                for item in raw_granular
                if isinstance(item, dict) and item.get("scope") is not None
            },
        )
        if isinstance(raw_granular, list)
        else []
    )
    result: dict[str, JsonValue] = {
        "is_valid": data.get("is_valid") is True,
        "scopes": cast(JsonValue, scopes),
        "granular_scope_names": cast(JsonValue, granular_scope_names),
        "granular_scope_count": len(granular_scope_names),
    }
    for field_name in ("expires_at", "data_access_expires_at"):
        value = data.get(field_name)
        if isinstance(value, int) and not isinstance(value, bool):
            result[field_name] = value
        else:
            result[field_name] = None
    return result


def _compatibility_success(
    *,
    operation: str,
    rows: Sequence[object],
    level: str | None = None,
    breakdowns: list[str] | None = None,
) -> ProviderCompatibilityCheck:
    return ProviderCompatibilityCheck(
        operation=operation,
        level=level,
        breakdowns=breakdowns or [],
        status=CompatibilityStatus.SUPPORTED if rows else CompatibilityStatus.EMPTY,
        row_count=len(rows),
    )


def _compatibility_error(
    *,
    operation: str,
    error: Exception,
    level: str | None = None,
    breakdowns: list[str] | None = None,
) -> ProviderCompatibilityCheck:
    status = CompatibilityStatus.UNAVAILABLE
    reason_code = type(error).__name__
    if isinstance(error, MetaPermissionError):
        status = CompatibilityStatus.PERMISSION_DENIED
    elif isinstance(error, MetaTransientAPIError) and (
        error.status_code == 429 or error.code in {4, 17, 32, 613}
    ):
        status = CompatibilityStatus.RATE_LIMITED
    elif isinstance(error, MetaPaginationLimitError):
        status = CompatibilityStatus.PARTIAL
    elif isinstance(error, MetaAPIError) and error.code == 100:
        status = CompatibilityStatus.INVALID_COMBINATION
    return ProviderCompatibilityCheck(
        operation=operation,
        level=level,
        breakdowns=breakdowns or [],
        status=status,
        reason_code=reason_code,
    )


def _query_plans(requested: Sequence[Breakdown]) -> list[tuple[str, ...]]:
    plans: list[tuple[str, ...]] = [()]
    for breakdown in requested:
        plan = META_BREAKDOWN_PLANS[breakdown]
        if plan and plan not in plans:
            plans.append(plan)
    return plans


def _normalize_account(payload: dict[str, JsonValue]) -> AdAccount:
    return AdAccount(
        provider_id=_required_text(payload, "id"),
        name=_text(payload.get("name")) or _required_text(payload, "id"),
        currency=_text(payload.get("currency")),
        minimum_daily_budget=_minor_money(payload.get("min_daily_budget")),
        timezone=_text(payload.get("timezone_name")) or "UTC",
        status=_text(payload.get("account_status")) or "UNKNOWN",
    )


def _normalize_entity(
    payload: dict[str, JsonValue],
    entity_type: AdEntityType,
    account: AdAccount,
) -> AdEntity:
    parent_id: str | None
    if entity_type is AdEntityType.CAMPAIGN:
        parent_id = account.provider_id
    elif entity_type is AdEntityType.AD_SET:
        parent_id = _text(payload.get("campaign_id"))
    else:
        parent_id = _text(payload.get("adset_id"))
    return AdEntity(
        provider_id=_required_text(payload, "id"),
        entity_type=entity_type,
        account_id=account.provider_id,
        parent_id=parent_id,
        name=_text(payload.get("name")) or _required_text(payload, "id"),
        status=_text(payload.get("status")) or "UNKNOWN",
        effective_status=_text(payload.get("effective_status")) or "UNKNOWN",
        daily_budget=_minor_money(payload.get("daily_budget")),
        lifetime_budget=_minor_money(payload.get("lifetime_budget")),
        currency=account.currency,
        attributes=_safe_attributes(payload, {"objective", "optimization_goal", "billing_event"}),
        updated_at=_datetime(payload.get("updated_time")),
    )


def _normalize_creative(payload: dict[str, JsonValue], account_id: str) -> Creative:
    return Creative(
        provider_id=_required_text(payload, "id"),
        account_id=account_id,
        name=_text(payload.get("name")) or _required_text(payload, "id"),
        title=_text(payload.get("title")),
        body=_text(payload.get("body")),
        format=_text(payload.get("object_type")),
        preview_url=_text(payload.get("thumbnail_url")) or _text(payload.get("image_url")),
    )


def _normalize_audience(payload: dict[str, JsonValue], account_id: str) -> Audience:
    return Audience(
        provider_id=_required_text(payload, "id"),
        account_id=account_id,
        name=_text(payload.get("name")) or _required_text(payload, "id"),
        subtype=_text(payload.get("subtype")) or "unknown",
        status=_nested_status(payload.get("delivery_status")),
        targeting_attributes=_safe_attributes(
            payload,
            {"approximate_count", "lookalike_spec", "retention_days"},
        ),
    )


def _normalize_insight(
    *,
    payload: dict[str, JsonValue],
    account: AdAccount,
    attribution_window: str,
    query_scope: str,
    creative_by_ad: dict[str, str],
    audience_by_ad_set: dict[str, str],
    conversion_action_types: set[str],
    value_action_types: set[str],
) -> InsightRow:
    ad_id = _required_text(payload, "ad_id")
    ad_set_id = _text(payload.get("adset_id"))
    actions = _action_values(payload.get("actions"))
    action_values = _action_values(payload.get("action_values"))
    conversions = sum(
        (value for key, value in actions.items() if key in conversion_action_types),
        Decimal("0"),
    )
    leads = sum(
        (value for key, value in actions.items() if "lead" in key.lower()),
        Decimal("0"),
    )
    revenue = sum(
        (value for key, value in action_values.items() if key in value_action_types),
        Decimal("0"),
    )
    dimensions = _dimensions(payload)
    dimensions["_query_scope"] = query_scope
    date_start = _required_date(payload, "date_start")
    dimensions.setdefault("day", date_start.strftime("%A"))
    return InsightRow(
        row_id=_insight_id(payload, dimensions),
        account_id=account.provider_id,
        entity_type=AdEntityType.AD,
        entity_id=ad_id,
        entity_name=_text(payload.get("ad_name")) or ad_id,
        currency=account.currency,
        attribution_window=attribution_window,
        campaign_id=_text(payload.get("campaign_id")),
        ad_set_id=ad_set_id,
        ad_id=ad_id,
        creative_id=creative_by_ad.get(ad_id),
        audience_id=audience_by_ad_set.get(ad_set_id or ""),
        date_start=date_start,
        date_stop=_required_date(payload, "date_stop"),
        dimensions=dimensions,
        metrics=build_metrics(
            spend=_decimal(payload.get("spend")),
            impressions=_decimal(payload.get("impressions")),
            reach=_decimal(payload.get("reach")),
            clicks=_decimal(payload.get("clicks")),
            link_clicks=_decimal(payload.get("inline_link_clicks")),
            conversions=conversions,
            leads=leads,
            revenue=revenue if action_values else None,
        ),
    )


def _provider_diagnostic(item: MetaRequestDiagnostic) -> ProviderDiagnostic:
    return ProviderDiagnostic(
        request_id=item.request_id,
        operation=item.operation,
        status_code=item.status_code,
        retry_count=item.retry_count,
        rate_limit_observed=item.rate_limit_observed,
        rate_limit_usage_percent=item.rate_limit_usage_percent,
        retry_after_seconds=item.retry_after_seconds,
        duration_ms=item.duration_ms,
        message=item.message,
    )


def _observability(
    snapshot: AdsSnapshot,
    budget: MetaRequestBudgetSnapshot,
) -> ProviderObservability:
    unavailable_metrics = sum(
        metric.availability is DataAvailability.UNAVAILABLE
        for row in snapshot.insights
        for metric in (
            row.metrics.spend,
            row.metrics.impressions,
            row.metrics.reach,
            row.metrics.clicks,
            row.metrics.link_clicks,
            row.metrics.conversions,
            row.metrics.leads,
            row.metrics.revenue,
            row.metrics.ctr,
            row.metrics.cpc,
            row.metrics.cpm,
            row.metrics.cpl,
            row.metrics.cpa,
            row.metrics.roas,
            row.metrics.frequency,
        )
    )
    freshest = max((row.date_stop for row in snapshot.insights), default=None)
    return ProviderObservability(
        request_count=budget.requests_used,
        successful_requests=sum(
            item.status_code is not None and 200 <= item.status_code < 300
            for item in snapshot.diagnostics
        ),
        transient_errors=sum(
            item.status_code == 429
            or (item.status_code is not None and item.status_code >= 500)
            or item.message in {"ReadTimeout", "ConnectTimeout", "TransportError"}
            for item in snapshot.diagnostics
        ),
        permanent_errors=sum(
            item.status_code is not None
            and 400 <= item.status_code < 500
            and item.status_code != 429
            for item in snapshot.diagnostics
        ),
        rate_limit_events=sum(item.status_code == 429 for item in snapshot.diagnostics),
        request_duration_ms=sum(item.duration_ms or 0 for item in snapshot.diagnostics),
        pages_fetched=budget.pages_fetched,
        rows_normalized=(
            len(snapshot.accounts)
            + len(snapshot.campaigns)
            + len(snapshot.ad_sets)
            + len(snapshot.ads)
            + len(snapshot.creatives)
            + len(snapshot.audiences)
            + len(snapshot.insights)
        ),
        duplicate_rows_rejected=budget.duplicate_rows_rejected,
        unavailable_metrics=unavailable_metrics,
        data_freshness_days=(date.today() - freshest).days if freshest is not None else None,
    )


def _normalize_state(
    payload: dict[str, JsonValue],
    object_type: str,
    provider: str,
    *,
    currency: str | None = None,
    minimum_daily_budget: Decimal | None = None,
) -> ProviderObjectState:
    safe: dict[str, JsonValue] = {
        key: value
        for key in [
            "id",
            "account_id",
            "status",
            "effective_status",
            "daily_budget",
            "lifetime_budget",
            "updated_time",
        ]
        if (value := payload.get(key)) is not None
    }
    if currency is not None:
        safe["currency"] = currency
    if minimum_daily_budget is not None:
        safe["minimum_daily_budget"] = str(minimum_daily_budget)
    serialized = json.dumps(safe, sort_keys=True, separators=(",", ":"))
    return ProviderObjectState(
        provider=provider,
        object_type=_entity_type(object_type),
        provider_object_id=_required_text(payload, "id"),
        status=_text(payload.get("status")) or _text(payload.get("effective_status")) or "UNKNOWN",
        daily_budget=_minor_money(payload.get("daily_budget")),
        currency=currency,
        updated_at=_datetime(payload.get("updated_time")),
        state_hash=hashlib.sha256(serialized.encode()).hexdigest(),
        raw_safe=safe,
    )


def _entity_type(value: str) -> AdEntityType:
    normalized = "ad_set" if value == "adset" else value
    return AdEntityType(normalized)


def _dimensions(payload: dict[str, JsonValue]) -> dict[str, str]:
    dimensions: dict[str, str] = {}
    publisher = _text(payload.get("publisher_platform"))
    position = _text(payload.get("platform_position"))
    if publisher or position:
        dimensions["placement"] = ":".join(item for item in [publisher, position] if item)
    for provider_key, internal_key in [
        ("region", "region"),
        ("age", "age"),
        ("gender", "gender"),
        ("hourly_stats_aggregated_by_advertiser_time_zone", "hour"),
    ]:
        if (value := _text(payload.get(provider_key))) is not None:
            dimensions[internal_key] = value
    return dimensions


def _action_values(value: JsonValue | None) -> dict[str, Decimal]:
    result: dict[str, Decimal] = {}
    if not isinstance(value, list):
        return result
    for item in value:
        if not isinstance(item, dict):
            continue
        action_type = _text(item.get("action_type"))
        amount = _decimal(item.get("value"))
        if action_type is not None and amount is not None:
            result[action_type] = result.get(action_type, Decimal("0")) + amount
    return result


def _audience_by_ad_set(payloads: Iterable[dict[str, JsonValue]]) -> dict[str, str]:
    result: dict[str, str] = {}
    for payload in payloads:
        ad_set_id = _text(payload.get("id"))
        targeting = payload.get("targeting")
        if ad_set_id is None or not isinstance(targeting, dict):
            continue
        custom_audiences = targeting.get("custom_audiences")
        if not isinstance(custom_audiences, list):
            continue
        audience = next((item for item in custom_audiences if isinstance(item, dict)), None)
        if audience is not None and (audience_id := _text(audience.get("id"))) is not None:
            result[ad_set_id] = audience_id
    return result


def _creative_by_ad(payloads: Iterable[dict[str, JsonValue]]) -> dict[str, str]:
    result: dict[str, str] = {}
    for payload in payloads:
        ad_id = _text(payload.get("id"))
        creative = payload.get("creative")
        if ad_id is not None and isinstance(creative, dict):
            creative_id = _text(creative.get("id"))
            if creative_id is not None:
                result[ad_id] = creative_id
    return result


def _extend_targeting_attributes(
    target: dict[str, set[str]],
    payloads: Iterable[dict[str, JsonValue]],
) -> None:
    for payload in payloads:
        targeting = payload.get("targeting")
        if not isinstance(targeting, dict):
            continue
        for key, value in targeting.items():
            serialized = json.dumps(value, sort_keys=True, separators=(",", ":"))
            target.setdefault(str(key), set()).add(serialized)


def _deduplicate_insights(rows: Iterable[InsightRow]) -> list[InsightRow]:
    result: list[InsightRow] = []
    seen: set[str] = set()
    for row in rows:
        if row.row_id not in seen:
            seen.add(row.row_id)
            result.append(row)
    return result


def _insight_id(payload: dict[str, JsonValue], dimensions: dict[str, str]) -> str:
    source = json.dumps(
        {
            "ad_id": payload.get("ad_id"),
            "date_start": payload.get("date_start"),
            "date_stop": payload.get("date_stop"),
            "dimensions": dimensions,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(source.encode()).hexdigest()


def _safe_attributes(
    payload: dict[str, JsonValue],
    keys: set[str],
) -> dict[str, JsonValue]:
    return {key: value for key in keys if (value := payload.get(key)) is not None}


def _required_text(payload: dict[str, JsonValue], key: str) -> str:
    value = _text(payload.get(key))
    if value is None:
        raise ValueError(f"Meta payload is missing required field {key!r}")
    return value


def _text(value: JsonValue | None) -> str | None:
    if isinstance(value, str | int | float):
        return str(value)
    return None


def _decimal(value: JsonValue | None) -> Decimal | None:
    text = _text(value)
    if text is None:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _minor_money(value: JsonValue | None) -> Decimal | None:
    amount = _decimal(value)
    return amount / Decimal("100") if amount is not None else None


def _datetime(value: JsonValue | None) -> datetime | None:
    text = _text(value)
    if text is None:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _required_date(payload: dict[str, JsonValue], key: str) -> date:
    text = _required_text(payload, key)
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"Meta payload contains invalid {key!r}") from exc


def _nested_status(value: JsonValue | None) -> str:
    if isinstance(value, dict):
        return _text(value.get("code")) or _text(value.get("description")) or "UNKNOWN"
    return _text(value) or "UNKNOWN"
