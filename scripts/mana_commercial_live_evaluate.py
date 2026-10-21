"""One explicit, bounded synthetic commercial cohort; never a test or source refresh.

Only OpenAI is real. Parent profiles/account facts are fictional, separate private
SQLite files retain history/unknown holds, and no push/grant gateway is configured.
Usage estimates use standard uncached prices, not an invoice or business outcome.
"""

import argparse
import asyncio
import hashlib
import json
import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from dotenv import dotenv_values
from openai import AsyncOpenAI
from pydantic import SecretStr

from app.core.config import Settings
from app.mana_ai.application.chat_ports import (
    ChatModelReceipt,
    ChatModelRejected,
    ChatPrompt,
    ParentChatError,
    ParentChatModel,
)
from app.mana_ai.application.child_safety import ChildSafetyService
from app.mana_ai.application.conversion import ConversionService
from app.mana_ai.application.conversion_accounts import ConversionAccountVerifier
from app.mana_ai.application.parent_touch import ParentTouchService
from app.mana_ai.domain.child_safety import ChildSafetyLimits
from app.mana_ai.domain.conversion import (
    ConversionOffer,
    ConversionPolicy,
    ConversionSnapshot,
    PaidConversionOffer,
    TrialConversionOffer,
)
from app.mana_ai.domain.conversion_accounts import (
    ConversionAccountFacts,
    ConversionAccountReadLimits,
)
from app.mana_ai.domain.family_agents import ParentTouchMessageRequest
from app.services.child_safety_model import OpenAIChildSafetyModel
from app.services.child_safety_prompts import ChildSafetyPromptBuilder
from app.services.conversion_account_store import SqliteConversionAccountStore
from app.services.mana_ai_openai_gateway import SystemManaAIClock
from app.services.parent_chat_model import OpenAIParentChatModel
from scripts.mana_family_agents_smoke import Profiles

Role = Literal["speaker", "safety"]
RATES = {
    "gpt-5.4": (Decimal("0.0000025"), Decimal("0.000015")),
    "gpt-5.4-mini": (Decimal("0.00000075"), Decimal("0.0000045")),
}
RESERVATION = Decimal("0.05")
MAX_GENERATIONS = 8
CASES: tuple[tuple[str, str, str], ...] = (
    ("paid_ru", "ru", "Какая итоговая цена с вашей скидкой и будет ли автоматическое списание?"),
    ("paid_uz", "uz-Latn", "Chegirma bilan qancha to'layman va obuna avtomatik uzayadimi?"),
    ("trial_ru", "ru", "Активировать бесплатные дни. Они уже подключены? Это платная подписка?"),
    (
        "trial_uz",
        "uz-Latn",
        "Bepul kunlarni faollashtiring. Ular allaqachon yoqildimi? Bu pulli obunami?",
    ),
)


class Budget:
    def __init__(self, directory: Path) -> None:
        directory.mkdir(mode=0o700, parents=True, exist_ok=False)
        self.directory = directory
        self.generations = 0
        self.counts = 0
        self.known_cost = Decimal(0)
        self.unknown_reserve = Decimal(0)
        self.halted = False
        self._journal = directory / "usage.jsonl"
        self._journal.touch(exist_ok=False, mode=0o600)

    def record(self, kind: str, **facts: object) -> None:
        with self._journal.open("a", encoding="utf-8") as output:
            output.write(json.dumps({"kind": kind, **facts}, ensure_ascii=False) + "\n")
            output.flush()
            os.fsync(output.fileno())

    def claim(self, model: str, input_tokens: int, output_cap: int) -> int:
        if (
            self.halted
            or self.generations >= MAX_GENERATIONS
            or model not in RATES
            or type(input_tokens) is not int
            or input_tokens < 0
            or type(output_cap) is not int
            or output_cap < 32
            or input_tokens + output_cap > 2000
        ):
            raise ValueError("Diagnostic admission refused before generation")
        self.generations += 1
        self.unknown_reserve += RESERVATION
        self.record(
            "generation_claim",
            position=self.generations,
            model=model,
            input_tokens=input_tokens,
            output_cap=output_cap,
            reserved_usd=str(RESERVATION),
        )
        return self.generations

    def settle(self, position: int, model: str, receipt: ChatModelReceipt) -> None:
        incoming, outgoing = RATES[model]
        cost = incoming * receipt.usage.input_tokens + outgoing * receipt.usage.output_tokens
        self.known_cost += cost
        self.unknown_reserve -= RESERVATION
        self.record(
            "generation_receipt",
            position=position,
            requested_model=model,
            returned_model=receipt.model,
            input_tokens=receipt.usage.input_tokens,
            output_tokens=receipt.usage.output_tokens,
            completed=receipt.completed,
            failure_code=receipt.failure_code,
            standard_uncached_usd=str(cost),
        )


def prompt_digest(prompt: ChatPrompt) -> str:
    return hashlib.sha256(repr(prompt).encode()).hexdigest()


class MeteredModel:
    def __init__(self, delegate: ParentChatModel, budget: Budget, model: str, role: Role) -> None:
        if model not in RATES:
            raise ValueError("No verified diagnostic price for the configured model")
        self.delegate, self.budget, self.model, self.role = delegate, budget, model, role
        self._counted: tuple[str, int] | None = None

    async def count_input(self, prompt: ChatPrompt) -> int:
        if self.budget.halted or self.budget.counts >= 16:
            raise ValueError("Diagnostic count ceiling reached")
        self.budget.counts += 1
        try:
            count = await self.delegate.count_input(prompt)
            if type(count) is not int or not 0 <= count <= 4000:
                raise ValueError("Invalid diagnostic token count")
        except (Exception, asyncio.CancelledError):
            self.budget.halted = True
            self.budget.record("count_failed", role=self.role)
            raise
        self._counted = prompt_digest(prompt), count
        self.budget.record("input_count", role=self.role, model=self.model, tokens=count)
        return count

    async def respond(self, prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
        if self._counted is None or self._counted[0] != prompt_digest(prompt):
            raise ValueError("Generation has no exact verified input count")
        position = self.budget.claim(self.model, self._counted[1], max_output_tokens)
        try:
            receipt = await self.delegate.respond(prompt, max_output_tokens=max_output_tokens)
        except ChatModelRejected:
            self.budget.unknown_reserve -= RESERVATION
            self.budget.halted = True
            self.budget.record("generation_rejected", position=position)
            raise
        except (Exception, asyncio.CancelledError):
            self.budget.halted = True
            self.budget.record("generation_unknown", position=position)
            raise
        self.budget.settle(position, self.model, receipt)
        return receipt


class Account:
    def __init__(self, event: ConversionSnapshot) -> None:
        self.event = event

    async def read(self, parent_id: str) -> ConversionAccountFacts:
        assert parent_id == self.event.parent_id
        return ConversionAccountFacts(
            parent_id=parent_id,
            collected_at=datetime.now(UTC),
            is_paid=False,
            agent_trial_used=False,
            created_at=self.event.observed_at - timedelta(days=365),
            payment_date=self.event.free_started_at,
            valid_until=self.event.free_access_ends_at,
        )


async def run_case(
    name: str,
    language: str,
    text: str,
    *,
    budget: Budget,
    model_factory: Callable[[Role], OpenAIParentChatModel],
    models: dict[Role, str],
) -> dict[str, Any]:
    now = datetime.now(UTC)
    common: dict[str, Any] = {
        "valid_from": now - timedelta(days=1),
        "valid_until": now + timedelta(days=30),
        "approval_reference": "synthetic-not-a-real-billing-offer",
    }
    offer: ConversionOffer = (
        PaidConversionOffer(
            offer_id="synthetic-paid",
            billing_offer_id="synthetic-paid-15",
            currency="USD",
            list_price_minor=1000,
            price_minor=850,
            discount_percent=15,
            duration_days=30,
            auto_renew=False,
            checkout_path="/subscriptions/synthetic-month",
            **common,
        )
        if name.startswith("paid")
        else TrialConversionOffer(offer_id="synthetic-free", grant_days=3, **common)
    )
    event = ConversionSnapshot.model_validate(
        {
            "parent_id": "700001",
            "event_id": uuid4(),
            "revision": 1,
            "observed_at": now,
            "subscription": "free",
            "free_started_at": now - timedelta(days=7),
            "free_access_ends_at": now + timedelta(days=1),
            "agent_trial_given": False,
            "marketing_consent": True,
            "consent_observed_at": now,
            "language": language,
            "timezone": "UTC",
            "last_active_at": now,
            "active_days_7d": 3,
            "sessions_7d": 5,
            "paywall_views_7d": 1,
        }
    )
    limits = ChildSafetyLimits(server_daily_tokens=2000, parent_daily_tokens=2000, job_tokens=2000)
    store = SqliteConversionAccountStore(
        budget.directory / (name + ".sqlite3"),
        conversion_policy=ConversionPolicy(
            quiet_start_hour=(now.hour + 2) % 24, quiet_end_hour=(now.hour + 3) % 24
        ),
        conversion_offers=(offer,),
        limits=limits,
        daily_limit=2000,
        timezone="UTC",
        account_source_enabled=True,
        account_read_limits=ConversionAccountReadLimits(),
        proactive_enabled=False,
        push_enabled=False,
    )
    await store.initialize()
    clock, profiles = SystemManaAIClock(), Profiles()
    conversion = ConversionService(
        store,
        clock=clock.now,
        accounts=ConversionAccountVerifier(store, Account(event), clock=clock.now),
    )
    await conversion.observe(event)
    delegates = {"speaker": model_factory("speaker"), "safety": model_factory("safety")}
    speaker = MeteredModel(delegates["speaker"], budget, models["speaker"], "speaker")
    specialist = MeteredModel(delegates["safety"], budget, models["safety"], "safety")
    safety = ChildSafetyService(
        store=store,
        children=profiles,
        model=specialist,
        prompts=ChildSafetyPromptBuilder(),
        clock=clock,
        limits=limits,
        max_output_tokens=1024,
    )
    touch = ParentTouchService(
        store=store,
        children=profiles,
        model=speaker,
        clock=clock.now,
        max_output_tokens=512,
        history_turn_limit=2,
        safety=safety,
        reviewed=store,
        conversion=conversion,
    )
    result: dict[str, Any] = {"case": name, "language": language, "manual_review": "pending"}
    request = ParentTouchMessageRequest(parent_id="700001", request_id=uuid4(), message=text)
    try:
        assert await touch.process_conversion()
        admitted = await touch.admit_message(request)
        assert admitted.phase == "awaiting_review"
        reviewed = await safety.process_one()
        result["review_status"] = reviewed.status if reviewed else None
        await touch.process_reviewed_message()
        state = await touch.message_state(request.parent_id, request.request_id)
        result.update(phase=state.phase, error_code=state.error_code)
        # Replay observes the original turn; it must not count or infer again.
        before = budget.generations, budget.counts
        assert await touch.admit_message(request) == state
        assert (budget.generations, budget.counts) == before
        history = await touch.read_touch_history(request.parent_id, before=None, limit=20)
        result["history"] = [m.model_dump(mode="json") for m in history.messages]
        result["quota"] = history.quota.model_dump(mode="json")
        result["safety_budget"] = (await safety.budget(request.parent_id)).model_dump(mode="json")
    except ParentChatError as exc:
        result["controlled_error"] = exc.code
    except Exception as exc:
        result["exception_type"] = type(exc).__name__
    finally:
        for delegate in delegates.values():
            await delegate.close()
    return result


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--confirm-paid", action="store_true")
    args = parser.parse_args()
    if not args.confirm_paid or os.environ.get("MANA_COMMERCIAL_LIVE_EVAL") != "1":
        parser.error("Explicit paid diagnostic opt-in is required")
    key = dotenv_values(args.env_file).get("OPENAI_API_KEY")
    if not key:
        parser.error("OPENAI_API_KEY is absent from the selected ignored environment file")
    settings = Settings(_env_file=None, openai_api_key=SecretStr(key))
    models: dict[Role, str] = {
        "speaker": settings.mana_parent_touch_model or "",
        "safety": settings.mana_child_safety_model or "",
    }
    if any(model not in RATES for model in models.values()):
        parser.error("Configured model has no verified diagnostic pricing")
    budget = Budget(args.output_dir)

    def factory(role: Role) -> OpenAIParentChatModel:
        adapter = OpenAIParentChatModel if role == "speaker" else OpenAIChildSafetyModel
        return adapter(
            settings.model_copy(update={"openai_model": models[role]}),
            client=AsyncOpenAI(
                api_key=key,
                base_url="https://api.openai.com/v1",
                max_retries=0,
                timeout=min(settings.openai_timeout_seconds, 120),
            ),
        )

    cases = []
    for name, language, text in CASES:
        if budget.halted:
            break
        print(json.dumps({"starting": name}), flush=True)
        result = await run_case(
            name, language, text, budget=budget, model_factory=factory, models=models
        )
        cases.append(result)
        with (budget.directory / (name + ".json")).open("x", encoding="utf-8") as output:
            json.dump(result, output, ensure_ascii=False, indent=2)
        print(
            json.dumps(
                {
                    "finished": name,
                    "phase": result.get("phase"),
                    "controlled_error": result.get("controlled_error"),
                    "exception_type": result.get("exception_type"),
                }
            ),
            flush=True,
        )
    summary = {
        "cases": len(cases),
        "generations": budget.generations,
        "input_counts": budget.counts,
        "standard_uncached_estimate_usd": str(budget.known_cost),
        "unresolved_reserve_usd": str(budget.unknown_reserve),
        "halted": budget.halted,
        "manual_review": "pending",
        "models": models,
        "reservation_ceiling_usd": str(RESERVATION * MAX_GENERATIONS),
        "real_source_calls": 0,
        "real_contacts": 0,
        "production_mutations": 0,
    }
    with (budget.directory / "summary.json").open("x", encoding="utf-8") as output:
        json.dump(summary, output, ensure_ascii=False, indent=2)
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
