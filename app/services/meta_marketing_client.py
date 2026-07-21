import json
from collections.abc import Mapping
from datetime import date
from typing import cast

import httpx
from pydantic import JsonValue

from app.core.config import Settings
from app.schemas.marketing import MetaInsightLevel


class MetaMarketingError(RuntimeError):
    """Raised when Meta Marketing API integration fails."""


class MetaConfigurationError(MetaMarketingError):
    """Raised when Meta Marketing API credentials are not configured."""


class MetaAPIError(MetaMarketingError):
    """Raised when Meta Marketing API returns an unsuccessful response."""


class MetaMarketingClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def api_version(self) -> str:
        return self._settings.meta_graph_api_version

    async def fetch_app(self) -> dict[str, JsonValue] | None:
        if not self._settings.meta_app_id:
            return None
        return await self._get_object(
            self._settings.meta_app_id,
            fields=["id", "name", "namespace", "category", "link", "app_domains"],
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

    async def fetch_insights(
        self,
        *,
        account_id: str,
        level: MetaInsightLevel,
        date_start: date,
        date_stop: date,
    ) -> list[dict[str, JsonValue]]:
        return await self._get_paginated(
            f"{normalize_ad_account_id(account_id)}/insights",
            params={
                "fields": ",".join(self._settings.meta_insights_fields),
                "level": level,
                "time_increment": "1",
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
            },
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
        items: list[dict[str, JsonValue]] = []
        next_url: str | None = self._build_url(path)
        next_params: dict[str, str] | None = {
            **dict(params),
            "limit": str(self._settings.meta_page_limit),
            "access_token": self._get_access_token(),
        }

        async with httpx.AsyncClient(timeout=self._settings.meta_request_timeout_seconds) as client:
            for _ in range(self._settings.meta_max_pages):
                if next_url is None:
                    break
                response = await client.get(next_url, params=next_params)
                payload = self._parse_response(response)
                data = payload.get("data", [])
                if isinstance(data, list):
                    items.extend(
                        cast(
                            list[dict[str, JsonValue]],
                            [item for item in data if isinstance(item, dict)],
                        ),
                    )

                paging = payload.get("paging", {})
                next_url = (
                    str(paging.get("next"))
                    if isinstance(paging, dict) and paging.get("next") is not None
                    else None
                )
                next_params = None

        return items

    async def _get_json(
        self,
        path: str,
        *,
        params: Mapping[str, str],
    ) -> dict[str, JsonValue]:
        request_params = {
            **dict(params),
            "access_token": self._get_access_token(),
        }
        async with httpx.AsyncClient(timeout=self._settings.meta_request_timeout_seconds) as client:
            response = await client.get(self._build_url(path), params=request_params)
        return self._parse_response(response)

    async def _post_json(
        self,
        path: str,
        *,
        params: Mapping[str, str],
    ) -> dict[str, JsonValue]:
        request_params = {
            **dict(params),
            "access_token": self._get_access_token(),
        }
        async with httpx.AsyncClient(timeout=self._settings.meta_request_timeout_seconds) as client:
            response = await client.post(self._build_url(path), data=request_params)
        return self._parse_response(response)

    def _parse_response(self, response: httpx.Response) -> dict[str, JsonValue]:
        try:
            payload = cast(dict[str, JsonValue], response.json())
        except ValueError as exc:
            raise MetaAPIError("Meta API returned a non-JSON response") from exc

        if response.is_error:
            error_payload = payload.get("error", {})
            message = "Meta API request failed"
            if isinstance(error_payload, dict) and error_payload.get("message") is not None:
                message = str(error_payload["message"])
            raise MetaAPIError(message)

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
