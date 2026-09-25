import asyncio
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError

from app.mana_operation_ai.application.ports import (
    Clock,
    ProviderPermanentError,
    ProviderTransientError,
)
from app.mana_operation_ai.domain.enums import IntegrationStatus
from app.mana_operation_ai.domain.models import IntegrationHealth
from app.mana_operation_ai.domain.retention import BackendActivityFacts

_AUTH_PATH = "/api/v1/admin-panel-auth/login/"
_ACCOUNT_PATH = "/api/v1/admin-panel-common/account/"
_CHILD_LIST_PATH = "/api/v1/admin-panel-child/child-list/"
_APP_USAGE_PATH = "/api/v1/admin-panel-child/app-usage-statistics/"
_REALTIME_USAGE_PATH = "/api/v1/admin-panel-child/camera-audio-usage-logs/"
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


class _LoginResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    access_token: str = Field(
        min_length=1,
        validation_alias=AliasChoices("access", "token", "access_token"),
    )


class _PageEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore")

    count: int | None = Field(
        default=None,
        ge=0,
        validation_alias=AliasChoices("count", "total", "total_count"),
    )
    results: list[dict[str, Any]] = Field(
        default_factory=list,
        validation_alias=AliasChoices("results", "data", "items"),
    )
    current_page: int | None = Field(default=None, ge=1)
    page_count: int | None = Field(default=None, ge=0)
    per_page: int | None = Field(default=None, ge=1)


class _EmbeddedActivityPage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    count: int | None = Field(
        default=None,
        ge=0,
        validation_alias=AliasChoices("count", "total", "total_count"),
    )
    results: list[Any] = Field(default_factory=list)


class _AppUsageRow(BaseModel):
    model_config = ConfigDict(extra="ignore")

    app_usage_statistics: _EmbeddedActivityPage


class _RealtimeUsageRow(BaseModel):
    model_config = ConfigDict(extra="ignore")

    camera_audio_usage_logs: list[Any]


@dataclass(frozen=True)
class _CountResult:
    count: int
    rows_scanned: int
    total_rows: int | None
    request_ids: list[str]
    complete: bool

    @property
    def completeness(self) -> Decimal:
        if self.complete:
            return Decimal("1")
        if self.total_rows is None or self.total_rows == 0:
            return Decimal("0")
        return min(Decimal(self.rows_scanned) / Decimal(self.total_rows), Decimal("1"))


class ManakidsAdminActivityAdapter:
    """Read-only Admin API adapter that emits aggregate facts and discards response rows."""

    integration_id = "manakids_admin_api"

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        base_url: str,
        username: str,
        password: str,
        clock: Clock,
        max_retries: int,
        retry_backoff_seconds: float,
        max_pages: int,
    ) -> None:
        self._client = client
        self._base_url = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._clock = clock
        self._max_retries = max_retries
        self._retry_backoff_seconds = retry_backoff_seconds
        self._max_pages = max_pages
        self._access_token: str | None = None
        self._auth_lock = asyncio.Lock()

    async def collect_activity(
        self,
        *,
        period_start: datetime,
        period_end: datetime,
    ) -> BackendActivityFacts:
        if period_end <= period_start:
            raise ValueError("Activity period end must be after its start")
        joined_params: dict[str, str | int] = {
            "date_joined_gte": period_start.date().isoformat(),
            "date_joined_lt": (period_end.date() + timedelta(days=1)).isoformat(),
            "limit": 1,
            "offset": 0,
        }
        activity_params: dict[str, str | int] = {
            "start_date": period_start.date().isoformat(),
            "end_date": period_end.date().isoformat(),
            "page": 1,
        }
        (
            (parents, parent_request_id),
            (children, child_request_id),
            (
                inventory,
                inventory_request_id,
            ),
            app_usage,
            realtime_usage,
        ) = await asyncio.gather(
            self._get_page(
                _ACCOUNT_PATH,
                params={**joined_params, "role": "PARENT"},
                require_count=True,
            ),
            self._get_page(
                _ACCOUNT_PATH,
                params={**joined_params, "role": "CHILD"},
                require_count=True,
            ),
            self._get_page(
                _CHILD_LIST_PATH,
                params={"limit": 1, "offset": 0},
                require_count=True,
            ),
            self._count_activity_rows(
                _APP_USAGE_PATH,
                params=activity_params,
                row_has_activity=_row_has_app_usage,
            ),
            self._count_activity_rows(
                _REALTIME_USAGE_PATH,
                params=activity_params,
                row_has_activity=_row_has_realtime_usage,
            ),
        )
        limitations = [
            "The documented backend endpoints expose child-level rows; this adapter persists "
            "only aggregate result counts.",
            "Account registration filters are date-granular and include the complete boundary "
            "calendar days.",
            "App usage and camera/audio/screen activity are not deduplicated across endpoints.",
        ]
        limitations.extend(
            _partial_scan_limitations(
                app_usage=app_usage,
                realtime_usage=realtime_usage,
            ),
        )
        return BackendActivityFacts(
            source=self.integration_id,
            period_start=period_start,
            period_end=period_end,
            collected_at=self._clock.now(),
            parent_accounts_joined=_page_count(parents),
            child_accounts_joined=_page_count(children),
            total_children=_page_count(inventory),
            children_with_app_usage=app_usage.count,
            children_with_realtime_feature_usage=realtime_usage.count,
            completeness=min(app_usage.completeness, realtime_usage.completeness),
            source_request_ids=_unique_nonempty(
                [
                    parent_request_id,
                    child_request_id,
                    inventory_request_id,
                    *app_usage.request_ids,
                    *realtime_usage.request_ids,
                ],
            ),
            limitations=limitations,
        )

    async def health(self) -> IntegrationHealth:
        started = time.monotonic()
        checked_at = self._clock.now()
        try:
            _, request_id = await self._get_page(
                _ACCOUNT_PATH,
                params={"limit": 1, "offset": 0},
                require_count=True,
            )
        except (ProviderPermanentError, ProviderTransientError) as exc:
            return IntegrationHealth(
                integration_id=self.integration_id,
                status=IntegrationStatus.UNHEALTHY,
                checked_at=checked_at,
                latency_ms=_latency_ms(started),
                message=f"Admin API read check failed ({type(exc).__name__})",
                diagnostics={"mode": "live_read_only"},
            )
        return IntegrationHealth(
            integration_id=self.integration_id,
            status=IntegrationStatus.HEALTHY,
            checked_at=checked_at,
            last_success_at=self._clock.now(),
            latency_ms=_latency_ms(started),
            message="Manakids Admin API read access is healthy",
            provider_request_id=request_id,
            diagnostics={"mode": "live_read_only"},
        )

    async def _get_page(
        self,
        path: str,
        *,
        params: Mapping[str, str | int],
        require_count: bool,
    ) -> tuple[_PageEnvelope, str | None]:
        payload, request_id = await self._authorized_json(path, params=params)
        try:
            if isinstance(payload, list):
                envelope = _PageEnvelope(results=payload)
            else:
                envelope = _PageEnvelope.model_validate(payload)
        except ValidationError:
            raise ProviderPermanentError("Admin API pagination contract is invalid") from None
        if require_count and envelope.count is None:
            raise ProviderPermanentError("Admin API pagination count is missing")
        return envelope, request_id

    async def _count_activity_rows(
        self,
        path: str,
        *,
        params: Mapping[str, str | int],
        row_has_activity: Callable[[dict[str, Any]], bool],
    ) -> _CountResult:
        request_ids: list[str] = []
        matching_rows = 0
        rows_scanned = 0
        total_rows: int | None = None
        complete = False
        for page_number in range(1, self._max_pages + 1):
            page, request_id = await self._get_page(
                path,
                params={**params, "page": page_number},
                require_count=False,
            )
            request_ids = _unique_nonempty([*request_ids, request_id])
            if page.count is not None:
                total_rows = max(total_rows or 0, page.count)
            matching_rows += sum(row_has_activity(row) for row in page.results)
            rows_scanned += len(page.results)

            if total_rows is not None and rows_scanned >= total_rows:
                complete = True
                break
            if page.page_count is not None and page_number >= page.page_count:
                complete = True
                break
            if not page.results:
                complete = total_rows in {None, rows_scanned}
                break
            if total_rows is None and page.page_count is None:
                page_size = page.per_page or 10
                if len(page.results) < page_size:
                    complete = True
                    break

        return _CountResult(
            count=matching_rows,
            rows_scanned=rows_scanned,
            total_rows=total_rows,
            request_ids=request_ids,
            complete=complete,
        )

    async def _authorized_json(
        self,
        path: str,
        *,
        params: Mapping[str, str | int],
    ) -> tuple[Any, str | None]:
        token = await self._token()
        response = await self._request(
            "GET",
            path,
            params=params,
            headers={"Authorization": f"Bearer {token}"},
        )
        if response.status_code == 401:
            async with self._auth_lock:
                if self._access_token == token:
                    self._access_token = None
            token = await self._token()
            response = await self._request(
                "GET",
                path,
                params=params,
                headers={"Authorization": f"Bearer {token}"},
            )
        _raise_for_status(response, operation="Admin API read")
        return _json_payload(response, operation="Admin API read"), _request_id(response)

    async def _token(self) -> str:
        if self._access_token is not None:
            return self._access_token
        async with self._auth_lock:
            if self._access_token is not None:
                return self._access_token
            response = await self._request(
                "POST",
                _AUTH_PATH,
                json={"username": self._username, "password": self._password},
            )
            _raise_for_status(response, operation="Admin API authentication")
            try:
                parsed = _LoginResponse.model_validate(
                    _json_payload(response, operation="Admin API authentication"),
                )
            except ValidationError:
                raise ProviderPermanentError(
                    "Admin API authentication response is invalid",
                ) from None
            self._access_token = parsed.access_token
            return parsed.access_token

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        url = f"{self._base_url}{path}"
        for attempt in range(self._max_retries + 1):
            try:
                response = await self._client.request(method, url, **kwargs)
            except httpx.RequestError as exc:
                if attempt >= self._max_retries:
                    raise ProviderTransientError("Admin API network request failed") from exc
                await asyncio.sleep(self._retry_backoff_seconds * (2**attempt))
                continue
            if response.status_code not in _RETRYABLE_STATUSES or attempt >= self._max_retries:
                return response
            await asyncio.sleep(self._retry_backoff_seconds * (2**attempt))
        raise ProviderTransientError("Admin API retry budget was exhausted")


def _page_count(page: _PageEnvelope) -> int:
    return page.count if page.count is not None else len(page.results)


def _row_has_app_usage(row: dict[str, Any]) -> bool:
    try:
        parsed = _AppUsageRow.model_validate(row)
    except ValidationError:
        raise ProviderPermanentError("Admin API app-usage row contract is invalid") from None
    return bool(parsed.app_usage_statistics.results) or bool(parsed.app_usage_statistics.count)


def _row_has_realtime_usage(row: dict[str, Any]) -> bool:
    try:
        parsed = _RealtimeUsageRow.model_validate(row)
    except ValidationError:
        raise ProviderPermanentError("Admin API realtime-usage row contract is invalid") from None
    return bool(parsed.camera_audio_usage_logs)


def _partial_scan_limitations(
    *,
    app_usage: _CountResult,
    realtime_usage: _CountResult,
) -> list[str]:
    limitations: list[str] = []
    for label, result in (
        ("App usage", app_usage),
        ("Camera/audio/screen", realtime_usage),
    ):
        if result.complete:
            continue
        population = str(result.total_rows) if result.total_rows is not None else "unknown"
        limitations.append(
            f"{label} activity is an observed count from a bounded scan of "
            f"{result.rows_scanned} of {population} child rows; it is not an extrapolated "
            "global count.",
        )
    return limitations


def _raise_for_status(response: httpx.Response, *, operation: str) -> None:
    if response.status_code < 400:
        return
    error = f"{operation} failed with HTTP {response.status_code}"
    if response.status_code in _RETRYABLE_STATUSES:
        raise ProviderTransientError(error)
    raise ProviderPermanentError(error)


def _json_payload(response: httpx.Response, *, operation: str) -> Any:
    try:
        return response.json()
    except ValueError as exc:
        raise ProviderPermanentError(f"{operation} returned invalid JSON") from exc


def _request_id(response: httpx.Response) -> str | None:
    value = response.headers.get("x-request-id") or response.headers.get("trace-id")
    return value if isinstance(value, str) else None


def _unique_nonempty(values: list[str | None]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _latency_ms(started: float) -> int:
    return max(round((time.monotonic() - started) * 1_000), 0)
