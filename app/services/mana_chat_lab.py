"""Isolated fictional-family lab; never imports a live data or write adapter."""

import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from app.core.config import get_settings
from app.mana_ai.application.chat_ports import (
    ChatModelReceipt,
    ChatPrompt,
    ParentChatError,
    ParentChatModel,
)
from app.mana_ai.application.child_safety import ChildSafetyService
from app.mana_ai.application.conversion import ConversionService
from app.mana_ai.application.family_sources import FamilySourceService
from app.mana_ai.application.parent_touch import ParentTouchService
from app.mana_ai.application.ports import Clock
from app.mana_ai.application.proactive_parent import ProactiveParentService
from app.mana_ai.application.source_safety import SourceSafetyService
from app.mana_ai.domain.chat import ChatChild, ChatTokens, ParentChildContext
from app.mana_ai.domain.child_safety import (
    ChildSafetyLimits,
    SafetyAssessmentPage,
    SafetyBudget,
    SafetyInformationNeed,
    SafetyModelDecision,
)
from app.mana_ai.domain.conversion import (
    ConversionPolicy,
    ConversionProposalPage,
    ConversionSnapshot,
    PaidConversionOffer,
)
from app.mana_ai.domain.enums import AnalysisVerdict, FindingCategory, RiskLevel
from app.mana_ai.domain.family_agents import AgentQuestionRequest, ParentTouchHistory
from app.mana_ai.domain.family_sources import (
    ChildBatteryFacts,
    FamilySourceChange,
    FamilySourceLimits,
)
from app.mana_ai.domain.proactive_parent import ParentContactContext
from app.mana_ai.domain.responses import FindingDraft, ModelAnalysis, SafetyMonitorDetails
from app.mana_ai.domain.source_safety import SourceSafetyPolicy, SourceSafetyReceipt
from app.services.child_safety_model import OpenAIChildSafetyModel
from app.services.child_safety_prompts import ChildSafetyPromptBuilder
from app.services.commercial_conversation_store import SqliteCommercialConversationStore
from app.services.family_agent_worker import FamilyAgentWorker
from app.services.mana_ai_openai_gateway import SystemManaAIClock
from app.services.parent_chat_model import OpenAIParentChatModel
from app.services.source_safety_store import SqliteSourceSafetyStore

LAB_PARENT = "900001"
LAB_CHILD = 900002


class ClosableModel(ParentChatModel, Protocol):
    async def close(self) -> None: ...


class LabProfiles:
    def __init__(self, clock: Clock) -> None:
        self._clock = clock

    async def read(self, parent_id: str) -> ParentChildContext:
        if parent_id != LAB_PARENT:
            raise ParentChatError("lab_family_not_allowed", 403)
        return ParentChildContext(
            parent_id=LAB_PARENT,
            children=[
                ChatChild(child_id=LAB_CHILD, name="Тестовый ребёнок", age=8, connected=True)
            ],
            collected_at=self._clock.now(),
            limitations=["Fictional lab family; no Manakids, Firebase or GA4 data."],
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

    async def respond(self, prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
        question_id = notice_id = None
        if self.role == "safety":
            data = json.loads(prompt.messages[0][1])
            if data["kind"] == "parent_message":
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


class LabState(BaseModel):
    mode: Literal["simulation", "real-model"]
    history: ParentTouchHistory
    assessments: SafetyAssessmentPage
    safety_budget: SafetyBudget
    conversions: ConversionProposalPage
    source_changes: list[FamilySourceChange]
    source_dispatches: list[SourceSafetyReceipt]


@dataclass(frozen=True)
class LabOptions:
    directory: Path
    real_model: bool = False
    clock: Clock = field(default_factory=SystemManaAIClock)
    worker_enabled: bool = True


class ChatLab:
    def __init__(self, options: LabOptions) -> None:
        self.options = options
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

    def _directory(self) -> Path:
        directory = self.options.directory
        marker = directory / "lab-state.json"
        expected = {"kind": "mana-fictional-chat-lab", "mode": self.mode, "parent_id": LAB_PARENT}
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
        directory, now = self._directory(), self.options.clock.now()
        limits = ChildSafetyLimits(
            server_daily_tokens=2000, parent_daily_tokens=2000, job_tokens=1000
        )
        offer = PaidConversionOffer(
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
            specialist = OpenAIChildSafetyModel(
                settings.model_copy(
                    update={
                        "openai_model": settings.mana_child_safety_model or settings.openai_model
                    }
                )
            )
        else:
            speaker, specialist = SimulatedModel("speaker"), SimulatedModel("safety")
        self._models = [speaker, specialist]
        profiles = LabProfiles(self.options.clock)
        policy = SourceSafetyPolicy(timezone="Asia/Samarkand")
        self.source_store = SqliteSourceSafetyStore(
            directory / "sources.sqlite3",
            binding="fake-lab-mana-battery-v1",
            limits=FamilySourceLimits(),
            policy=policy,
            enabled=True,
        )
        await self.source_store.initialize()
        self.battery = LabBatterySource(directory, self.options.clock)
        self.sources = FamilySourceService(
            self.source_store, profiles, self.battery, clock=self.options.clock.now
        )
        self.safety = ChildSafetyService(
            store=self.store,
            children=profiles,
            model=specialist,
            prompts=ChildSafetyPromptBuilder(),
            clock=self.options.clock,
            limits=limits,
            max_output_tokens=512,
        )
        proactive = ProactiveParentService(self.store, clock=self.options.clock.now)
        self.touch = ParentTouchService(
            store=self.store,
            children=profiles,
            model=speaker,
            clock=self.options.clock.now,
            max_output_tokens=512,
            history_turn_limit=2,
            safety=self.safety,
            reviewed=self.store,
            conversion=ConversionService(self.store, clock=self.options.clock.now),
            proactive=proactive,
        )
        self.source_safety = SourceSafetyService(
            self.source_store, self.safety, profiles, policy=policy, clock=self.options.clock.now
        )
        if await self.store.contact_context(LAB_PARENT, now) is None:
            await proactive.register(
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
                )
            )
        self._worker = FamilyAgentWorker(
            self.safety,
            self.touch,
            clock=self.options.clock.now,
            interval=0.25,
            source_safety=self.source_safety,
        )
        if self.options.worker_enabled:
            self._worker.start()

    async def close(self) -> None:
        if self._worker is not None:
            await self._worker.close()
        for model in self._models:
            await model.close()

    async def state(self) -> LabState:
        assert self.touch.conversion is not None
        return LabState(
            mode=self.mode,
            history=await self.touch.read_touch_history(LAB_PARENT, before=None, limit=100),
            assessments=await self.safety.assessments(LAB_PARENT, after=0, limit=100),
            safety_budget=await self.safety.budget(LAB_PARENT),
            conversions=await self.touch.conversion.proposals(LAB_PARENT, after=0, limit=100),
            source_changes=[event for _, event in await self.source_store.changes(LAB_PARENT)],
            source_dispatches=await self.source_store.dispatch_receipts(LAB_PARENT),
        )

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
            scenarios=[
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
