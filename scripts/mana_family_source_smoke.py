"""Networkless packaged source/cache acceptance; all family/provider data is fictional."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.config import Settings
from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.domain.chat import ChatChild, ParentChildContext
from app.mana_ai.domain.family_sources import ChildBatteryFacts, FamilySourceTarget
from app.services.family_source_runtime import family_source_runtime

NOW = datetime(2026, 10, 24, 9, tzinfo=UTC)


class Profiles:
    async def read(self, parent_id: str) -> ParentChildContext:
        assert parent_id == "123"
        return ParentChildContext(
            parent_id=parent_id,
            children=[ChatChild(child_id=child, age=8, connected=True) for child in (124, 125)],
            collected_at=NOW,
            limitations=["Synthetic family only"],
        )


class Provider:
    def __init__(self) -> None:
        self.oauth, self.queries = 0, 0

    def handle(self, request: httpx.Request) -> httpx.Response:
        if str(request.url) == "https://oauth2.googleapis.com/token":
            self.oauth += 1
            return httpx.Response(
                200,
                json={
                    "access_token": "fake-source-token",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                },
            )
        assert request.url.host == "firestore.googleapis.com"
        self.queries += 1
        query = json.loads(request.content)["structuredQuery"]
        assert query["limit"] == 2 and "orderBy" not in query
        child = int(query["where"]["fieldFilter"]["value"]["integerValue"])
        if child == 125:
            raise httpx.ReadTimeout("Synthetic unknown response", request=request)
        assert child == 124
        return httpx.Response(
            200,
            json=[
                {
                    "readTime": NOW.isoformat(),
                    "document": {
                        "name": "projects/test-project/databases/(default)/documents/battery/fake",
                        "updateTime": (NOW - timedelta(seconds=1)).isoformat(),
                        "fields": {
                            "childId": {"integerValue": str(child)},
                            "percent": {"integerValue": "12"},
                            "created_at": {
                                "timestampValue": (NOW - timedelta(seconds=2)).isoformat()
                            },
                        },
                    },
                }
            ],
        )


async def run() -> None:
    with TemporaryDirectory(prefix="mana-source-smoke-") as temporary:
        directory = Path(temporary)
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        credentials = directory / "fictional-key.json"
        credentials.write_text(
            json.dumps(
                {
                    "type": "service_account",
                    "project_id": "test-project",
                    "private_key_id": "a" * 40,
                    "private_key": key.private_bytes(
                        serialization.Encoding.PEM,
                        serialization.PrivateFormat.PKCS8,
                        serialization.NoEncryption(),
                    ).decode(),
                    "client_email": "synthetic@test-project.iam.gserviceaccount.com",
                    "token_uri": "https://untrusted.invalid/not-used",
                }
            )
        )
        settings = Settings(
            _env_file=None,
            openai_api_key="fake-key",
            app_api_key="fake-backend-credential-for-networkless-test-only",
            mana_parent_chat_enabled=True,
            mana_parent_touch_enabled=True,
            mana_parent_chat_database_path=directory / "unused-chat.sqlite3",
            manakids_api_username="fake-user",
            manakids_api_password="fake-password",
            mana_family_sources_enabled=True,
            mana_family_firebase_mana_confirmed=True,
            mana_family_source_database_path=directory / "source.sqlite3",
            firebase_project_id="test-project",
            firebase_service_account_file=credentials,
        )
        provider = Provider()
        request = FamilySourceTarget(parent_id="123", child_id=124, request_id=uuid4())
        unknown_request = request.model_copy(update={"child_id": 125, "request_id": uuid4()})
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider.handle)) as client:
            runtime = await family_source_runtime(settings, client, Profiles(), clock=lambda: NOW)
            assert runtime and provider.oauth == provider.queries == 0
            result = await runtime.reads.read_child_battery(request)
            assert result.status == "completed" and isinstance(result.facts, ChildBatteryFacts)
            assert result.facts.percent == 12
            cached = await runtime.reads.read_child_battery(
                request.model_copy(update={"request_id": uuid4()})
            )
            assert cached.cache_hit and cached.facts == result.facts
            unknown = await runtime.reads.read_child_battery(unknown_request)
            assert unknown.status == "unknown" and unknown.document_units_reserved == 2
            restarted = await family_source_runtime(settings, client, Profiles(), clock=lambda: NOW)
            assert restarted and await restarted.reads.read_child_battery(request) == result
            assert await restarted.reads.read_child_battery(unknown_request) == unknown
            try:
                await restarted.reads.read_child_battery(
                    unknown_request.model_copy(update={"request_id": uuid4()})
                )
            except ParentChatError as error:
                assert error.code == "family_source_read_unresolved"
            else:
                raise AssertionError("Unknown reads must not become another provider attempt")
        assert provider.oauth == 1 and provider.queries == 2
        print(json.dumps({"status": "passed", "oauth": 1, "queries": 2, "real_network_calls": 0}))


if __name__ == "__main__":
    asyncio.run(run())
