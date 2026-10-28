"""Actual factories and HTTP adapters, using fictional providers exclusively."""

from pathlib import Path

import httpx
import pytest

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.domain.child_safety import ChildSafetyLimits
from app.services import parent_chat_runtime as runtime_module
from app.services.family_source_runtime import family_source_runtime
from app.services.manakids_family_inventory import ManakidsFamilyInventory
from app.services.parent_chat_children import ManakidsChatChildrenSource
from app.services.parent_setup_store import SqliteClosedParentSetupStore, SqliteParentSetupStore
from app.services.setup_collection_store import SqliteSetupCollectionStore
from tests.test_family_collection_adapters import Auth, page
from tests.test_family_source_runtime import NOW, config, make_credential_file
from tests.test_parent_chat_adapters import parent_payload


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("count", [None, 1, 2])
async def test_profile_completeness_needs_exact_count_and_new_explicit_capture(
    enabled: bool, count: int | None
) -> None:
    payload = parent_payload()
    if count is not None:
        payload["results"][0]["children_count"] = count
    requests: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request.method)
        return httpx.Response(200, json={"access": "fake"} if request.method == "POST" else payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        source = ManakidsChatChildrenSource(
            client=client,
            base_url="https://api.manakids.uz",
            username="fake",
            password="fake",
            clock=lambda: NOW,
            include_child_coverage=enabled,
        )
        if count == 2:
            with pytest.raises(ParentChatError):
                await source.read("123")
        else:
            result = await source.read("123")
            assert result.children_complete is (True if count == 1 and enabled else None)
            assert ("children_complete" in result.model_dump()) is (count == 1 and enabled)
    assert requests == ["POST", "GET"]


@pytest.mark.parametrize("enabled", [False, True])
async def test_inventory_proves_each_parent_separately_without_another_request(
    enabled: bool,
) -> None:
    payload = page()
    rows = payload["results"]
    assert isinstance(rows, list)
    rows[0]["children_count"] = 1
    calls: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        inventory = ManakidsFamilyInventory(
            client,
            Auth(),
            base_url="https://api.manakids.uz",
            clock=lambda: NOW,
            include_child_coverage=enabled,
        )
        result = await inventory.read(0, 2)
    assert result.families[0].children_complete is (True if enabled else None)
    assert result.families[1].children_complete is None
    assert "children_complete" not in result.families[1].model_dump()
    assert calls == ["GET"]


async def test_current_factory_active_stopped_closed_and_collection_are_lazy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    requests: list[str] = []

    def deny(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.host or "")
        raise AssertionError("Unexpected idle provider request")

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", lambda **kwargs: httpx.MockTransport(deny))
    flags = (
        "mana_parent_touch_review_first_enabled",
        "mana_child_safety_enabled",
        "mana_child_safety_source_tools_enabled",
        "mana_family_source_safety_enabled",
        "mana_family_app_usage_enabled",
        "mana_family_source_reviews_enabled",
        "mana_parent_reminders_enabled",
        "mana_client_retention_enabled",
        "mana_client_upsell_enabled",
        "mana_retention_expiry_enabled",
        "mana_parent_touch_manager_enabled",
        "mana_parent_touch_clarifications_enabled",
        "mana_parent_support_questions_enabled",
        "mana_client_upsell_currency_enabled",
        "mana_upsell_inline_results_enabled",
        "mana_parent_touch_tariff_handoff_enabled",
        "mana_family_compact_inputs_enabled",
        "mana_parent_touch_compact_publication_enabled",
        "mana_parent_touch_compact_manager_enabled",
        "mana_family_day_usage_enabled",
        "mana_family_location_enabled",
        "mana_family_saved_observations_enabled",
        "mana_family_compact_source_tools_enabled",
        "mana_parent_setup_enabled",
        "mana_parent_touch_proactive_enabled",
    )
    credentials = make_credential_file(tmp_path)
    settings = config(
        tmp_path,
        credentials,
        **dict.fromkeys(flags, True),
        openai_timeout_seconds=30,
        mana_child_safety_limits=ChildSafetyLimits(
            server_daily_tokens=2000,
            parent_daily_tokens=2000,
            job_tokens=2000,
            lease_seconds=360,
        ),
    )
    for enabled in (True, False):
        async with runtime_module.parent_chat_runtime(
            settings.model_copy(update={"mana_parent_setup_enabled": enabled})
        ) as service:
            assert service and isinstance(service.store, SqliteParentSetupStore)
            with service.store._connect() as db:
                assert db.execute("PRAGMA user_version").fetchone()[0] == 42
                assert not db.execute("SELECT 1 FROM setup_epochs").fetchone()
            if enabled:
                async with httpx.AsyncClient(transport=httpx.MockTransport(deny)) as client:
                    profiles = ManakidsChatChildrenSource(
                        client=client,
                        base_url="https://api.manakids.uz",
                        username="fake",
                        password="fake",
                    )
                    sources = await family_source_runtime(
                        settings.model_copy(update={"mana_family_collection_enabled": True}),
                        client,
                        profiles,
                        clock=lambda: NOW,
                        account_auth=profiles,
                        day_identities=profiles,
                        setup_receiver=service.store,
                    )
                    assert sources and isinstance(
                        sources.collection_store, SqliteSetupCollectionStore
                    )
                    assert sources.collection and not await sources.collection.process_one()
    async with runtime_module.parent_chat_runtime(
        settings.model_copy(
            update={"mana_parent_chat_enabled": False, "mana_parent_touch_enabled": False}
        )
    ) as closed:
        assert closed is None
    async with runtime_module.parent_chat_runtime(
        config(
            tmp_path,
            credentials,
            mana_parent_touch_enabled=False,
            mana_family_sources_enabled=False,
        )
    ) as closed:
        assert closed and isinstance(closed.store, SqliteClosedParentSetupStore)
    assert not requests
