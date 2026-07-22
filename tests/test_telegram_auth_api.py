import json
import re
from pathlib import Path
from typing import cast

from httpx import ASGITransport, AsyncClient
from pytest import MonkeyPatch

from app.core.config import get_settings
from app.main import create_app
from app.mana_operation_ai.application.auth_service import AdminAuthService
from app.mana_operation_ai.application.runtime import SystemClock, UuidGenerator
from app.mana_operation_ai.domain.auth import AuthPolicy
from app.mana_operation_ai.infrastructure.persistence.auth_repository import (
    SqlAlchemyAdminAuthRepository,
)

ORIGIN = "http://testserver"
BOOTSTRAP_TELEGRAM_ID = 976835256
SECOND_BOOTSTRAP_TELEGRAM_ID = 51456737
THIRD_TELEGRAM_ID = 777000111


class CapturingSender:
    def __init__(self) -> None:
        self.code: str | None = None

    async def send_login_code(self, *, telegram_id: int, code: str, ttl_seconds: int) -> None:
        del telegram_id, ttl_seconds
        self.code = code


def configure_auth_env(monkeypatch: MonkeyPatch, database_path: Path, sink_path: Path) -> None:
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("MARKETING_DATABASE_PATH", str(database_path))
    monkeypatch.setenv("OPERATION_DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")
    monkeypatch.setenv("OPERATION_SCHEDULER_ENABLED", "0")
    monkeypatch.setenv("MANA_TELEGRAM_AUTH_ENABLED", "1")
    monkeypatch.setenv("MANA_OTP_HMAC_SECRET", "test-api-auth-secret-with-enough-entropy-123456")
    monkeypatch.setenv("MANA_TELEGRAM_BOT_USERNAME", "mana_test_bot")
    monkeypatch.setenv(
        "MANA_BOOTSTRAP_ADMIN_TELEGRAM_IDS",
        f"{BOOTSTRAP_TELEGRAM_ID},{SECOND_BOOTSTRAP_TELEGRAM_ID}",
    )
    monkeypatch.setenv("MANA_TRUSTED_ORIGINS", f'["{ORIGIN}"]')
    monkeypatch.setenv("MANA_AUTH_TEST_MODE", "1")
    monkeypatch.setenv("MANA_AUTH_TEST_OTP_SINK_PATH", str(sink_path))
    monkeypatch.setenv("OPERATION_ALLOW_INSECURE_DEV_HEADERS", "0")
    monkeypatch.setenv("OPERATION_VIEWER_API_KEY", "test-service-viewer-key")
    get_settings.cache_clear()


def last_code(sink_path: Path, telegram_id: int) -> str:
    records = [json.loads(line) for line in sink_path.read_text().splitlines()]
    matches = [record for record in records if record["telegram_id"] == telegram_id]
    code = matches[-1]["code"]
    if not isinstance(code, str):
        raise AssertionError("OTP sink code must be a string")
    return code


async def login(client: AsyncClient, sink_path: Path, telegram_id: int) -> dict[str, object]:
    requested = await client.post(
        "/api/v1/auth/telegram/request-code",
        headers={"Origin": ORIGIN},
        json={"telegram_id": telegram_id},
    )
    assert requested.status_code == 202
    assert re.search(r"(?<!\d)\d{6}(?!\d)", requested.text) is None
    code = last_code(sink_path, telegram_id)
    verified = await client.post(
        "/api/v1/auth/telegram/verify-code",
        headers={"Origin": ORIGIN},
        json={"telegram_id": telegram_id, "code": code},
    )
    assert verified.status_code == 200
    assert "mana_admin_session" in verified.headers.get_list("set-cookie")[0]
    assert "HttpOnly" in " ".join(verified.headers.get_list("set-cookie"))
    assert "SameSite=lax" in " ".join(verified.headers.get_list("set-cookie"))
    body = cast(dict[str, object], verified.json())
    assert body["authenticated"] is True
    return body


def csrf_headers(client: AsyncClient) -> dict[str, str]:
    token = client.cookies.get("mana_csrf")
    if token is None:
        raise AssertionError("CSRF cookie is missing")
    return {"Origin": ORIGIN, "X-CSRF-Token": token}


async def test_browser_auth_session_csrf_rbac_and_logout(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    sink_path = tmp_path / "otp-sink.jsonl"
    configure_auth_env(monkeypatch, tmp_path / "auth-api.db", sink_path)
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as client,
    ):
        anonymous = await client.get("/api/v1/auth/session")
        assert anonymous.json() == {
            "authenticated": False,
            "user": None,
            "expires_at": None,
            "ads_provider": None,
            "provider_mode": None,
            "live_meta_read_only": False,
        }

        logged_in = await login(client, sink_path, BOOTSTRAP_TELEGRAM_ID)
        user = logged_in["user"]
        assert isinstance(user, dict)
        assert user["role"] == "admin"
        assert user["telegram_id"] == BOOTSTRAP_TELEGRAM_ID

        restored = await client.get("/api/v1/auth/session")
        assert restored.status_code == 200
        assert restored.json()["user"]["user_id"] == user["user_id"]

        dashboard = await client.get("/api/v1/admin/operation/dashboard")
        assert dashboard.status_code == 200
        missing_csrf = await client.post(
            "/api/v1/admin/operation/agents/marketing-agent/run",
            headers={"Origin": ORIGIN},
            json={"job_type": "analysis"},
        )
        assert missing_csrf.status_code == 403
        with_csrf = await client.post(
            "/api/v1/admin/operation/agents/marketing-agent/run",
            headers=csrf_headers(client),
            json={"job_type": "analysis", "idempotency_key": "auth-session-run"},
        )
        assert with_csrf.status_code == 202

        users = await client.get("/api/v1/admin/users")
        assert users.status_code == 200
        assert users.json()["total"] == 2
        created = await client.post(
            "/api/v1/admin/users",
            headers=csrf_headers(client),
            json={
                "telegram_id": THIRD_TELEGRAM_ID,
                "role": "viewer",
                "display_name": "Third User",
                "username": "@third_user",
            },
        )
        assert created.status_code == 201
        third_user_id = created.json()["user_id"]
        assert created.json()["username"] == "third_user"

        self_change = await client.patch(
            f"/api/v1/admin/users/{user['user_id']}",
            headers=csrf_headers(client),
            json={"role": "viewer"},
        )
        assert self_change.status_code == 409
        assert self_change.json()["detail"] == "self_access_change_forbidden"

        untrusted = await client.post(
            f"/api/v1/admin/users/{third_user_id}/sessions/revoke",
            headers={
                "Origin": "https://attacker.example",
                "X-CSRF-Token": csrf_headers(client)["X-CSRF-Token"],
            },
        )
        assert untrusted.status_code == 403

        logout = await client.post("/api/v1/auth/logout", headers=csrf_headers(client))
        assert logout.status_code == 204
        assert (await client.get("/api/v1/auth/session")).json()["authenticated"] is False
        assert (await client.get("/api/v1/admin/operation/dashboard")).status_code == 401

    get_settings.cache_clear()


async def test_disabling_user_revokes_sessions_and_headers_cannot_forge_identity(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    sink_path = tmp_path / "otp-sink.jsonl"
    configure_auth_env(monkeypatch, tmp_path / "revocation.db", sink_path)
    app = create_app()
    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url=ORIGIN) as admin_client:
            await login(admin_client, sink_path, BOOTSTRAP_TELEGRAM_ID)
            users = (await admin_client.get("/api/v1/admin/users")).json()["items"]
            second = next(
                item for item in users if item["telegram_id"] == SECOND_BOOTSTRAP_TELEGRAM_ID
            )
            async with AsyncClient(transport=transport, base_url=ORIGIN) as second_client:
                await login(second_client, sink_path, SECOND_BOOTSTRAP_TELEGRAM_ID)
                assert (await second_client.get("/api/v1/auth/session")).json()["authenticated"]
                disabled = await admin_client.patch(
                    f"/api/v1/admin/users/{second['user_id']}",
                    headers=csrf_headers(admin_client),
                    json={"status": "disabled", "disabled_reason": "Access review"},
                )
                assert disabled.status_code == 200
                assert disabled.json()["status"] == "disabled"
                assert (await second_client.get("/api/v1/auth/session")).json()[
                    "authenticated"
                ] is False

            reenabled = await admin_client.patch(
                f"/api/v1/admin/users/{second['user_id']}",
                headers=csrf_headers(admin_client),
                json={"status": "active"},
            )
            assert reenabled.status_code == 200
            assert reenabled.json()["disabled_reason"] is None

        async with AsyncClient(transport=transport, base_url=ORIGIN) as forged_client:
            forged = await forged_client.get(
                "/api/v1/admin/operation/dashboard",
                headers={"X-MANA-Actor-ID": "forged", "X-MANA-Role": "admin"},
            )
            assert forged.status_code == 401
            service_access = await forged_client.get(
                "/api/v1/admin/operation/dashboard",
                headers={"X-API-Key": "test-service-viewer-key"},
            )
            assert service_access.status_code == 200

    get_settings.cache_clear()


async def test_production_session_cookie_is_secure_and_session_payload_is_minimal(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "production-cookie.db"
    configure_auth_env(monkeypatch, database_path, tmp_path / "unused-sink.jsonl")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("MANA_AUTH_TEST_MODE", "0")
    monkeypatch.delenv("MANA_AUTH_TEST_OTP_SINK_PATH", raising=False)
    monkeypatch.setenv("MANA_TELEGRAM_BOT_TOKEN", "test-production-bot-token")
    monkeypatch.setenv("MANA_TRUSTED_ORIGINS", '["https://admin.example"]')
    monkeypatch.setenv("CORS_ORIGINS", '["https://admin.example"]')
    get_settings.cache_clear()
    app = create_app()
    async with app.router.lifespan_context(app):
        settings = app.state.settings
        sender = CapturingSender()
        app.state.admin_auth_service = AdminAuthService(
            repository=SqlAlchemyAdminAuthRepository(app.state.operation_database),
            sender=sender,
            clock=SystemClock(),
            ids=UuidGenerator(),
            policy=AuthPolicy(
                otp_ttl_seconds=settings.mana_otp_ttl_seconds,
                resend_cooldown_seconds=settings.mana_otp_resend_cooldown_seconds,
                max_verify_attempts=settings.mana_otp_max_verify_attempts,
                request_limit_per_user=settings.mana_otp_request_limit_per_user,
                request_limit_per_ip=settings.mana_otp_request_limit_per_ip,
                verify_limit_per_ip=settings.mana_otp_verify_limit_per_ip,
                global_request_limit=settings.mana_otp_global_request_limit,
                rate_window_seconds=settings.mana_otp_rate_window_seconds,
                lockout_failures=settings.mana_otp_lockout_failures,
                lockout_seconds=settings.mana_otp_lockout_seconds,
                session_ttl_seconds=settings.mana_session_ttl_seconds,
            ),
            hmac_secret=settings.mana_otp_hmac_secret.get_secret_value(),
            bot_username=settings.mana_telegram_bot_username,
        )
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="https://admin.example",
        ) as client:
            requested = await client.post(
                "/api/v1/auth/telegram/request-code",
                headers={"Origin": "https://admin.example"},
                json={"telegram_id": BOOTSTRAP_TELEGRAM_ID},
            )
            assert requested.status_code == 202
            assert sender.code is not None
            verified = await client.post(
                "/api/v1/auth/telegram/verify-code",
                headers={"Origin": "https://admin.example"},
                json={"telegram_id": BOOTSTRAP_TELEGRAM_ID, "code": sender.code},
            )
            assert verified.status_code == 200
            cookies = " ".join(verified.headers.get_list("set-cookie"))
            assert "HttpOnly" in cookies
            assert "Secure" in cookies
            assert "SameSite=lax" in cookies
            user = verified.json()["user"]
            assert set(user) == {
                "user_id",
                "telegram_id",
                "display_name",
                "username",
                "role",
                "permissions",
            }
            assert user["permissions"] == ["view", "operate", "approve", "administer"]
    get_settings.cache_clear()
