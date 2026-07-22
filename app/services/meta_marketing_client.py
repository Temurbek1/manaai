import asyncio
import hashlib
import json
import logging
import re
import time
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import date
from typing import cast
from uuid import uuid4

import httpx
from pydantic import JsonValue

from app.core.config import Settings
from app.schemas.marketing import MetaInsightLevel

logger = logging.getLogger(__name__)


class MetaMarketingError(RuntimeError):
    """Raised when Meta Marketing API integration fails."""


class MetaConfigurationError(MetaMarketingError):
    """Raised when Meta Marketing API credentials are not configured."""


class MetaAPIError(MetaMarketingError):
    """Raised when Meta Marketing API returns an unsuccessful response."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        code: int | None = None,
        subcode: int | None = None,
        is_transient: bool = False,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.subcode = subcode
        self.is_transient = is_transient
        self.request_id = request_id


class MetaTransientAPIError(MetaAPIError):
    """Raised for an explicitly retryable Meta response."""


class MetaPermissionError(MetaAPIError):
    """Raised when the token lacks the required Meta permission."""


class MetaAuthenticationError(MetaAPIError):
    """Raised when Meta rejects the access token."""


class MetaObjectNotFoundError(MetaAPIError):
    """Raised when Meta reports that a requested object is unavailable."""


class MetaReadOnlyViolation(MetaMarketingError):
    """Raised before any non-GET Meta request can reach the network."""


class MetaPaginationLimitError(MetaAPIError):
    """Raised instead of silently accepting a truncated paginated response."""


class MetaRequestBudgetExceeded(MetaMarketingError):
    """Raised before a live run can exceed its request, retry, page, or time budget."""


@dataclass(frozen=True, slots=True)
class MetaRequestDiagnostic:
    operation: str
    request_id: str | None
    status_code: int | None
    retry_count: int
    rate_limit_observed: bool
    rate_limit_usage_percent: int | None = None
    retry_after_seconds: int | None = None
    duration_ms: int | None = None
    message: str | None = None


@dataclass(frozen=True, slots=True)
class MetaRequestBudgetSnapshot:
    correlation_id: str
    max_requests: int
    max_duration_seconds: int
    max_total_retries: int
    max_pages: int
    requests_used: int
    retries_used: int
    pages_fetched: int
    rows_received: int
    duplicate_rows_rejected: int
    elapsed_ms: int
    cancelled: bool
    run_id: str | None = None


@dataclass(slots=True)
class MetaRequestBudgetTracker:
    max_requests: int
    max_duration_seconds: int
    max_total_retries: int
    max_pages: int
    correlation_id: str = field(default_factory=lambda: str(uuid4()))
    run_id: str | None = None
    requests_used: int = 0
    retries_used: int = 0
    pages_fetched: int = 0
    rows_received: int = 0
    duplicate_rows_rejected: int = 0
    cancelled: bool = False
    started_at: float = field(default_factory=time.monotonic)

    def reserve_request(self, retry_count: int) -> None:
        self._require_active()
        if self.requests_used >= self.max_requests:
            raise MetaRequestBudgetExceeded("Meta live request-count budget was exhausted")
        if retry_count > 0:
            if self.retries_used >= self.max_total_retries:
                raise MetaRequestBudgetExceeded("Meta live retry budget was exhausted")
            self.retries_used += 1
        self.requests_used += 1

    def reserve_page(self) -> None:
        self._require_active()
        if self.pages_fetched >= self.max_pages:
            raise MetaRequestBudgetExceeded("Meta live page budget was exhausted")
        self.pages_fetched += 1

    def record_page_rows(self, *, rows: int, duplicates: int) -> None:
        self.rows_received += rows
        self.duplicate_rows_rejected += duplicates

    def cancel(self) -> None:
        self.cancelled = True

    def snapshot(self) -> MetaRequestBudgetSnapshot:
        return MetaRequestBudgetSnapshot(
            correlation_id=self.correlation_id,
            max_requests=self.max_requests,
            max_duration_seconds=self.max_duration_seconds,
            max_total_retries=self.max_total_retries,
            max_pages=self.max_pages,
            requests_used=self.requests_used,
            retries_used=self.retries_used,
            pages_fetched=self.pages_fetched,
            rows_received=self.rows_received,
            duplicate_rows_rejected=self.duplicate_rows_rejected,
            elapsed_ms=max(int((time.monotonic() - self.started_at) * 1_000), 0),
            cancelled=self.cancelled,
            run_id=self.run_id,
        )

    def _require_active(self) -> None:
        if self.cancelled:
            raise MetaRequestBudgetExceeded("Meta live request budget was cancelled")
        if time.monotonic() - self.started_at > self.max_duration_seconds:
            raise MetaRequestBudgetExceeded("Meta live duration budget was exhausted")


class MetaMarketingClient:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._transport = transport
        self._diagnostics: list[MetaRequestDiagnostic] = []
        self._budget_context: ContextVar[MetaRequestBudgetTracker | None] = ContextVar(
            f"meta_request_budget_{id(self)}",
            default=None,
        )
        self._last_budget: MetaRequestBudgetSnapshot | None = None

    @property
    def api_version(self) -> str:
        return self._settings.meta_graph_api_version

    def consume_diagnostics(self) -> list[MetaRequestDiagnostic]:
        diagnostics = list(self._diagnostics)
        self._diagnostics.clear()
        return diagnostics

    @property
    def last_request_budget(self) -> MetaRequestBudgetSnapshot | None:
        return self._last_budget

    @asynccontextmanager
    async def request_budget(
        self,
        *,
        run_id: str | None = None,
        correlation_id: str | None = None,
    ) -> AsyncIterator[MetaRequestBudgetTracker]:
        current = self._budget_context.get()
        if current is not None:
            yield current
            return
        tracker = MetaRequestBudgetTracker(
            max_requests=self._settings.meta_live_max_requests,
            max_duration_seconds=self._settings.meta_live_max_duration_seconds,
            max_total_retries=self._settings.meta_live_max_total_retries,
            max_pages=self._settings.meta_live_max_pages,
            correlation_id=correlation_id or str(uuid4()),
            run_id=run_id,
        )
        token = self._budget_context.set(tracker)
        try:
            yield tracker
        finally:
            self._last_budget = tracker.snapshot()
            self._budget_context.reset(token)

    def cancel_active_run(self) -> bool:
        tracker = self._budget_context.get()
        if tracker is None:
            return False
        tracker.cancel()
        return True

    async def fetch_app(self) -> dict[str, JsonValue] | None:
        if not self._settings.meta_app_id:
            return None
        return await self._get_object(
            self._settings.meta_app_id,
            fields=["id", "name", "namespace", "category", "link", "app_domains"],
        )

    async def fetch_token_debug(self) -> dict[str, JsonValue]:
        token = self._get_access_token()
        return await self._get_json(
            "debug_token",
            params={"input_token": token},
        )

    async def fetch_business(self) -> dict[str, JsonValue] | None:
        if not self._settings.meta_business_id:
            return None
        return await self._get_object(
            self._settings.meta_business_id,
            fields=self._settings.meta_business_fields,
        )

    async def fetch_business_owned_pixels(self) -> list[dict[str, JsonValue]]:
        if not self._settings.meta_business_id:
            return []
        return await self._get_paginated(
            f"{self._settings.meta_business_id}/owned_pixels",
            params={"fields": ",".join(self._settings.meta_pixel_fields)},
        )

    async def fetch_configured_ad_accounts(self) -> list[dict[str, JsonValue]]:
        if self._settings.meta_ad_account_ids:
            return [
                await self._get_object(
                    normalize_ad_account_id(account_id),
                    fields=self._settings.meta_ad_account_fields,
                )
                for account_id in self._settings.meta_ad_account_ids
            ]

        if self._settings.meta_business_id:
            owned = await self._get_paginated(
                f"{self._settings.meta_business_id}/owned_ad_accounts",
                params={"fields": ",".join(self._settings.meta_ad_account_fields)},
            )
            client = await self._get_paginated(
                f"{self._settings.meta_business_id}/client_ad_accounts",
                params={"fields": ",".join(self._settings.meta_ad_account_fields)},
            )
            return _dedupe_by_id([*owned, *client])

        return await self._get_paginated(
            "me/adaccounts",
            params={"fields": ",".join(self._settings.meta_ad_account_fields)},
        )

    async def fetch_ad_account(self, account_id: str) -> dict[str, JsonValue]:
        return await self._get_object(
            normalize_ad_account_id(account_id),
            fields=self._settings.meta_ad_account_fields,
        )

    async def fetch_campaigns(self, account_id: str) -> list[dict[str, JsonValue]]:
        return await self._get_paginated(
            f"{normalize_ad_account_id(account_id)}/campaigns",
            params={"fields": ",".join(self._settings.meta_campaign_fields)},
        )

    async def fetch_adsets(self, account_id: str) -> list[dict[str, JsonValue]]:
        return await self._get_paginated(
            f"{normalize_ad_account_id(account_id)}/adsets",
            params={"fields": ",".join(self._settings.meta_adset_fields)},
        )

    async def fetch_ads(self, account_id: str) -> list[dict[str, JsonValue]]:
        return await self._get_paginated(
            f"{normalize_ad_account_id(account_id)}/ads",
            params={"fields": ",".join(self._settings.meta_ad_fields)},
        )

    async def fetch_ad_creatives(self, account_id: str) -> list[dict[str, JsonValue]]:
        return await self._get_paginated(
            f"{normalize_ad_account_id(account_id)}/adcreatives",
            params={"fields": ",".join(self._settings.meta_creative_fields)},
        )

    async def fetch_custom_conversions(self, account_id: str) -> list[dict[str, JsonValue]]:
        return await self._get_paginated(
            f"{normalize_ad_account_id(account_id)}/customconversions",
            params={"fields": ",".join(self._settings.meta_custom_conversion_fields)},
        )

    async def fetch_custom_audiences(self, account_id: str) -> list[dict[str, JsonValue]]:
        return await self._get_paginated(
            f"{normalize_ad_account_id(account_id)}/customaudiences",
            params={"fields": ",".join(self._settings.meta_custom_audience_fields)},
        )

    async def fetch_insights(
        self,
        *,
        account_id: str,
        level: MetaInsightLevel,
        date_start: date,
        date_stop: date,
        breakdowns: list[str] | None = None,
        action_breakdowns: list[str] | None = None,
        time_increment: int | str = 1,
        attribution_windows: list[str] | None = None,
    ) -> list[dict[str, JsonValue]]:
        params = {
            "fields": ",".join(self._settings.meta_insights_fields),
            "level": level,
            "time_increment": str(time_increment),
            "time_range": json.dumps(
                {
                    "since": date_start.isoformat(),
                    "until": date_stop.isoformat(),
                },
                separators=(",", ":"),
            ),
            "action_attribution_windows": json.dumps(
                attribution_windows or self._settings.meta_action_attribution_windows,
                separators=(",", ":"),
            ),
        }
        if breakdowns:
            params["breakdowns"] = ",".join(breakdowns)
        if action_breakdowns:
            params["action_breakdowns"] = ",".join(action_breakdowns)

        return await self._get_paginated(
            f"{normalize_ad_account_id(account_id)}/insights",
            params=params,
        )

    async def create_insights_async_job(
        self,
        *,
        account_id: str,
        level: MetaInsightLevel,
        date_start: date,
        date_stop: date,
        fields: list[str] | None = None,
        breakdowns: list[str] | None = None,
        action_breakdowns: list[str] | None = None,
        time_increment: int | str = 1,
    ) -> dict[str, JsonValue]:
        params: dict[str, str] = {
            "fields": ",".join(fields or self._settings.meta_insights_fields),
            "level": level,
            "time_increment": str(time_increment),
            "time_range": json.dumps(
                {
                    "since": date_start.isoformat(),
                    "until": date_stop.isoformat(),
                },
                separators=(",", ":"),
            ),
            "action_attribution_windows": json.dumps(
                self._settings.meta_action_attribution_windows,
                separators=(",", ":"),
            ),
            "async": "true",
        }
        if breakdowns:
            params["breakdowns"] = ",".join(breakdowns)
        if action_breakdowns:
            params["action_breakdowns"] = ",".join(action_breakdowns)

        return await self._post_json(
            f"{normalize_ad_account_id(account_id)}/insights",
            params=params,
        )

    async def fetch_insights_async_job_status(
        self,
        report_run_id: str,
    ) -> dict[str, JsonValue]:
        return await self._get_object(
            report_run_id,
            fields=[
                "id",
                "async_status",
                "async_percent_completion",
                "date_start",
                "date_stop",
            ],
        )

    async def fetch_insights_async_job_results(
        self,
        *,
        report_run_id: str,
        fields: list[str] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, JsonValue]]:
        params = {
            "fields": ",".join(fields or self._settings.meta_insights_fields),
            "limit": str(limit or self._settings.meta_page_limit),
        }
        return await self._get_paginated(f"{report_run_id}/insights", params=params)

    async def fetch_object_state(self, provider_object_id: str) -> dict[str, JsonValue]:
        return await self._get_object(
            provider_object_id,
            fields=[
                "id",
                "account_id",
                "status",
                "effective_status",
                "daily_budget",
                "lifetime_budget",
                "updated_time",
            ],
        )

    async def _get_object(
        self,
        path: str,
        *,
        fields: list[str],
    ) -> dict[str, JsonValue]:
        payload = await self._get_json(path, params={"fields": ",".join(fields)})
        return payload

    async def _get_paginated(
        self,
        path: str,
        *,
        params: Mapping[str, str],
    ) -> list[dict[str, JsonValue]]:
        async with self.request_budget() as budget:
            items: list[dict[str, JsonValue]] = []
            seen: set[str] = set()
            next_url: str | None = self._build_url(path)
            next_params: dict[str, str] | None = {
                **dict(params),
                "limit": str(self._settings.meta_page_limit),
                "access_token": self._get_access_token(),
            }

            async with httpx.AsyncClient(
                timeout=self._settings.meta_request_timeout_seconds,
                transport=self._transport,
            ) as client:
                for _ in range(min(self._settings.meta_max_pages, budget.max_pages)):
                    if next_url is None:
                        break
                    budget.reserve_page()
                    payload = await self._request_json(
                        client,
                        "GET",
                        next_url,
                        params=next_params,
                        operation=_sanitized_operation(path),
                    )
                    data = payload.get("data", [])
                    page_items = cast(
                        list[dict[str, JsonValue]],
                        [item for item in data if isinstance(item, dict)]
                        if isinstance(data, list)
                        else [],
                    )
                    duplicate_count = 0
                    for item in page_items:
                        key = _payload_key(item)
                        if key in seen:
                            duplicate_count += 1
                            continue
                        seen.add(key)
                        items.append(item)
                    budget.record_page_rows(
                        rows=len(page_items),
                        duplicates=duplicate_count,
                    )

                    paging = payload.get("paging", {})
                    next_url = (
                        str(paging.get("next"))
                        if isinstance(paging, dict) and paging.get("next") is not None
                        else None
                    )
                    next_params = None

            if next_url is not None:
                self._diagnostics.append(
                    MetaRequestDiagnostic(
                        operation=_sanitized_operation(path),
                        request_id=None,
                        status_code=None,
                        retry_count=0,
                        rate_limit_observed=False,
                        message="pagination_limit_exceeded",
                    ),
                )
                raise MetaPaginationLimitError(
                    "Meta pagination exceeded the configured page safety limit",
                )

            return sorted(items, key=_payload_key)

    async def _get_json(
        self,
        path: str,
        *,
        params: Mapping[str, str],
    ) -> dict[str, JsonValue]:
        async with self.request_budget():
            request_params = {
                **dict(params),
                "access_token": self._get_access_token(),
            }
            async with httpx.AsyncClient(
                timeout=self._settings.meta_request_timeout_seconds,
                transport=self._transport,
            ) as client:
                return await self._request_json(
                    client,
                    "GET",
                    self._build_url(path),
                    params=request_params,
                    operation=_sanitized_operation(path),
                )

    async def _post_json(
        self,
        path: str,
        *,
        params: Mapping[str, str],
    ) -> dict[str, JsonValue]:
        del path, params
        raise MetaReadOnlyViolation(
            "META_LIVE_MODE=read_only forbids every Meta POST request",
        )

    async def _request_json(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        data: Mapping[str, str] | None = None,
        operation: str,
    ) -> dict[str, JsonValue]:
        budget = self._budget_context.get()
        if budget is None:
            raise MetaRequestBudgetExceeded("Meta request has no active live-run budget")
        for retry_count in range(self._settings.meta_max_retries + 1):
            budget.reserve_request(retry_count)
            started_at = time.monotonic()
            try:
                response = await client.request(method, url, params=params, data=data)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                duration_ms = max(int((time.monotonic() - started_at) * 1_000), 0)
                self._diagnostics.append(
                    MetaRequestDiagnostic(
                        operation=operation,
                        request_id=None,
                        status_code=None,
                        retry_count=retry_count,
                        rate_limit_observed=False,
                        duration_ms=duration_ms,
                        message=type(exc).__name__,
                    ),
                )
                _log_request(
                    budget=budget,
                    api_version=self.api_version,
                    operation=operation,
                    status_code=None,
                    duration_ms=duration_ms,
                    retry_count=retry_count,
                    error_class=type(exc).__name__,
                )
                if retry_count >= self._settings.meta_max_retries:
                    raise MetaTransientAPIError(
                        "Meta API request failed after retries",
                        is_transient=True,
                    ) from exc
                await self._backoff(retry_count)
                continue

            request_id = response.headers.get("x-fb-request-id") or response.headers.get(
                "x-fb-trace-id",
            )
            duration_ms = max(int((time.monotonic() - started_at) * 1_000), 0)
            rate_limit_usage = _rate_limit_usage_percent(response.headers)
            rate_limited = response.status_code == 429 or rate_limit_usage is not None
            retryable = self._is_retryable_response(response)
            self._diagnostics.append(
                MetaRequestDiagnostic(
                    operation=operation,
                    request_id=request_id,
                    status_code=response.status_code,
                    retry_count=retry_count,
                    rate_limit_observed=rate_limited,
                    rate_limit_usage_percent=rate_limit_usage,
                    retry_after_seconds=_header_int(response.headers, "retry-after"),
                    duration_ms=duration_ms,
                ),
            )
            _log_request(
                budget=budget,
                api_version=self.api_version,
                operation=operation,
                status_code=response.status_code,
                duration_ms=duration_ms,
                retry_count=retry_count,
                error_class=_response_error_class(response),
            )
            if retryable and retry_count < self._settings.meta_max_retries:
                await self._backoff(retry_count)
                continue
            return self._parse_response(response, request_id=request_id)
        raise MetaTransientAPIError(
            "Meta API request failed after retries",
            is_transient=True,
        )

    async def _backoff(self, retry_count: int) -> None:
        delay = self._settings.meta_retry_backoff_seconds * (2**retry_count)
        await asyncio.sleep(delay)

    @staticmethod
    def _is_retryable_response(response: httpx.Response) -> bool:
        if response.status_code in {429, 500, 502, 503, 504}:
            return True
        try:
            payload = response.json()
        except ValueError:
            return False
        error = payload.get("error") if isinstance(payload, dict) else None
        code = error.get("code") if isinstance(error, dict) else None
        is_transient = error.get("is_transient") is True if isinstance(error, dict) else False
        return is_transient or code in {1, 2, 4, 17, 32, 613}

    def _parse_response(
        self,
        response: httpx.Response,
        *,
        request_id: str | None,
    ) -> dict[str, JsonValue]:
        try:
            payload = cast(dict[str, JsonValue], response.json())
        except ValueError as exc:
            malformed_response_error = (
                MetaTransientAPIError if response.status_code >= 500 else MetaAPIError
            )
            raise malformed_response_error(
                "Meta API returned a non-JSON response",
                status_code=response.status_code,
                is_transient=response.status_code >= 500,
                request_id=request_id,
            ) from exc

        if response.is_error:
            error_payload = payload.get("error", {})
            message = "Meta API request failed"
            code: int | None = None
            subcode: int | None = None
            is_transient = False
            if isinstance(error_payload, dict):
                if error_payload.get("message") is not None:
                    message = str(error_payload["message"])
                code = _optional_int(error_payload.get("code"))
                subcode = _optional_int(error_payload.get("error_subcode"))
                is_transient = error_payload.get("is_transient") is True
            error_type: type[MetaAPIError]
            if code in {102, 190}:
                error_type = MetaAuthenticationError
            elif code in {10, 200, 294}:
                error_type = MetaPermissionError
            elif code == 100 and subcode == 33:
                error_type = MetaObjectNotFoundError
            elif is_transient or response.status_code in {429, 500, 502, 503, 504}:
                error_type = MetaTransientAPIError
                is_transient = True
            else:
                error_type = MetaAPIError
            raise error_type(
                message,
                status_code=response.status_code,
                code=code,
                subcode=subcode,
                is_transient=is_transient,
                request_id=request_id,
            )

        return payload

    def _build_url(self, path: str) -> str:
        base_url = self._settings.meta_graph_base_url.rstrip("/")
        version = self._settings.meta_graph_api_version.strip("/")
        normalized_path = path.strip("/")
        return f"{base_url}/{version}/{normalized_path}"

    def _get_access_token(self) -> str:
        if self._settings.meta_access_token is None:
            raise MetaConfigurationError("META_ACCESS_TOKEN is not configured")
        token = self._settings.meta_access_token.get_secret_value()
        if not token:
            raise MetaConfigurationError("META_ACCESS_TOKEN is empty")
        return token


def normalize_ad_account_id(account_id: str) -> str:
    value = account_id.strip()
    return value if value.startswith("act_") else f"act_{value}"


def _sanitized_operation(path: str) -> str:
    normalized = path.strip("/")
    if normalized == "debug_token":
        return "GET token/debug"
    parts = normalized.split("/")
    resource = parts[-1] if len(parts) > 1 else "object"
    if parts[0].startswith("act_"):
        alias = hashlib.sha256(parts[0].encode()).hexdigest()[:10]
        return f"GET ad_account[{alias}]/{resource}"
    known_resources = {
        "adaccounts",
        "ads",
        "adcreatives",
        "adsets",
        "campaigns",
        "client_ad_accounts",
        "customaudiences",
        "customconversions",
        "insights",
        "owned_ad_accounts",
        "owned_pixels",
    }
    if resource in known_resources:
        return f"GET graph_object/{resource}"
    return "GET graph_object"


def _response_error_class(response: httpx.Response) -> str | None:
    if response.status_code < 400:
        return None
    if response.status_code in {401, 403}:
        return "authentication_or_permission"
    if response.status_code == 429:
        return "rate_limit"
    if response.status_code >= 500:
        return "provider_transient"
    return "provider_permanent"


def _log_request(
    *,
    budget: MetaRequestBudgetTracker,
    api_version: str,
    operation: str,
    status_code: int | None,
    duration_ms: int,
    retry_count: int,
    error_class: str | None,
) -> None:
    account_alias_match = re.search(r"ad_account\[([a-f0-9]+)\]", operation)
    logger.info(
        "meta_read_request",
        extra={
            "meta_correlation_id": budget.correlation_id,
            "meta_run_id": budget.run_id,
            "meta_account_alias": (
                account_alias_match.group(1) if account_alias_match is not None else None
            ),
            "meta_api_version": api_version,
            "meta_operation": operation,
            "meta_status_code": status_code,
            "meta_duration_ms": duration_ms,
            "meta_retry_count": retry_count,
            "meta_error_class": error_class,
        },
    )


def _payload_key(payload: dict[str, JsonValue]) -> str:
    identifier = payload.get("id")
    if identifier is not None:
        return f"id:{identifier}"
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _rate_limit_usage_percent(headers: httpx.Headers) -> int | None:
    values: list[int] = []
    for name in (
        "x-business-use-case-usage",
        "x-app-usage",
        "x-ad-account-usage",
        "x-fb-ads-insights-throttle",
    ):
        raw = headers.get(name)
        if raw is None:
            continue
        try:
            payload: object = json.loads(raw)
        except ValueError:
            continue
        _collect_usage_percentages(payload, values)
    return max(values) if values else None


def _collect_usage_percentages(payload: object, values: list[int]) -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in {"call_count", "total_cputime", "total_time", "acc_id_util_pct"}:
                parsed = _optional_int(cast(JsonValue, value))
                if parsed is not None and parsed >= 0:
                    values.append(parsed)
            else:
                _collect_usage_percentages(value, values)
    elif isinstance(payload, list):
        for item in payload:
            _collect_usage_percentages(item, values)


def _header_int(headers: httpx.Headers, name: str) -> int | None:
    raw = headers.get(name)
    if raw is None:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value >= 0 else None


def _dedupe_by_id(items: list[dict[str, JsonValue]]) -> list[dict[str, JsonValue]]:
    result: list[dict[str, JsonValue]] = []
    seen: set[str] = set()
    for item in items:
        item_id = item.get("id")
        if item_id is None:
            result.append(item)
            continue
        item_id_str = str(item_id)
        if item_id_str in seen:
            continue
        seen.add(item_id_str)
        result.append(item)
    return result


def _optional_int(value: JsonValue | None) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None
