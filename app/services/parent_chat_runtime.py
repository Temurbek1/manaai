from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import httpx

from app.core.config import Settings
from app.mana_ai.application.chat_ports import ParentChildrenSource
from app.mana_ai.application.child_safety import ChildSafetyService
from app.mana_ai.application.client_retention import ClientRetentionService
from app.mana_ai.application.client_upsell import ClientUpsellService
from app.mana_ai.application.conversion import ConversionService
from app.mana_ai.application.conversion_accounts import ConversionAccountVerifier
from app.mana_ai.application.conversion_grants import TrialGrantService
from app.mana_ai.application.parent_chat import ParentChatService
from app.mana_ai.application.parent_reminders import ParentReminderService
from app.mana_ai.application.parent_setup import ParentSetupService, SetupProfileSource
from app.mana_ai.application.parent_touch import ParentTouchService
from app.mana_ai.application.parent_touch_manager import manager_binding
from app.mana_ai.application.proactive_parent import ProactiveParentService
from app.mana_ai.application.retention_expiry import RetentionExpiryService, RetentionProfileSource
from app.mana_ai.application.reviewed_message_ports import ReviewedMessageStore
from app.mana_ai.application.source_reviews import SourceReviewService
from app.mana_ai.application.source_safety import SourceSafetyService
from app.mana_ai.application.source_tool_workflow import SourceToolWorkflow
from app.services.child_safety_model import OpenAIChildSafetyModel
from app.services.child_safety_prompts import ChildSafetyPromptBuilder
from app.services.child_safety_store import SqliteChildSafetyStore
from app.services.child_source_model import OpenAIChildSourceModel
from app.services.client_retention_store import (
    SqliteClientRetentionStore,
    SqliteClosedClientRetentionStore,
)
from app.services.client_upsell_store import SqliteClientUpsellStore, SqliteClosedClientUpsellStore
from app.services.commercial_conversation_store import (
    SqliteClosedCommercialConversationStore,
    SqliteCommercialConversationStore,
)
from app.services.compact_family_input_store import (
    SqliteClosedCompactFamilyInputStore,
    SqliteCompactFamilyInputStore,
)
from app.services.compact_manager_decision_store import (
    SqliteClosedCompactManagerDecisionStore,
    SqliteCompactManagerDecisionStore,
)
from app.services.compact_parent_publication_store import (
    SqliteClosedCompactParentPublicationStore,
    SqliteCompactParentPublicationStore,
)
from app.services.compact_source_tool_store import (
    SqliteClosedCompactSourceToolStore,
    SqliteCompactSourceToolStore,
)
from app.services.conversion_account_store import (
    SqliteClosedConversionAccountStore,
    SqliteConversionAccountStore,
)
from app.services.conversion_store import SqliteClosedConversionStore, SqliteConversionStore
from app.services.dated_review_safety_store import (
    SqliteClosedDatedReviewSafetyStore,
    SqliteDatedReviewSafetyStore,
)
from app.services.dated_source_safety_store import (
    SqliteClosedDatedSourceSafetyStore,
    SqliteDatedSourceSafetyStore,
)
from app.services.direct_reminder_store import (
    SqliteClosedDirectReminderStore,
    SqliteDirectReminderStore,
)
from app.services.family_agent_store import SqliteFamilyAgentStore
from app.services.family_agent_worker import FamilyAgentWorker
from app.services.family_collection_worker import FamilyCollectionWorker
from app.services.family_compatibility_store import (
    SqliteClosedSafetyBrokerStore,
    SqliteFamilyCompatibilityStore,
    family_storage_version,
)
from app.services.family_source_runtime import family_source_runtime
from app.services.inline_upsell_store import (
    SqliteClosedInlineUpsellStore,
    SqliteInlineUpsellStore,
)
from app.services.literal_tariff_followup_store import (
    SqliteClosedLiteralTariffFollowupStore,
    SqliteLiteralTariffFollowupStore,
)
from app.services.location_comparison_safety_store import (
    SqliteClosedLocationComparisonSafetyStore,
    SqliteLocationComparisonSafetyStore,
)
from app.services.location_safety_store import (
    SqliteClosedLocationSafetyStore,
    SqliteLocationSafetyStore,
)
from app.services.mana_ai_openai_gateway import SystemManaAIClock
from app.services.manakids_conversion_accounts import ManakidsConversionAccountSource
from app.services.manakids_conversion_catalog import ManakidsConversionCatalogSource
from app.services.manakids_parent_push import ManakidsParentPushGateway
from app.services.manakids_trial_grants import ManakidsTrialGrantGateway
from app.services.parent_chat_children import ManakidsChatChildrenSource
from app.services.parent_chat_model import OpenAIParentChatModel
from app.services.parent_chat_store import SqliteParentChatStore
from app.services.parent_clarification_store import (
    SqliteClosedParentClarificationStore,
    SqliteParentClarificationStore,
)
from app.services.parent_reminder_store import (
    SqliteClosedParentReminderStore,
    SqliteParentReminderStore,
)
from app.services.parent_setup_store import SqliteClosedParentSetupStore, SqliteParentSetupStore
from app.services.parent_support_question_store import (
    SqliteClosedParentSupportQuestionStore,
    SqliteParentSupportQuestionStore,
)
from app.services.parent_touch_manager_store import (
    SqliteClosedParentTouchManagerStore,
    SqliteParentTouchManagerStore,
)
from app.services.proactive_parent_store import (
    SqliteClosedProactiveParentStore,
    SqliteProactiveParentStore,
)
from app.services.retention_expiry_store import (
    SqliteClosedRetentionExpiryStore,
    SqliteRetentionExpiryStore,
)
from app.services.reviewed_message_store import (
    SqliteClosedReviewedBrokerStore,
    SqliteReviewedMessageStore,
)
from app.services.safety_remainder_store import (
    SqliteClosedSafetyRemainderStore,
    SqliteSafetyRemainderStore,
)
from app.services.saved_observation_runtime import saved_observation_service
from app.services.saved_observation_safety_store import (
    SqliteClosedSavedObservationSafetyStore,
    SqliteSavedObservationSafetyStore,
)
from app.services.shared_conversion_profile_store import (
    SqliteClosedSharedConversionProfileStore,
    SqliteSharedConversionProfileStore,
)
from app.services.source_review_cache import SqliteSourceReviewCache
from app.services.source_review_safety_store import (
    SqliteClosedSourceReviewSafetyStore,
    SqliteSourceReviewSafetyStore,
)
from app.services.source_tool_prompts import SourceToolPromptBuilder
from app.services.source_tool_safety_store import (
    SqliteClosedObservationToolSafetyStore,
    SqliteClosedSourceToolSafetyStore,
    SqliteObservationToolSafetyStore,
    SqliteSourceToolSafetyStore,
)
from app.services.tariff_followup_store import (
    SqliteClosedTariffFollowupStore,
    SqliteTariffFollowupStore,
)
from app.services.tariff_handoff_store import (
    SqliteClosedTariffHandoffStore,
    SqliteTariffHandoffStore,
)
from app.services.trial_end_store import SqliteClosedTrialEndStore, SqliteTrialEndStore
from app.services.trial_period_store import SqliteClosedTrialPeriodStore, SqliteTrialPeriodStore
from app.services.upsell_currency_store import (
    SqliteClosedUpsellCurrencyStore,
    SqliteUpsellCurrencyStore,
)
from app.services.usage_comparison_safety_store import (
    SqliteClosedUsageComparisonSafetyStore,
    SqliteUsageComparisonSafetyStore,
)


@asynccontextmanager
async def parent_chat_runtime(settings: Settings) -> AsyncIterator[ParentChatService | None]:
    if not settings.mana_parent_chat_enabled:
        yield None
        return
    assert settings.manakids_api_username and settings.manakids_api_password
    store: SqliteParentChatStore
    store_arguments = {
        "daily_limit": settings.mana_parent_chat_daily_tokens,
        "max_attempts": settings.mana_parent_chat_max_attempts_per_day,
    }
    version = await family_storage_version(settings.mana_parent_chat_database_path)
    if (
        version
        in {
            17,
            18,
            19,
            20,
            21,
            22,
            23,
            26,
            27,
            28,
            29,
            30,
            31,
            32,
            33,
            34,
            35,
            36,
            37,
            38,
            39,
            40,
            41,
            42,
            43,
            44,
        }
        and settings.mana_child_safety_enabled
        and not settings.mana_client_upsell_enabled
    ):
        raise RuntimeError("V17 execution requires its compatible full chat reader")
    if (
        version == 16
        and settings.mana_child_safety_enabled
        and not settings.mana_client_upsell_enabled
    ):
        raise RuntimeError("V16 execution requires its captured Upsell runtime")
    if (
        version == 15
        and settings.mana_child_safety_enabled
        and not settings.mana_client_retention_enabled
    ):
        raise RuntimeError("V15 execution requires its captured Retention runtime")
    if (
        version == 14
        and settings.mana_child_safety_enabled
        and not settings.mana_parent_reminders_enabled
    ):
        raise RuntimeError("V14 execution requires its captured parent-assistant runtime")
    if (
        version == 13
        and settings.mana_child_safety_source_tools_enabled
        and not (settings.mana_family_source_reviews_enabled)
    ):
        raise RuntimeError("V13 execution requires its captured source-review runtime")
    reviewed: ReviewedMessageStore | None = None
    if settings.mana_child_safety_source_tools_enabled:
        assert settings.mana_child_safety_limits is not None
        if version == 12 and not settings.mana_family_app_usage_enabled:
            raise RuntimeError("V12 safety execution requires its captured observation runtime")
        native_class = (
            SqliteSourceReviewSafetyStore
            if settings.mana_family_source_reviews_enabled
            else (
                SqliteObservationToolSafetyStore
                if settings.mana_family_app_usage_enabled
                else SqliteSourceToolSafetyStore
            )
        )
        native_options: dict[str, Any] = dict(
            native_model=settings.mana_child_safety_model or settings.openai_model,
            native_reasoning_effort=settings.openai_reasoning_effort,
            native_verbosity=settings.openai_verbosity,
            native_wall_timeout_seconds=min(settings.openai_timeout_seconds, 120) + 10,
            native_max_output_tokens=settings.mana_child_safety_max_output_tokens,
            conversion_policy=settings.mana_conversion_policy,
            conversion_offers=settings.mana_conversion_offers,
            limits=settings.mana_child_safety_limits,
            timezone=settings.mana_parent_chat_timezone,
            question_limit=settings.mana_parent_touch_question_limit,
            push_queue_limit=settings.mana_parent_push_queue_limit,
            push_max_age_seconds=settings.mana_parent_push_max_age_seconds,
            push_daily_attempt_limit=settings.mana_parent_push_daily_attempt_limit,
            proactive_enabled=settings.mana_parent_touch_proactive_enabled,
            push_enabled=settings.mana_parent_push_enabled,
            conversation_enabled=settings.mana_conversion_conversation_enabled,
            account_source_enabled=settings.mana_conversion_account_source_enabled,
            account_read_limits=settings.mana_conversion_account_read_limits,
            **store_arguments,
        )
        profile_options: dict[str, Any] = {}
        if (
            settings.mana_parent_setup_enabled
            or settings.mana_parent_touch_direct_reminders_enabled
            or settings.mana_parent_touch_compact_decisions_enabled
            or version in {42, 43, 44}
        ):
            profile_options.update(
                parent_setup_enabled=settings.mana_parent_setup_enabled,
                parent_setup_policy=settings.mana_parent_setup_policy,
                setup_binding=settings.manakids_api_base_url
                + "/api/v1/admin-panel-parent/parent-list/",
            )
        if settings.mana_parent_touch_compact_decisions_enabled or version == 44:
            profile_options["compact_decisions_enabled"] = (
                settings.mana_parent_touch_compact_decisions_enabled
            )
        if settings.mana_parent_touch_direct_reminders_enabled or version in {43, 44}:
            profile_options["direct_reminders_enabled"] = (
                settings.mana_parent_touch_direct_reminders_enabled
            )
        if settings.mana_family_compact_source_tools_enabled or version in {41, 42, 43, 44}:
            profile_options["compact_source_tools_enabled"] = (
                settings.mana_family_compact_source_tools_enabled
            )
        if settings.mana_upsell_literal_followups_enabled or version in {40, 41, 42, 43, 44}:
            profile_options["literal_tariff_followups_enabled"] = (
                settings.mana_upsell_literal_followups_enabled
            )
        if settings.mana_upsell_followups_enabled or version in {39, 40, 41, 42, 43, 44}:
            profile_options["tariff_followups_enabled"] = settings.mana_upsell_followups_enabled
        if settings.mana_family_saved_observations_enabled or version in {
            38,
            39,
            40,
            41,
            42,
            43,
            44,
        }:
            profile_options["saved_observations_enabled"] = (
                settings.mana_family_saved_observations_enabled
            )
            profile_options["saved_observation_limits"] = (
                settings.mana_family_saved_observation_limits
            )
        if (
            settings.mana_family_location_comparisons_enabled
            or settings.mana_family_saved_observations_enabled
            or settings.mana_upsell_followups_enabled
            or version in {37, 38, 39, 40, 41, 42, 43, 44}
        ):
            profile_options["location_time_labels_enabled"] = (
                settings.mana_family_location_time_labels_enabled
            )
        if settings.mana_family_location_comparisons_enabled or version == 37:
            profile_options["location_comparisons_enabled"] = (
                settings.mana_family_location_comparisons_enabled
            )
        if settings.mana_parent_touch_compact_publication_enabled or version in {
            36,
            37,
            38,
            39,
            40,
            41,
            42,
            43,
            44,
        }:
            profile_options["compact_manager_enabled"] = (
                settings.mana_parent_touch_compact_manager_enabled
            )
            profile_options["compact_publication_enabled"] = (
                settings.mana_parent_touch_compact_publication_enabled
            )
        if settings.mana_family_compact_inputs_enabled or version in {
            35,
            36,
            37,
            38,
            39,
            40,
            41,
            42,
            43,
            44,
        }:
            profile_options["compact_inputs_enabled"] = settings.mana_family_compact_inputs_enabled
        if settings.mana_parent_touch_tariff_handoff_enabled or version in {
            33,
            34,
            35,
            36,
            37,
            38,
            39,
            40,
            41,
            42,
            43,
            44,
        }:
            profile_options["tariff_handoff_enabled"] = (
                settings.mana_parent_touch_tariff_handoff_enabled
            )
        if settings.mana_upsell_inline_results_enabled or version in {
            32,
            33,
            34,
            35,
            36,
            37,
            38,
            39,
            40,
            41,
            42,
            43,
            44,
        }:
            profile_options["inline_enabled"] = settings.mana_upsell_inline_results_enabled
        if settings.mana_client_upsell_currency_enabled or version in {
            31,
            32,
            33,
            34,
            35,
            36,
            37,
            38,
            39,
            40,
            41,
            42,
            43,
            44,
        }:
            profile_options["currency_enabled"] = settings.mana_client_upsell_currency_enabled
        if settings.mana_family_usage_comparisons_enabled or version in {
            30,
            31,
            32,
            33,
            34,
            35,
            36,
            37,
            38,
            39,
            40,
            41,
            42,
            43,
            44,
        }:
            profile_options["comparisons_enabled"] = settings.mana_family_usage_comparisons_enabled
        if settings.mana_parent_touch_clarifications_enabled or version in {
            29,
            30,
            31,
            32,
            33,
            34,
            35,
            36,
            37,
            38,
            39,
            40,
            41,
            42,
            43,
            44,
        }:
            profile_options["clarifications_enabled"] = (
                settings.mana_parent_touch_clarifications_enabled
            )
        if settings.mana_parent_support_questions_enabled or version in {
            28,
            29,
            30,
            31,
            32,
            33,
            34,
            35,
            36,
            37,
            38,
            39,
            40,
            41,
            42,
            43,
            44,
        }:
            profile_options["parent_questions_enabled"] = (
                settings.mana_parent_support_questions_enabled
            )
        if settings.mana_child_safety_remainder_enabled or version in {
            27,
            28,
            29,
            30,
            31,
            32,
            33,
            34,
            35,
            36,
            37,
            38,
            39,
            40,
            41,
            42,
            43,
            44,
        }:
            profile_options.update(
                remainder_enabled=settings.mana_child_safety_remainder_enabled,
            )
        if settings.mana_retention_trial_end_enabled or version in {
            26,
            27,
            28,
            29,
            30,
            31,
            32,
            33,
            34,
            35,
            36,
            37,
            38,
            39,
            40,
            41,
            42,
            43,
            44,
        }:
            profile_options.update(
                trial_end_enabled=settings.mana_retention_trial_end_enabled,
                trial_end_policy=settings.mana_retention_trial_end_policy,
            )
        if settings.mana_family_location_enabled or version in {
            23,
            26,
            27,
            28,
            29,
            30,
            31,
            32,
            33,
            34,
            35,
            36,
            37,
            38,
            39,
            40,
            41,
            42,
            43,
            44,
        }:
            profile_options["location_enabled"] = settings.mana_family_location_enabled
        if (
            settings.mana_conversion_trial_periods_enabled
            or settings.mana_family_location_enabled
            or version
            in {22, 23, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44}
        ):
            profile_options["trial_periods_enabled"] = (
                settings.mana_conversion_trial_periods_enabled
            )
        if settings.mana_parent_touch_manager_enabled or version in {
            21,
            22,
            23,
            26,
            27,
            28,
            29,
            30,
            31,
            32,
            33,
            34,
            35,
            36,
            37,
            38,
            39,
            40,
            41,
            42,
            43,
            44,
        }:
            model_name = settings.mana_parent_touch_model or settings.openai_model
            profile_options.update(
                manager_enabled=settings.mana_parent_touch_manager_enabled,
                manager_model=model_name,
                manager_binding=manager_binding(
                    model_name,
                    settings.openai_reasoning_effort,
                    settings.openai_verbosity,
                    settings.mana_parent_chat_max_output_tokens,
                    settings.openai_timeout_seconds,
                ),
            )
        if (
            settings.mana_conversion_shared_profile_enabled
            or settings.mana_parent_touch_manager_enabled
            or version
            in {
                20,
                21,
                22,
                23,
                26,
                27,
                28,
                29,
                30,
                31,
                32,
                33,
                34,
                35,
                36,
                37,
                38,
                39,
                40,
                41,
                42,
                43,
                44,
            }
        ):
            profile_options.update(
                shared_profile_enabled=settings.mana_conversion_shared_profile_enabled,
                shared_profile_policy=settings.mana_conversion_shared_profile_policy,
            )
        if settings.mana_family_day_usage_enabled or version in {
            18,
            19,
            20,
            21,
            22,
            23,
            26,
            27,
            28,
            29,
            30,
            31,
            32,
            33,
            34,
            35,
            36,
            37,
            38,
            39,
            40,
            41,
            42,
            43,
            44,
        }:
            profile_options["day_tools_enabled"] = settings.mana_family_day_usage_enabled
        if settings.mana_family_day_reviews_enabled or version in {
            19,
            20,
            21,
            22,
            23,
            26,
            27,
            28,
            29,
            30,
            31,
            32,
            33,
            34,
            35,
            36,
            37,
            38,
            39,
            40,
            41,
            42,
            43,
            44,
        }:
            profile_options["dated_reviews_enabled"] = settings.mana_family_day_reviews_enabled
        native_store = (
            (
                SqliteCompactManagerDecisionStore
                if settings.mana_parent_touch_compact_decisions_enabled or version == 44
                else SqliteDirectReminderStore
                if settings.mana_parent_touch_direct_reminders_enabled or version == 43
                else SqliteParentSetupStore
                if settings.mana_parent_setup_enabled or version == 42
                else SqliteCompactSourceToolStore
                if settings.mana_family_compact_source_tools_enabled or version == 41
                else SqliteLiteralTariffFollowupStore
                if settings.mana_upsell_literal_followups_enabled or version == 40
                else SqliteTariffFollowupStore
                if settings.mana_upsell_followups_enabled or version == 39
                else SqliteSavedObservationSafetyStore
                if settings.mana_family_saved_observations_enabled or version == 38
                else SqliteLocationComparisonSafetyStore
                if settings.mana_family_location_comparisons_enabled or version == 37
                else SqliteCompactParentPublicationStore
                if settings.mana_parent_touch_compact_publication_enabled or version == 36
                else SqliteCompactFamilyInputStore
                if settings.mana_family_compact_inputs_enabled
                or version in {35, 36, 37, 38, 39, 40, 41, 42, 43, 44}
                else SqliteTariffHandoffStore
                if settings.mana_parent_touch_tariff_handoff_enabled
                or version in {33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44}
                else SqliteInlineUpsellStore
                if settings.mana_upsell_inline_results_enabled or version == 32
                else SqliteUpsellCurrencyStore
                if settings.mana_client_upsell_currency_enabled or version == 31
                else SqliteUsageComparisonSafetyStore
                if settings.mana_family_usage_comparisons_enabled or version == 30
                else SqliteParentClarificationStore
                if settings.mana_parent_touch_clarifications_enabled
                or version in {29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44}
                else SqliteParentSupportQuestionStore
                if settings.mana_parent_support_questions_enabled
                or version in {28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44}
                else SqliteSafetyRemainderStore
                if settings.mana_child_safety_remainder_enabled
                or version
                in {27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44}
                else SqliteTrialEndStore
                if settings.mana_retention_trial_end_enabled
                or version
                in {26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44}
                else SqliteLocationSafetyStore
                if settings.mana_family_location_enabled or version == 23
                else SqliteTrialPeriodStore
                if settings.mana_conversion_trial_periods_enabled or version == 22
                else SqliteParentTouchManagerStore
                if settings.mana_parent_touch_manager_enabled or version == 21
                else SqliteSharedConversionProfileStore
                if settings.mana_conversion_shared_profile_enabled or version == 20
                else SqliteDatedReviewSafetyStore
                if settings.mana_family_day_reviews_enabled or version == 19
                else SqliteDatedSourceSafetyStore
                if settings.mana_family_day_usage_enabled or version in {18, 19}
                else SqliteRetentionExpiryStore
            )(
                settings.mana_parent_chat_database_path,
                reminder_policy=settings.mana_parent_reminder_policy,
                retention_policy=settings.mana_client_retention_policy,
                upsell_policy=settings.mana_client_upsell_policy,
                catalog_binding=settings.manakids_api_base_url + "/api/v1/tariffs/",
                expiry_policy=settings.mana_retention_expiry_policy,
                expiry_enabled=settings.mana_retention_expiry_enabled,
                **profile_options,
                profile_binding=settings.manakids_api_base_url
                + "/api/v1/admin-panel-parent/parent-list/",
                **native_options,
            )
            if settings.mana_retention_expiry_enabled
            or version
            in {
                17,
                18,
                19,
                20,
                21,
                22,
                23,
                26,
                27,
                28,
                29,
                30,
                31,
                32,
                33,
                34,
                35,
                36,
                37,
                38,
                39,
                40,
                41,
                42,
                43,
                44,
            }
            else SqliteClientUpsellStore(
                settings.mana_parent_chat_database_path,
                reminder_policy=settings.mana_parent_reminder_policy,
                retention_policy=settings.mana_client_retention_policy,
                upsell_policy=settings.mana_client_upsell_policy,
                catalog_binding=settings.manakids_api_base_url + "/api/v1/tariffs/",
                **native_options,
            )
            if settings.mana_client_upsell_enabled
            else SqliteClientRetentionStore(
                settings.mana_parent_chat_database_path,
                reminder_policy=settings.mana_parent_reminder_policy,
                retention_policy=settings.mana_client_retention_policy,
                **native_options,
            )
            if settings.mana_client_retention_enabled
            else SqliteParentReminderStore(
                settings.mana_parent_chat_database_path,
                reminder_policy=settings.mana_parent_reminder_policy,
                **native_options,
            )
            if settings.mana_parent_reminders_enabled
            else native_class(settings.mana_parent_chat_database_path, **native_options)
        )
        store, reviewed = native_store, native_store
    elif version in {
        11,
        12,
        13,
        14,
        15,
        16,
        17,
        18,
        19,
        20,
        21,
        22,
        23,
        26,
        27,
        28,
        29,
        30,
        31,
        32,
        33,
        34,
        35,
        36,
        37,
        38,
        39,
        40,
        41,
        42,
        43,
        44,
    }:
        if settings.mana_child_safety_enabled:
            raise RuntimeError("V11 safety execution requires its captured native source runtime")
        closed_class = (
            SqliteClosedCompactManagerDecisionStore
            if version == 44
            else SqliteClosedDirectReminderStore
            if version == 43
            else SqliteClosedParentSetupStore
            if version == 42
            else SqliteClosedCompactSourceToolStore
            if version == 41
            else SqliteClosedLiteralTariffFollowupStore
            if version == 40
            else SqliteClosedTariffFollowupStore
            if version == 39
            else SqliteClosedSavedObservationSafetyStore
            if version == 38
            else SqliteClosedLocationComparisonSafetyStore
            if version == 37
            else SqliteClosedCompactParentPublicationStore
            if version == 36
            else SqliteClosedCompactFamilyInputStore
            if version == 35
            else SqliteClosedTariffHandoffStore
            if version in {33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44}
            else SqliteClosedInlineUpsellStore
            if version == 32
            else SqliteClosedUpsellCurrencyStore
            if version == 31
            else SqliteClosedUsageComparisonSafetyStore
            if version == 30
            else SqliteClosedParentClarificationStore
            if version in {29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44}
            else SqliteClosedParentSupportQuestionStore
            if version in {28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44}
            else SqliteClosedSafetyRemainderStore
            if version in {27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44}
            else SqliteClosedTrialEndStore
            if version == 26
            else SqliteClosedLocationSafetyStore
            if version == 23
            else SqliteClosedTrialPeriodStore
            if version == 22
            else SqliteClosedParentTouchManagerStore
            if version == 21
            else SqliteClosedSharedConversionProfileStore
            if version == 20
            else SqliteClosedDatedReviewSafetyStore
            if version == 19
            else SqliteClosedDatedSourceSafetyStore
            if version == 18
            else SqliteClosedRetentionExpiryStore
            if version == 17
            else SqliteClosedClientUpsellStore
            if version == 16
            else SqliteClosedClientRetentionStore
            if version == 15
            else SqliteClosedParentReminderStore
            if version == 14
            else (
                SqliteClosedSourceReviewSafetyStore
                if version == 13
                else (
                    SqliteClosedObservationToolSafetyStore
                    if version == 12
                    else SqliteClosedSourceToolSafetyStore
                )
            )
        )
        closed_native = closed_class(
            settings.mana_parent_chat_database_path,
            history_only=not settings.mana_parent_touch_enabled,
            timezone=settings.mana_parent_chat_timezone,
            question_limit=settings.mana_parent_touch_question_limit,
            **({"storage_version": version} if version in {33, 34} else {}),
            **store_arguments,
        )
        store, reviewed = closed_native, closed_native
    elif settings.mana_conversion_account_source_enabled or (
        version == 10 and settings.mana_parent_touch_review_first_enabled
    ):
        assert settings.mana_child_safety_limits is not None
        account_store = SqliteConversionAccountStore(
            settings.mana_parent_chat_database_path,
            conversion_policy=settings.mana_conversion_policy,
            conversion_offers=settings.mana_conversion_offers,
            limits=settings.mana_child_safety_limits,
            timezone=settings.mana_parent_chat_timezone,
            question_limit=settings.mana_parent_touch_question_limit,
            push_queue_limit=settings.mana_parent_push_queue_limit,
            push_max_age_seconds=settings.mana_parent_push_max_age_seconds,
            push_daily_attempt_limit=settings.mana_parent_push_daily_attempt_limit,
            proactive_enabled=settings.mana_parent_touch_proactive_enabled,
            push_enabled=settings.mana_parent_push_enabled,
            conversation_enabled=settings.mana_conversion_conversation_enabled,
            account_source_enabled=settings.mana_conversion_account_source_enabled,
            account_read_limits=settings.mana_conversion_account_read_limits,
            **store_arguments,
        )
        store, reviewed = account_store, account_store
    elif version == 10:
        if settings.mana_child_safety_enabled:
            raise RuntimeError("V10 safety execution requires the captured review-first runtime")
        closed_account_store = SqliteClosedConversionAccountStore(
            settings.mana_parent_chat_database_path,
            history_only=not settings.mana_parent_touch_enabled,
            timezone=settings.mana_parent_chat_timezone,
            question_limit=settings.mana_parent_touch_question_limit,
            **store_arguments,
        )
        store, reviewed = closed_account_store, closed_account_store
    elif settings.mana_conversion_conversation_enabled or (
        version == 9 and settings.mana_parent_touch_review_first_enabled
    ):
        assert settings.mana_child_safety_limits is not None
        commercial_store = SqliteCommercialConversationStore(
            settings.mana_parent_chat_database_path,
            conversion_policy=settings.mana_conversion_policy,
            conversion_offers=settings.mana_conversion_offers,
            limits=settings.mana_child_safety_limits,
            timezone=settings.mana_parent_chat_timezone,
            question_limit=settings.mana_parent_touch_question_limit,
            push_queue_limit=settings.mana_parent_push_queue_limit,
            push_max_age_seconds=settings.mana_parent_push_max_age_seconds,
            push_daily_attempt_limit=settings.mana_parent_push_daily_attempt_limit,
            proactive_enabled=settings.mana_parent_touch_proactive_enabled,
            push_enabled=settings.mana_parent_push_enabled,
            conversation_enabled=settings.mana_conversion_conversation_enabled,
            **store_arguments,
        )
        store, reviewed = commercial_store, commercial_store
    elif version == 9:
        if settings.mana_child_safety_enabled:
            raise RuntimeError("V9 safety execution requires the captured review-first runtime")
        closed_commercial_store = SqliteClosedCommercialConversationStore(
            settings.mana_parent_chat_database_path,
            history_only=not settings.mana_parent_touch_enabled,
            timezone=settings.mana_parent_chat_timezone,
            question_limit=settings.mana_parent_touch_question_limit,
            **store_arguments,
        )
        store, reviewed = closed_commercial_store, closed_commercial_store
    elif (
        settings.mana_parent_touch_proactive_enabled
        or version == 8
        and settings.mana_parent_touch_review_first_enabled
    ):
        assert settings.mana_child_safety_limits is not None
        proactive_store = SqliteProactiveParentStore(
            settings.mana_parent_chat_database_path,
            conversion_policy=settings.mana_conversion_policy,
            conversion_offers=settings.mana_conversion_offers,
            limits=settings.mana_child_safety_limits,
            timezone=settings.mana_parent_chat_timezone,
            question_limit=settings.mana_parent_touch_question_limit,
            push_queue_limit=settings.mana_parent_push_queue_limit,
            push_max_age_seconds=settings.mana_parent_push_max_age_seconds,
            push_daily_attempt_limit=settings.mana_parent_push_daily_attempt_limit,
            proactive_enabled=settings.mana_parent_touch_proactive_enabled,
            push_enabled=settings.mana_parent_push_enabled,
            **store_arguments,
        )
        store, reviewed = proactive_store, proactive_store
    elif version == 8:
        if settings.mana_child_safety_enabled:
            raise RuntimeError("V8 safety execution requires the captured review-first runtime")
        closed_proactive_store = SqliteClosedProactiveParentStore(
            settings.mana_parent_chat_database_path,
            history_only=not settings.mana_parent_touch_enabled,
            timezone=settings.mana_parent_chat_timezone,
            question_limit=settings.mana_parent_touch_question_limit,
            **store_arguments,
        )
        store, reviewed = closed_proactive_store, closed_proactive_store
    elif (
        settings.mana_conversion_enabled
        or version == 7
        and settings.mana_parent_touch_review_first_enabled
    ):
        assert settings.mana_child_safety_limits is not None
        conversion_store = SqliteConversionStore(
            settings.mana_parent_chat_database_path,
            conversion_policy=settings.mana_conversion_policy,
            conversion_offers=settings.mana_conversion_offers,
            limits=settings.mana_child_safety_limits,
            timezone=settings.mana_parent_chat_timezone,
            question_limit=settings.mana_parent_touch_question_limit,
            **store_arguments,
        )
        store, reviewed = conversion_store, conversion_store
    elif version == 7:
        if settings.mana_child_safety_enabled:
            raise RuntimeError("V7 safety execution requires the captured review-first runtime")
        closed_conversion_store = SqliteClosedConversionStore(
            settings.mana_parent_chat_database_path,
            history_only=not settings.mana_parent_touch_enabled,
            timezone=settings.mana_parent_chat_timezone,
            question_limit=settings.mana_parent_touch_question_limit,
            **store_arguments,
        )
        store, reviewed = closed_conversion_store, closed_conversion_store
    elif settings.mana_parent_touch_review_first_enabled:
        assert settings.mana_child_safety_limits is not None
        review_store = SqliteReviewedMessageStore(
            settings.mana_parent_chat_database_path,
            limits=settings.mana_child_safety_limits,
            timezone=settings.mana_parent_chat_timezone,
            question_limit=settings.mana_parent_touch_question_limit,
            **store_arguments,
        )
        store, reviewed = review_store, review_store
    elif version == 6 and settings.mana_child_safety_enabled:
        raise RuntimeError("V6 safety execution requires the captured review-first runtime")
    elif version == 6 and settings.mana_parent_touch_enabled:
        closed_review_store = SqliteClosedReviewedBrokerStore(
            settings.mana_parent_chat_database_path,
            timezone=settings.mana_parent_chat_timezone,
            question_limit=settings.mana_parent_touch_question_limit,
            **store_arguments,
        )
        store, reviewed = closed_review_store, closed_review_store
    elif settings.mana_child_safety_enabled:
        assert settings.mana_child_safety_limits is not None
        store = SqliteChildSafetyStore(
            settings.mana_parent_chat_database_path,
            limits=settings.mana_child_safety_limits,
            timezone=settings.mana_parent_chat_timezone,
            question_limit=settings.mana_parent_touch_question_limit,
            **store_arguments,
        )
    elif settings.mana_parent_touch_enabled and version == 5:
        store = SqliteClosedSafetyBrokerStore(
            settings.mana_parent_chat_database_path,
            timezone=settings.mana_parent_chat_timezone,
            question_limit=settings.mana_parent_touch_question_limit,
            **store_arguments,
        )
    elif version >= 2 and (not settings.mana_parent_touch_enabled or version >= 4):
        store = SqliteFamilyCompatibilityStore(
            settings.mana_parent_chat_database_path,
            version=version,
            history_only=not settings.mana_parent_touch_enabled,
            timezone=settings.mana_parent_chat_timezone,
            question_limit=settings.mana_parent_touch_question_limit,
            **store_arguments,
        )
    elif settings.mana_parent_touch_enabled:
        store = SqliteFamilyAgentStore(
            settings.mana_parent_chat_database_path,
            timezone=settings.mana_parent_chat_timezone,
            question_limit=settings.mana_parent_touch_question_limit,
            **store_arguments,
        )
    else:
        store = SqliteParentChatStore(
            settings.mana_parent_chat_database_path,
            timezone=settings.mana_parent_chat_timezone,
            **store_arguments,
        )
    await store.initialize()
    async with httpx.AsyncClient(
        timeout=15, follow_redirects=False, transport=httpx.AsyncHTTPTransport(retries=0)
    ) as client:
        touch_settings = (
            settings.model_copy(update={"openai_model": settings.mana_parent_touch_model})
            if settings.mana_parent_touch_enabled and settings.mana_parent_touch_model
            else settings
        )
        model = OpenAIParentChatModel(touch_settings)
        safety_model: OpenAIChildSafetyModel | None = None
        worker: FamilyAgentWorker | None = None
        collection_worker: FamilyCollectionWorker | None = None
        try:
            profile_source = ManakidsChatChildrenSource(
                client=client,
                base_url=settings.manakids_api_base_url,
                username=settings.manakids_api_username,
                password=settings.manakids_api_password.get_secret_value(),
                wall_timeout_seconds=settings.mana_parent_chat_source_timeout_seconds,
                include_child_coverage=settings.mana_parent_setup_enabled,
            )
            children: ParentChildrenSource = (
                RetentionProfileSource(profile_source, store, clock=lambda: datetime.now(UTC))
                if isinstance(store, SqliteRetentionExpiryStore)
                and settings.mana_retention_expiry_enabled
                else profile_source
            )
            if settings.mana_parent_setup_enabled and isinstance(store, SqliteParentSetupStore):
                children = SetupProfileSource(children, store, clock=lambda: datetime.now(UTC))
            if settings.mana_family_app_usage_enabled or settings.mana_family_collection_enabled:
                sources = await family_source_runtime(
                    settings,
                    client,
                    children,
                    clock=lambda: datetime.now(UTC),
                    account_auth=profile_source,
                    day_identities=profile_source,
                    setup_receiver=store if isinstance(store, SqliteParentSetupStore) else None,
                    tariff_receiver=store
                    if isinstance(store, SqliteRetentionExpiryStore)
                    else None,
                )
            else:
                sources = await family_source_runtime(
                    settings, client, children, clock=lambda: datetime.now(UTC)
                )
            if isinstance(store, SqliteFamilyAgentStore) and settings.mana_parent_touch_enabled:
                safety = None
                if isinstance(store, SqliteChildSafetyStore):
                    assert settings.mana_child_safety_limits is not None
                    safety_settings = (
                        settings.model_copy(
                            update={"openai_model": settings.mana_child_safety_model}
                        )
                        if settings.mana_child_safety_model
                        else settings
                    )
                    safety_model = (
                        OpenAIChildSourceModel(safety_settings)
                        if settings.mana_child_safety_source_tools_enabled
                        else OpenAIChildSafetyModel(safety_settings)
                    )
                    native_sources = None
                    if isinstance(store, SqliteSourceToolSafetyStore):
                        assert sources is not None and isinstance(
                            safety_model, OpenAIChildSourceModel
                        )
                        native_sources = SourceToolWorkflow(
                            store=store,
                            children=children,
                            model=safety_model,
                            prompts=SourceToolPromptBuilder(),
                            sources=sources.reads,
                            day_usage=sources.day_usage,
                            saved_observations=saved_observation_service(
                                path=settings.mana_family_source_database_path,
                                binding=(
                                    f"mana:firebase:{settings.firebase_project_id}:"
                                    f"{settings.firebase_database_id}:child-battery-v1"
                                ),
                                source_limits=settings.mana_family_source_limits,
                                children=children,
                                clock=lambda: datetime.now(UTC),
                                maximum_age_seconds=settings.mana_family_source_maximum_age_seconds,
                                app_usage=settings.mana_family_app_usage_enabled,
                                location=settings.mana_family_location_enabled,
                                day_usage=settings.mana_family_day_usage_enabled,
                            )
                            if settings.mana_family_saved_observations_enabled
                            else None,
                            clock=SystemManaAIClock(),
                            limits=settings.mana_child_safety_limits,
                            max_output_tokens=settings.mana_child_safety_max_output_tokens,
                        )
                    safety = ChildSafetyService(
                        store=store,
                        children=children,
                        model=safety_model,
                        prompts=ChildSafetyPromptBuilder(),
                        clock=SystemManaAIClock(),
                        limits=settings.mana_child_safety_limits,
                        max_output_tokens=settings.mana_child_safety_max_output_tokens,
                        native_sources=native_sources,
                    )
                service: ParentChatService = ParentTouchService(
                    store=store,
                    children=children,
                    model=model,
                    clock=lambda: datetime.now(UTC),
                    max_output_tokens=settings.mana_parent_chat_max_output_tokens,
                    history_turn_limit=settings.mana_parent_chat_history_turns,
                    safety=safety,
                    reviewed=reviewed,
                    manager=store if isinstance(store, SqliteParentTouchManagerStore) else None,
                    parent_publications=store
                    if isinstance(store, SqliteCompactParentPublicationStore)
                    else None,
                    tariff_followups=store
                    if isinstance(store, SqliteTariffFollowupStore)
                    else None,
                    input_presentations=store
                    if isinstance(store, SqliteCompactFamilyInputStore)
                    else None,
                    sources=sources.reads if sources else None,
                    collection=sources.collection if sources else None,
                    upsell=ClientUpsellService(
                        store,
                        ManakidsConversionCatalogSource(
                            client=client,
                            base_url=settings.manakids_api_base_url,
                            username=settings.manakids_api_username,
                            password=settings.manakids_api_password.get_secret_value(),
                            clock=lambda: datetime.now(UTC),
                        ),
                        children,
                        clock=lambda: datetime.now(UTC),
                    )
                    if isinstance(store, SqliteClientUpsellStore)
                    else None,
                    expiry=RetentionExpiryService(store, clock=lambda: datetime.now(UTC))
                    if isinstance(store, SqliteRetentionExpiryStore)
                    and settings.mana_retention_expiry_enabled
                    else None,
                    direct_reminders=store
                    if isinstance(store, SqliteDirectReminderStore)
                    else None,
                    setup=ParentSetupService(store, clock=lambda: datetime.now(UTC))
                    if isinstance(store, SqliteParentSetupStore)
                    and settings.mana_parent_setup_enabled
                    else None,
                    retention=ClientRetentionService(store, clock=lambda: datetime.now(UTC))
                    if isinstance(store, SqliteClientRetentionStore)
                    else None,
                    reminders=ParentReminderService(
                        store, children, clock=lambda: datetime.now(UTC)
                    )
                    if isinstance(store, SqliteParentReminderStore)
                    else None,
                    proactive=(
                        ProactiveParentService(
                            store,
                            clock=lambda: datetime.now(UTC),
                            gateway=(
                                ManakidsParentPushGateway(
                                    client=client,
                                    base_url=settings.manakids_api_base_url,
                                    username=settings.manakids_api_username,
                                    password=settings.manakids_api_password.get_secret_value(),
                                )
                                if settings.mana_parent_push_enabled
                                else None
                            ),
                        )
                        if settings.mana_parent_touch_proactive_enabled
                        and isinstance(store, SqliteProactiveParentStore)
                        else None
                    ),
                    conversion=(
                        ConversionService(
                            store,
                            clock=lambda: datetime.now(UTC),
                            accounts=(
                                ConversionAccountVerifier(
                                    store,
                                    (
                                        ManakidsConversionAccountSource(
                                            client=client,
                                            base_url=settings.manakids_api_base_url,
                                            username=settings.manakids_api_username,
                                            password=settings.manakids_api_password.get_secret_value(),
                                            wall_timeout_seconds=(
                                                settings.mana_parent_chat_source_timeout_seconds
                                            ),
                                        )
                                        if settings.mana_conversion_account_source_enabled
                                        else None
                                    ),
                                    clock=lambda: datetime.now(UTC),
                                )
                                if isinstance(store, SqliteConversionAccountStore)
                                else None
                            ),
                            grants=(
                                TrialGrantService(
                                    store,
                                    ManakidsTrialGrantGateway(
                                        client=client,
                                        base_url=settings.manakids_api_base_url,
                                        username=settings.manakids_api_username,
                                        password=settings.manakids_api_password.get_secret_value(),
                                    ),
                                    clock=lambda: datetime.now(UTC),
                                )
                                if settings.mana_conversion_trial_grants_enabled
                                else None
                            ),
                        )
                        if settings.mana_conversion_enabled
                        and isinstance(store, SqliteConversionStore)
                        else None
                    ),
                )
                if safety is not None:
                    assert isinstance(service, ParentTouchService)
                    worker = FamilyAgentWorker(
                        safety,
                        service,
                        clock=lambda: datetime.now(UTC),
                        interval=settings.mana_child_safety_poll_seconds,
                        parallel_enabled=settings.mana_family_parallel_worker_enabled,
                        source_reviews=SourceReviewService(
                            sources.store,
                            store,
                            children,
                            clock=lambda: datetime.now(UTC),
                            available=lambda: safety.worker_available,
                        )
                        if sources
                        and isinstance(sources.store, SqliteSourceReviewCache)
                        and isinstance(store, SqliteSourceReviewSafetyStore)
                        else None,
                        source_safety=(
                            SourceSafetyService(
                                sources.store,
                                safety,
                                children,
                                policy=sources.safety_policy,
                                clock=lambda: datetime.now(UTC),
                            )
                            if sources and settings.mana_family_source_safety_enabled
                            else None
                        ),
                    )
                    worker.start()
            else:
                service = ParentChatService(
                    store=store,
                    children=children,
                    model=model,
                    clock=lambda: datetime.now(UTC),
                    max_output_tokens=settings.mana_parent_chat_max_output_tokens,
                    history_turn_limit=settings.mana_parent_chat_history_turns,
                )
            if sources and sources.collection is not None:
                collection_worker = FamilyCollectionWorker(
                    sources.collection, interval=settings.mana_family_collection_poll_seconds
                )
                collection_worker.start()
            yield service
        finally:
            if collection_worker is not None:
                await collection_worker.close()
            if worker is not None:
                await worker.close()
            if safety_model is not None:
                await safety_model.close()
            await model.close()
