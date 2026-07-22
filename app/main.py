from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.auth_rate_limiter import AuthenticationRateLimiter
from app.core.config import get_settings
from app.core.logging import configure_application_logging
from app.core.middleware import EXPOSED_RESPONSE_HEADERS, request_trace_middleware
from app.core.openapi import API_DESCRIPTION, OPENAPI_TAGS, SWAGGER_UI_PARAMETERS
from app.mana_operation_ai.application.action_lifecycle import ActionLifecycleService
from app.mana_operation_ai.application.admin_service import OperationAdminService
from app.mana_operation_ai.application.agent_service import AgentService
from app.mana_operation_ai.application.maintenance import OperationMaintenanceService
from app.mana_operation_ai.application.marketing.agent import MarketingAgent
from app.mana_operation_ai.application.marketing.analytics import MarketingAnalyticsEngine
from app.mana_operation_ai.application.marketing.reporting import MarketingReportBuilder
from app.mana_operation_ai.application.policy import PolicyService
from app.mana_operation_ai.application.registry import AdsPlatformRegistry, AgentRegistry
from app.mana_operation_ai.application.runtime import SystemClock, UuidGenerator
from app.mana_operation_ai.background.scheduler import InProcessScheduler
from app.mana_operation_ai.infrastructure.ads.fake_meta import FakeMetaAdsAdapter
from app.mana_operation_ai.infrastructure.ads.meta import MetaAdsAdapter
from app.mana_operation_ai.infrastructure.notifications.logging import (
    StructuredLogNotificationAdapter,
)
from app.mana_operation_ai.infrastructure.persistence.database import OperationDatabase
from app.mana_operation_ai.infrastructure.persistence.repository import (
    SqlAlchemyOperationRepository,
)
from app.services.marketing_analysis_service import MarketingAnalysisService
from app.services.marketing_graph_service import MarketingGraphService
from app.services.marketing_metrics import MarketingMetricsBuilder
from app.services.marketing_pattern_service import MarketingPatternService
from app.services.marketing_report_service import MarketingReportService
from app.services.marketing_repository import MarketingRepository
from app.services.marketing_sync_service import MarketingSyncService
from app.services.meta_marketing_client import MetaMarketingClient
from app.services.openai_service import OpenAIService


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    openai_service = OpenAIService(settings=settings)
    marketing_repository = MarketingRepository(database_path=settings.marketing_database_path)
    await marketing_repository.initialize()
    meta_client = MetaMarketingClient(settings=settings)
    operation_database = OperationDatabase(settings.effective_operation_database_url)
    if settings.operation_auto_create_schema:
        await operation_database.create_schema()
    operation_repository = SqlAlchemyOperationRepository(operation_database)
    clock = SystemClock()
    ids = UuidGenerator()
    ads_platforms = AdsPlatformRegistry()
    ads_platforms.register(FakeMetaAdsAdapter(clock=clock))
    ads_platforms.register(MetaAdsAdapter(client=meta_client, settings=settings, clock=clock))
    policy_service = PolicyService(
        repository=operation_repository,
        clock=clock,
        ids=ids,
        global_execution_limit_per_day=settings.operation_global_execution_limit_per_day,
        agent_execution_limit_per_day=settings.operation_agent_execution_limit_per_day,
    )
    action_lifecycle = ActionLifecycleService(
        repository=operation_repository,
        platforms=ads_platforms,
        policy=policy_service,
        clock=clock,
        ids=ids,
        dry_run=settings.operation_dry_run,
        allow_self_approval=settings.operation_allow_self_approval,
        global_kill_switch_default=settings.operation_global_kill_switch,
        lock_timeout_seconds=settings.operation_job_timeout_seconds,
        verification_attempts=settings.operation_verification_attempts,
        verification_delay_seconds=settings.operation_verification_delay_seconds,
    )
    agent_registry = AgentRegistry()
    agent_registry.register(
        MarketingAgent(
            provider=ads_platforms.get(settings.operation_ads_provider),
            repository=operation_repository,
            analytics=MarketingAnalyticsEngine(ids=ids),
            actions=action_lifecycle,
            reports=MarketingReportBuilder(),
            notifications=StructuredLogNotificationAdapter(),
            clock=clock,
            ids=ids,
        ),
    )
    agent_service = AgentService(
        registry=agent_registry,
        repository=operation_repository,
        clock=clock,
        ids=ids,
        job_timeout_seconds=settings.operation_job_timeout_seconds,
        global_kill_switch_default=settings.operation_global_kill_switch,
    )
    await agent_service.bootstrap()
    operation_admin_service = OperationAdminService(
        repository=operation_repository,
        agents=agent_registry,
        platforms=ads_platforms,
        runner=agent_service,
        actions=action_lifecycle,
        clock=clock,
        ids=ids,
        default_ads_provider=settings.operation_ads_provider,
    )
    maintenance_service = OperationMaintenanceService(
        repository=operation_repository,
        platforms=ads_platforms,
        agents=agent_registry,
        clock=clock,
        ids=ids,
        retention_days=settings.operation_data_retention_days,
    )
    operation_scheduler = InProcessScheduler(
        repository=operation_repository,
        admin=operation_admin_service,
        maintenance=maintenance_service,
        clock=clock,
        poll_seconds=settings.operation_scheduler_poll_seconds,
        job_timeout_seconds=settings.operation_job_timeout_seconds,
    )
    if settings.operation_scheduler_enabled:
        operation_scheduler.start()
    metrics_builder = MarketingMetricsBuilder(
        conversion_action_types=settings.marketing_conversion_action_types,
        value_action_types=settings.marketing_value_action_types,
    )

    app.state.settings = settings
    app.state.openai_service = openai_service
    app.state.marketing_repository = marketing_repository
    app.state.meta_marketing_client = meta_client
    app.state.marketing_sync_service = MarketingSyncService(
        meta_client=meta_client,
        repository=marketing_repository,
    )
    app.state.marketing_pattern_service = MarketingPatternService(
        repository=marketing_repository,
        metrics_builder=metrics_builder,
        measurement_stale_after_days=settings.marketing_measurement_stale_after_days,
    )
    app.state.marketing_graph_service = MarketingGraphService(repository=marketing_repository)
    app.state.marketing_report_service = MarketingReportService(repository=marketing_repository)
    app.state.marketing_analysis_service = MarketingAnalysisService(
        repository=marketing_repository,
        metrics_builder=metrics_builder,
        pattern_service=app.state.marketing_pattern_service,
        graph_service=app.state.marketing_graph_service,
        openai_service=openai_service,
    )
    app.state.operation_database = operation_database
    app.state.operation_repository = operation_repository
    app.state.operation_agent_registry = agent_registry
    app.state.operation_ads_platforms = ads_platforms
    app.state.operation_agent_service = agent_service
    app.state.operation_action_lifecycle = action_lifecycle
    app.state.operation_admin_service = operation_admin_service
    app.state.operation_maintenance_service = maintenance_service
    app.state.operation_scheduler = operation_scheduler
    try:
        yield
    finally:
        await operation_scheduler.stop()
        await operation_database.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_application_logging(
        level=settings.log_level,
        secrets=[
            settings.openai_api_key.get_secret_value(),
            settings.meta_access_token.get_secret_value() if settings.meta_access_token else "",
            settings.app_api_key.get_secret_value() if settings.app_api_key else "",
            *(
                secret.get_secret_value()
                for secret in [
                    settings.operation_viewer_api_key,
                    settings.operation_operator_api_key,
                    settings.operation_approver_api_key,
                    settings.operation_admin_api_key,
                ]
                if secret is not None
            ),
        ],
    )
    app = FastAPI(
        title=settings.app_name,
        summary="AI integration API layer for ManaAI.",
        description=API_DESCRIPTION,
        version=settings.app_version,
        contact={
            "name": "ManaAI API maintainers",
        },
        license_info={
            "name": "Proprietary",
        },
        openapi_tags=OPENAPI_TAGS,
        swagger_ui_parameters=SWAGGER_UI_PARAMETERS,
        docs_url="/docs" if settings.is_docs_enabled else None,
        redoc_url="/redoc" if settings.is_docs_enabled else None,
        openapi_url="/openapi.json" if settings.is_docs_enabled else None,
        lifespan=lifespan,
    )
    app.state.auth_rate_limiter = AuthenticationRateLimiter(
        failure_limit=settings.auth_failure_limit,
        window_seconds=settings.auth_failure_window_seconds,
    )

    app.middleware("http")(request_trace_middleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=EXPOSED_RESPONSE_HEADERS,
    )

    app.include_router(api_router, prefix="/api/v1")
    return app


app = create_app()
