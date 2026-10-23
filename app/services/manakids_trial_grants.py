"""Documented non-paid agent tariff endpoint; no payment/transaction API calls."""

import json
from datetime import datetime, timedelta

import httpx
from pydantic import AwareDatetime, BaseModel, ConfigDict, StrictBool, field_validator

from app.mana_ai.application.conversion_grants import TrialGrantRejected
from app.mana_ai.domain.conversion_grants import TrialGrantResult

KNOWN_REFUSALS = frozenset(
    {
        "invalid_days",
        "invalid_parent_id",
        "parent_not_found",
        "trial_already_given",
        "has_active_paid_tariff",
        "agent_tariff_not_configured",
        "agent_tariff_limit_missing",
    }
)
_METADATA_FIELDS = frozenset({"is_paid", "created_at", "agent_trial_used"})


class _GrantMetadata(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)

    is_paid: StrictBool
    created_at: AwareDatetime
    agent_trial_used: StrictBool

    @field_validator("created_at", mode="before")
    @classmethod
    def explicit_created_date(cls, value: object) -> datetime:
        if not isinstance(value, str):
            raise ValueError("Grant creation must be an ISO datetime string")
        return datetime.fromisoformat(value)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Ambiguous grant response")
        result[key] = value
    return result


def _verify_metadata(data: dict[str, object], result: TrialGrantResult, days: int) -> None:
    # Keep the documented legacy receipt readable. Once the provider supplies
    # any new metadata, require the whole strict group; never coerce unknowns.
    if not _METADATA_FIELDS.intersection(data):
        return
    metadata = _GrantMetadata.model_validate(data)
    if metadata.is_paid or not metadata.agent_trial_used:
        raise ValueError("Receipt does not verify a consumed non-paid grant")
    expected_start = result.valid_until - timedelta(days=days)
    if abs((metadata.created_at - expected_start).total_seconds()) > 300:
        raise ValueError("Grant creation does not match its requested period")


class ManakidsTrialGrantGateway:
    def __init__(
        self, *, client: httpx.AsyncClient, base_url: str, username: str, password: str
    ) -> None:
        self._client, self._base = client, base_url.rstrip("/")
        self._username, self._password = username, password

    async def _payload(self, response: httpx.Response) -> object:
        data = bytearray()
        async for chunk in response.aiter_bytes(chunk_size=4096):
            data.extend(chunk)
            if len(data) > 16384:
                raise ValueError("Bounded provider receipt exceeded")
        return json.loads(data, object_pairs_hook=_unique_object)

    async def _access(self) -> str:
        # Each distinct durable action obtains fresh credentials before its one
        # write. Never guess the upstream JWT lifetime or reuse another action's
        # token: a stale credential must not consume a parent's lifetime grant.
        try:
            async with self._client.stream(
                "POST",
                self._base + "/api/v1/admin-panel-auth/login/",
                json={"username": self._username, "password": self._password},
                headers={"User-Agent": "MANA-Conversion/1.0"},
                follow_redirects=False,
            ) as response:
                if response.status_code != 200:
                    raise TrialGrantRejected("trial_grant_auth_unavailable")
                payload = await self._payload(response)
            if not isinstance(payload, dict) or not isinstance(payload.get("access"), str):
                raise ValueError("Missing JWT access receipt")
            token = str(payload["access"])
            if not token or len(token) > 8192:
                raise ValueError("Invalid JWT access receipt")
            return token
        except TrialGrantRejected:
            raise
        except (ValueError, httpx.HTTPError):
            raise TrialGrantRejected("trial_grant_auth_unavailable") from None

    async def grant(self, parent_id: str, days: int) -> TrialGrantResult:
        if (
            not parent_id.isascii()
            or not parent_id.isdecimal()
            or not 0 < int(parent_id) <= 2**63 - 1
        ):
            raise TrialGrantRejected("invalid_parent_id")
        if type(days) is not int or not 1 <= days <= 30:
            raise TrialGrantRejected("invalid_days")
        token = await self._access()
        # A durable per-parent claim already exists. Never retry/re-login this write.
        async with self._client.stream(
            "POST",
            self._base + "/api/v1/admin-panel-payment/agent-grant-tariff/",
            json={"parent_id": int(parent_id), "days": days},
            headers={"Authorization": f"Bearer {token}", "User-Agent": "MANA-Conversion/1.0"},
            follow_redirects=False,
        ) as response:
            if response.status_code in {401, 403}:
                raise TrialGrantRejected("trial_grant_not_authorized")
            payload = await self._payload(response)
            if (
                response.status_code in {400, 404, 409}
                and isinstance(payload, dict)
                and payload.get("success") is False
                and payload.get("code") in KNOWN_REFUSALS
            ):
                raise TrialGrantRejected(str(payload["code"]))
            if (
                response.status_code != 201
                or not isinstance(payload, dict)
                or payload.get("success") is not True
            ):
                raise ValueError("Unverified grant outcome")
            data = payload.get("data")
            if not isinstance(data, dict) or type(data.get("parent_id")) is not int:
                raise ValueError("Unverified parent receipt")
            result = TrialGrantResult.model_validate(
                {
                    "purchase_id": data.get("purchase_id"),
                    "parent_id": str(data["parent_id"]),
                    "tariff": data.get("tariff"),
                    "valid_until": data.get("valid_until"),
                }
            )
            _verify_metadata(data, result, days)
            # Metadata verifies this response only; do not change legacy SQL
            # receipt JSON or make it a fresh subscription/contact permission.
            return result
