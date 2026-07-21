import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from httpx import ASGITransport, AsyncClient
from pytest import MonkeyPatch

from app.core.config import get_settings
from app.main import create_app
from app.schemas.marketing import (
    MarketingAnalysisReport,
    MarketingAnalysisRequest,
    MarketingAnalysisResponse,
    MarketingFinding,
    MarketingGraphResponse,
    MarketingKpiSummary,
    MarketingPattern,
    MetaInsightLevel,
    MetaInsightsAsyncJobIngestRequest,
    MetaInsightsAsyncJobRequest,
    MetaSyncRequest,
    RawMarketingRecordInput,
)
from app.services.marketing_analysis_service import MarketingAnalysisService
from app.services.marketing_metrics import MarketingMetricsBuilder
from app.services.marketing_repository import MarketingRepository
from app.services.marketing_sync_service import MarketingSyncService
from app.services.meta_marketing_client import MetaMarketingClient


def configure_test_env(monkeypatch: MonkeyPatch, database_path: Path) -> None:
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.delenv("APP_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("MARKETING_DATABASE_PATH", str(database_path))
    monkeypatch.setenv("META_APP_ID", "test-meta-app-id")
    monkeypatch.delenv("META_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("META_BUSINESS_ID", raising=False)
    monkeypatch.setenv("META_AD_ACCOUNT_IDS", "[]")
    get_settings.cache_clear()


async def test_marketing_config_endpoint(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    configure_test_env(monkeypatch, tmp_path / "marketing.db")
    app = create_app()

    async with app.router.lifespan_context(app), AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/api/v1/marketing/config")

    assert response.status_code == 200
    body = response.json()
    assert body["api_auth_required"] is False
    assert body["api_key_configured"] is False
    assert body["meta_app_id_configured"] is True
    assert response.json()["meta_configured"] is False
    get_settings.cache_clear()


async def test_raw_marketing_ingestion_and_listing(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_test_env(monkeypatch, tmp_path / "marketing.db")
    app = create_app()

    async with app.router.lifespan_context(app), AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        ingest_response = await client.post(
            "/api/v1/marketing/raw",
            json={
                "records": [
                    {
                        "source": "manual_upload",
                        "entity_type": "insight",
                        "provider_record_id": "campaign:1:2026-07-01:2026-07-01",
                        "account_id": "act_100",
                        "observed_at": "2026-07-01T00:00:00+00:00",
                        "payload": {
                            "campaign_id": "1",
                            "campaign_name": "Search prospecting",
                            "date_start": "2026-07-01",
                            "date_stop": "2026-07-01",
                            "spend": "100",
                            "impressions": "10000",
                            "clicks": "250",
                            "actions": [{"action_type": "lead", "value": "20"}],
                        },
                    },
                ],
            },
        )
        list_response = await client.get(
            "/api/v1/marketing/raw",
            params={"account_id": "act_100", "entity_type": "insight"},
        )

    assert ingest_response.status_code == 201
    assert ingest_response.json()["inserted_count"] == 1
    assert list_response.status_code == 200
    body = list_response.json()
    assert body["total"] == 1
    assert body["records"][0]["payload"]["campaign_name"] == "Search prospecting"
    get_settings.cache_clear()


async def test_raw_marketing_search_filters_payload_dimensions_and_provider_ids(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_test_env(monkeypatch, tmp_path / "marketing.db")
    app = create_app()

    async with app.router.lifespan_context(app), AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        ingest_response = await client.post(
            "/api/v1/marketing/raw",
            json={
                "records": [
                    {
                        "source": "manual_upload",
                        "entity_type": "insight",
                        "provider_record_id": "ad:1:2026-07-01:dim-facebook-feed",
                        "account_id": "act_100",
                        "observed_at": "2026-07-01T00:00:00+00:00",
                        "payload": {
                            "_meta_level": "ad",
                            "ad_id": "1",
                            "date_start": "2026-07-01",
                            "date_stop": "2026-07-01",
                            "spend": "100",
                            "publisher_platform": "facebook",
                            "platform_position": "feed",
                        },
                    },
                    {
                        "source": "manual_upload",
                        "entity_type": "insight",
                        "provider_record_id": "ad:2:2026-07-01:dim-facebook-feed",
                        "account_id": "act_100",
                        "observed_at": "2026-07-01T00:00:00+00:00",
                        "payload": {
                            "_meta_level": "ad",
                            "ad_id": "2",
                            "date_start": "2026-07-01",
                            "date_stop": "2026-07-01",
                            "spend": "25",
                            "publisher_platform": "facebook",
                            "platform_position": "feed",
                        },
                    },
                    {
                        "source": "manual_upload",
                        "entity_type": "insight",
                        "provider_record_id": "ad:3:2026-07-01:dim-instagram-stories",
                        "account_id": "act_100",
                        "observed_at": "2026-07-01T00:00:00+00:00",
                        "payload": {
                            "_meta_level": "ad",
                            "ad_id": "3",
                            "date_start": "2026-07-01",
                            "date_stop": "2026-07-01",
                            "spend": "10",
                            "publisher_platform": "instagram",
                            "platform_position": "stories",
                        },
                    },
                ],
            },
        )
        dimension_response = await client.post(
            "/api/v1/marketing/raw/search",
            json={
                "account_ids": ["act_100"],
                "entity_types": ["insight"],
                "payload_filters": {"_meta_level": "ad"},
                "dimension_filters": {"publisher_platform": "facebook"},
                "limit": 10,
            },
        )
        provider_response = await client.post(
            "/api/v1/marketing/raw/search",
            json={
                "provider_record_ids": ["ad:3:2026-07-01:dim-instagram-stories"],
            },
        )
        invalid_response = await client.post(
            "/api/v1/marketing/raw/search",
            json={"payload_filters": {"nested.field": "not-allowed"}},
        )

    assert ingest_response.status_code == 201
    assert dimension_response.status_code == 200
    dimension_body = dimension_response.json()
    assert dimension_body["total"] == 2
    assert {
        record["provider_record_id"] for record in dimension_body["records"]
    } == {
        "ad:1:2026-07-01:dim-facebook-feed",
        "ad:2:2026-07-01:dim-facebook-feed",
    }
    assert provider_response.status_code == 200
    assert provider_response.json()["total"] == 1
    assert provider_response.json()["records"][0]["payload"]["publisher_platform"] == "instagram"
    assert invalid_response.status_code == 422
    get_settings.cache_clear()


async def test_marketing_metrics_builder_computes_kpis(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_test_env(monkeypatch, tmp_path / "marketing.db")
    repository = MarketingRepository(database_path=tmp_path / "marketing.db")
    await repository.initialize()
    inserted = await repository.insert_raw_records(
        [
            RawMarketingRecordInput(
                source="manual_upload",
                entity_type="insight",
                account_id="act_100",
                payload={
                    "_meta_level": "campaign",
                    "campaign_id": "1",
                    "campaign_name": "Prospecting",
                    "date_start": "2026-07-01",
                    "date_stop": "2026-07-01",
                    "spend": "200",
                    "impressions": "20000",
                    "reach": "15000",
                    "clicks": "500",
                    "inline_link_clicks": "450",
                    "actions": [{"action_type": "purchase", "value": "10"}],
                    "action_values": [{"action_type": "purchase", "value": "1000"}],
                    "publisher_platform": "facebook",
                    "platform_position": "feed",
                },
            ),
        ],
    )
    builder = MarketingMetricsBuilder(
        conversion_action_types=["purchase"],
        value_action_types=["purchase"],
    )

    rows = builder.build_rows(inserted)
    summary = builder.summarize(rows)

    assert len(rows) == 1
    assert rows[0].ctr == 0.025
    assert rows[0].cpc == 0.4
    assert rows[0].cpa == 20
    assert rows[0].roas == 5
    assert rows[0].dimensions == {
        "platform_position": "feed",
        "publisher_platform": "facebook",
    }
    assert summary.total_spend == 200
    get_settings.cache_clear()


async def test_marketing_patterns_endpoint_detects_wasted_spend(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_test_env(monkeypatch, tmp_path / "marketing.db")
    app = create_app()

    async with app.router.lifespan_context(app), AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        ingest_response = await client.post(
            "/api/v1/marketing/raw",
            json={
                "records": [
                    {
                        "source": "manual_upload",
                        "entity_type": "insight",
                        "account_id": "act_100",
                        "payload": {
                            "_meta_level": "ad",
                            "ad_id": "ad-waste",
                            "ad_name": "Expensive ad",
                            "date_start": "2026-07-01",
                            "date_stop": "2026-07-01",
                            "spend": "100",
                            "impressions": "10000",
                            "clicks": "200",
                            "publisher_platform": "facebook",
                            "platform_position": "feed",
                        },
                    },
                    {
                        "source": "manual_upload",
                        "entity_type": "insight",
                        "account_id": "act_100",
                        "payload": {
                            "_meta_level": "ad",
                            "ad_id": "ad-waste-2",
                            "ad_name": "Second expensive ad",
                            "date_start": "2026-07-01",
                            "date_stop": "2026-07-01",
                            "spend": "25",
                            "impressions": "2500",
                            "clicks": "50",
                            "publisher_platform": "facebook",
                            "platform_position": "feed",
                        },
                    },
                    {
                        "source": "manual_upload",
                        "entity_type": "insight",
                        "account_id": "act_100",
                        "payload": {
                            "_meta_level": "ad",
                            "ad_id": "ad-efficient",
                            "ad_name": "Efficient ad",
                            "date_start": "2026-07-01",
                            "date_stop": "2026-07-01",
                            "spend": "10",
                            "impressions": "2000",
                            "clicks": "100",
                            "actions": [{"action_type": "lead", "value": "5"}],
                            "publisher_platform": "instagram",
                            "platform_position": "stories",
                        },
                    },
                ],
            },
        )
        pattern_response = await client.post(
            "/api/v1/marketing/patterns",
            json={"account_ids": ["act_100"], "max_patterns": 10},
        )

    assert ingest_response.status_code == 201
    assert pattern_response.status_code == 200
    body = pattern_response.json()
    assert body["source_record_count"] == 3
    assert "wasted_spend" in {pattern["type"] for pattern in body["patterns"]}
    assert "segment_waste" in {pattern["type"] for pattern in body["patterns"]}
    assert "segment_efficiency_opportunity" in {
        pattern["type"] for pattern in body["patterns"]
    }
    wasted_pattern = next(
        pattern for pattern in body["patterns"] if pattern["type"] == "wasted_spend"
    )
    assert wasted_pattern["dimensions"] == {
        "platform_position": "feed",
        "publisher_platform": "facebook",
    }
    assert any(
        pattern["type"] == "segment_waste"
        and pattern["value"] == 125
        and pattern["dimensions"] == {"publisher_platform": "facebook"}
        for pattern in body["patterns"]
    )
    get_settings.cache_clear()


async def test_marketing_patterns_endpoint_detects_creative_rollup_waste(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_test_env(monkeypatch, tmp_path / "marketing.db")
    app = create_app()

    async with app.router.lifespan_context(app), AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        ingest_response = await client.post(
            "/api/v1/marketing/raw",
            json={
                "records": [
                    {
                        "source": "manual_upload",
                        "entity_type": "creative",
                        "provider_record_id": "creative-1",
                        "account_id": "act_100",
                        "payload": {
                            "id": "creative-1",
                            "name": "Variant A",
                            "title": "Variant A headline",
                        },
                    },
                    {
                        "source": "manual_upload",
                        "entity_type": "ad",
                        "provider_record_id": "ad-1",
                        "account_id": "act_100",
                        "payload": {
                            "id": "ad-1",
                            "name": "Ad 1",
                            "creative": {"id": "creative-1"},
                        },
                    },
                    {
                        "source": "manual_upload",
                        "entity_type": "ad",
                        "provider_record_id": "ad-2",
                        "account_id": "act_100",
                        "payload": {
                            "id": "ad-2",
                            "name": "Ad 2",
                            "creative": {"id": "creative-1"},
                        },
                    },
                    {
                        "source": "manual_upload",
                        "entity_type": "insight",
                        "account_id": "act_100",
                        "payload": {
                            "_meta_level": "ad",
                            "ad_id": "ad-1",
                            "ad_name": "Ad 1",
                            "date_start": "2026-07-01",
                            "date_stop": "2026-07-01",
                            "spend": "80",
                            "impressions": "8000",
                            "clicks": "160",
                        },
                    },
                    {
                        "source": "manual_upload",
                        "entity_type": "insight",
                        "account_id": "act_100",
                        "payload": {
                            "_meta_level": "ad",
                            "ad_id": "ad-2",
                            "ad_name": "Ad 2",
                            "date_start": "2026-07-01",
                            "date_stop": "2026-07-01",
                            "spend": "40",
                            "impressions": "4000",
                            "clicks": "80",
                        },
                    },
                    {
                        "source": "manual_upload",
                        "entity_type": "insight",
                        "account_id": "act_100",
                        "payload": {
                            "_meta_level": "ad",
                            "ad_id": "ad-control",
                            "ad_name": "Control ad",
                            "date_start": "2026-07-01",
                            "date_stop": "2026-07-01",
                            "spend": "40",
                            "impressions": "6000",
                            "clicks": "100",
                            "actions": [{"action_type": "lead", "value": "4"}],
                        },
                    },
                ],
            },
        )
        pattern_response = await client.post(
            "/api/v1/marketing/patterns",
            json={"account_ids": ["act_100"], "max_patterns": 20},
        )

    assert ingest_response.status_code == 201
    assert pattern_response.status_code == 200
    body = pattern_response.json()
    assert body["source_record_count"] == 6
    creative_pattern = next(
        pattern for pattern in body["patterns"] if pattern["type"] == "creative_waste"
    )
    assert creative_pattern["entity_id"] == "creative-1"
    assert creative_pattern["entity_name"] == "Variant A"
    assert creative_pattern["level"] == "creative"
    assert creative_pattern["value"] == 120
    assert creative_pattern["dimensions"] == {"creative_id": "creative-1"}
    assert len(creative_pattern["evidence_record_ids"]) == 3
    get_settings.cache_clear()


async def test_marketing_patterns_endpoint_detects_audience_rollup_waste(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_test_env(monkeypatch, tmp_path / "marketing.db")
    app = create_app()

    async with app.router.lifespan_context(app), AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        ingest_response = await client.post(
            "/api/v1/marketing/raw",
            json={
                "records": [
                    {
                        "source": "manual_upload",
                        "entity_type": "custom_audience",
                        "provider_record_id": "audience-1",
                        "account_id": "act_100",
                        "payload": {
                            "id": "audience-1",
                            "name": "Retargeting 30d",
                            "subtype": "WEBSITE",
                        },
                    },
                    {
                        "source": "manual_upload",
                        "entity_type": "adset",
                        "provider_record_id": "adset-1",
                        "account_id": "act_100",
                        "payload": {
                            "id": "adset-1",
                            "name": "Retargeting ad set",
                            "targeting": {
                                "custom_audiences": [
                                    {"id": "audience-1", "name": "Retargeting 30d"},
                                ],
                            },
                        },
                    },
                    {
                        "source": "manual_upload",
                        "entity_type": "ad",
                        "provider_record_id": "ad-1",
                        "account_id": "act_100",
                        "parent_id": "adset-1",
                        "payload": {
                            "id": "ad-1",
                            "name": "Audience ad 1",
                            "adset_id": "adset-1",
                        },
                    },
                    {
                        "source": "manual_upload",
                        "entity_type": "ad",
                        "provider_record_id": "ad-2",
                        "account_id": "act_100",
                        "parent_id": "adset-1",
                        "payload": {
                            "id": "ad-2",
                            "name": "Audience ad 2",
                            "adset_id": "adset-1",
                        },
                    },
                    {
                        "source": "manual_upload",
                        "entity_type": "insight",
                        "account_id": "act_100",
                        "payload": {
                            "_meta_level": "ad",
                            "ad_id": "ad-1",
                            "ad_name": "Audience ad 1",
                            "date_start": "2026-07-01",
                            "date_stop": "2026-07-01",
                            "spend": "80",
                            "impressions": "8000",
                            "clicks": "160",
                        },
                    },
                    {
                        "source": "manual_upload",
                        "entity_type": "insight",
                        "account_id": "act_100",
                        "payload": {
                            "_meta_level": "ad",
                            "ad_id": "ad-2",
                            "ad_name": "Audience ad 2",
                            "date_start": "2026-07-01",
                            "date_stop": "2026-07-01",
                            "spend": "40",
                            "impressions": "4000",
                            "clicks": "80",
                        },
                    },
                    {
                        "source": "manual_upload",
                        "entity_type": "insight",
                        "account_id": "act_100",
                        "payload": {
                            "_meta_level": "ad",
                            "ad_id": "ad-control",
                            "ad_name": "Control ad",
                            "date_start": "2026-07-01",
                            "date_stop": "2026-07-01",
                            "spend": "40",
                            "impressions": "6000",
                            "clicks": "100",
                            "actions": [{"action_type": "lead", "value": "4"}],
                        },
                    },
                ],
            },
        )
        pattern_response = await client.post(
            "/api/v1/marketing/patterns",
            json={"account_ids": ["act_100"], "max_patterns": 20},
        )

    assert ingest_response.status_code == 201
    assert pattern_response.status_code == 200
    body = pattern_response.json()
    assert body["source_record_count"] == 7
    audience_pattern = next(
        pattern for pattern in body["patterns"] if pattern["type"] == "audience_waste"
    )
    assert audience_pattern["entity_id"] == "audience-1"
    assert audience_pattern["entity_name"] == "Retargeting 30d"
    assert audience_pattern["level"] == "custom_audience"
    assert audience_pattern["value"] == 120
    assert audience_pattern["dimensions"] == {
        "custom_audience_id": "audience-1",
        "targeting_role": "included",
    }
    assert len(audience_pattern["evidence_record_ids"]) == 4
    get_settings.cache_clear()


async def test_marketing_patterns_endpoint_detects_hierarchy_rollup_waste(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_test_env(monkeypatch, tmp_path / "marketing.db")
    app = create_app()

    async with app.router.lifespan_context(app), AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        ingest_response = await client.post(
            "/api/v1/marketing/raw",
            json={
                "records": [
                    {
                        "source": "manual_upload",
                        "entity_type": "campaign",
                        "provider_record_id": "campaign-1",
                        "account_id": "act_100",
                        "payload": {"id": "campaign-1", "name": "Prospecting"},
                    },
                    {
                        "source": "manual_upload",
                        "entity_type": "adset",
                        "provider_record_id": "adset-1",
                        "account_id": "act_100",
                        "parent_id": "campaign-1",
                        "payload": {
                            "id": "adset-1",
                            "name": "Broad ad set",
                            "campaign_id": "campaign-1",
                        },
                    },
                    {
                        "source": "manual_upload",
                        "entity_type": "ad",
                        "provider_record_id": "ad-1",
                        "account_id": "act_100",
                        "parent_id": "adset-1",
                        "payload": {
                            "id": "ad-1",
                            "name": "Ad 1",
                            "adset_id": "adset-1",
                        },
                    },
                    {
                        "source": "manual_upload",
                        "entity_type": "ad",
                        "provider_record_id": "ad-2",
                        "account_id": "act_100",
                        "parent_id": "adset-1",
                        "payload": {
                            "id": "ad-2",
                            "name": "Ad 2",
                            "adset_id": "adset-1",
                        },
                    },
                    {
                        "source": "manual_upload",
                        "entity_type": "insight",
                        "account_id": "act_100",
                        "payload": {
                            "_meta_level": "ad",
                            "ad_id": "ad-1",
                            "ad_name": "Ad 1",
                            "date_start": "2026-07-01",
                            "date_stop": "2026-07-01",
                            "spend": "80",
                            "impressions": "8000",
                            "clicks": "160",
                        },
                    },
                    {
                        "source": "manual_upload",
                        "entity_type": "insight",
                        "account_id": "act_100",
                        "payload": {
                            "_meta_level": "ad",
                            "ad_id": "ad-2",
                            "ad_name": "Ad 2",
                            "date_start": "2026-07-01",
                            "date_stop": "2026-07-01",
                            "spend": "40",
                            "impressions": "4000",
                            "clicks": "80",
                        },
                    },
                    {
                        "source": "manual_upload",
                        "entity_type": "insight",
                        "account_id": "act_100",
                        "payload": {
                            "_meta_level": "ad",
                            "ad_id": "ad-control",
                            "ad_name": "Control ad",
                            "date_start": "2026-07-01",
                            "date_stop": "2026-07-01",
                            "spend": "40",
                            "impressions": "6000",
                            "clicks": "100",
                            "actions": [{"action_type": "lead", "value": "4"}],
                        },
                    },
                ],
            },
        )
        pattern_response = await client.post(
            "/api/v1/marketing/patterns",
            json={"account_ids": ["act_100"], "max_patterns": 20},
        )

    assert ingest_response.status_code == 201
    assert pattern_response.status_code == 200
    body = pattern_response.json()
    assert body["source_record_count"] == 7
    adset_pattern = next(
        pattern for pattern in body["patterns"] if pattern["type"] == "adset_rollup_waste"
    )
    campaign_pattern = next(
        pattern for pattern in body["patterns"] if pattern["type"] == "campaign_rollup_waste"
    )
    assert adset_pattern["entity_id"] == "adset-1"
    assert adset_pattern["entity_name"] == "Broad ad set"
    assert adset_pattern["dimensions"] == {
        "adset_id": "adset-1",
        "rollup_level": "adset",
    }
    assert adset_pattern["value"] == 120
    assert len(adset_pattern["evidence_record_ids"]) == 3
    assert campaign_pattern["entity_id"] == "campaign-1"
    assert campaign_pattern["entity_name"] == "Prospecting"
    assert campaign_pattern["dimensions"] == {
        "campaign_id": "campaign-1",
        "rollup_level": "campaign",
    }
    assert campaign_pattern["value"] == 120
    assert len(campaign_pattern["evidence_record_ids"]) == 3
    get_settings.cache_clear()


async def test_marketing_patterns_endpoint_detects_unmapped_action_signals(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_test_env(monkeypatch, tmp_path / "marketing.db")
    app = create_app()

    async with app.router.lifespan_context(app), AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        ingest_response = await client.post(
            "/api/v1/marketing/raw",
            json={
                "records": [
                    {
                        "source": "manual_upload",
                        "entity_type": "insight",
                        "account_id": "act_100",
                        "payload": {
                            "_meta_level": "ad",
                            "ad_id": "ad-unmapped-action",
                            "ad_name": "Ad with unmapped action",
                            "date_start": "2026-07-01",
                            "date_stop": "2026-07-01",
                            "spend": "100",
                            "impressions": "10000",
                            "clicks": "200",
                            "actions": [
                                {
                                    "action_type": "offsite_conversion.fb_pixel_custom",
                                    "value": "7",
                                },
                            ],
                        },
                    },
                    {
                        "source": "manual_upload",
                        "entity_type": "insight",
                        "account_id": "act_100",
                        "payload": {
                            "_meta_level": "ad",
                            "ad_id": "ad-efficient",
                            "ad_name": "Efficient ad",
                            "date_start": "2026-07-01",
                            "date_stop": "2026-07-01",
                            "spend": "25",
                            "impressions": "3000",
                            "clicks": "100",
                            "actions": [{"action_type": "lead", "value": "5"}],
                        },
                    },
                ],
            },
        )
        pattern_response = await client.post(
            "/api/v1/marketing/patterns",
            json={"account_ids": ["act_100"], "max_patterns": 20},
        )

    assert ingest_response.status_code == 201
    assert pattern_response.status_code == 200
    body = pattern_response.json()
    action_pattern = next(
        pattern for pattern in body["patterns"] if pattern["type"] == "unmapped_action_signal"
    )
    assert action_pattern["direction"] == "neutral"
    assert action_pattern["metric"] == "unmapped_action_value"
    assert action_pattern["value"] == 7
    assert action_pattern["dimensions"] == {
        "action_type": "offsite_conversion.fb_pixel_custom",
        "configured_conversion_action_types": "5",
    }
    assert len(action_pattern["evidence_record_ids"]) == 1
    get_settings.cache_clear()


async def test_marketing_patterns_endpoint_detects_measurement_health_issues(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_test_env(monkeypatch, tmp_path / "marketing.db")
    app = create_app()

    async with app.router.lifespan_context(app), AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        ingest_response = await client.post(
            "/api/v1/marketing/raw",
            json={
                "records": [
                    {
                        "source": "manual_upload",
                        "entity_type": "insight",
                        "account_id": "act_100",
                        "payload": {
                            "_meta_level": "ad",
                            "ad_id": "ad-measurement",
                            "ad_name": "Ad with measurement issue",
                            "date_start": "2026-07-01",
                            "date_stop": "2026-07-01",
                            "spend": "100",
                            "impressions": "10000",
                            "clicks": "150",
                            "actions": [{"action_type": "lead", "value": "3"}],
                        },
                    },
                    {
                        "source": "manual_upload",
                        "entity_type": "pixel",
                        "provider_record_id": "pixel-1",
                        "payload": {
                            "id": "pixel-1",
                            "name": "Website Pixel",
                            "is_unavailable": True,
                            "last_fired_time": "2020-01-01T00:00:00+00:00",
                        },
                    },
                    {
                        "source": "manual_upload",
                        "entity_type": "custom_conversion",
                        "provider_record_id": "custom-conversion-1",
                        "account_id": "act_100",
                        "parent_id": "pixel-1",
                        "payload": {
                            "id": "custom-conversion-1",
                            "name": "Purchase conversion",
                            "pixel": {"id": "pixel-1"},
                            "is_archived": True,
                            "last_fired_time": "2020-01-01T00:00:00+00:00",
                        },
                    },
                ],
            },
        )
        pattern_response = await client.post(
            "/api/v1/marketing/patterns",
            json={"account_ids": ["act_100"], "max_patterns": 20},
        )

    assert ingest_response.status_code == 201
    assert pattern_response.status_code == 200
    body = pattern_response.json()
    assert body["source_record_count"] == 3

    pattern_types = {pattern["type"] for pattern in body["patterns"]}
    assert {
        "pixel_unavailable",
        "custom_conversion_archived",
        "measurement_event_stale",
    } <= pattern_types

    pixel_pattern = next(
        pattern for pattern in body["patterns"] if pattern["type"] == "pixel_unavailable"
    )
    assert pixel_pattern["entity_id"] == "pixel-1"
    assert pixel_pattern["level"] == "pixel"
    assert pixel_pattern["dimensions"] == {"measurement_entity_type": "pixel"}
    assert len(pixel_pattern["evidence_record_ids"]) == 1

    custom_conversion_pattern = next(
        pattern
        for pattern in body["patterns"]
        if pattern["type"] == "custom_conversion_archived"
    )
    assert custom_conversion_pattern["entity_id"] == "custom-conversion-1"
    assert custom_conversion_pattern["dimensions"] == {
        "measurement_entity_type": "custom_conversion",
        "pixel_id": "pixel-1",
    }

    stale_patterns = [
        pattern for pattern in body["patterns"] if pattern["type"] == "measurement_event_stale"
    ]
    assert any(
        pattern["entity_id"] == "pixel-1"
        and pattern["metric"] == "days_since_last_fired"
        and pattern["value"] > 14
        and pattern["benchmark"] == 14
        for pattern in stale_patterns
    )
    get_settings.cache_clear()


async def test_marketing_patterns_endpoint_reports_measurement_health_without_insights(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_test_env(monkeypatch, tmp_path / "marketing.db")
    app = create_app()

    async with app.router.lifespan_context(app), AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        ingest_response = await client.post(
            "/api/v1/marketing/raw",
            json={
                "records": [
                    {
                        "source": "manual_upload",
                        "entity_type": "pixel",
                        "provider_record_id": "pixel-1",
                        "payload": {
                            "id": "pixel-1",
                            "name": "Website Pixel",
                            "is_unavailable": True,
                        },
                    },
                ],
            },
        )
        pattern_response = await client.post(
            "/api/v1/marketing/patterns",
            json={"account_ids": ["act_100"], "max_patterns": 10},
        )

    assert ingest_response.status_code == 201
    assert pattern_response.status_code == 200
    body = pattern_response.json()
    assert body["source_record_count"] == 1
    assert {"data_quality", "pixel_unavailable"} <= {
        pattern["type"] for pattern in body["patterns"]
    }
    get_settings.cache_clear()


async def test_marketing_graph_endpoint_builds_entity_edges(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_test_env(monkeypatch, tmp_path / "marketing.db")
    app = create_app()

    async with app.router.lifespan_context(app), AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        ingest_response = await client.post(
            "/api/v1/marketing/raw",
            json={
                "records": [
                    {
                        "source": "manual_upload",
                        "entity_type": "campaign",
                        "provider_record_id": "campaign-1",
                        "account_id": "act_100",
                        "payload": {"id": "campaign-1", "name": "Campaign"},
                    },
                    {
                        "source": "manual_upload",
                        "entity_type": "adset",
                        "provider_record_id": "adset-1",
                        "account_id": "act_100",
                        "parent_id": "campaign-1",
                        "payload": {
                            "id": "adset-1",
                            "name": "Ad set",
                            "campaign_id": "campaign-1",
                            "targeting": {
                                "custom_audiences": [
                                    {"id": "audience-1", "name": "High value customers"},
                                ],
                                "excluded_custom_audiences": [
                                    {"id": "audience-2", "name": "Existing buyers"},
                                ],
                            },
                        },
                    },
                    {
                        "source": "manual_upload",
                        "entity_type": "custom_audience",
                        "provider_record_id": "audience-1",
                        "account_id": "act_100",
                        "payload": {
                            "id": "audience-1",
                            "name": "High value customers",
                            "subtype": "CUSTOM",
                            "approximate_count": 1500,
                        },
                    },
                    {
                        "source": "manual_upload",
                        "entity_type": "ad",
                        "provider_record_id": "ad-1",
                        "account_id": "act_100",
                        "parent_id": "adset-1",
                        "payload": {
                            "id": "ad-1",
                            "name": "Ad",
                            "adset_id": "adset-1",
                            "creative": {"id": "creative-1"},
                        },
                    },
                    {
                        "source": "manual_upload",
                        "entity_type": "creative",
                        "provider_record_id": "creative-1",
                        "account_id": "act_100",
                        "payload": {
                            "id": "creative-1",
                            "name": "Creative",
                            "title": "Creative headline",
                            "body": "Creative primary text",
                            "object_type": "SHARE",
                            "call_to_action_type": "LEARN_MORE",
                        },
                    },
                    {
                        "source": "manual_upload",
                        "entity_type": "pixel",
                        "provider_record_id": "pixel-1",
                        "parent_id": "business-1",
                        "payload": {
                            "id": "pixel-1",
                            "name": "Website Pixel",
                            "owner_business": {"id": "business-1"},
                        },
                    },
                    {
                        "source": "manual_upload",
                        "entity_type": "custom_conversion",
                        "provider_record_id": "custom-conversion-1",
                        "account_id": "act_100",
                        "parent_id": "pixel-1",
                        "payload": {
                            "id": "custom-conversion-1",
                            "name": "Purchase conversion",
                            "custom_event_type": "PURCHASE",
                            "event_source_type": "PIXEL",
                            "pixel": {"id": "pixel-1"},
                            "rule": {"event": {"eq": "Purchase"}},
                        },
                    },
                    {
                        "source": "manual_upload",
                        "entity_type": "insight",
                        "account_id": "act_100",
                        "payload": {
                            "ad_id": "ad-1",
                            "date_start": "2026-07-01",
                            "date_stop": "2026-07-01",
                            "spend": "25",
                            "impressions": "1000",
                            "clicks": "50",
                        },
                    },
                ],
            },
        )
        graph_response = await client.post(
            "/api/v1/marketing/graph",
            json={"account_ids": ["act_100"], "include_insights": True},
        )

    assert ingest_response.status_code == 201
    assert graph_response.status_code == 200
    body = graph_response.json()
    edge_pairs = {(edge["source_id"], edge["target_id"], edge["type"]) for edge in body["edges"]}
    assert ("campaign:campaign-1", "adset:adset-1", "contains") in edge_pairs
    assert ("adset:adset-1", "ad:ad-1", "contains") in edge_pairs
    assert ("ad:ad-1", "creative:creative-1", "created_from") in edge_pairs
    assert ("business:business-1", "pixel:pixel-1", "owns") in edge_pairs
    assert ("pixel:pixel-1", "custom_conversion:custom-conversion-1", "reports") in edge_pairs
    assert ("adset:adset-1", "custom_audience:audience-1", "targets") in edge_pairs
    assert ("adset:adset-1", "custom_audience:audience-2", "targets") in edge_pairs
    assert any(edge_type == "measures" for _, _, edge_type in edge_pairs)
    creative_node = next(node for node in body["nodes"] if node["id"] == "creative:creative-1")
    assert creative_node["attributes"]["title"] == "Creative headline"
    assert creative_node["attributes"]["call_to_action_type"] == "LEARN_MORE"
    conversion_node = next(
        node for node in body["nodes"] if node["id"] == "custom_conversion:custom-conversion-1"
    )
    assert conversion_node["attributes"]["custom_event_type"] == "PURCHASE"
    audience_node = next(
        node for node in body["nodes"] if node["id"] == "custom_audience:audience-1"
    )
    assert audience_node["attributes"]["subtype"] == "CUSTOM"
    get_settings.cache_clear()


async def test_marketing_repository_saves_and_reads_analysis_reports(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_test_env(monkeypatch, tmp_path / "marketing.db")
    repository = MarketingRepository(database_path=tmp_path / "marketing.db")
    await repository.initialize()
    request = MarketingAnalysisRequest(question="Audit report persistence")
    response = _make_marketing_analysis_response(
        report_id="report-history-1",
        executive_summary="Stored report summary.",
    )

    await repository.save_analysis_report(request=request, response=response)
    summaries, total = await repository.list_analysis_reports(limit=10, offset=0)
    loaded = await repository.get_analysis_report("report-history-1")

    assert total == 1
    assert summaries[0].report_id == "report-history-1"
    assert loaded is not None
    assert loaded.report.executive_summary == "Stored report summary."
    assert loaded.graph.source_record_count == 0
    get_settings.cache_clear()


async def test_marketing_repository_reads_legacy_analysis_report_rows(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "marketing.db"
    configure_test_env(monkeypatch, database_path)
    repository = MarketingRepository(database_path=database_path)
    await repository.initialize()
    report = _make_marketing_analysis_response(
        report_id="legacy-report-1",
        executive_summary="Legacy report summary.",
    )

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO marketing_analysis_reports (
                id,
                generated_at,
                model,
                source_record_count,
                request_json,
                kpi_json,
                report_json,
                source_record_ids_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-report-1",
                report.generated_at.isoformat(),
                report.model,
                1,
                MarketingAnalysisRequest(question="Legacy report").model_dump_json(),
                report.kpi_summary.model_dump_json(),
                report.report.model_dump_json(),
                '["raw-record-1"]',
            ),
        )

    loaded = await repository.get_analysis_report("legacy-report-1")

    assert loaded is not None
    assert loaded.report.executive_summary == "Legacy report summary."
    assert loaded.source_record_ids == ["raw-record-1"]
    assert loaded.patterns == []
    assert loaded.graph.source_record_count == 1
    get_settings.cache_clear()


async def test_marketing_reports_endpoints_return_saved_analysis_reports(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_test_env(monkeypatch, tmp_path / "marketing.db")
    app = create_app()
    saved_report = _make_marketing_analysis_response(
        report_id="api-report-1",
        executive_summary="Saved API report.",
    )

    async with app.router.lifespan_context(app), AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        repository = cast(MarketingRepository, app.state.marketing_repository)
        await repository.save_analysis_report(
            request=MarketingAnalysisRequest(question="Expose saved reports"),
            response=saved_report,
        )
        list_response = await client.get("/api/v1/marketing/reports")
        detail_response = await client.get("/api/v1/marketing/reports/api-report-1")
        missing_response = await client.get("/api/v1/marketing/reports/missing-report")

    assert list_response.status_code == 200
    assert list_response.json()["total"] == 1
    assert list_response.json()["reports"][0]["report_id"] == "api-report-1"
    assert detail_response.status_code == 200
    assert detail_response.json()["report"]["executive_summary"] == "Saved API report."
    assert missing_response.status_code == 404
    get_settings.cache_clear()


async def test_marketing_report_evidence_endpoint_returns_referenced_raw_records(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_test_env(monkeypatch, tmp_path / "marketing.db")
    app = create_app()

    async with app.router.lifespan_context(app), AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        repository = cast(MarketingRepository, app.state.marketing_repository)
        inserted = await repository.insert_raw_records(
            [
                RawMarketingRecordInput(
                    source="manual_upload",
                    entity_type="insight",
                    account_id="act_100",
                    payload={
                        "_meta_level": "ad",
                        "ad_id": "ad-1",
                        "spend": "25",
                        "clicks": "50",
                    },
                ),
                RawMarketingRecordInput(
                    source="manual_upload",
                    entity_type="creative",
                    provider_record_id="creative-1",
                    account_id="act_100",
                    payload={"id": "creative-1", "name": "Creative"},
                ),
            ],
        )
        saved_report = _make_marketing_analysis_response(
            report_id="api-report-evidence-1",
            executive_summary="Saved API report with evidence.",
        ).model_copy(
            update={
                "source_record_count": 2,
                "source_record_ids": [inserted[0].id],
                "patterns": [
                    MarketingPattern(
                        type="creative_waste",
                        direction="negative",
                        title="Creative has waste",
                        explanation="Creative evidence is stored for audit.",
                        entity_id="creative-1",
                        entity_name="Creative",
                        level="creative",
                        metric="creative_spend_without_conversions",
                        value=25,
                        benchmark=1,
                        confidence="high",
                        evidence_record_ids=[inserted[1].id, "missing-record-id"],
                        suggested_raw_queries=[
                            "Search raw records by provider_record_id=creative-1.",
                        ],
                        dimensions={"creative_id": "creative-1"},
                    ),
                ],
            },
        )
        await repository.save_analysis_report(
            request=MarketingAnalysisRequest(question="Expose evidence bundle"),
            response=saved_report,
        )

        bundle_response = await client.get(
            "/api/v1/marketing/reports/api-report-evidence-1/evidence",
        )
        missing_response = await client.get(
            "/api/v1/marketing/reports/missing-report/evidence",
        )

    assert bundle_response.status_code == 200
    body = bundle_response.json()
    assert body["report"]["report_id"] == "api-report-evidence-1"
    assert [record["id"] for record in body["raw_records"]] == [
        inserted[0].id,
        inserted[1].id,
    ]
    assert body["missing_record_ids"] == ["missing-record-id"]
    assert body["raw_records"][1]["payload"]["name"] == "Creative"
    assert missing_response.status_code == 404
    get_settings.cache_clear()


async def test_meta_sync_service_stores_structure_and_insights(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_test_env(monkeypatch, tmp_path / "marketing.db")
    repository = MarketingRepository(database_path=tmp_path / "marketing.db")
    await repository.initialize()
    service = MarketingSyncService(
        meta_client=cast(MetaMarketingClient, FakeMetaMarketingClient()),
        repository=repository,
    )

    response = await service.sync_meta(
        MetaSyncRequest(
            date_start="2026-07-01",
            date_stop="2026-07-01",
            levels=["campaign"],
            breakdowns=["publisher_platform", "platform_position"],
            action_breakdowns=["action_type"],
            time_increment=1,
        ),
    )
    records, total = await repository.list_raw_records(limit=100)
    insight_record = next(record for record in records if record.entity_type == "insight")

    assert response.inserted_count == 11
    assert response.records_by_entity_type == {
        "ad": 1,
        "ad_account": 1,
        "adset": 1,
        "app": 1,
        "business": 1,
        "campaign": 1,
        "creative": 1,
        "custom_audience": 1,
        "custom_conversion": 1,
        "insight": 1,
        "pixel": 1,
    }
    assert total == 11
    assert {record.entity_type for record in records} == {
        "ad",
        "ad_account",
        "adset",
        "app",
        "business",
        "campaign",
        "creative",
        "custom_audience",
        "custom_conversion",
        "insight",
        "pixel",
    }
    assert insight_record.payload["_meta_breakdowns"] == [
        "publisher_platform",
        "platform_position",
    ]
    assert insight_record.payload["_meta_action_breakdowns"] == ["action_type"]
    assert insight_record.payload["_meta_time_increment"] == "1"
    assert insight_record.payload["_requested_breakdowns"] == [
        "publisher_platform",
        "platform_position",
    ]
    assert insight_record.provider_record_id is not None
    assert ":dim-" in insight_record.provider_record_id
    get_settings.cache_clear()


async def test_meta_discovery_service_stores_app_and_ad_accounts(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_test_env(monkeypatch, tmp_path / "marketing.db")
    repository = MarketingRepository(database_path=tmp_path / "marketing.db")
    await repository.initialize()
    service = MarketingSyncService(
        meta_client=cast(MetaMarketingClient, FakeMetaMarketingClient()),
        repository=repository,
    )

    response = await service.discover_meta_assets()
    records, total = await repository.list_raw_records(limit=100)

    assert response.app_collected is True
    assert response.ad_account_count == 1
    assert response.inserted_count == 6
    assert response.records_by_entity_type == {
        "ad_account": 1,
        "app": 1,
        "business": 1,
        "custom_audience": 1,
        "custom_conversion": 1,
        "pixel": 1,
    }
    assert total == 6
    assert {record.entity_type for record in records} == {
        "ad_account",
        "app",
        "business",
        "custom_audience",
        "custom_conversion",
        "pixel",
    }
    get_settings.cache_clear()


async def test_meta_async_insights_job_flow_stores_job_and_results(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_test_env(monkeypatch, tmp_path / "marketing.db")
    repository = MarketingRepository(database_path=tmp_path / "marketing.db")
    await repository.initialize()
    service = MarketingSyncService(
        meta_client=cast(MetaMarketingClient, FakeMetaMarketingClient()),
        repository=repository,
    )

    create_response = await service.create_insights_async_job(
        MetaInsightsAsyncJobRequest(
            account_id="act_100",
            date_start="2026-07-01",
            date_stop="2026-07-07",
            level="ad",
        ),
    )
    status_response = await service.get_insights_async_job_status(create_response.report_run_id)
    ingest_response = await service.ingest_insights_async_job_results(
        report_run_id=create_response.report_run_id,
        request=MetaInsightsAsyncJobIngestRequest(account_id="act_100", level="ad"),
    )
    records, total = await repository.list_raw_records(limit=100)

    assert create_response.report_run_id == "report-run-1"
    assert create_response.raw_record_id is not None
    assert status_response.is_complete is True
    assert ingest_response.inserted_count == 1
    assert total == 2
    assert {record.entity_type for record in records} == {"insight", "insights_job"}
    get_settings.cache_clear()


async def test_marketing_analyze_endpoint_uses_service_dependency(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_test_env(monkeypatch, tmp_path / "marketing.db")
    app = create_app()

    async with app.router.lifespan_context(app), AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        app.state.marketing_analysis_service = cast(
            MarketingAnalysisService,
            FakeMarketingAnalysisService(),
        )
        response = await client.post(
            "/api/v1/marketing/analyze",
            json={"question": "What should we do next?"},
        )

    assert response.status_code == 200
    assert response.json()["report"]["health_score"] == 72
    assert response.json()["report"]["key_findings"][0]["type"] == "opportunity"
    get_settings.cache_clear()


class FakeMarketingAnalysisService:
    async def analyze(self, request: MarketingAnalysisRequest) -> MarketingAnalysisResponse:
        return _make_marketing_analysis_response(
            report_id="report-1",
            executive_summary=f"Answered: {request.question}",
            health_score=72,
        )


def _make_marketing_analysis_response(
    *,
    report_id: str,
    executive_summary: str,
    health_score: int = 50,
    model: str = "test-model",
) -> MarketingAnalysisResponse:
    return MarketingAnalysisResponse(
        report_id=report_id,
        generated_at=datetime.now(UTC),
        model=model,
        source_record_count=0,
        source_record_ids=[],
        kpi_summary=MarketingKpiSummary(
            total_spend=0,
            total_impressions=0,
            total_reach=0,
            total_clicks=0,
            total_inline_link_clicks=0,
            total_conversions=0,
            total_conversion_value=0,
            ctr=None,
            cpc=None,
            cpm=None,
            cpa=None,
            roas=None,
        ),
        kpis=[],
        patterns=[],
        graph=MarketingGraphResponse(
            generated_at=datetime.now(UTC),
            source_record_count=0,
            nodes=[],
            edges=[],
        ),
        report=MarketingAnalysisReport(
            executive_summary=executive_summary,
            health_score=health_score,
            key_findings=[
                MarketingFinding(
                    type="opportunity",
                    title="Scale the best segment",
                    explanation="The test fake found a scalable segment.",
                    evidence=["Fake evidence"],
                    confidence="high",
                    recommended_action="Increase budget carefully.",
                ),
            ],
            prioritized_actions=["Increase budget carefully."],
            data_quality_notes=["Fake service used for route isolation."],
            raw_data_followups=["Inspect source records."],
        ),
    )


class FakeMetaMarketingClient:
    @property
    def api_version(self) -> str:
        return "v25.0"

    async def fetch_app(self) -> dict[str, object]:
        return {"id": "test-app", "name": "Test App"}

    async def fetch_business(self) -> dict[str, object]:
        return {"id": "business-1", "name": "Test Business"}

    async def fetch_business_owned_pixels(self) -> list[dict[str, object]]:
        return [
            {
                "id": "pixel-1",
                "name": "Website Pixel",
                "owner_business": {"id": "business-1"},
            },
        ]

    async def fetch_configured_ad_accounts(self) -> list[dict[str, object]]:
        return [{"id": "act_100", "name": "Test Account"}]

    async def fetch_campaigns(self, account_id: str) -> list[dict[str, object]]:
        return [{"id": "campaign-1", "name": f"Campaign for {account_id}"}]

    async def fetch_adsets(self, account_id: str) -> list[dict[str, object]]:
        return [
            {
                "id": "adset-1",
                "name": f"Ad set for {account_id}",
                "campaign_id": "campaign-1",
                "targeting": {
                    "custom_audiences": [
                        {"id": "audience-1", "name": "High value customers"},
                    ],
                },
            },
        ]

    async def fetch_ads(self, account_id: str) -> list[dict[str, object]]:
        return [
            {
                "id": "ad-1",
                "name": f"Ad for {account_id}",
                "campaign_id": "campaign-1",
                "adset_id": "adset-1",
                "creative": {"id": "creative-1"},
            },
        ]

    async def fetch_ad_creatives(self, account_id: str) -> list[dict[str, object]]:
        return [
            {
                "id": "creative-1",
                "name": f"Creative for {account_id}",
                "title": "Creative headline",
                "body": "Creative primary text",
                "object_type": "SHARE",
                "call_to_action_type": "LEARN_MORE",
            },
        ]

    async def fetch_custom_conversions(self, account_id: str) -> list[dict[str, object]]:
        return [
            {
                "id": "custom-conversion-1",
                "name": f"Purchase conversion for {account_id}",
                "custom_event_type": "PURCHASE",
                "event_source_type": "PIXEL",
                "pixel": {"id": "pixel-1"},
                "rule": {"event": {"eq": "Purchase"}},
            },
        ]

    async def fetch_custom_audiences(self, account_id: str) -> list[dict[str, object]]:
        return [
            {
                "id": "audience-1",
                "name": f"High value customers for {account_id}",
                "subtype": "CUSTOM",
                "approximate_count": 1500,
            },
        ]

    async def fetch_insights(
        self,
        *,
        account_id: str,
        level: MetaInsightLevel,
        date_start: object,
        date_stop: object,
        breakdowns: list[str] | None = None,
        action_breakdowns: list[str] | None = None,
        time_increment: int | str = 1,
    ) -> list[dict[str, object]]:
        return [
            {
                "account_id": account_id,
                "campaign_id": "campaign-1",
                "campaign_name": "Prospecting",
                "date_start": str(date_start),
                "date_stop": str(date_stop),
                "spend": "100",
                "impressions": "10000",
                "clicks": "250",
                "actions": [{"action_type": "lead", "value": "20"}],
                "_requested_level": level,
                "_requested_breakdowns": breakdowns or [],
                "_requested_action_breakdowns": action_breakdowns or [],
                "_requested_time_increment": str(time_increment),
                "publisher_platform": "facebook",
                "platform_position": "feed",
            },
        ]

    async def create_insights_async_job(
        self,
        *,
        account_id: str,
        level: MetaInsightLevel,
        date_start: object,
        date_stop: object,
        fields: list[str] | None = None,
        breakdowns: list[str] | None = None,
        action_breakdowns: list[str] | None = None,
        time_increment: int | str = 1,
    ) -> dict[str, object]:
        return {
            "report_run_id": "report-run-1",
            "account_id": account_id,
            "level": level,
            "date_start": str(date_start),
            "date_stop": str(date_stop),
            "fields": fields or [],
            "breakdowns": breakdowns or [],
            "action_breakdowns": action_breakdowns or [],
            "time_increment": time_increment,
        }

    async def fetch_insights_async_job_status(self, report_run_id: str) -> dict[str, object]:
        return {
            "id": report_run_id,
            "async_status": "Job Completed",
            "async_percent_completion": 100,
        }

    async def fetch_insights_async_job_results(
        self,
        *,
        report_run_id: str,
        fields: list[str] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, object]]:
        return [
            {
                "ad_id": "ad-1",
                "ad_name": "Winning ad",
                "account_id": "act_100",
                "date_start": "2026-07-01",
                "date_stop": "2026-07-01",
                "spend": "50",
                "impressions": "5000",
                "clicks": "125",
                "_report_run_id": report_run_id,
                "_limit": limit,
                "_fields": fields or [],
            },
        ]
