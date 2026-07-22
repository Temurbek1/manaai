import os

import pytest

from app.core.config import get_settings
from app.main import create_app
from app.mana_operation_ai.domain.enums import IntegrationStatus, ProviderMode

pytestmark = [
    pytest.mark.live_meta,
    pytest.mark.skipif(
        os.getenv("META_LIVE_READONLY_VERIFY") != "1",
        reason="Live Meta GET checks require META_LIVE_READONLY_VERIFY=1",
    ),
]


async def test_configured_meta_account_health_is_read_only() -> None:
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.meta_live_mode == "read_only"
    assert settings.operation_dry_run is True
    assert settings.meta_real_writes_enabled is False
    assert settings.operation_ads_provider == "meta"

    app = create_app()
    async with app.router.lifespan_context(app):
        health = await app.state.operation_ads_platforms.get("meta").health()

    assert health.status is IntegrationStatus.HEALTHY
    assert health.diagnostics.get("provider_mode") == ProviderMode.LIVE_READ_ONLY.value
    assert health.diagnostics.get("write_operations_available") is False
    assert health.diagnostics.get("account_count") == 1
    assert isinstance(health.diagnostics.get("selected_account_alias"), str)
    get_settings.cache_clear()
