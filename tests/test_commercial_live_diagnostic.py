"""The opt-in live harness is verified here with fakes; no paid APIs in tests."""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.mana_ai.application.chat_ports import ChatModelReceipt, ChatModelRejected, ChatPrompt
from app.mana_ai.application.parent_touch_offers import render_parent_offer
from app.mana_ai.domain.chat import ChatTokens, ResponseLanguage
from app.services.parent_chat_model import OpenAIParentChatModel
from scripts.mana_commercial_live_evaluate import CASES, Budget, MeteredModel, Role, run_case
from tests.test_conversion_agent import trial_offer


class FakeModel(OpenAIParentChatModel):
    def __init__(self, role: Role = "speaker", failure: str | None = None) -> None:
        self.role, self.failure = role, failure
        self.calls = 0
        self.counts = 0

    async def count_input(self, prompt: ChatPrompt) -> int:
        self.counts += 1
        if self.failure == "count":
            raise ValueError("fake-private-count-error")
        return 100

    async def respond(self, prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
        self.calls += 1
        if self.failure == "unknown":
            raise TimeoutError("fake-private-provider-error")
        if self.failure == "rejected":
            raise ChatModelRejected
        return ChatModelReceipt(
            usage=ChatTokens(input_tokens=100, output_tokens=50),
            model="gpt-5.4-mini" if self.role == "safety" else "gpt-5.4",
            answer=json.dumps(
                {
                    "analysis": None,
                    "question": None,
                    "followup_summary": "Only an adult subscription question.",
                }
            )
            if self.role == "safety"
            else "Taklif shartlari ko'rsatildi."
            if prompt.response_language == "uz-Latn"
            else "Условия предложения объяснены.",
            completed=self.failure != "invalid",
            failure_code="reply_schema_invalid" if self.failure == "invalid" else None,
        )

    async def close(self) -> None:
        pass


async def test_budget_ceiling_and_exact_count_precede_actual_delegate(tmp_path: Path) -> None:
    budget = Budget(tmp_path / "party")
    delegate = FakeModel()
    model = MeteredModel(delegate, budget, "gpt-5.4", "speaker")
    prompt = ChatPrompt("synthetic instructions", (("user", "synthetic question"),))
    await model.count_input(prompt)
    for _ in range(8):
        await model.respond(prompt, max_output_tokens=512)
    assert delegate.calls == budget.generations == 8
    assert budget.known_cost == Decimal("0.0080000") and budget.unknown_reserve == 0
    with pytest.raises(ValueError, match="admission refused"):
        await model.respond(prompt, max_output_tokens=512)
    changed = ChatPrompt("changed", prompt.messages)
    with pytest.raises(ValueError, match="exact verified"):
        await model.respond(changed, max_output_tokens=512)
    assert delegate.calls == 8


@pytest.mark.parametrize("failure", ["count", "unknown", "rejected", "invalid"])
async def test_diagnostic_retains_unknowns_or_verified_cost_without_retry(
    tmp_path: Path, failure: str
) -> None:
    budget = Budget(tmp_path / "party")
    delegate = FakeModel(failure=failure)
    model = MeteredModel(delegate, budget, "gpt-5.4", "speaker")
    prompt = ChatPrompt("synthetic", (("user", "question"),))
    if failure == "count":
        with pytest.raises(ValueError):
            await model.count_input(prompt)
        assert budget.halted and budget.generations == 0
    else:
        await model.count_input(prompt)
        if failure == "unknown":
            with pytest.raises(TimeoutError):
                await model.respond(prompt, max_output_tokens=512)
            assert budget.halted and budget.unknown_reserve == Decimal("0.05")
        elif failure == "rejected":
            with pytest.raises(ChatModelRejected):
                await model.respond(prompt, max_output_tokens=512)
            assert budget.halted and budget.unknown_reserve == 0
        else:
            receipt = await model.respond(prompt, max_output_tokens=512)
            assert not receipt.completed and budget.known_cost > 0
            assert budget.unknown_reserve == 0 and not budget.halted
    journal = (budget.directory / "usage.jsonl").read_text()
    assert "fake-private" not in journal
    if budget.halted:
        before = delegate.calls, delegate.counts
        with pytest.raises(ValueError):
            await model.count_input(prompt)
        assert (delegate.calls, delegate.counts) == before


async def test_four_case_driver_uses_actual_services_but_only_fake_models(tmp_path: Path) -> None:
    budget = Budget(tmp_path / "party")
    for name, language, text in CASES:
        result = await run_case(
            name,
            language,
            text,
            budget=budget,
            model_factory=FakeModel,
            models={"speaker": "gpt-5.4", "safety": "gpt-5.4-mini"},
        )
        assert result.get("phase") == "completed", result
        assert result["quota"]["daily_limit"] == 2000
        assert result["manual_review"] == "pending"
    assert budget.generations == 8 and not budget.halted and budget.unknown_reserve == 0


def test_existing_output_refuses_overwrite_and_unsupported_model_has_no_call(
    tmp_path: Path,
) -> None:
    budget = Budget(tmp_path / "party")
    with pytest.raises(FileExistsError):
        Budget(budget.directory)
    with pytest.raises(ValueError, match="verified diagnostic price"):
        MeteredModel(FakeModel(), budget, "unapproved-model", "speaker")
    with pytest.raises(ValueError, match="admission refused"):
        budget.claim("gpt-5.4", 1800, 512)
    assert budget.generations == 0


def test_free_grant_wording_does_not_invent_future_billing_terms() -> None:
    examples: tuple[tuple[ResponseLanguage, str, str], ...] = (
        ("ru", "не создаёт платёж или транзакцию", "Без платежа и автосписания"),
        ("uz-Latn", "to'lov yoki tranzaksiya yaratmaydi", "avtomatik yechishsiz"),
        ("uz-Cyrl", "тўлов ёки транзакция яратмайди", "автоматик ечишсиз"),
        ("en", "creates no payment or transaction", "No payment or automatic charge"),
    )
    for language, known, unsupported in examples:
        text = render_parent_offer(trial_offer(), 7, language)
        assert known in text and unsupported not in text
