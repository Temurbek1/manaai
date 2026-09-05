from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.auth_rate_limiter import AuthenticationRateLimiter
from app.core.config import get_settings
from app.core.logging import configure_application_logging
from app.core.middleware import EXPOSED_RESPONSE_HEADERS, request_trace_middleware
from app.core.openapi import API_DESCRIPTION, OPENAPI_TAGS, SWAGGER_UI_PARAMETERS
from app.core.rate_limiter import RequestRateLimiter
from app.mana_ai.application.service import ManaAIAnalysisService
from app.mana_operation_ai.application.action_executors import (
    ActionExecutorRegistry,
    AdvertisingActionExecutor,
    ExperimentActionExecutor,
)
from app.mana_operation_ai.application.action_lifecycle import ActionLifecycleService
from app.mana_operation_ai.application.action_policies import (
    ActionPolicyRegistry,
    AdvertisingPolicyEvaluator,
    GrowthExperimentPolicyEvaluator,
)
from app.mana_operation_ai.application.admin_service import OperationAdminService
from app.mana_operation_ai.application.agent_service import AgentService
from app.mana_operation_ai.application.auth_ports import TelegramOtpSender
from app.mana_operation_ai.application.auth_service import AdminAuthService
from app.mana_operation_ai.application.capabilities import CapabilityRegistry
from app.mana_operation_ai.application.growth.agent import GrowthAgent
from app.mana_operation_ai.application.growth.funnel import GrowthFunnelCapabilityHandler
from app.mana_operation_ai.application.maintenance import OperationMaintenanceService
from app.mana_operation_ai.application.marketing.agent import AdvertisingCapabilityHandler
from app.mana_operation_ai.application.marketing.analytics import MarketingAnalyticsEngine
from app.mana_operation_ai.application.marketing.reporting import MarketingReportBuilder
from app.mana_operation_ai.application.policy import PolicyService
from app.mana_operation_ai.application.ports import BackendActivityPort, MobileActivityPort
from app.mana_operation_ai.application.registry import AdsPlatformRegistry, AgentRegistry
from app.mana_operation_ai.application.retention.agent import RetentionAgent
from app.mana_operation_ai.application.retention.engagement import (
    RetentionEngagementCapabilityHandler,
)
from app.mana_operation_ai.application.runtime import SystemClock, UuidGenerator
from app.mana_operation_ai.background.scheduler import InProcessScheduler
from app.mana_operation_ai.domain.auth import AuthPolicy
from app.mana_operation_ai.infrastructure.ads.fake_meta import FakeMetaAdsAdapter
from app.mana_operation_ai.infrastructure.ads.meta import MetaAdsAdapter
from app.mana_operation_ai.infrastructure.growth.fake import (
    FakeAttributionAdapter,
    FakeBillingReadAdapter,
    FakeExperimentAdapter,
    FakeProductAnalyticsAdapter,
)
from app.mana_operation_ai.infrastructure.notifications.logging import (
    StructuredLogNotificationAdapter,
)
from app.mana_operation_ai.infrastructure.persistence.auth_repository import (
    SqlAlchemyAdminAuthRepository,
)
from app.mana_operation_ai.infrastructure.persistence.database import OperationDatabase
from app.mana_operation_ai.infrastructure.persistence.repository import (
    SqlAlchemyOperationRepository,
)
from app.mana_operation_ai.infrastructure.retention.fake import (
    FakeBackendActivityAdapter,
    FakeMobileActivityAdapter,
)
from app.mana_operation_ai.infrastructure.retention.firestore import (
    FirestoreMobileActivityAdapter,
    GoogleServiceAccountTokenProvider,
)
from app.mana_operation_ai.infrastructure.retention.manakids import (
    ManakidsAdminActivityAdapter,
)
from app.mana_operation_ai.infrastructure.telegram.sender import (
    FileTelegramOtpSender,
    TelegramBotOtpSender,
    UnavailableTelegramOtpSender,
)
from app.services.mana_ai_openai_gateway import ManaAIOpenAIModelGateway, SystemManaAIClock
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
    mana_ai_analysis_service = ManaAIAnalysisService(
        gateway=ManaAIOpenAIModelGateway(openai_service),
        clock=SystemManaAIClock(),
    )
    marketing_repository = MarketingRepository(database_path=settings.marketing_database_path)
    await marketing_repository.initialize()
    meta_client = MetaMarketingClient(settings=settings)
    operation_database = OperationDatabase(settings.effective_operation_database_url)
    if settings.operation_auto_create_schema:
        await operation_database.create_schema()
    operation_repository = SqlAlchemyOperationRepository(operation_database)
    auth_repository = SqlAlchemyAdminAuthRepository(operation_database)
    clock = SystemClock()
    ids = UuidGenerator()
    first_party_http_clients: list[httpx.AsyncClient] = []
    backend_activity: BackendActivityPort
    mobile_activity: MobileActivityPort
    if settings.operation_product_activity_provider == "manakids_firebase":
        if (
            settings.manakids_api_username is None
            or settings.manakids_api_password is None
            or settings.firebase_project_id is None
            or settings.firebase_service_account_file is None
        ):
            raise RuntimeError("Live product activity settings are incomplete")
        firebase_token_provider = GoogleServiceAccountTokenProvider(
            str(settings.firebase_service_account_file),
        )
        manakids_http = httpx.AsyncClient(timeout=settings.manakids_request_timeout_seconds)
        firestore_http = httpx.AsyncClient(timeout=settings.firebase_request_timeout_seconds)
        first_party_http_clients.extend([manakids_http, firestore_http])
        backend_activity = ManakidsAdminActivityAdapter(
            client=manakids_http,
            base_url=settings.manakids_api_base_url,
            username=settings.manakids_api_username,
            password=settings.manakids_api_password.get_secret_value(),
            clock=clock,
            max_retries=settings.manakids_max_retries,
            retry_backoff_seconds=settings.manakids_retry_backoff_seconds,
            max_pages=settings.manakids_max_pages,
        )
        mobile_activity = FirestoreMobileActivityAdapter(
            client=firestore_http,
            project_id=settings.firebase_project_id,
            database_id=settings.firebase_database_id,
            collection_id=settings.firebase_activity_collection,
            token_provider=firebase_token_provider,
            clock=clock,
            max_documents=settings.firebase_max_activity_documents,
            max_retries=settings.firebase_max_retries,
            retry_backoff_seconds=settings.firebase_retry_backoff_seconds,
        )
    else:
        backend_activity = FakeBackendActivityAdapter(clock=clock)
        mobile_activity = FakeMobileActivityAdapter(clock=clock)
    otp_sender: TelegramOtpSender
    if settings.mana_auth_test_mode:
        if settings.mana_auth_test_otp_sink_path is None:
            raise RuntimeError("Telegram authentication test sink is unavailable")
        otp_sender = FileTelegramOtpSender(settings.mana_auth_test_otp_sink_path)
    elif settings.mana_telegram_bot_token is not None:
        otp_sender = TelegramBotOtpSender(
            bot_token=settings.mana_telegram_bot_token.get_secret_value(),
        )
    else:
        otp_sender = UnavailableTelegramOtpSender()
    auth_service = AdminAuthService(
        repository=auth_repository,
        sender=otp_sender,
        clock=clock,
        ids=ids,
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
        hmac_secret=(
            settings.mana_otp_hmac_secret.get_secret_value()
            if settings.mana_otp_hmac_secret is not None
            else None
        ),
        bot_username=settings.mana_telegram_bot_username,
    )
    if settings.mana_telegram_auth_enabled:
        await auth_service.bootstrap_admins(settings.bootstrap_admin_telegram_ids)
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
    experiment_platform = FakeExperimentAdapter(clock=clock)
    action_executors = ActionExecutorRegistry()
    for platform_name in ("fake_meta", "meta"):
        action_executors.register(AdvertisingActionExecutor(ads_platforms.get(platform_name)))
    action_executors.register(ExperimentActionExecutor(experiment_platform))
    action_policies = ActionPolicyRegistry()
    action_policies.register(AdvertisingPolicyEvaluator(policy_service))
    action_policies.register(
        GrowthExperimentPolicyEvaluator(
            repository=operation_repository,
            clock=clock,
            ids=ids,
            global_execution_limit_per_day=settings.operation_global_execution_limit_per_day,
            agent_execution_limit_per_day=settings.operation_agent_execution_limit_per_day,
        ),
    )
    action_lifecycle = ActionLifecycleService(
        repository=operation_repository,
        executors=action_executors,
        policies=action_policies,
        clock=clock,
        ids=ids,
        dry_run=settings.operation_dry_run,
        allow_self_approval=settings.operation_allow_self_approval,
        global_kill_switch_default=settings.operation_global_kill_switch,
        lock_timeout_seconds=settings.operation_job_timeout_seconds,
        verification_attempts=settings.operation_verification_attempts,
        verification_delay_seconds=settings.operation_verification_delay_seconds,
    )
    growth_capability_registry = CapabilityRegistry()
    growth_capability_registry.register(
        AdvertisingCapabilityHandler(
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
    growth_capability_registry.register(
        GrowthFunnelCapabilityHandler(
            product_analytics=FakeProductAnalyticsAdapter(clock=clock),
            billing=FakeBillingReadAdapter(clock=clock),
            attribution=FakeAttributionAdapter(clock=clock),
            experiments=experiment_platform,
            actions=action_lifecycle,
            repository=operation_repository,
            clock=clock,
            ids=ids,
        ),
    )
    retention_capability_registry = CapabilityRegistry()
    retention_capability_registry.register(
        RetentionEngagementCapabilityHandler(
            backend_activity=backend_activity,
            mobile_activity=mobile_activity,
            repository=operation_repository,
            clock=clock,
            ids=ids,
        ),
    )
    agent_registry = AgentRegistry()
    agent_registry.register(
        GrowthAgent(
            capabilities=growth_capability_registry,
            repository=operation_repository,
            clock=clock,
        ),
    )
    agent_registry.register(
        RetentionAgent(
            capabilities=retention_capability_registry,
            repository=operation_repository,
            clock=clock,
        ),
    )
    agent_registry.register_alias("marketing-agent", "growth-agent")
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
        executors=action_executors,
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
    app.state.mana_ai_analysis_service = mana_ai_analysis_service
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
    app.state.admin_auth_repository = auth_repository
    app.state.admin_auth_service = auth_service
    app.state.operation_agent_registry = agent_registry
    app.state.operation_ads_platforms = ads_platforms
    app.state.operation_experiment_platform = experiment_platform
    app.state.operation_backend_activity = backend_activity
    app.state.operation_mobile_activity = mobile_activity
    app.state.operation_agent_service = agent_service
    app.state.operation_action_lifecycle = action_lifecycle
    app.state.operation_admin_service = operation_admin_service
    app.state.operation_maintenance_service = maintenance_service
    app.state.operation_scheduler = operation_scheduler
    try:
        yield
    finally:
        await operation_scheduler.stop()
        for client in first_party_http_clients:
            await client.aclose()
        await operation_database.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_application_logging(
        level=settings.log_level,
        secrets=[
            settings.openai_api_key.get_secret_value(),
            settings.meta_access_token.get_secret_value() if settings.meta_access_token else "",
            (
                settings.manakids_api_password.get_secret_value()
                if settings.manakids_api_password
                else ""
            ),
            settings.app_api_key.get_secret_value() if settings.app_api_key else "",
            (
                settings.mana_telegram_bot_token.get_secret_value()
                if settings.mana_telegram_bot_token
                else ""
            ),
            (
                settings.mana_otp_hmac_secret.get_secret_value()
                if settings.mana_otp_hmac_secret
                else ""
            ),
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
    app.state.request_rate_limiter = RequestRateLimiter(
        request_limit=settings.api_rate_limit_requests,
        window_seconds=settings.api_rate_limit_window_seconds,
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
