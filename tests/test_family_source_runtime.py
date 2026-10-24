"""Real server wiring and OAuth signer, exclusively fictional HTTP responses."""

import asyncio
import base64
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs
from uuid import uuid4

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import ValidationError
from pytest import MonkeyPatch

from app.core.config import Settings
from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.application.parent_touch import ParentTouchService
from app.mana_ai.domain.child_safety import ChildSafetyLimits
from app.mana_ai.domain.family_sources import ChildBatteryFacts, FamilySourceTarget
from app.services import parent_chat_runtime as runtime_module
from app.services.family_google_auth import FamilyFirestoreToken
from app.services.family_source_runtime import family_source_runtime
from app.services.parent_chat_children import ManakidsChatChildrenSource
from tests.test_parent_chat import Children, Model
from tests.test_parent_chat_api import BACKEND_TOKEN

NOW = datetime(2026, 10, 16, 12, tzinfo=UTC)


@pytest.fixture
def credential_file(tmp_path: Path) -> Path:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    path = tmp_path / "synthetic-credentials.json"
    path.write_text(
        json.dumps(
            {
                "type": "service_account",
                "project_id": "test-project",
                "private_key_id": "a" * 40,
                "private_key": pem,
                "client_email": "synthetic@test-project.iam.gserviceaccount.com",
                "token_uri": "https://untrusted.invalid/never-send-here",
            }
        )
    )
    return path


def config(path: Path, credentials: Path, **changes: object) -> Settings:
    return Settings.model_validate(
        {
            "openai_api_key": "fake-key",
            "app_api_key": BACKEND_TOKEN,
            "mana_parent_chat_enabled": True,
            "mana_parent_chat_database_path": path / "chat.sqlite3",
            "mana_parent_touch_enabled": True,
            "manakids_api_username": "synthetic",
            "manakids_api_password": "synthetic",
            "mana_family_sources_enabled": True,
            "mana_family_firebase_mana_confirmed": True,
            "mana_family_source_database_path": path / "source.sqlite3",
            "firebase_project_id": "test-project",
            "firebase_service_account_file": credentials,
        }
        | changes
    )


class Google:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.denied = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.host == "oauth2.googleapis.com":
            assert str(request.url) == "https://oauth2.googleapis.com/token"
            form = parse_qs(request.content.decode())
            assert form["grant_type"] == ["urn:ietf:params:oauth:grant-type:jwt-bearer"]
            encoded = form["assertion"][0].split(".")[1]
            claims = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
            assert claims == {
                "iss": "synthetic@test-project.iam.gserviceaccount.com",
                "scope": "https://www.googleapis.com/auth/datastore",
                "aud": "https://oauth2.googleapis.com/token",
                "iat": int(NOW.timestamp()),
                "exp": int(NOW.timestamp()) + 3600,
            }
            return httpx.Response(
                200,
                json={
                    "access_token": "fake-source-token",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                },
            )
        assert request.url.host == "firestore.googleapis.com"
        assert request.headers["authorization"] == "Bearer fake-source-token"
        query = json.loads(request.content)["structuredQuery"]
        assert query["limit"] == 2
        assert query["where"]["fieldFilter"]["value"] == {"integerValue": "124"}
        if self.denied:
            return httpx.Response(403, json={"error": "not persisted"})
        return httpx.Response(
            200,
            json=[
                {
                    "readTime": NOW.isoformat(),
                    "document": {
                        "name": (
                            "projects/test-project/databases/(default)/documents/battery/fixture"
                        ),
                        "updateTime": (NOW - timedelta(seconds=1)).isoformat(),
                        "fields": {
                            "childId": {"integerValue": "124"},
                            "percent": {"stringValue": "12"},
                            "created_at": {
                                "timestampValue": (NOW - timedelta(seconds=2)).isoformat()
                            },
                        },
                    },
                }
            ],
        )


def target() -> FamilySourceTarget:
    return FamilySourceTarget(parent_id="123", child_id=124, request_id=uuid4())


async def test_real_factory_is_lazy_and_shared_cache_and_exact_replay_survive_restart(
    tmp_path: Path, credential_file: Path
) -> None:
    provider, children = Google(), Children()
    settings = config(tmp_path, credential_file)
    request = target()
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        runtime = await family_source_runtime(settings, client, children, clock=lambda: NOW)
        assert runtime and not provider.requests and children.calls == 0
        receipt = await runtime.reads.read_child_battery(request)
        assert receipt.status == "completed" and isinstance(receipt.facts, ChildBatteryFacts)
        assert receipt.facts.percent == 12
        assert len(provider.requests) == 2 and children.calls == 1
        assert not await runtime.store.claim_next_dispatch(NOW)
        second = await runtime.reads.read_child_battery(target())
        assert second.cache_hit and second.facts == receipt.facts
        assert len(provider.requests) == 2 and children.calls == 2
        restarted = await family_source_runtime(settings, client, children, clock=lambda: NOW)
        assert restarted
        assert await restarted.reads.read_child_battery(request) == receipt
        assert len(provider.requests) == 2 and children.calls == 2
        # Enabling a consumer later never backfills old reads captured as disabled.
        enabled = config(
            tmp_path,
            credential_file,
            mana_family_source_safety_enabled=True,
            mana_child_safety_enabled=True,
            mana_child_safety_limits=ChildSafetyLimits(
                server_daily_tokens=2000, parent_daily_tokens=2000, job_tokens=1000
            ),
            mana_child_safety_max_output_tokens=512,
        )
        subsequent = await family_source_runtime(enabled, client, children, clock=lambda: NOW)
        assert subsequent
        old = await subsequent.store.claim_next_dispatch(NOW)
        assert old and old.receipt.phase == "skipped" and old.receipt.reason == "not_admitted"
        assert await subsequent.store.claim_next_dispatch(NOW) is None


async def test_firestore_auth_denial_closes_durable_source_across_restart(
    tmp_path: Path, credential_file: Path
) -> None:
    provider = Google()
    provider.denied = True
    settings = config(tmp_path, credential_file)
    request = target()
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        runtime = await family_source_runtime(settings, client, Children(), clock=lambda: NOW)
        assert runtime
        denied = await runtime.reads.read_child_battery(request)
        assert denied.status == "failed" and denied.error_code == "family_source_auth_denied"
        restarted = await family_source_runtime(settings, client, Children(), clock=lambda: NOW)
        assert restarted and await restarted.reads.read_child_battery(request) == denied
        with pytest.raises(ParentChatError, match="family_source_circuit_open"):
            await restarted.reads.read_child_battery(target())
        assert len(provider.requests) == 2


async def test_ownership_precedes_oauth_and_firestore(
    tmp_path: Path, credential_file: Path
) -> None:
    provider, children = Google(), Children()
    children.owner_mismatch = True
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        runtime = await family_source_runtime(
            config(tmp_path, credential_file), client, children, clock=lambda: NOW
        )
        assert runtime
        result = await runtime.reads.read_child_battery(target())
        assert result.status == "failed" and not provider.requests


async def test_disabled_factory_does_not_read_credentials_or_create_storage(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, openai_api_key="fake-key")
    async with httpx.AsyncClient(transport=httpx.MockTransport(Google())) as client:
        assert await family_source_runtime(settings, client, Children(), clock=lambda: NOW) is None
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "changes",
    [
        {"mana_family_firebase_mana_confirmed": False},
        {"mana_parent_touch_enabled": False},
        {"firebase_project_id": None},
        {"firebase_service_account_file": None},
        {"mana_family_source_database_path": ":memory:"},
        {"mana_family_source_safety_enabled": True},
    ],
)
def test_source_configuration_requires_independent_authority_and_storage(
    tmp_path: Path, credential_file: Path, changes: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        config(tmp_path, credential_file, **changes)
    for name in ("mana_parent_chat_database_path", "marketing_database_path"):
        with pytest.raises(ValidationError):
            config(tmp_path, credential_file, **{name: tmp_path / "source.sqlite3"})
    with pytest.raises(ValidationError):
        config(
            tmp_path,
            credential_file,
            operation_database_url=f"sqlite+aiosqlite:///{tmp_path}/source.sqlite3",
        )


async def test_credentials_are_project_bound_and_errors_never_include_key_data(
    credential_file: Path,
) -> None:
    provider = Google()
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        with pytest.raises(ValueError, match="credentials are invalid") as error:
            FamilyFirestoreToken(
                client, credential_file, project_id="foreign-project", clock=lambda: NOW
            )
        assert "PRIVATE KEY" not in str(error.value) and not provider.requests


@pytest.mark.parametrize(
    "payload",
    [
        {"access_token": "fake-newline\n", "expires_in": 3600, "token_type": "Bearer"},
        {"access_token": "synthetic", "expires_in": True, "token_type": "Bearer"},
        {"access_token": "synthetic", "expires_in": 3601, "token_type": "Bearer"},
        {"access_token": "synthetic", "expires_in": 3600, "token_type": "Other"},
        ["invalid"],
    ],
)
async def test_invalid_oauth_receipt_is_not_retried(credential_file: Path, payload: object) -> None:
    calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        auth = FamilyFirestoreToken(
            client, credential_file, project_id="test-project", clock=lambda: NOW
        )
        with pytest.raises(ParentChatError, match="family_source_invalid"):
            await auth.token()
        with pytest.raises(ParentChatError, match="family_source_auth_denied"):
            await auth.token()
    assert calls == 1


async def test_transient_oauth_failure_has_no_transport_retry_and_rejects_immediate_refresh(
    credential_file: Path,
) -> None:
    calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        auth = FamilyFirestoreToken(
            client, credential_file, project_id="test-project", clock=lambda: NOW
        )
        for _ in range(2):
            with pytest.raises(ParentChatError, match="family_source_unavailable"):
                await auth.token()
    assert calls == 1


async def test_oauth_expiry_is_measured_from_dispatch_not_receipt(credential_file: Path) -> None:
    current = NOW

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal current
        current += timedelta(seconds=3600)
        return httpx.Response(
            200,
            json={"access_token": "fake-source-token", "token_type": "Bearer", "expires_in": 3600},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        auth = FamilyFirestoreToken(
            client, credential_file, project_id="test-project", clock=lambda: current
        )
        with pytest.raises(ParentChatError, match="family_source_unavailable"):
            await auth.token()


async def test_concurrent_token_requests_share_one_exchange(credential_file: Path) -> None:
    provider = Google()
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        auth = FamilyFirestoreToken(
            client, credential_file, project_id="test-project", clock=lambda: NOW
        )
        assert await asyncio.gather(*(auth.token() for _ in range(5))) == ["fake-source-token"] * 5
    assert len(provider.requests) == 1


async def test_parent_runtime_exposes_sources_without_starting_any_external_refresh(
    tmp_path: Path, credential_file: Path, monkeypatch: MonkeyPatch
) -> None:
    class ClosedModel(Model):
        async def close(self) -> None:
            pass

    monkeypatch.setattr(runtime_module, "OpenAIParentChatModel", lambda settings: ClosedModel())
    monkeypatch.setattr(runtime_module, "ManakidsChatChildrenSource", lambda **kwargs: Children())
    provider = Google()
    monkeypatch.setattr(httpx, "AsyncHTTPTransport", lambda **kwargs: httpx.MockTransport(provider))
    settings = config(tmp_path, credential_file)
    async with runtime_module.parent_chat_runtime(settings) as service:
        assert isinstance(service, ParentTouchService) and service.sources is not None
        assert (await service.history("123", before=None, limit=20)).messages == []
    assert not provider.requests


async def test_lost_oauth_response_retains_source_hold_without_automatic_retry(
    tmp_path: Path, credential_file: Path
) -> None:
    calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("Synthetic lost receipt", request=request)

    settings, request = config(tmp_path, credential_file), target()
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        runtime = await family_source_runtime(settings, client, Children(), clock=lambda: NOW)
        assert runtime
        unknown = await runtime.reads.read_child_battery(request)
        assert unknown.status == "unknown" and unknown.document_units_reserved == 2
        restarted = await family_source_runtime(settings, client, Children(), clock=lambda: NOW)
        assert restarted and await restarted.reads.read_child_battery(request) == unknown
        with pytest.raises(ParentChatError, match="family_source_read_unresolved"):
            await restarted.reads.read_child_battery(target())
    assert calls == 1


@pytest.mark.parametrize("status", [400, 401, 403, 307])
async def test_rejected_oauth_never_follows_redirects_or_repeats(
    credential_file: Path, status: int
) -> None:
    calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status, headers={"Location": "https://untrusted.invalid/token"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        auth = FamilyFirestoreToken(
            client, credential_file, project_id="test-project", clock=lambda: NOW
        )
        for _ in range(2):
            with pytest.raises(ParentChatError, match="family_source_auth_denied"):
                await auth.token()
    assert calls == 1


@pytest.mark.parametrize("denial_at", ["login", "profile", "oauth_receipt"])
async def test_authentication_gate_failures_close_source_before_next_family_attempt(
    tmp_path: Path, credential_file: Path, denial_at: str
) -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/login/"):
            return httpx.Response(403 if denial_at == "login" else 200, json={"access": "fake-jwt"})
        if request.url.path.endswith("/parent-list/"):
            return httpx.Response(403)
        assert request.url.host == "oauth2.googleapis.com" and denial_at == "oauth_receipt"
        return httpx.Response(200, json={"access_token": "fake-incomplete-receipt"})

    settings = config(tmp_path, credential_file)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        children = (
            ManakidsChatChildrenSource(
                client=client,
                base_url="https://synthetic.invalid",
                username="fake-user",
                password="fake-password",
            )
            if denial_at != "oauth_receipt"
            else Children()
        )
        runtime = await family_source_runtime(settings, client, children, clock=lambda: NOW)
        assert runtime
        result = await runtime.reads.read_child_battery(target())
        assert result.status == "failed"
        assert result.error_code == (
            "family_source_invalid" if denial_at == "oauth_receipt" else "family_source_auth_denied"
        )
        count = len(requests)
        restarted = await family_source_runtime(settings, client, children, clock=lambda: NOW)
        assert restarted
        with pytest.raises(ParentChatError, match="family_source_circuit_open"):
            await restarted.reads.read_child_battery(target())
        assert len(requests) == count
        assert all(request.url.host != "firestore.googleapis.com" for request in requests)


async def test_app_usage_runtime_uses_existing_auth_without_google_requests(
    tmp_path: Path, credential_file: Path
) -> None:
    from tests.test_child_app_usage import page

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.host == "api.manakids.uz"
        if request.url.path.endswith("/login/"):
            return httpx.Response(200, json={"access": "fake-access-token"})
        if request.url.path.endswith("/parent-list/"):
            assert request.url.params["parent_id"] == "123"
            return httpx.Response(
                200,
                json={
                    "count": 1,
                    "next": None,
                    "results": [
                        {
                            "id": 123,
                            "children": [
                                {"id": 124, "fullname": "Fictional child", "is_connected": True}
                            ],
                        }
                    ],
                },
            )
        assert request.url.path.endswith("/app-usage-statistics/124/")
        return httpx.Response(200, json=page())

    settings = config(
        tmp_path,
        credential_file,
        mana_parent_touch_review_first_enabled=True,
        mana_child_safety_enabled=True,
        mana_child_safety_source_tools_enabled=True,
        mana_family_app_usage_enabled=True,
        mana_child_safety_limits=ChildSafetyLimits(
            server_daily_tokens=2000, parent_daily_tokens=2000, job_tokens=2000
        ),
        mana_child_safety_max_output_tokens=512,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        profiles = ManakidsChatChildrenSource(
            client=client,
            base_url="https://api.manakids.uz",
            username="fake-user",
            password="fake-password",
        )
        runtime = await family_source_runtime(
            settings, client, profiles, clock=lambda: datetime.now(UTC), account_auth=profiles
        )
        assert runtime and not requests
        req = FamilySourceTarget(
            parent_id="123", child_id=124, request_id=uuid4(), source="manakids.child_app_usage.v1"
        )
        receipt = await runtime.reads.read_child_app_usage(req)
        assert receipt.status == "completed" and receipt.source == "manakids.child_app_usage.v1"
        assert len(requests) == 3
        assert await runtime.reads.read_child_app_usage(req) == receipt and len(requests) == 3
