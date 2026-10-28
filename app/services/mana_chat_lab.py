"""Isolated fictional-family lab; never imports a live data or write adapter."""

import asyncio
import json
import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, Protocol
from uuid import NAMESPACE_URL, uuid4, uuid5
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app.core.config import get_settings
from app.mana_ai.application.chat_actions import ChatActionService
from app.mana_ai.application.chat_ports import (
    ChatModelReceipt,
    ChatPrompt,
    ParentChatError,
    ParentChatModel,
    ParentChildrenSource,
)
from app.mana_ai.application.child_safety import ChildSafetyService
from app.mana_ai.application.client_retention import ClientRetentionService
from app.mana_ai.application.client_upsell import ClientUpsellService
from app.mana_ai.application.conversion import ConversionService
from app.mana_ai.application.day_usage_service import FamilyDayUsageService
from app.mana_ai.application.family_sources import FamilySourceService
from app.mana_ai.application.parent_reminders import ParentReminderService
from app.mana_ai.application.parent_touch import ParentTouchService
from app.mana_ai.application.parent_touch_manager import manager_binding
from app.mana_ai.application.ports import Clock
from app.mana_ai.application.proactive_parent import ProactiveParentService
from app.mana_ai.application.retention_expiry import RetentionExpiryService, RetentionProfileSource
from app.mana_ai.application.source_reviews import SourceReviewService
from app.mana_ai.application.source_safety import SourceSafetyService
from app.mana_ai.application.source_tool_workflow import SourceToolWorkflow
from app.mana_ai.application.trial_action_cards import TrialButtonGrantService
from app.mana_ai.application.upsell_text import TARIFF_HANDOFF_PLACEHOLDER
from app.mana_ai.domain.chat import ChatChild, ChatTokens, ParentChildContext, ParentTariffContext
from app.mana_ai.domain.chat_actions import ChatActionCard, ChatActionCreate
from app.mana_ai.domain.child_location import ChildLocationFacts, LocationComparisonView
from app.mana_ai.domain.child_safety import (
    ChildSafetyLimits,
    SafetyAssessmentPage,
    SafetyBudget,
    SafetyInformationNeed,
    SafetyModelDecision,
    SafetySourceReviewDecision,
)
from app.mana_ai.domain.client_retention import ClientRetentionPolicy
from app.mana_ai.domain.client_upsell import ClientUpsellPolicy, UpsellChoice, UpsellEnquiry
from app.mana_ai.domain.conversion import (
    ConversionOffer,
    ConversionPolicy,
    ConversionProposalPage,
    ConversionSnapshot,
    PaidConversionOffer,
    TrialConversionOffer,
)
from app.mana_ai.domain.conversion_accounts import ConversionAccountReadLimits
from app.mana_ai.domain.conversion_catalog import (
    ConversionCatalogObservation,
    ConversionTariffPrice,
)
from app.mana_ai.domain.enums import AnalysisVerdict, FindingCategory, RiskLevel
from app.mana_ai.domain.family_agents import (
    AgentQuestionRequest,
    ParentTouchHistory,
    ParentTouchMessageRequest,
)
from app.mana_ai.domain.family_collection import FamilyCollectionWindow
from app.mana_ai.domain.family_day_usage import (
    DayUsageTarget,
    FamilyDayUsagePage,
    ParentUsageLookup,
)
from app.mana_ai.domain.family_sources import (
    AppUsageCounter,
    ChildAppUsageFacts,
    ChildBatteryFacts,
    FamilySourceChange,
    FamilySourceLimits,
)
from app.mana_ai.domain.parent_reminders import ReminderCandidate, ReminderPolicy
from app.mana_ai.domain.parent_touch_manager import ManagerTarget, ParentTouchManagerHandoff
from app.mana_ai.domain.proactive_parent import ParentContactContext
from app.mana_ai.domain.responses import FindingDraft, ModelAnalysis, SafetyMonitorDetails
from app.mana_ai.domain.retention_expiry import RetentionExpiryPolicy, RetentionTariffFact
from app.mana_ai.domain.saved_observations import SavedObservationLimits
from app.mana_ai.domain.source_reviews import (
    CounterComparisonView,
    SourceReviewPolicy,
    SourceReviewWork,
)
from app.mana_ai.domain.source_safety import SourceSafetyPolicy, SourceSafetyReceipt
from app.services.child_safety_model import OpenAIChildSafetyModel
from app.services.child_safety_prompts import ChildSafetyPromptBuilder
from app.services.child_source_model import OpenAIChildSourceModel
from app.services.client_retention_store import SqliteClientRetentionStore
from app.services.client_upsell_store import SqliteClientUpsellStore
from app.services.commercial_conversation_store import SqliteCommercialConversationStore
from app.services.compact_family_input_store import SqliteCompactFamilyInputStore
from app.services.compact_parent_publication_store import SqliteCompactParentPublicationStore
from app.services.dated_review_safety_store import SqliteDatedReviewSafetyStore
from app.services.dated_source_safety_store import SqliteDatedSourceSafetyStore
from app.services.day_review_cache import SqliteDayReviewCache
from app.services.day_usage_cache import SqliteDayUsageCache
from app.services.family_agent_worker import FamilyAgentWorker
from app.services.inline_upsell_store import SqliteInlineUpsellStore
from app.services.lab_chat_action_store import SimulatedChatActionExecutor, SqliteLabChatActionStore
from app.services.lab_collection import LabCollection, LabCollectionClock, lab_collection_store
from app.services.lab_location import LabLocationSource
from app.services.lab_location_comparison import (
    LabComparisonLocationSource,
    LabLocationComparisonClock,
    location_comparison_text,
)
from app.services.lab_native_source_model import LabNativeSourceModel
from app.services.lab_tariff_followup import simulated_tariff_refinement
from app.services.lab_trial_action_store import LabTrialActionExecutor, SqliteLabTrialActionStore
from app.services.lab_trial_end import LabTrialEndClock
from app.services.lab_trial_period import LabTrialGrantGateway, LabTrialProfiles, seed_trial_history
from app.services.lab_usage_comparison import LabUsageComparisonClock, comparison_text
from app.services.location_comparison_cache import SqliteLocationComparisonCache
from app.services.location_comparison_safety_store import SqliteLocationComparisonSafetyStore
from app.services.location_safety_store import SqliteLocationSafetyStore
from app.services.location_source_cache import SqliteLocationSourceCache
from app.services.location_time_cache import SqliteLocationTimeCache
from app.services.mana_ai_openai_gateway import SystemManaAIClock
from app.services.multi_family_source_store import SqliteMultiFamilySourceStore
from app.services.parent_chat_model import OpenAIParentChatModel
from app.services.parent_clarification_store import SqliteParentClarificationStore
from app.services.parent_reminder_store import SqliteParentReminderStore
from app.services.parent_support_question_store import SqliteParentSupportQuestionStore
from app.services.parent_touch_manager_store import SqliteParentTouchManagerStore
from app.services.retention_expiry_store import SqliteRetentionExpiryStore
from app.services.safety_remainder_store import SqliteSafetyRemainderStore
from app.services.saved_observation_runtime import saved_observation_service
from app.services.saved_observation_safety_store import SqliteSavedObservationSafetyStore
from app.services.shared_conversion_profile_store import SqliteSharedConversionProfileStore
from app.services.source_review_cache import SqliteSourceReviewCache
from app.services.source_review_safety_store import SqliteSourceReviewSafetyStore
from app.services.source_safety_store import SqliteSourceSafetyStore
from app.services.source_tool_prompts import SourceToolPromptBuilder
from app.services.source_tool_safety_store import (
    SqliteObservationToolSafetyStore,
    SqliteSourceToolSafetyStore,
)
from app.services.tariff_followup_store import SqliteTariffFollowupStore
from app.services.tariff_handoff_store import SqliteTariffHandoffStore
from app.services.trial_end_store import SqliteTrialEndStore
from app.services.trial_period_store import SqliteTrialPeriodStore
from app.services.upsell_currency_store import SqliteUpsellCurrencyStore
from app.services.usage_comparison_cache import SqliteUsageComparisonCache
from app.services.usage_comparison_safety_store import SqliteUsageComparisonSafetyStore

LAB_PARENT = "900001"
LAB_CHILD = 900002


class LabAppUsageSource:
    def __init__(self, clock: Clock) -> None:
        self._clock, self.calls = clock, 0

    async def read(self, child_id: int) -> ChildAppUsageFacts:
        if child_id != LAB_CHILD:
            raise ValueError("Only the fictional lab child is allowed")
        self.calls += 1
        return ChildAppUsageFacts(
            child_id=child_id,
            status="available",
            returned_apps=1,
            total_apps=3,
            complete=False,
            collected_at=self._clock.now(),
            entries=(
                AppUsageCounter(
                    app_name="Fictional lessons",
                    provider_recorded_at="2026-10-23 23:43:43",
                    reported_seconds=3600,
                ),
            ),
        )


class LabDayUsageSource:
    """Fictional date-filtered family source; no username or provider is accessed."""

    def __init__(
        self, profiles: ParentChildrenSource, clock: Clock, *, comparison_story: bool = False
    ) -> None:
        self._profiles, self._clock, self.calls = profiles, clock, 0
        self._comparison_story = comparison_story

    async def read_usage_lookup(self, parent_id: str) -> ParentUsageLookup:
        context = await self._profiles.read(parent_id)
        return ParentUsageLookup(
            parent_id=context.parent_id,
            username=SecretStr("fictional-lookup"),
            connected_child_ids=tuple(c.child_id for c in context.children if c.connected),
            collected_at=context.collected_at,
        )

    async def read(self, parent_id: str, requested_day: date) -> FamilyDayUsagePage:
        return await self.read_verified(await self.read_usage_lookup(parent_id), requested_day)

    async def read_verified(
        self, lookup: ParentUsageLookup, requested_day: date
    ) -> FamilyDayUsagePage:
        self.calls += 1
        now = self._clock.now()
        facts = ChildAppUsageFacts(
            child_id=LAB_CHILD,
            status="available",
            returned_apps=1,
            total_apps=3,
            complete=False,
            collected_at=now,
            entries=(
                AppUsageCounter(
                    app_name="Fictional lessons",
                    provider_recorded_at=requested_day.isoformat() + " 12:00:00",
                    reported_seconds=1800
                    if self._comparison_story and requested_day == date(2026, 10, 24)
                    else 3600,
                ),
            ),
        )
        return FamilyDayUsagePage(
            parent_id=lookup.parent_id,
            requested_day=requested_day,
            ownership_collected_at=lookup.collected_at,
            collected_at=now,
            owned_children_count=len(lookup.connected_child_ids),
            provider_children_count=1,
            children=(facts,),
            complete_family=True,
        )


class ClosableModel(ParentChatModel, Protocol):
    async def close(self) -> None: ...


class LabCatalog:
    """Fictional fixture matching known price shapes; never a live catalog read."""

    def __init__(self, clock: Clock) -> None:
        self._clock, self.calls = clock, 0

    async def read(self) -> ConversionCatalogObservation:
        self.calls += 1
        return ConversionCatalogObservation(
            collected_at=self._clock.now(),
            tariffs=tuple(
                ConversionTariffPrice(
                    tariff_id=identity, currency="UZS", price_minor=price, duration_days=days
                )
                for identity, price, days in [
                    ("3", 6000000, 30),
                    ("8", 16200000, 90),
                    ("9", 29900000, 180),
                    ("4", 59900000, 365),
                ]
            ),
        )


class LabProfiles:
    def __init__(
        self, clock: Clock, *, tariff_context: bool = False, tariff_until: datetime | None = None
    ) -> None:
        self._clock = clock
        self._tariff_context = tariff_context
        self._tariff_until = tariff_until

    async def read(self, parent_id: str) -> ParentChildContext:
        if parent_id != LAB_PARENT:
            raise ParentChatError("lab_family_not_allowed", 403)
        now = self._clock.now()
        return ParentChildContext(
            parent_id=LAB_PARENT,
            children=[
                ChatChild(child_id=LAB_CHILD, name="Тестовый ребёнок", age=8, connected=True)
            ],
            collected_at=now,
            limitations=["Fictional lab family; no Manakids, Firebase or GA4 data."],
            tariff=ParentTariffContext(
                collected_at=now,
                tariff_name="Fictional 1-Month",
                is_paid=True,
                valid_until=self._tariff_until
                or datetime(2026, 11, 23, 16, 0, tzinfo=ZoneInfo("Asia/Tashkent")),
                payment_date=None,
                agent_trial_used=True,
            )
            if self._tariff_context
            else None,
        )


class LabBatterySource:
    """One durable fictional observation; restart does not invent new device data."""

    def __init__(self, directory: Path, clock: Clock) -> None:
        self._clock, self.calls = clock, 0
        path = directory / "source-fixture.json"
        if path.is_symlink():
            raise ValueError("Lab fixtures cannot use symlinks")
        observed = clock.now() - timedelta(seconds=30)
        if not path.exists():
            fixture = ChildBatteryFacts(
                child_id=LAB_CHILD,
                status="available",
                percent=12,
                observed_at=observed,
                source_updated_at=observed,
                collected_at=clock.now(),
                quality="dated",
            )
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(descriptor, "w") as stream:
                stream.write(fixture.model_dump_json())
                stream.flush()
                os.fsync(stream.fileno())
        if path.stat().st_size > 1024:
            raise ValueError("Invalid lab fixture")
        self._fixture = ChildBatteryFacts.model_validate_json(path.read_text())
        if self._fixture.child_id != LAB_CHILD or self._fixture.percent != 12:
            raise ValueError("Unexpected lab fixture")

    async def read(self, child_id: int) -> ChildBatteryFacts:
        if child_id != LAB_CHILD:
            raise ParentChatError("lab_child_not_allowed", 403)
        self.calls += 1
        return ChildBatteryFacts.model_validate(
            self._fixture.model_dump() | {"collected_at": self._clock.now()}
        )


class SimulatedModel:
    """Deterministic protocol demonstration, not an actual neural-network answer."""

    def __init__(self, role: Literal["speaker", "safety"]) -> None:
        self.role = role

    async def count_input(self, prompt: ChatPrompt) -> int:
        return 100

    @staticmethod
    def _tariff_enquiry(latest: str) -> UpsellEnquiry:
        currency = "UZS" if "UZS" in latest.upper() else "USD" if "USD" in latest.upper() else None
        return UpsellEnquiry(
            parent_quote=latest,
            objective="list",
            currency=currency,
            minimum_days=90 if "90" in latest else 1,
            maximum_days=90 if "90" in latest else 366,
            maximum_price_minor=20000000 if "200000" in latest else None,
        )

    async def respond(self, prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
        if (
            self.role == "speaker"
            and prompt.manager_scope
            and prompt.manager_scope.stage == "route"
        ):
            text = prompt.messages[-1][1].casefold()
            spoken_language = prompt.manager_scope.language
            if (
                prompt.manager_scope.language_reference is not None
                and "qanday" in prompt.manager_scope.language_reference.casefold()
            ):
                spoken_language = "uz-Latn"  # Only the explicit fictional lab story.
            if prompt.manager_scope.clarifications_enabled and any(
                t in text
                for t in ("как настроить мана", "как настроить mana", "mana qanday sozlanadi")
            ):
                question = (
                    "Telefoningiz Androidmi yoki iPhonemi?"
                    if spoken_language == "uz-Latn"
                    else "У вас Android или iPhone?"
                )
                return ChatModelReceipt(
                    usage=ChatTokens(input_tokens=100, output_tokens=50),
                    model="lab-simulated-not-billed",
                    completed=True,
                    answer=question,
                    clarification_question=question,
                )
            if prompt.manager_scope.clarifications_enabled and text.strip() in {
                "android",
                "iphone",
            }:
                return ChatModelReceipt(
                    usage=ChatTokens(input_tokens=100, output_tokens=50),
                    model="lab-simulated-not-billed",
                    completed=True,
                    answer=(
                        "MANA bildirishnomalariga ruxsatni telefon sozlamalaridan tekshiring."
                        if spoken_language == "uz-Latn"
                        else "Проверьте разрешение уведомлений MANA в настройках телефона."
                    ),
                )
            refinement = simulated_tariff_refinement(
                json.loads(prompt.messages[0][1]), prompt.messages[-1][1]
            )
            target: ManagerTarget | None = (
                "upsell"
                if refinement is not None
                else "reminder"
                if any(t in text for t in ("напомни", "eslat", "remind"))
                else "upsell"
                if any(
                    t in text for t in ("тариф", "tarif", "цен", "narx", "price", "заканчивается")
                )
                else None
                if any(t in text for t in ("привет", "спасибо", "hello", "salom", "rahmat"))
                else "child_safety"
            )
            enquiry = refinement or (
                self._tariff_enquiry(prompt.messages[-1][1])
                if target == "upsell"
                and prompt.manager_scope.tariff_handoff_enabled
                and not any(
                    t in text for t in ("какой у меня тариф", "заканчивается", "mening tarifim")
                )
                else None
            )
            return ChatModelReceipt(
                usage=ChatTokens(input_tokens=100, output_tokens=50),
                model="lab-simulated-not-billed",
                completed=True,
                answer=TARIFF_HANDOFF_PLACEHOLDER
                if enquiry is not None
                else None
                if target
                else {
                    "ru": "Здравствуйте. Помогу с MANA.",
                    "uz-Latn": "Salom. MANA bo‘yicha yordam beraman.",
                    "uz-Cyrl": "Салом. MANA бўйича ёрдам бераман.",
                    "en": "Hello. I can help with MANA.",
                }[prompt.manager_scope.language],
                manager_handoff=ParentTouchManagerHandoff(
                    target=target, call_id="call_" + uuid4().hex, tariff_enquiry=enquiry
                )
                if target
                else None,
            )
        if (
            self.role == "speaker"
            and prompt.notice is None
            and prompt.question is None
            and any(
                term in prompt.messages[-1][1].casefold()
                for term in ("какой у меня тариф", "когда заканчивается", "mening tarifim")
            )
            and '"parent_tariff"' in prompt.messages[0][1]
        ):
            uz = "mening tarifim" in prompt.messages[-1][1].casefold()
            tariff = ParentTariffContext.model_validate(
                json.loads(prompt.messages[0][1])["parent_tariff"]
            )
            until = tariff.valid_until
            if (
                until
                and prompt.reminder_scope
                and prompt.reminder_scope.timezone_basis == "verified_contact"
            ):
                until = until.astimezone(ZoneInfo(prompt.reminder_scope.default_timezone))
            date = (
                f"{until:%Y-%m-%d %H:%M}, UTC{until:%z}"
                if until
                else "noma’lum"
                if uz
                else "дата неизвестна"
            )
            name = tariff.tariff_name or ("nomi noma’lum" if uz else "название неизвестно")
            return ChatModelReceipt(
                usage=ChatTokens(input_tokens=100, output_tokens=50),
                model="lab-simulated-not-billed",
                answer=(
                    f"Ilovada {name} tarifi ko‘rsatilgan; muddati {date}."
                    if uz
                    else f"В приложении указан тариф {name}; срок — {date}."
                ),
                completed=True,
            )
        question_id = notice_id = None
        if self.role == "safety":
            decision: SafetyModelDecision | SafetySourceReviewDecision
            data = json.loads(prompt.messages[0][1])
            if data["kind"] == "source_review":
                location_facts = next(
                    (
                        s["facts"]
                        for s in data["snapshots"]
                        if s["source"] == "firebase.child_location.v1"
                    ),
                    None,
                )
                decision = SafetySourceReviewDecision(
                    analysis=None,
                    followup_summary=(
                        location_comparison_text(
                            LocationComparisonView.model_validate(data["saved_location_comparison"])
                        )
                        if data.get("saved_location_comparison") is not None
                        else comparison_text(
                            CounterComparisonView.model_validate(data["saved_counter_comparison"])
                        )
                        if data.get("saved_counter_comparison") is not None
                        else f"Последняя запись местоположения от {location_facts['observed_at']}; "
                        "текущее местоположение неизвестно. Проверьте карту в приложении."
                        if location_facts is not None
                        else "Снимки батареи и приложений получены; период счётчиков "
                        "и текущее подключение неизвестны. Проверьте заряд телефона."
                    ),
                    question=None,
                    notify_parent=True,
                )
            elif data["kind"] == "parent_message":
                chat_text = " ".join(item["content"] for item in data["chat"]).casefold()
                wants_sleep = any(
                    word in chat_text for word in ("сон", "спит", "уснуть", "uyqu", "uxla", "sleep")
                )
                decision = SafetyModelDecision(
                    analysis=None,
                    followup_summary=(
                        "Fictional lab: parent message reviewed; no new sensor measurement."
                    ),
                    question=SafetyInformationNeed(
                        child_alias="child-1",
                        information_key="sleep.bedtime",
                        question="Во сколько ребёнок обычно ложится спать?",
                        reason="The fictional parent's sleep request needs a bedtime.",
                        priority=1,
                    )
                    if wants_sleep and not data.get("conversation_needs")
                    else None,
                )
            elif data["new_observation"]["capability_input"].get("battery"):
                battery = data["new_observation"]["capability_input"]["battery"][0]
                decision = SafetyModelDecision(
                    analysis=ModelAnalysis(
                        verdict=AnalysisVerdict.WARN,
                        summary=(
                            f"Симуляция: по датированному измерению заряд {battery['percent']}%."
                        ),
                        details=SafetyMonitorDetails(
                            parent_context="Fictional battery only; connectivity is unknown.",
                            significant_event_count=1,
                        ),
                        findings=[
                            FindingDraft(
                                category=FindingCategory.BATTERY_ANOMALY,
                                risk_level=RiskLevel.MEDIUM,
                                confidence=95,
                                title="Низкий заряд в тестовом измерении",
                                summary=(f"Заряд {battery['percent']}%; подключение неизвестно."),
                                recommendation="При возможности зарядите телефон.",
                                evidence_ids=[battery["evidence_id"]],
                            )
                        ],
                    ),
                    followup_summary=None,
                    question=None,
                )
            else:
                decision = SafetyModelDecision(
                    analysis=ModelAnalysis(
                        verdict=AnalysisVerdict.ALERT,
                        summary="Симуляция: в тестовом уведомлении есть угроза.",
                        details=SafetyMonitorDetails(
                            parent_context="Fictional lab observation only.",
                            significant_event_count=1,
                        ),
                        findings=[
                            FindingDraft(
                                category=FindingCategory.THREAT,
                                risk_level=RiskLevel.HIGH,
                                confidence=95,
                                title="Тестовая угроза",
                                summary="Синтетический текст содержит угрозу.",
                                recommendation="Спокойно уточните, в безопасности ли ребёнок.",
                                evidence_ids=["lab-threat"],
                            )
                        ],
                    ),
                    followup_summary=None,
                    question=None,
                )
            answer = decision.model_dump_json()
        else:
            uzbek = prompt.response_language == "uz-Latn"
            if prompt.upsell_scope is not None:
                latest = prompt.messages[-1][1]
                if (
                    prompt.upsell_scope.protocol == "catalog-currency-v2"
                    and prompt.question is None
                    and (prompt.notice is None or prompt.notice.kind != "urgent")
                    and any(
                        word in latest.casefold()
                        for word in (
                            "тариф",
                            "tarif",
                            "цен",
                            "narx",
                            "price",
                            "стоимост",
                            "сколько стоит",
                            "дешев",
                            "arzon",
                            "cheap",
                        )
                    )
                ):
                    enquiry = self._tariff_enquiry(latest)
                    currency = enquiry.currency
                    return ChatModelReceipt(
                        usage=ChatTokens(input_tokens=100, output_tokens=50),
                        model="lab-simulated-not-billed",
                        completed=True,
                        answer="Catalog enquiry awaiting host validation.",
                        upsell_enquiry=enquiry if currency is None else None,
                        upsell_choice=UpsellChoice.model_validate(enquiry.model_dump())
                        if currency
                        else None,
                    )
                if any(
                    q in latest.casefold()
                    for q in (
                        "тариф на 3 месяца",
                        "тариф на 90 дней",
                        "3 oylik tarif",
                        "90-day tariff",
                    )
                ):
                    return ChatModelReceipt(
                        usage=ChatTokens(input_tokens=100, output_tokens=50),
                        model="lab-simulated-not-billed",
                        completed=True,
                        answer="Catalog enquiry awaiting host validation.",
                        upsell_choice=UpsellChoice(
                            parent_quote=latest,
                            objective="lowest_total",
                            currency="UZS",
                            minimum_days=90,
                            maximum_days=90,
                            maximum_price_minor=None,
                        ),
                    )
            if prompt.retention_scope is not None and prompt.question is not None:
                return ChatModelReceipt(
                    usage=ChatTokens(input_tokens=100, output_tokens=50),
                    model="lab-simulated-not-billed",
                    completed=True,
                    question_id=prompt.question.question_id,
                    answer=(
                        "MANA sozlamalari bilan yordam bera olaman. Qaysi sozlamani tushuntiray?"
                        if prompt.response_language == "uz-Latn"
                        else "Помогу разобраться с настройками MANA. С какой настройкой помочь?"
                    ),
                )
            if prompt.retention_scope is not None:
                return ChatModelReceipt(
                    usage=ChatTokens(input_tokens=100, output_tokens=50),
                    model="lab-simulated-not-billed",
                    completed=True,
                    answer=(
                        "Avvalgi suhbatimizga qaytishingiz mumkin. "
                        "Sozlamalar bo‘yicha yordam bera olaman."
                    )
                    if prompt.response_language == "uz-Latn"
                    else (
                        "Можно вернуться к прошлому разговору. "
                        "Помогу разобраться с настройками MANA."
                    ),
                )
            if prompt.reminder_scope:
                latest = prompt.messages[-1][1].casefold()
                task = next(
                    (
                        q
                        for q in ("купить тетради", "daftar sotib olish", "buy notebooks")
                        if q in latest
                    ),
                    None,
                )
                if task is not None:
                    scope = prompt.reminder_scope
                    due = (
                        scope.now.astimezone(ZoneInfo(scope.default_timezone)) + timedelta(days=1)
                    ).replace(hour=9, minute=0, second=0, microsecond=0)
                    return ChatModelReceipt(
                        usage=ChatTokens(input_tokens=100, output_tokens=50),
                        model="lab-simulated-not-billed",
                        answer="Reminder draft pending host validation.",
                        completed=True,
                        reminder_candidate=ReminderCandidate(
                            content=task,
                            due_at=None if "позже" in latest else due,
                            timezone=scope.default_timezone,
                        ),
                    )
            if prompt.question is not None:
                answer = (
                    "Farzandingiz odatda soat nechada uxlaydi?"
                    if uzbek
                    else prompt.question.question
                )
                question_id = prompt.question.question_id
            elif prompt.notice is not None:
                observed = prompt.notice.assessment.signal_first_observed_at
                date = observed.isoformat() if observed else "unknown"
                battery_notice = any(
                    finding.category == FindingCategory.BATTERY_ANOMALY
                    for finding in prompt.notice.assessment.significant_findings
                )
                answer = (
                    (
                        (
                            f"{date} o‘lchovida quvvat 12%. Imkon bo‘lsa, telefonni quvvatlang. "
                            "Hozirgi ulanish holati noma’lum."
                        )
                        if uzbek
                        else (
                            f"В измерении от {date} заряд 12%. При возможности зарядите телефон. "
                            "Текущее подключение неизвестно."
                        )
                    )
                    if battery_notice
                    else (
                        f"Sinov bildirishnomasida tahdid bor ({date}). "
                        "Bolangiz xavfsizligini xotirjam tekshiring."
                        if uzbek
                        else f"В тестовом уведомлении от {date} есть угроза. "
                        "Спокойно проверьте, в безопасности ли ребёнок."
                    )
                )
                notice_id = prompt.notice.notice_id
                if prompt.notice.source_observations:
                    answer = (
                        "Qurilma yozuvlari bor. Ilova hisoblagichlarining davri va vaqt zonasi "
                        "noma’lum; bu kunlik ekran vaqti emas. Telefon quvvatini tekshiring."
                        if uzbek
                        else "Есть снимки данных устройства. Период счётчиков приложений "
                        "и часовой пояс неизвестны; это не экранное время за день. "
                        "Проверьте заряд телефона."
                    )
                    for fact in prompt.notice.source_observations:
                        if isinstance(fact, ChildLocationFacts):
                            stamp = fact.observed_at.isoformat() if fact.observed_at else "unknown"
                            if len(prompt.notice.source_observations) == 1:
                                answer = ""
                            answer += (
                                f" Oxirgi joylashuv yozuvi {stamp}; hozirgi joylashuv noma’lum."
                                if uzbek
                                else f" Последняя запись местоположения от {stamp}; "
                                "текущее местоположение неизвестно."
                            )
                if prompt.notice.location_comparison is not None:
                    answer = location_comparison_text(
                        prompt.notice.location_comparison, uzbek=uzbek
                    )
                if prompt.notice.counter_comparison is not None:
                    answer = comparison_text(prompt.notice.counter_comparison, uzbek=uzbek)
                if prompt.notice.query_calendar_days and prompt.notice.counter_comparison is None:
                    answer = (
                        ", ".join(d.isoformat() for d in prompt.notice.query_calendar_days)
                        + ": "
                        + answer
                    )
            else:
                guidance = json.loads(prompt.messages[0][1]).get("specialist_guidance", {})
                sources = guidance.get("source_observations", [])
                if guidance.get("day_usage_query"):
                    day = guidance["day_usage_query"]
                    answer = (
                        (
                            f"{day} so‘rovi bo‘yicha ilova hisoblagichlarining bir qismi bor. "
                            "Davr va vaqt zonasi noma’lum; bu kunlik ekran vaqti emas."
                            if uzbek or "ilova" in prompt.messages[-1][1].casefold()
                            else f"По запросу за {day} есть часть счётчиков приложений. "
                            "Период и часовой пояс неизвестны; это не экранное время за день."
                        )
                        if guidance.get("day_usage_child_returned")
                        else f"{day}: ребёнка нет в полученной странице; использование неизвестно."
                    )
                elif sources and "entries" in sources[0]:
                    answer = (
                        "Ilovalar hisoblagichlarining bir qismi bor; davr va vaqt zonasi "
                        "noma’lum. Bu kunlik ekran vaqti emas."
                        if uzbek or "ilova" in prompt.messages[-1][1].casefold()
                        else "Есть часть счётчиков приложений; период и часовой пояс неизвестны. "
                        "Это не экранное время за день."
                    )
                elif sources and "is_moving" in sources[0]:
                    stamp = sources[0]["observed_at"] or "unknown"
                    answer = (
                        f"Oxirgi joylashuv yozuvi {stamp}. Hozirgi joylashuv noma’lum. "
                        "Ilovadagi xaritani tekshiring."
                        if uzbek
                        else f"Последняя запись местоположения от {stamp}. "
                        "Текущее местоположение неизвестно. Проверьте карту в приложении."
                    )
                elif sources and sources[0]["status"] == "available":
                    stamp = sources[0]["observed_at"] or "unknown"
                    # An unknown presentation hint remains model-directed. This
                    # narrow fictional example is not a production detector.
                    last = prompt.messages[-1][1].casefold()
                    source_uzbek = uzbek or (
                        prompt.response_language is None and "farzand" in last and "quvvat" in last
                    )
                    answer = (
                        f"{stamp} yozuvida quvvat {sources[0]['percent']}%. Ulanish noma’lum."
                        if source_uzbek
                        else (
                            f"По записи от {stamp} заряд {sources[0]['percent']}%. "
                            "Подключение неизвестно."
                        )
                    )
                else:
                    answer = (
                        "Tushundim. Bu bepul simulyatsiya javobi."
                        if uzbek
                        else "Понял. Это ответ бесплатной симуляции; "
                        "для свободного диалога запустите режим реальной модели."
                    )
        return ChatModelReceipt(
            usage=ChatTokens(input_tokens=100, output_tokens=50),
            model="lab-simulated-not-billed",
            answer=answer,
            completed=True,
            question_id=question_id,
            notice_id=notice_id,
        )

    async def close(self) -> None:
        pass


class LabScenario(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str
    title: str
    path: str
    body: dict[str, object]
    local: bool = False


class LabBootstrap(BaseModel):
    mode: Literal["simulation", "real-model"]
    parent_id: str
    child_id: int
    scenarios: list[LabScenario]
    scheduled_collection: bool = False
    action_cards_enabled: bool = False
    trial_action_cards_enabled: bool = False
    trial_end_enabled: bool = False
    seeded_history: Literal["fictional_trial_grant"] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


class LabState(BaseModel):
    mode: Literal["simulation", "real-model"]
    history: ParentTouchHistory
    assessments: SafetyAssessmentPage
    safety_budget: SafetyBudget
    conversions: ConversionProposalPage
    source_changes: list[FamilySourceChange]
    source_dispatches: list[SourceSafetyReceipt]
    collection_windows: list[FamilyCollectionWindow] = []
    source_reviews: list[SourceReviewWork] = []
    action_cards: list[ChatActionCard] = []


@dataclass(frozen=True)
class LabOptions:
    directory: Path
    real_model: bool = False
    clock: Clock = field(default_factory=SystemManaAIClock)
    worker_enabled: bool = True
    native_sources: bool = False
    native_observations: bool = False
    scheduled_collection: bool = False
    source_reviews: bool = False
    reminders: bool = False
    retention: bool = False
    upsell: bool = False
    tariff_context: bool = False
    expiry: bool = False
    collection_tariffs: bool = False
    day_usage: bool = False
    dated_reviews: bool = False
    day_collection: bool = False
    shared_conversion_profile: bool = False
    manager: bool = False
    trial_periods: bool = False
    location: bool = False
    location_comparisons: bool = False
    location_time_labels: bool = False
    saved_observations: bool = False
    saved_observation_limits: SavedObservationLimits = field(default_factory=SavedObservationLimits)
    tariff_followups: bool = False
    action_cards: bool = False
    trial_action_cards: bool = False
    trial_end: bool = False
    parallel_worker: bool = False
    safety_remainder: bool = False
    parent_support_questions: bool = False
    clarifications: bool = False
    usage_comparisons: bool = False
    upsell_currency: bool = False
    inline_upsell: bool = False
    tariff_handoff: bool = False
    compact_inputs: bool = False
    compact_publication: bool = False
    compact_manager: bool = False
    expiry_fixture_days: Literal[2, 30] = 2


class ChatLab:
    def __init__(self, options: LabOptions) -> None:
        if options.location_time_labels and not options.location_comparisons:
            raise ValueError("Location time labels need the captured comparison lab")
        if options.saved_observations and not (options.compact_manager and options.location):
            raise ValueError("Saved observation lab needs compact manager and location cache")
        if options.tariff_followups and not options.compact_manager:
            raise ValueError("Tariff follow-ups need the compact tariff manager")
        if options.location_comparisons and not (options.location and options.compact_publication):
            raise ValueError("Location comparison lab requires captured location publication")
        if options.compact_manager and not options.compact_publication:
            raise ValueError("Compact manager lab requires captured publication")
        if options.compact_publication and not options.compact_inputs:
            raise ValueError("Compact publication lab requires captured compact inputs")
        if options.compact_inputs and not options.tariff_handoff:
            raise ValueError("Compact input lab requires the current typed tariff profile")
        if options.tariff_handoff and not options.inline_upsell:
            raise ValueError("Typed tariff handoff requires inline results")
        if options.inline_upsell and not options.upsell_currency:
            raise ValueError("Inline results require the governed currency lab")
        if options.upsell_currency and (
            not options.manager or not options.upsell or options.action_cards
        ):
            raise ValueError("Currency lab requires the governed tariff manager")
        if options.usage_comparisons and (
            not options.dated_reviews
            or not options.day_usage
            or not options.manager
            or options.action_cards
        ):
            raise ValueError("Usage comparison lab requires the governed dated-review profile")
        if options.clarifications and (not options.manager or options.action_cards):
            raise ValueError("Clarification lab requires the current manager profile")
        if options.parent_support_questions and (
            not options.manager or not options.retention or options.action_cards
        ):
            raise ValueError("Parent support lab requires the complete Retention profile")
        if options.safety_remainder and (
            not options.manager or not options.source_reviews or options.action_cards
        ):
            raise ValueError("Safety remainder lab requires its complete family profile")
        if options.trial_end and (not options.trial_periods or options.action_cards):
            raise ValueError("Trial-end lab requires its own confirmed-period profile")
        if options.trial_action_cards and (not options.action_cards or options.trial_periods):
            raise ValueError("Trial-action lab requires buttons without a pre-granted fixture")
        if options.action_cards and (not options.manager or options.real_model):
            raise ValueError("Action-card lab requires the fictional manager profile")
        if type(options.expiry_fixture_days) is not int or options.expiry_fixture_days not in {
            2,
            30,
        }:
            raise ValueError("Unsupported fictional expiry fixture")
        if options.location and not (options.day_usage and options.manager):
            raise ValueError("Location lab requires the governed native manager profile")
        if options.trial_periods and not options.manager:
            raise ValueError("Trial-period lab requires the current manager profile")
        if options.manager and not options.expiry:
            raise ValueError("Manager lab requires the current complete family profile")
        if options.shared_conversion_profile and (not options.expiry or options.real_model):
            raise ValueError("Shared conversion lab requires the existing profile observer")
        if options.dated_reviews and not options.day_usage:
            raise ValueError("Dated reviews require the captured day source")
        if options.day_collection and not (options.dated_reviews and options.scheduled_collection):
            raise ValueError("Dated collection requires its source reviews and fictional windows")
        if options.day_usage and not options.expiry:
            raise ValueError("Dated usage lab requires the full current family profile")
        if options.collection_tariffs and not (options.expiry and options.scheduled_collection):
            raise ValueError("Inventory tariff lab requires its full fictional collection profile")
        if options.expiry and (not options.upsell or not options.tariff_context):
            raise ValueError("Expiry lab requires its full profile and fictional tariff")
        if options.native_observations and not options.native_sources:
            raise ValueError("Observation lab requires the native workflow")
        if options.source_reviews and (
            not options.native_observations
            or options.scheduled_collection
            and not (options.collection_tariffs or options.day_collection)
        ):
            raise ValueError("Source-review lab requires native observations and its own directory")
        if options.scheduled_collection and (
            options.real_model
            or not options.native_observations
            or not isinstance(options.clock, LabCollectionClock)
        ):
            raise ValueError("Collection lab requires fictional time, sources and model")
        if isinstance(options.clock, LabUsageComparisonClock) and (
            options.real_model or not (options.usage_comparisons or options.location_comparisons)
        ):
            raise ValueError("Fictional comparison time cannot be used for paid models")
        self.options: LabOptions = options
        if options.upsell and not options.retention:
            raise ValueError("Upsell lab requires the complete conversation runtime")
        if options.retention and not options.reminders:
            raise ValueError("Retention lab requires the complete conversation profile")
        if options.reminders and not options.source_reviews:
            raise ValueError("The assistant lab requires the complete source-review profile")
        self.mode: Literal["simulation", "real-model"] = (
            "real-model" if options.real_model else "simulation"
        )
        self.touch: ParentTouchService
        self.safety: ChildSafetyService
        self.store: SqliteCommercialConversationStore
        self._models: list[ClosableModel] = []
        self._worker: FamilyAgentWorker | None = None
        self.source_store: SqliteSourceSafetyStore
        self.sources: FamilySourceService
        self.source_safety: SourceSafetyService
        self.battery: LabBatterySource
        self.collection: LabCollection | None = None
        self.action_cards: ChatActionService | None = None
        self.trial_grants: TrialButtonGrantService | None = None
        self.trial_gateway: LabTrialGrantGateway | None = None

    def _directory(self) -> Path:
        directory = self.options.directory
        marker = directory / "lab-state.json"
        expected: dict[str, object] = {
            "kind": "mana-fictional-chat-lab",
            "mode": self.mode,
            "parent_id": LAB_PARENT,
        }
        if self.options.native_sources:
            expected["native_sources"] = True
        if self.options.native_observations:
            expected["native_observations"] = True
        if self.options.scheduled_collection:
            expected["scheduled_collection"] = True
        if self.options.source_reviews:
            expected["source_reviews"] = True
        if self.options.reminders:
            expected["reminders"] = True
        if self.options.retention:
            expected["retention"] = True
        if self.options.upsell:
            expected["upsell"] = True
        if self.options.tariff_context:
            expected["tariff_context"] = True
        if self.options.expiry:
            expected["expiry"] = True
        if self.options.expiry_fixture_days != 2:
            expected["expiry_fixture_days"] = self.options.expiry_fixture_days
        if self.options.day_usage:
            expected["day_usage"] = True
        if self.options.dated_reviews:
            expected["dated_reviews"] = True
        if self.options.day_collection:
            expected["day_collection"] = True
        if self.options.collection_tariffs:
            expected["collection_tariffs"] = True
        if self.options.shared_conversion_profile:
            expected["shared_conversion_profile"] = True
        if self.options.manager:
            expected["manager"] = True
        if self.options.trial_periods:
            expected["trial_periods"] = True
        if self.options.location:
            expected["location"] = True
        if self.options.location_comparisons:
            expected["location_comparisons"] = True
        if self.options.location_time_labels:
            expected["location_time_labels"] = True
        if self.options.saved_observations:
            expected["saved_observations"] = True
            expected["saved_observation_limits"] = (
                self.options.saved_observation_limits.model_dump()
            )
        if self.options.tariff_followups:
            expected["tariff_followups"] = True
        if self.options.action_cards:
            expected["action_cards"] = True
        if self.options.trial_action_cards:
            expected["trial_action_cards"] = True
        if self.options.trial_end:
            expected["trial_end"] = True
        if self.options.parallel_worker:
            expected["parallel_worker"] = True
        if self.options.clarifications:
            expected["clarifications"] = True
        if self.options.usage_comparisons:
            expected["usage_comparisons"] = True
        if self.options.upsell_currency:
            expected["upsell_currency"] = True
            if isinstance(self.options.clock, LabUsageComparisonClock):
                expected["clock"] = "fictional_usage_comparison_v1"
        if self.options.inline_upsell:
            expected["inline_upsell"] = True
        if self.options.tariff_handoff:
            expected["tariff_handoff"] = True
        if self.options.compact_manager:
            expected["compact_manager"] = True
        if self.options.compact_publication:
            expected["compact_publication"] = True
        if self.options.compact_inputs:
            expected["compact_inputs"] = True
        if isinstance(self.options.clock, LabLocationComparisonClock):
            expected["clock"] = self.options.clock.kind
        if self.options.parent_support_questions:
            expected["parent_support_questions"] = True
        if self.options.safety_remainder:
            expected["safety_remainder"] = True
        if (
            directory.is_symlink()
            or marker.is_symlink()
            or (directory / "family.sqlite3").is_symlink()
        ):
            raise ValueError("Lab storage cannot use symlinks")
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if marker.exists():
            if json.loads(marker.read_text()) != expected:
                raise ValueError("The directory belongs to a different lab mode")
        else:
            if any(directory.iterdir()):
                raise ValueError("Refusing an unmarked non-empty storage directory")
            descriptor = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w") as stream:
                json.dump(expected, stream)
                stream.flush()
                os.fsync(stream.fileno())
        return directory

    async def start(self) -> None:
        directory = self._directory()
        if isinstance(self.options.clock, LabUsageComparisonClock):
            self.options.clock.restore(directory)
        if self.options.trial_end and isinstance(self.options.clock, LabTrialEndClock):
            self.options.clock.restore(directory)
        tariff_until = None
        if self.options.expiry:
            fixture = directory / "expiry-tariff.json"
            if fixture.is_symlink():
                raise ValueError("Expiry fixture cannot be a symlink")
            if not fixture.exists():
                with os.fdopen(
                    os.open(fixture, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w"
                ) as stream:
                    stream.write(
                        json.dumps(
                            {
                                "valid_until": (
                                    self.options.clock.now()
                                    + timedelta(days=self.options.expiry_fixture_days)
                                ).isoformat()
                            }
                        )
                    )
                    stream.flush()
                    os.fsync(stream.fileno())
            if fixture.stat().st_size > 200:
                raise ValueError("Invalid expiry fixture")
            tariff_until = datetime.fromisoformat(json.loads(fixture.read_text())["valid_until"])
            if tariff_until.utcoffset() is None:
                raise ValueError("Expiry fixture requires an explicit timezone")
        collection_store = None
        if self.options.scheduled_collection:
            assert isinstance(self.options.clock, LabCollectionClock)
            collection_store = await lab_collection_store(
                directory,
                self.options.clock,
                tariffs=self.options.collection_tariffs,
                dated=self.options.day_collection,
                location=self.options.location,
            )
        now = self.options.clock.now()
        limits = ChildSafetyLimits(
            server_daily_tokens=2000,
            parent_daily_tokens=2000,
            job_tokens=2000 if self.options.native_sources else 1000,
        )
        offer: ConversionOffer = PaidConversionOffer(
            offer_id="lab-only",
            billing_offer_id="lab-only-no-payment",
            approval_reference="fictional-lab-only-not-commercial-approval",
            valid_from=datetime(2026, 1, 1, tzinfo=UTC),
            valid_until=datetime(2030, 1, 1, tzinfo=UTC),
            currency="UZS",
            list_price_minor=6000000,
            price_minor=6000000,
            duration_days=30,
            auto_renew=False,
            checkout_path="/subscriptions/lab-only",
        )
        if self.options.trial_periods or self.options.trial_action_cards:
            offer = TrialConversionOffer(
                offer_id="lab-only",
                approval_reference="fictional-one-day-fixture-never-a-customer-offer",
                valid_from=datetime(2026, 1, 1, tzinfo=UTC),
                valid_until=datetime(2030, 1, 1, tzinfo=UTC),
                grant_days=1,
            )
        speaker: ClosableModel
        specialist: ClosableModel
        if self.options.real_model:
            settings = get_settings()
            speaker = OpenAIParentChatModel(
                settings.model_copy(
                    update={
                        "openai_model": settings.mana_parent_touch_model or settings.openai_model
                    }
                )
            )
            specialist = (
                OpenAIChildSourceModel if self.options.native_sources else OpenAIChildSafetyModel
            )(
                settings.model_copy(
                    update={
                        "openai_model": settings.mana_child_safety_model or settings.openai_model
                    }
                )
            )
        else:
            speaker, specialist = SimulatedModel("speaker"), SimulatedModel("safety")
            if self.options.native_sources:
                specialist = LabNativeSourceModel(specialist)
        self._models = [speaker, specialist]
        if self.options.native_sources:
            assert isinstance(specialist, OpenAIChildSourceModel)
            profile = specialist.source_profile
            native_store_class = (
                SqliteTariffFollowupStore
                if self.options.tariff_followups
                else SqliteSavedObservationSafetyStore
                if self.options.saved_observations
                else SqliteLocationComparisonSafetyStore
                if self.options.location_comparisons
                else SqliteCompactParentPublicationStore
                if self.options.compact_publication
                else SqliteCompactFamilyInputStore
                if self.options.compact_inputs
                else SqliteTariffHandoffStore
                if self.options.tariff_handoff
                else SqliteInlineUpsellStore
                if self.options.inline_upsell
                else SqliteUpsellCurrencyStore
                if self.options.upsell_currency
                else SqliteUsageComparisonSafetyStore
                if self.options.usage_comparisons
                else SqliteParentClarificationStore
                if self.options.clarifications
                else SqliteParentSupportQuestionStore
                if self.options.parent_support_questions
                else SqliteSafetyRemainderStore
                if self.options.safety_remainder
                else SqliteTrialEndStore
                if self.options.trial_end
                else SqliteLabTrialActionStore
                if self.options.trial_action_cards
                else SqliteLabChatActionStore
                if self.options.action_cards
                else SqliteLocationSafetyStore
                if self.options.location
                else SqliteTrialPeriodStore
                if self.options.trial_periods
                else SqliteParentTouchManagerStore
                if self.options.manager
                else SqliteSharedConversionProfileStore
                if self.options.shared_conversion_profile
                else SqliteDatedReviewSafetyStore
                if self.options.dated_reviews
                else SqliteDatedSourceSafetyStore
                if self.options.day_usage
                else SqliteRetentionExpiryStore
                if self.options.expiry
                else SqliteClientUpsellStore
                if self.options.upsell
                else SqliteClientRetentionStore
                if self.options.retention
                else SqliteParentReminderStore
                if self.options.reminders
                else (
                    SqliteSourceReviewSafetyStore
                    if self.options.source_reviews
                    else (
                        SqliteObservationToolSafetyStore
                        if self.options.native_observations
                        else SqliteSourceToolSafetyStore
                    )
                )
            )
            reminder_options: dict[str, Any] = (
                {"reminder_policy": ReminderPolicy()} if self.options.reminders else {}
            )
            if self.options.retention:
                reminder_options["retention_policy"] = ClientRetentionPolicy()
            if self.options.upsell:
                reminder_options.update(
                    upsell_policy=ClientUpsellPolicy(), catalog_binding="fictional-mana-catalog-v1"
                )
            if self.options.expiry:
                reminder_options.update(
                    expiry_policy=RetentionExpiryPolicy(),
                    profile_binding="fictional-mana-profile-v1",
                )
            if self.options.day_usage:
                reminder_options["day_tools_enabled"] = True
            if self.options.dated_reviews:
                reminder_options["dated_reviews_enabled"] = True
            if self.options.shared_conversion_profile:
                reminder_options["shared_profile_enabled"] = True
            if self.options.trial_periods:
                reminder_options["trial_periods_enabled"] = True
            if self.options.trial_end:
                reminder_options["trial_end_enabled"] = True
            if self.options.clarifications:
                reminder_options["clarifications_enabled"] = True
            if self.options.usage_comparisons:
                reminder_options["comparisons_enabled"] = True
            if self.options.upsell_currency:
                reminder_options["currency_enabled"] = True
            if self.options.inline_upsell:
                reminder_options["inline_enabled"] = True
            if self.options.tariff_handoff:
                reminder_options["tariff_handoff_enabled"] = True
            if self.options.compact_publication:
                reminder_options["compact_publication_enabled"] = True
                reminder_options["compact_manager_enabled"] = self.options.compact_manager
            if self.options.compact_inputs:
                reminder_options["compact_inputs_enabled"] = True
            if self.options.parent_support_questions:
                reminder_options["parent_questions_enabled"] = True
            if self.options.safety_remainder:
                reminder_options["remainder_enabled"] = True
            if self.options.trial_action_cards:
                reminder_options.update(trial_cards_enabled=True, trial_periods_enabled=True)
            if self.options.location:
                reminder_options["location_enabled"] = True
            if self.options.location_comparisons:
                reminder_options["location_comparisons_enabled"] = True
            if self.options.location_time_labels:
                reminder_options["location_time_labels_enabled"] = True
            if self.options.saved_observations:
                reminder_options["saved_observations_enabled"] = True
                reminder_options["saved_observation_limits"] = self.options.saved_observation_limits
            if self.options.tariff_followups:
                reminder_options["tariff_followups_enabled"] = True
            if self.options.manager:
                manager_model = (
                    (settings.mana_parent_touch_model or settings.openai_model)
                    if self.options.real_model
                    else "lab-simulated-not-billed"
                )
                reminder_options.update(
                    manager_enabled=True,
                    manager_model=manager_model,
                    manager_binding=manager_binding(
                        manager_model,
                        settings.openai_reasoning_effort,
                        settings.openai_verbosity,
                        512,
                        settings.openai_timeout_seconds,
                    )
                    if self.options.real_model
                    else "fictional-manager-v1",
                )
            self.store = native_store_class(
                directory / "family.sqlite3",
                native_model=profile.model_name,
                native_reasoning_effort=profile.reasoning_effort,
                native_verbosity=profile.verbosity,
                native_wall_timeout_seconds=profile.wall_timeout_seconds,
                native_max_output_tokens=512,
                conversion_policy=ConversionPolicy(),
                conversion_offers=(offer,),
                limits=limits,
                daily_limit=2000,
                timezone="Asia/Samarkand",
                proactive_enabled=True,
                conversation_enabled=True,
                account_read_limits=ConversionAccountReadLimits(),
                **reminder_options,
            )
        else:
            self.store = SqliteCommercialConversationStore(
                directory / "family.sqlite3",
                conversion_policy=ConversionPolicy(),
                conversion_offers=(offer,),
                limits=limits,
                daily_limit=2000,
                timezone="Asia/Samarkand",
                push_enabled=False,
            )
        await self.store.initialize()
        if self.options.action_cards:
            assert isinstance(self.store, SqliteLabChatActionStore)
            self.action_cards = ChatActionService(
                self.store, SimulatedChatActionExecutor(), self.options.clock
            )
        if self.options.trial_action_cards:
            assert isinstance(self.store, SqliteLabTrialActionStore)
            self.trial_gateway = LabTrialGrantGateway(self.options.clock.now)
            self.trial_grants = TrialButtonGrantService(
                self.store, self.trial_gateway, clock=self.options.clock.now
            )
            self.action_cards = ChatActionService(
                self.store,
                LabTrialActionExecutor(self.store, self.trial_grants),
                self.options.clock,
            )
        if self.options.shared_conversion_profile and isinstance(
            self.options.clock, LabCollectionClock
        ):
            with self.store._connect() as db:
                latest = db.execute(
                    "SELECT MAX(collected_at) FROM conversion_profile_heads"
                ).fetchone()[0]
            if latest:
                self.options.clock.restore(datetime.fromisoformat(latest))
                now = self.options.clock.now()
        profiles: ParentChildrenSource = LabProfiles(
            self.options.clock,
            tariff_context=self.options.tariff_context,
            tariff_until=tariff_until,
        )
        if self.options.trial_periods or self.options.trial_action_cards:
            assert isinstance(self.store, SqliteTrialPeriodStore)
            profiles = LabTrialProfiles(profiles, self.store)
        if isinstance(self.store, SqliteRetentionExpiryStore):
            profiles = RetentionProfileSource(profiles, self.store, clock=self.options.clock.now)
        self._profiles = profiles
        policy = SourceSafetyPolicy(timezone="Asia/Samarkand")
        source_class = (
            SqliteMultiFamilySourceStore
            if self.options.native_observations
            else SqliteSourceSafetyStore
        )
        self.source_store = (
            (
                SqliteLocationTimeCache
                if self.options.location_time_labels
                else SqliteLocationComparisonCache
                if self.options.location_comparisons
                else SqliteUsageComparisonCache
                if self.options.usage_comparisons
                else SqliteLocationSourceCache
                if self.options.location
                else SqliteDayReviewCache
                if self.options.dated_reviews
                else SqliteDayUsageCache
                if self.options.day_usage
                else SqliteSourceReviewCache
            )(
                directory / "sources.sqlite3",
                binding="fake-lab-mana-battery-v1",
                limits=FamilySourceLimits(),
                policy=policy,
                enabled=True,
                review_policy=SourceReviewPolicy(coalesce_seconds=0)
                if self.options.day_collection
                else SourceReviewPolicy(),
                **({"comparisons_enabled": True} if self.options.usage_comparisons else {}),
                **(
                    {"location_comparisons_enabled": True}
                    if self.options.location_comparisons
                    else {}
                ),
                **(
                    {"location_time_labels_enabled": True}
                    if self.options.location_time_labels
                    else {}
                ),
                **({"location_enabled": True} if self.options.location else {}),
                **({"dated_reviews_enabled": True} if self.options.dated_reviews else {}),
            )
            if self.options.source_reviews
            else source_class(
                directory / "sources.sqlite3",
                binding="fake-lab-mana-battery-v1",
                limits=FamilySourceLimits(),
                policy=policy,
                enabled=True,
            )
        )
        await self.source_store.initialize()
        self.battery = LabBatterySource(directory, self.options.clock)
        self.app_usage = LabAppUsageSource(self.options.clock)
        self.location = (
            LabComparisonLocationSource(self.options.clock.now)
            if isinstance(self.options.clock, LabLocationComparisonClock)
            else LabLocationSource(self.options.clock.now)
        )
        self.sources = FamilySourceService(
            self.source_store,
            profiles,
            self.battery,
            clock=self.options.clock.now,
            app_usage=self.app_usage if self.options.native_observations else None,
            location=self.location if self.options.location else None,
        )
        self.day_provider = LabDayUsageSource(
            profiles, self.options.clock, comparison_story=self.options.usage_comparisons
        )
        self.day_usage = (
            FamilyDayUsageService(
                self.source_store,
                self.day_provider,
                self.day_provider,
                clock=self.options.clock.now,
            )
            if isinstance(self.source_store, SqliteDayUsageCache)
            else None
        )
        native = None
        if self.options.native_sources:
            assert isinstance(self.store, SqliteSourceToolSafetyStore)
            assert isinstance(specialist, OpenAIChildSourceModel)
            native = SourceToolWorkflow(
                store=self.store,
                children=profiles,
                model=specialist,
                prompts=SourceToolPromptBuilder(),
                sources=self.sources,
                day_usage=self.day_usage,
                saved_observations=saved_observation_service(
                    path=directory / "sources.sqlite3",
                    binding="fake-lab-mana-battery-v1",
                    source_limits=FamilySourceLimits(),
                    children=profiles,
                    clock=self.options.clock.now,
                    maximum_age_seconds=policy.maximum_age_seconds,
                    app_usage=self.options.native_observations,
                    location=self.options.location,
                    day_usage=self.options.day_usage,
                )
                if self.options.saved_observations
                else None,
                clock=self.options.clock,
                limits=limits,
                max_output_tokens=512,
            )
        self.safety = ChildSafetyService(
            store=self.store,
            children=profiles,
            model=specialist,
            prompts=ChildSafetyPromptBuilder(),
            clock=self.options.clock,
            limits=limits,
            max_output_tokens=512,
            native_sources=native,
        )
        proactive = ProactiveParentService(self.store, clock=self.options.clock.now)
        self.catalog = LabCatalog(self.options.clock)
        self.touch = ParentTouchService(
            store=self.store,
            children=profiles,
            model=speaker,
            manager=self.store if isinstance(self.store, SqliteParentTouchManagerStore) else None,
            parent_publications=self.store
            if isinstance(self.store, SqliteCompactParentPublicationStore)
            else None,
            tariff_followups=self.store
            if isinstance(self.store, SqliteTariffFollowupStore)
            else None,
            input_presentations=self.store
            if isinstance(self.store, SqliteCompactFamilyInputStore)
            else None,
            clock=self.options.clock.now,
            max_output_tokens=512,
            history_turn_limit=2,
            safety=self.safety,
            reviewed=self.store,
            conversion=ConversionService(
                self.store, clock=self.options.clock.now, grants=self.trial_grants
            ),
            proactive=proactive,
            sources=self.sources,
            upsell=ClientUpsellService(
                self.store, self.catalog, profiles, clock=self.options.clock.now
            )
            if isinstance(self.store, SqliteClientUpsellStore)
            else None,
            expiry=RetentionExpiryService(self.store, clock=self.options.clock.now)
            if isinstance(self.store, SqliteRetentionExpiryStore)
            else None,
            retention=ClientRetentionService(self.store, clock=self.options.clock.now)
            if isinstance(self.store, SqliteClientRetentionStore)
            else None,
            reminders=ParentReminderService(self.store, profiles, clock=self.options.clock.now)
            if isinstance(self.store, SqliteParentReminderStore)
            else None,
        )
        self.source_safety = SourceSafetyService(
            self.source_store, self.safety, profiles, policy=policy, clock=self.options.clock.now
        )
        if collection_store is not None:
            assert isinstance(self.options.clock, LabCollectionClock)
            assert isinstance(self.source_store, SqliteMultiFamilySourceStore)
            self.collection = LabCollection(
                collection_store,
                self.options.clock,
                self.sources,
                self.source_store,
                parent_id=LAB_PARENT,
                child_id=LAB_CHILD,
                tariff_receiver=self.store
                if isinstance(self.store, SqliteRetentionExpiryStore)
                else None,
                tariff_deadline=tariff_until if self.options.collection_tariffs else None,
                day_usage=self.day_usage if self.options.day_collection else None,
            )
            self.touch.collection = self.collection.service
        if await self.store.contact_context(LAB_PARENT, now) is None:
            await proactive.register(
                ParentContactContext(
                    parent_id=LAB_PARENT,
                    event_id=uuid4(),
                    revision=int(now.timestamp() * 1000000),
                    observed_at=now,
                    valid_until=now + timedelta(days=1),
                    language="en"
                    if self.options.trial_periods and self.options.real_model
                    else "ru",
                    timezone="America/New_York"
                    if self.options.trial_periods and self.options.real_model
                    else "Asia/Samarkand",
                    safety_chat_consent=True,
                    safety_push_consent=False,
                    marketing_push_consent=False,
                    retention_chat_consent=self.options.expiry,
                )
            )
        if self.options.trial_periods:
            assert isinstance(self.store, SqliteTrialPeriodStore)
            await seed_trial_history(self.store, self.options.clock, directory)
            await profiles.read(LAB_PARENT)
        self._worker = FamilyAgentWorker(
            self.safety,
            self.touch,
            clock=self.options.clock.now,
            interval=0.25,
            parallel_enabled=self.options.parallel_worker,
            source_safety=self.source_safety,
            source_reviews=SourceReviewService(
                self.source_store,
                self.store,
                profiles,
                clock=self.options.clock.now,
                available=lambda: self.safety.worker_available,
            )
            if isinstance(self.source_store, SqliteSourceReviewCache)
            and isinstance(self.store, SqliteSourceReviewSafetyStore)
            else None,
        )
        if self.options.worker_enabled:
            self._worker.start()

    async def close(self) -> None:
        if self._worker is not None:
            await self._worker.close()
        for model in self._models:
            await model.close()

    async def state(self) -> LabState:
        # Keep this composite debug projection coherent across worker commits.
        # A single observer connection detects changes while async repositories
        # read their own transactions. Observation retries never call providers.
        with closing(sqlite3.connect(self.options.directory / "family.sqlite3")) as observer:
            for _ in range(5):
                version = observer.execute("PRAGMA data_version").fetchone()[0]
                result = await self._state_once()
                if observer.execute("PRAGMA data_version").fetchone()[0] == version:
                    return result
                await asyncio.sleep(0)
        raise ParentChatError("lab_state_busy", 409)

    async def _state_once(self) -> LabState:
        assert self.touch.conversion is not None
        # These are separate SQL observations. Read publication statuses before
        # history so a newly published proposal cannot refer to an older empty
        # history captured before the worker committed its message.
        conversions = await self.touch.conversion.proposals(LAB_PARENT, after=0, limit=100)
        assessments = await self.safety.assessments(LAB_PARENT, after=0, limit=100)
        safety_budget = await self.safety.budget(LAB_PARENT)
        changes = [event for _, event in await self.source_store.changes(LAB_PARENT)]
        dispatches = await self.source_store.dispatch_receipts(LAB_PARENT)
        windows = list(await self.collection.service.windows()) if self.collection else []
        cards: list[ChatActionCard] = []
        if self.action_cards:
            after = 0
            while True:
                page = await self.action_cards.list(LAB_PARENT, after=after, limit=100)
                cards.extend(page.cards)
                if page.next_after is None:
                    break
                after = page.next_after
        return LabState(
            mode=self.mode,
            history=await self.touch.read_touch_history(LAB_PARENT, before=None, limit=100),
            assessments=assessments,
            safety_budget=safety_budget,
            conversions=conversions,
            source_changes=changes,
            source_dispatches=dispatches,
            collection_windows=windows,
            action_cards=cards,
            source_reviews=await self.source_store.reviews(LAB_PARENT)
            if isinstance(self.source_store, SqliteSourceReviewCache)
            else [],
        )

    async def prepare_usage_comparison(self) -> dict[str, object]:
        if (
            not self.options.usage_comparisons
            or self.options.real_model
            or not isinstance(self.options.clock, LabUsageComparisonClock)
            or isinstance(self.options.clock, LabLocationComparisonClock)
        ):
            raise ParentChatError("lab_usage_comparison_disabled", 409)
        assert self.day_usage is not None and self.touch.proactive is not None
        baseline = await self.day_usage.read_for_analysis(
            DayUsageTarget(
                parent_id=LAB_PARENT,
                child_id=LAB_CHILD,
                requested_day=date(2026, 10, 24),
                request_id=uuid5(NAMESPACE_URL, "fictional-usage-comparison-baseline-v1"),
            )
        )
        if baseline.status != "completed":
            raise ParentChatError("lab_usage_comparison_unresolved", 409)
        self.options.clock.next_day()
        now = self.options.clock.now()
        if await self.store.contact_context(LAB_PARENT, now) is None:
            await self.touch.proactive.register(
                ParentContactContext(
                    parent_id=LAB_PARENT,
                    event_id=uuid4(),
                    revision=int(now.timestamp() * 1000000),
                    observed_at=now,
                    valid_until=now + timedelta(days=1),
                    language="ru",
                    timezone="Asia/Samarkand",
                    safety_chat_consent=True,
                    safety_push_consent=False,
                    marketing_push_consent=False,
                    retention_chat_consent=self.options.expiry,
                )
            )
        current = await self.day_usage.read_for_analysis(
            DayUsageTarget(
                parent_id=LAB_PARENT,
                child_id=LAB_CHILD,
                requested_day=date(2026, 10, 25),
                request_id=uuid5(NAMESPACE_URL, "fictional-usage-comparison-current-v1"),
            )
        )
        if current.status != "completed":
            raise ParentChatError("lab_usage_comparison_unresolved", 409)
        self.options.clock.ready()
        return {"status": "completed", "cache_hit": True, "external_requests": 0}

    async def prepare_retention_scenario(self) -> dict[str, str]:
        if not self.options.retention or not isinstance(self.store, SqliteClientRetentionStore):
            raise ParentChatError("lab_retention_disabled", 409)
        if self.options.real_model:
            raise ParentChatError("lab_retention_fixture_requires_simulation", 409)
        now = self.options.clock.now()
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT,
            request_id=uuid5(NAMESPACE_URL, "fictional-retention-lab-v1"),
            message="Как помочь ребёнку не отвлекаться на телефон во время уроков?",
        )
        with self.store._transaction() as db:
            if db.execute(
                "SELECT 1 FROM parent_chat_turns WHERE parent_id=? AND request_id=?",
                (LAB_PARENT, str(request.request_id)),
            ).fetchone():
                return {"status": "already_prepared"}
            if db.execute("SELECT 1 FROM parent_chat_turns").fetchone():
                raise ParentChatError("lab_retention_requires_empty_history", 409)
            self.store._host_reply(
                db,
                request,
                LAB_PARENT,
                request.request_id,
                "Тестовая история: обсудили короткие учебные интервалы и перерывы.",
                now - timedelta(days=15),
            )
        assert self.touch.proactive is not None
        prior = await self.store.contact_context(LAB_PARENT, now)
        assert prior is not None
        await self.touch.proactive.register(
            prior.model_copy(
                update={
                    "event_id": uuid4(),
                    "revision": prior.revision + 1,
                    "observed_at": now,
                    "valid_until": now + timedelta(days=1),
                    "retention_chat_consent": True,
                }
            )
        )
        return {"status": "prepared"}

    async def prepare_expiry_scenario(self) -> dict[str, str]:
        if not self.options.expiry:
            raise ParentChatError("expiry_fixture_disabled", 409)
        await self._profiles.read(LAB_PARENT)
        return {"status": "completed"}

    async def prepare_trial_end_scenario(self) -> dict[str, str]:
        if (
            not self.options.trial_end
            or self.options.real_model
            or not isinstance(self.options.clock, LabTrialEndClock)
        ):
            raise ParentChatError("lab_trial_end_fixture_disabled", 409)
        marker = self.options.directory / "fictional-trial-end.json"
        if marker.exists():
            self.options.clock.restore(self.options.directory)
            return {"status": "completed", "mode": "simulation"}
        with self.store._connect() as db:
            raw = db.execute(
                "SELECT payload FROM parent_contact_contexts WHERE parent_id=?", (LAB_PARENT,)
            ).fetchone()
            assert raw
            contact = ParentContactContext.model_validate_json(raw[0])
        with os.fdopen(os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as stream:
            json.dump({"version": 1, "status": "admitted"}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        self.options.clock.advance_to_end()
        now = self.options.clock.now()
        assert self.touch.proactive
        await self.touch.proactive.register(
            contact.model_copy(
                update={
                    "event_id": uuid4(),
                    "revision": contact.revision + 1,
                    "observed_at": now,
                    "valid_until": now + timedelta(days=1),
                }
            )
        )
        await self._profiles.read(LAB_PARENT)
        with marker.open("w") as stream:
            json.dump({"version": 1, "status": "completed"}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        return {"status": "completed", "mode": "simulation"}

    async def prepare_conversion_profile(self, is_paid: bool | None) -> dict[str, str]:
        if not self.options.shared_conversion_profile:
            raise ParentChatError("lab_shared_conversion_profile_disabled", 409)
        assert isinstance(self.store, SqliteSharedConversionProfileStore)
        if isinstance(self.options.clock, LabCollectionClock) and is_paid is True:
            self.options.clock.advance(15)
        now = self.options.clock.now()
        await self.store.observe_inventory_tariffs(
            (
                RetentionTariffFact(
                    parent_id=LAB_PARENT,
                    collected_at=now,
                    is_paid=is_paid,
                    valid_until=now + timedelta(days=1),
                ),
            ),
            now,
        )
        return {"status": "observed", "mode": "simulation"}

    def bootstrap(self) -> LabBootstrap:
        now = self.options.clock.now()
        needs = AgentQuestionRequest(
            parent_id=LAB_PARENT,
            child_id=LAB_CHILD,
            agent_id="child-safety",
            request_id=uuid4(),
            information_key="sleep.bedtime",
            question="Во сколько ребёнок обычно ложится спать?",
            reason="Fictional lab needs the bedtime to discuss the routine.",
            source_revision="lab-bedtime-v1",
            observed_at=now,
            expires_at=now + timedelta(hours=1),
        )
        account = ConversionSnapshot(
            parent_id=LAB_PARENT,
            event_id=uuid4(),
            revision=int(now.timestamp() * 1000000),
            observed_at=now,
            subscription="free",
            free_started_at=now - timedelta(days=7),
            free_access_ends_at=now + timedelta(days=1),
            agent_trial_given=False,
            marketing_consent=True,
            consent_observed_at=now,
            language="ru",
            timezone="Asia/Samarkand",
            last_active_at=now - timedelta(minutes=15),
            active_days_7d=3,
            sessions_7d=5,
            paywall_views_7d=1,
        )
        return LabBootstrap(
            mode=self.mode,
            parent_id=LAB_PARENT,
            child_id=LAB_CHILD,
            scheduled_collection=self.options.scheduled_collection,
            action_cards_enabled=self.options.action_cards,
            trial_action_cards_enabled=self.options.trial_action_cards,
            trial_end_enabled=self.options.trial_end,
            seeded_history="fictional_trial_grant" if self.options.trial_periods else None,
            scenarios=[
                *(
                    [
                        LabScenario(
                            key="location-comparison",
                            title="Две GPS-записи (симуляция)",
                            path="/lab/location-comparison",
                            body={"parent_id": LAB_PARENT},
                            local=True,
                        )
                    ]
                    if self.options.location_comparisons
                    and isinstance(self.options.clock, LabLocationComparisonClock)
                    else []
                ),
                *(
                    [
                        LabScenario(
                            key="usage-comparison",
                            title="Сопоставить два дня (симуляция)",
                            path="/lab/usage-comparison",
                            body={"parent_id": LAB_PARENT},
                            local=True,
                        )
                    ]
                    if self.options.usage_comparisons
                    and isinstance(self.options.clock, LabUsageComparisonClock)
                    and not isinstance(self.options.clock, LabLocationComparisonClock)
                    else []
                ),
                *(
                    [
                        LabScenario(
                            key="trial-end",
                            title="Бесплатный период завершился (тест)",
                            path="/lab/trial-end",
                            local=True,
                            body={"parent_id": LAB_PARENT},
                        )
                    ]
                    if self.options.trial_end
                    else []
                ),
                *(
                    [
                        LabScenario(
                            key="action-card",
                            title="Действие с кнопками",
                            path="/parent-touch/action-cards",
                            body=ChatActionCreate(
                                parent_id=LAB_PARENT,
                                request_id=uuid4(),
                                action_type="sandbox_demo",
                                title="Подтвердите тестовое действие",
                                text="Проверим подтверждение в чате. Реальные данные не изменятся.",
                                buttons=(
                                    {"id": "confirm", "label": "Подтвердить"},
                                    {"id": "cancel", "label": "Отмена"},
                                ),
                            ).model_dump(mode="json"),
                        )
                    ]
                    if self.options.action_cards
                    else []
                ),
                *(
                    [
                        LabScenario(
                            key="source-location",
                            title="Последнее местоположение (тестовый источник)",
                            path="/lab/child-observation",
                            local=True,
                            body={
                                "parent_id": LAB_PARENT,
                                "child_id": LAB_CHILD,
                                "request_id": str(uuid4()),
                                "source": "firebase.child_location.v1",
                            },
                        )
                    ]
                    if self.options.location
                    else []
                ),
                *(
                    [
                        LabScenario(
                            key="conversion-profile-" + key,
                            title=title,
                            path="/lab/conversion-profile",
                            local=True,
                            body={"parent_id": LAB_PARENT, "is_paid": paid},
                        )
                        for key, title, paid in (
                            ("free", "Профиль: не оплачен (симуляция)", False),
                            ("paid", "Профиль: оплачен (симуляция)", True),
                            ("unknown", "Профиль: статус неизвестен (симуляция)", None),
                        )
                    ]
                    if self.options.shared_conversion_profile
                    else []
                ),
                *(
                    [
                        LabScenario(
                            key="expiry",
                            title="Проверить срок тестового тарифа"
                            if self.options.expiry_fixture_days == 30
                            else "Скоро истекает тариф (вымышленные данные)",
                            path="/lab/expiry-profile",
                            body={"parent_id": LAB_PARENT},
                            local=True,
                        )
                    ]
                    if self.options.expiry
                    else []
                ),
                *(
                    [
                        LabScenario(
                            key="retention",
                            title="Возврат после паузы (вымышленная история)",
                            path="/lab/retention-scenario",
                            body={"parent_id": LAB_PARENT},
                            local=True,
                        )
                    ]
                    if self.options.retention and not self.options.real_model
                    else []
                ),
                *(
                    [
                        LabScenario(
                            key="source-apps",
                            title="Приложения (тестовый источник)",
                            path="/lab/child-observation",
                            local=True,
                            body={
                                "parent_id": LAB_PARENT,
                                "child_id": LAB_CHILD,
                                "request_id": str(uuid4()),
                                "source": "manakids.child_app_usage.v1",
                            },
                        )
                    ]
                    if self.options.native_observations
                    else []
                ),
                *(
                    [
                        LabScenario(
                            key=f"collection-{hour}",
                            title=f"Сбор {hour:02}:00 (симуляция)",
                            path="/lab/collection",
                            local=True,
                            body={"parent_id": LAB_PARENT, "hour": hour},
                        )
                        for hour in (9, 15)
                    ]
                    if self.collection
                    else []
                ),
                LabScenario(
                    key="battery",
                    title="Низкий заряд (тестовый источник)",
                    path="/lab/child-battery",
                    local=True,
                    body={
                        "parent_id": LAB_PARENT,
                        "child_id": LAB_CHILD,
                        "request_id": str(uuid4()),
                    },
                ),
                LabScenario(
                    key="question",
                    title="Вопрос от Child-Safety",
                    path="/parent-touch/requests",
                    body=needs.model_dump(mode="json"),
                ),
                LabScenario(
                    key="safety",
                    title="Тестовый тревожный сигнал",
                    path="/child-safety/safety-monitor",
                    body={
                        "parent_id": LAB_PARENT,
                        "child_id": LAB_CHILD,
                        "request_id": str(uuid4()),
                        "source_revision": "lab-threat-v1",
                        "analysis": {
                            "request_id": "lab-threat-v1",
                            "occurred_at": now.isoformat(),
                            "locale": "ru",
                            "data_minimized": True,
                            "subject": {
                                "subject_id": str(LAB_CHILD),
                                "age_band": "age_7_12",
                                "timezone": "Asia/Samarkand",
                            },
                            "input": {
                                "notifications": [
                                    {
                                        "evidence_id": "lab-threat",
                                        "observed_at": now.isoformat(),
                                        "application": "Fictional lab",
                                        "excerpt": "Тестовый текст: я тебе угрожаю.",
                                    }
                                ]
                            },
                        },
                    },
                ),
                LabScenario(
                    key="conversion",
                    title="7 дней бесплатного доступа",
                    path="/conversion-agent/events",
                    body=account.model_dump(mode="json"),
                ),
                LabScenario(
                    key="paid",
                    title="Аккаунт стал платным",
                    path="/conversion-agent/events",
                    body=account.model_copy(
                        update={
                            "event_id": uuid4(),
                            "revision": account.revision + 1,
                            "subscription": "paid",
                        }
                    ).model_dump(mode="json"),
                ),
            ],
        )
