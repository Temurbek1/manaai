import asyncio
import hashlib
import json
from decimal import Decimal
from pathlib import Path
from typing import Literal
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import SecretStr
from pytest import CaptureFixture, MonkeyPatch

import app.core.config as config
import app.mana_operation_ai.infrastructure.chat_model as chat_model
import scripts.operation_chat_evaluate as evaluation_module
from app.core.config import Settings
from app.mana_operation_ai.application.chat_service import INSTRUCTIONS
from app.mana_operation_ai.domain.cost_control import ResourceUsage
from app.mana_operation_ai.infrastructure.chat_model import (
    OpenAIConversationModel,
    conversation_input_bound,
)
from app.mana_operation_ai.infrastructure.persistence.cost_ledger import SqlAlchemyCostLedger
from app.mana_operation_ai.infrastructure.persistence.database import OperationDatabase
from scripts.operation_chat_evaluate import (
    EvaluationPreflightError,
    _record_attempt,
    evaluate,
    evaluation_cases,
    evaluation_limits,
    main,
    prepare_requests,
)
from tests.test_operation_chat_costs import response
from tests.test_operation_cost_ledger import Clock


def test_paired_contexts_are_synthetic_scoped_deterministic_and_bounded() -> None:
    requests = prepare_requests()
    assert len(requests) == 16 and requests == prepare_requests()
    assert {item.case_id for item in requests} == {case.case_id for case in evaluation_cases()}
    for reference, bounded in zip(requests[::2], requests[1::2], strict=True):
        assert reference.case_id == bounded.case_id
        assert reference.variant == "reference" and bounded.variant == "bounded"
        raw, compact = json.loads(reference.context), json.loads(bounded.context)
        assert raw["message"] == compact["message"]
        assert raw["topic"] == compact["topic"]
        parent_allowed = (
            compact["topic"]["product"] == "mana"
            and compact["topic"]["agent_id"] == "retention-agent"
        )
        assert compact["parent_summary_enabled"] is parent_allowed
        assert ("mana_parents" in compact["allowed_next_actions"]) is parent_allowed
        assert bounded.context_bytes <= 24_000
        assert reference.context_sha256 == hashlib.sha256(reference.context.encode()).hexdigest()
        assert reference.input_reservation == conversation_input_bound(
            instructions=INSTRUCTIONS, context=reference.context
        )
        assert reference.input_reservation <= 64_000
        for old, new in zip(raw["saved_reports"], compact["saved_reports"], strict=True):
            for key in (
                "id",
                "report_created_at",
                "collected_at",
                "fresh_until",
                "refresh_status",
                "product",
                "capability_key",
                "report_type",
            ):
                assert old[key] == new[key]
            assert new["product"] == compact["topic"]["product"]
            assert new["scope_verified"] is True
        if reference.case_id == "long_history_goal":
            assert reference.context_bytes > bounded.context_bytes
            assert compact["older_turns_omitted"] == 0
            assert compact["history_text_shortened"] is True
            assert "$30/месяц" in reference.context and "$30/месяц" in bounded.context
            assert "Не предлагать скидки или контакт с родителями" in bounded.context
            assert [turn["user"] for turn in raw["history"]] == [
                turn["user"] for turn in compact["history"]
            ]
        if reference.case_id == "untrusted_long_reports":
            assert compact["report_text_shortened"] is True
            assert reference.context_bytes > bounded.context_bytes
        if compact["topic"]["product"] == "360rec":
            assert compact["saved_reports"] == []
    assert 0 < sum(item.cost_reservation_microusd for item in requests) < 500_000


@pytest.mark.parametrize(
    "arguments,dataset",
    [
        ([], "operation-chat-synthetic-v5"),
        (["--reasoning-comparison"], "operation-chat-reasoning-holdout-v3"),
        (["--model-comparison"], "operation-chat-model-comparison-v2"),
        (["--validation-comparison"], "operation-chat-validation-comparison-v2"),
        (["--mini-reasoning-comparison"], "operation-chat-mini-reasoning-v1"),
        (["--fresh-comparison"], "operation-chat-fresh-comparison-v1"),
        (["--flagship-quality"], "operation-chat-flagship-quality-v1"),
        (["--sol-quality"], "operation-chat-sol-quality-v1"),
    ],
)
def test_offline_cli_never_loads_credentials_constructs_sdk_or_sends_http(
    monkeypatch: MonkeyPatch, capsys: CaptureFixture[str], arguments: list[str], dataset: str
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("Offline QA touched a provider or developer credentials")

    monkeypatch.setattr(config, "get_settings", forbidden)
    monkeypatch.setattr(chat_model, "OpenAIConversationModel", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)
    assert main(arguments) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["live_provider_calls"] == 0 and plan["quality_status"] == "not_evaluated"
    assert plan["maximum_calls"] == (
        8 if any(flag in arguments for flag in ("--flagship-quality", "--sol-quality")) else 16
    )
    assert plan["dataset_version"] == dataset
    assert plan["instructions"] == INSTRUCTIONS
    assert plan["instructions_sha256"] == hashlib.sha256(INSTRUCTIONS.encode()).hexdigest()
    assert Decimal(plan["conservative_token_cost_usd"]) < Decimal("0.50")


def test_reasoning_comparison_preserves_context_model_and_positive_controls() -> None:
    requests = prepare_requests(reasoning_comparison=True)
    assert len(requests) == 16
    assert requests == prepare_requests(reasoning_comparison=True)
    assert {item.case_id for item in requests}.isdisjoint(
        {case.case_id for case in evaluation_cases()}
    )
    for baseline, low in zip(requests[::2], requests[1::2], strict=True):
        assert baseline.case_id == low.case_id
        assert (baseline.variant, baseline.requested_reasoning_effort) == ("nano_none", "none")
        assert (low.variant, low.requested_reasoning_effort) == ("nano_low", "low")
        assert baseline.context == low.context
        assert baseline.context_sha256 == low.context_sha256
        assert baseline.cost_reservation_microusd == low.cost_reservation_microusd
        assert low.context_bytes <= 24_000 and low.input_reservation <= 64_000
    assert {"parent_refresh_positive", "growth_approval_positive"}.issubset(
        {item.case_id for item in requests}
    )
    omitted = next(item for item in requests if item.case_id == "omitted_agreement_holdout")
    assert json.loads(omitted.context)["older_turns_omitted"] == 9
    excerpt = next(item for item in requests if item.case_id == "excerpt_and_injection_holdout")
    assert json.loads(excerpt.context)["report_text_shortened"] is True


def test_model_comparison_prices_each_explicit_profile_without_changing_reasoning() -> None:
    requests = prepare_requests(model_comparison=True)
    assert len(requests) == 16 and requests == prepare_requests(model_comparison=True)
    for baseline, candidate in zip(requests[::2], requests[1::2], strict=True):
        assert baseline.case_id == candidate.case_id
        assert baseline.requested_model == "gpt-5.4-nano"
        assert candidate.requested_model == "gpt-5.4-mini" and candidate.variant == "mini_none"
        assert baseline.requested_reasoning_effort == candidate.requested_reasoning_effort == "none"
        assert baseline.context == candidate.context
        assert baseline.context_sha256 == candidate.context_sha256
        assert baseline.cost_reservation_microusd < candidate.cost_reservation_microusd
    with pytest.raises(EvaluationPreflightError, match="mutually exclusive"):
        prepare_requests(model_comparison=True, reasoning_comparison=True)


def test_validation_comparison_has_disjoint_tasks_and_preserves_tail_constraints() -> None:
    requests = prepare_requests(validation_comparison=True)
    assert len(requests) == 16 and requests == prepare_requests(validation_comparison=True)
    case_ids = {item.case_id for item in requests}
    assert case_ids == {case.case_id for case in evaluation_module.validation_cases()}
    assert case_ids.isdisjoint({case.case_id for case in evaluation_cases()})
    assert case_ids.isdisjoint({case.case_id for case in evaluation_module.reasoning_cases()})
    for baseline, candidate in zip(requests[::2], requests[1::2], strict=True):
        assert baseline.case_id == candidate.case_id
        assert baseline.variant == "nano_none" and candidate.variant == "mini_none"
        assert baseline.requested_model == "gpt-5.4-nano"
        assert candidate.requested_model == "gpt-5.4-mini"
        assert baseline.requested_reasoning_effort == candidate.requested_reasoning_effort == "none"
        assert baseline.context_sha256 == candidate.context_sha256
        assert baseline.context == candidate.context
        assert baseline.context_bytes <= 24_000 and baseline.input_reservation <= 64_000
        context = json.loads(baseline.context)
        assert len(context["saved_reports"]) <= 2
        assert all(
            report["product"] == context["topic"]["product"] and report["scope_verified"] is True
            for report in context["saved_reports"]
        )
        if context["topic"]["agent_id"] == "technical-agent":
            assert context["allowed_next_actions"] == ["none"]
    history = next(item for item in requests if item.case_id == "validation_long_user_tail")
    compact = json.loads(history.context)
    first_user = compact["history"][0]["user"]
    assert first_user.index("$17/месяц") > 3000
    assert "Запрещены скидки, контакт с родителями и чтение Parent API" in first_user
    assert len(compact["history"]) == 6 and compact["older_turns_omitted"] == 0
    assert compact["history_text_shortened"] is True
    assert 0 < sum(item.cost_reservation_microusd for item in requests) < 400_000


@pytest.mark.parametrize(
    "reasoning,model",
    [(True, False), (False, True), (True, True)],
)
def test_validation_comparison_cannot_be_combined_with_other_modes(
    reasoning: bool, model: bool
) -> None:
    with pytest.raises(EvaluationPreflightError, match="mutually exclusive"):
        prepare_requests(
            reasoning_comparison=reasoning,
            model_comparison=model,
            validation_comparison=True,
        )


def test_mini_reasoning_comparison_preserves_inputs_rates_and_changes_only_effort() -> None:
    requests = prepare_requests(mini_reasoning_comparison=True)
    assert len(requests) == 16 and requests == prepare_requests(mini_reasoning_comparison=True)
    assert {item.case_id for item in requests} == {
        case.case_id for case in evaluation_module.validation_cases()
    }
    for baseline, candidate in zip(requests[::2], requests[1::2], strict=True):
        assert baseline.variant == "mini_none" and candidate.variant == "mini_low"
        assert baseline.requested_model == candidate.requested_model == "gpt-5.4-mini"
        assert baseline.requested_reasoning_effort == "none"
        assert candidate.requested_reasoning_effort == "low"
        assert baseline.context == candidate.context
        assert baseline.context_sha256 == candidate.context_sha256
        assert baseline.cost_reservation_microusd == candidate.cost_reservation_microusd
        assert baseline.context_bytes <= 24_000
    assert 0 < sum(item.cost_reservation_microusd for item in requests) < 350_000


def test_fresh_comparison_freezes_disjoint_tasks_pairs_and_critical_criteria() -> None:
    requests = prepare_requests(fresh_comparison=True)
    assert len(requests) == 16 and requests == prepare_requests(fresh_comparison=True)
    case_ids = {item.case_id for item in requests}
    for previous in [
        evaluation_cases(),
        evaluation_module.reasoning_cases(),
        evaluation_module.validation_cases(),
    ]:
        assert case_ids.isdisjoint({case.case_id for case in previous})
    for baseline, candidate in zip(requests[::2], requests[1::2], strict=True):
        assert baseline.variant == "nano_none" and candidate.variant == "mini_low"
        assert baseline.requested_model == "gpt-5.4-nano"
        assert candidate.requested_model == "gpt-5.4-mini"
        assert baseline.requested_reasoning_effort == "none"
        assert candidate.requested_reasoning_effort == "low"
        assert baseline.context == candidate.context
        assert baseline.context_sha256 == candidate.context_sha256
        assert baseline.review_checks == candidate.review_checks
        assert len(baseline.review_checks) >= 3
        assert baseline.context_bytes <= 24_000 and baseline.input_reservation <= 64_000
    history = next(item for item in requests if item.case_id == "fresh_history_user_over_assistant")
    compact = json.loads(history.context)
    assert len(compact["history"]) == 6
    assert compact["history_text_shortened"] is True and compact["older_turns_omitted"] == 0
    assert compact["history"][0]["user"].index("$23/месяц") > 3000
    assert "Никаких скидок, сообщений родителям и новых обращений к источникам" in history.context
    excerpt = next(item for item in requests if item.case_id == "fresh_hostile_source_and_excerpt")
    assert json.loads(excerpt.context)["report_text_shortened"] is True
    assert evaluation_limits(requests, approved_usd=Decimal("0.25")).daily.llm_calls == 16


def test_flagship_quality_preserves_all_tasks_context_and_explicit_output_budget() -> None:
    requests = prepare_requests(flagship_quality=True)
    baselines = prepare_requests(fresh_comparison=True)[::2]
    assert len(requests) == 8 and requests == prepare_requests(flagship_quality=True)
    for baseline, candidate in zip(baselines, requests, strict=True):
        assert candidate.variant == "full_low"
        assert candidate.requested_model == "gpt-5.4"
        assert candidate.requested_reasoning_effort == "low"
        assert candidate.max_output_tokens == 1536
        assert baseline.max_output_tokens == 2048
        assert candidate.case_id == baseline.case_id
        assert candidate.context == baseline.context
        assert candidate.context_sha256 == baseline.context_sha256
        assert candidate.review_checks == baseline.review_checks
        assert candidate.cost_reservation_microusd == evaluation_module.FULL_RATES.reserve_microusd(
            input_tokens=candidate.input_reservation, output_tokens=1536
        )
    limits = evaluation_limits(requests, approved_usd=Decimal("0.49"))
    assert limits.daily == limits.monthly
    assert limits.daily.llm_calls == limits.daily.provider_requests == 8
    assert limits.daily.output_tokens == 8 * 1536
    assert limits.daily.document_reads == limits.daily.data_microusd == 0
    assert limits.daily.llm_microusd == 490_000
    with pytest.raises(EvaluationPreflightError, match="entire batch"):
        evaluation_limits(requests, approved_usd=Decimal("0.40"))


@pytest.mark.parametrize("mode", ["reasoning", "model", "validation", "mini_reasoning", "fresh"])
def test_flagship_quality_is_exclusive_with_all_prior_modes(mode: str) -> None:
    with pytest.raises(EvaluationPreflightError, match="mutually exclusive"):
        prepare_requests(
            reasoning_comparison=mode == "reasoning",
            model_comparison=mode == "model",
            validation_comparison=mode == "validation",
            mini_reasoning_comparison=mode == "mini_reasoning",
            fresh_comparison=mode == "fresh",
            flagship_quality=True,
        )


def test_sol_quality_preserves_all_regressions_and_reserves_cache_write_upper_bound() -> None:
    requests = prepare_requests(sol_quality=True)
    baselines = prepare_requests(fresh_comparison=True)[::2]
    assert len(requests) == 8 and requests == prepare_requests(sol_quality=True)
    # Prompt refinements may change the reservation, but must fit the approved
    # batch ceiling. Per-request accounting remains checked exactly below;
    # historical archived diagnostics retain their original hashes/charges.
    assert 0 < sum(item.cost_reservation_microusd for item in requests) <= 490_000
    for baseline, candidate in zip(baselines, requests, strict=True):
        assert candidate.variant == "sol_low"
        assert candidate.requested_model == "gpt-6.1-sol"
        assert candidate.requested_reasoning_effort == "low"
        assert candidate.max_output_tokens == baseline.max_output_tokens == 2048
        assert candidate.case_id == baseline.case_id
        assert candidate.context == baseline.context
        assert candidate.context_sha256 == baseline.context_sha256
        assert candidate.review_checks == baseline.review_checks
        assert candidate.cost_reservation_microusd == evaluation_module.SOL_RATES.reserve_microusd(
            input_tokens=candidate.input_reservation, output_tokens=2048
        )
    limits = evaluation_limits(requests, approved_usd=Decimal("0.49"))
    assert limits.daily == limits.monthly
    assert limits.daily.llm_calls == limits.daily.provider_requests == 8
    assert limits.daily.output_tokens == 8 * 2048
    assert limits.daily.document_reads == limits.daily.data_microusd == 0
    with pytest.raises(EvaluationPreflightError, match="entire batch"):
        evaluation_limits(requests, approved_usd=Decimal("0.44"))


@pytest.mark.parametrize(
    "mode", ["reasoning", "model", "validation", "mini_reasoning", "fresh", "flagship"]
)
def test_sol_quality_is_exclusive_with_every_prior_mode(mode: str) -> None:
    with pytest.raises(EvaluationPreflightError, match="mutually exclusive"):
        prepare_requests(
            reasoning_comparison=mode == "reasoning",
            model_comparison=mode == "model",
            validation_comparison=mode == "validation",
            mini_reasoning_comparison=mode == "mini_reasoning",
            fresh_comparison=mode == "fresh",
            flagship_quality=mode == "flagship",
            sol_quality=True,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_at", [None, 1, 4])
@pytest.mark.parametrize("profile", ["flagship", "sol"])
async def test_stronger_profile_fake_sdk_is_metered_isolated_and_stops_on_failure(
    tmp_path: Path, monkeypatch: MonkeyPatch, fail_at: int | None, profile: str
) -> None:
    model_name = "gpt-5.4" if profile == "flagship" else "gpt-6.1-sol"
    output_limit = 1536 if profile == "flagship" else 2048
    variant = "full_low" if profile == "flagship" else "sol_low"
    rates = evaluation_module.FULL_RATES if profile == "flagship" else evaluation_module.SOL_RATES
    settings = Settings(_env_file=None, openai_api_key="fake-flagship-key")
    monkeypatch.setattr(config, "get_settings", lambda: settings)
    monkeypatch.setattr(evaluation_module, "__file__", str(tmp_path / "scripts" / "evaluate.py"))
    clients: list[OpenAIConversationModel] = []
    parses: list[AsyncMock] = []

    def gateway_factory(
        configured: Settings, *, ledger: SqlAlchemyCostLedger
    ) -> OpenAIConversationModel:
        gateway = OpenAIConversationModel(configured, ledger=ledger)
        results: list[object] = [response(configured) for _ in range(8)]
        if fail_at is not None:
            results[fail_at - 1] = TimeoutError("fake-flagship-secret")
        parse = AsyncMock(side_effect=results)
        monkeypatch.setattr(gateway._client.responses, "parse", parse)
        clients.append(gateway)
        parses.append(parse)
        return gateway

    async def forbidden_send(*args: object, **kwargs: object) -> httpx.Response:
        raise AssertionError("Fake flagship QA reached the network")

    monkeypatch.setattr(chat_model, "OpenAIConversationModel", gateway_factory)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden_send)
    requests = prepare_requests(
        flagship_quality=profile == "flagship", sol_quality=profile == "sol"
    )
    report = await evaluation_module._live(
        requests,
        approval_id="example-flagship",
        budget=Decimal("0.49"),
        context_bytes=24_000,
    )
    assert report["all_requests_completed"] is (fail_at is None)
    assert report["product_source_calls"] == report["operational_actions"] == 0
    assert len(clients) == 1 and clients[0]._client.is_closed()
    assert clients[0]._client.max_retries == 0
    assert settings.effective_operation_chat_model == "gpt-5.4-nano"
    assert settings.effective_operation_chat_reasoning_effort == "none"
    assert settings.openai_max_output_tokens == 2048
    assert settings.effective_audio_moderation_model == "gpt-5.4-nano"
    parse = parses[0]
    assert parse.call_count == (fail_at or 8)
    for call in parse.call_args_list:
        assert call.kwargs["model"] == model_name
        assert call.kwargs["reasoning"] == {"effort": "low"}
        assert call.kwargs["max_output_tokens"] == output_limit
        assert call.kwargs["store"] is False
        assert call.kwargs["service_tier"] == "default"
    directory = tmp_path / "output/operation-chat-evaluation/example-flagship"
    text = directory.joinpath("results.json").read_text()
    saved = json.loads(text)
    assert "fake-flagship" not in text
    assert saved["runtime_model_settings"]["profile_max_output_tokens"] == {variant: output_limit}
    assert saved["runtime_model_settings"]["comparison_models"] == [model_name]
    assert len(saved["results"]) == (fail_at or 8)
    assert all(result["max_output_tokens"] == output_limit for result in saved["results"])
    known = rates.actual_microusd(
        input_tokens=200, output_tokens=100, cached_tokens=40, cache_write_tokens=30
    )
    assert saved["charge_accounting"] == {
        "attempted_calls": fail_at or 8,
        "settled_calls": fail_at - 1 if fail_at is not None else 8,
        "known_microusd": known * (fail_at - 1 if fail_at is not None else 8),
        "unknown_holds": 1 if fail_at is not None else 0,
        "reserved_unknown_microusd": requests[fail_at - 1].cost_reservation_microusd
        if fail_at is not None
        else 0,
    }
    if fail_at is not None:
        assert saved["results"][-1]["failure_kind"] == "TimeoutError"
        expected = known * (fail_at - 1) + requests[fail_at - 1].cost_reservation_microusd
        assert saved["periods"][-1]["usage"]["llm_microusd"] == expected
    with pytest.raises(FileExistsError):
        await evaluation_module._live(
            requests,
            approval_id="example-flagship",
            budget=Decimal("0.49"),
            context_bytes=24_000,
        )
    assert len(clients) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("output_limit,effort", [(1536, "low"), (2047, "low"), (2048, "none")])
async def test_sol_unreviewed_or_unsupported_profile_is_refused_before_sdk(
    monkeypatch: MonkeyPatch, output_limit: int, effort: str
) -> None:
    settings = Settings(_env_file=None, openai_api_key="fake-sol-profile-key")
    monkeypatch.setattr(config, "get_settings", lambda: settings)

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("Unreviewed Sol profile constructed a gateway")

    monkeypatch.setattr(chat_model, "OpenAIConversationModel", forbidden)
    requests = prepare_requests(sol_quality=True)
    requests[0] = requests[0].model_copy(
        update={"max_output_tokens": output_limit, "requested_reasoning_effort": effort}
    )
    with pytest.raises(EvaluationPreflightError, match="current none baseline"):
        await evaluation_module._live(
            requests,
            approval_id="example-wrong-sol-profile",
            budget=Decimal("0.49"),
            context_bytes=24_000,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("output_limit", [1024, 1535, 2048])
async def test_flagship_unreviewed_output_ceiling_is_refused_before_sdk_construction(
    monkeypatch: MonkeyPatch, output_limit: int
) -> None:
    settings = Settings(_env_file=None, openai_api_key="fake-profile-key")
    monkeypatch.setattr(config, "get_settings", lambda: settings)

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("Unreviewed output profile constructed a gateway")

    monkeypatch.setattr(chat_model, "OpenAIConversationModel", forbidden)
    requests = prepare_requests(flagship_quality=True)
    requests[0] = requests[0].model_copy(update={"max_output_tokens": output_limit})
    with pytest.raises(EvaluationPreflightError, match="current none baseline"):
        await evaluation_module._live(
            requests,
            approval_id="example-wrong-full-ceiling",
            budget=Decimal("0.49"),
            context_bytes=24_000,
        )


@pytest.mark.parametrize("mode", ["reasoning", "model", "validation", "mini_reasoning"])
def test_fresh_comparison_is_exclusive_with_every_prior_mode(mode: str) -> None:
    with pytest.raises(EvaluationPreflightError, match="mutually exclusive"):
        prepare_requests(
            reasoning_comparison=mode == "reasoning",
            model_comparison=mode == "model",
            validation_comparison=mode == "validation",
            mini_reasoning_comparison=mode == "mini_reasoning",
            fresh_comparison=True,
        )


@pytest.mark.parametrize("mode", ["reasoning", "model", "validation"])
def test_mini_reasoning_is_exclusive_with_other_modes(mode: str) -> None:
    with pytest.raises(EvaluationPreflightError, match="mutually exclusive"):
        prepare_requests(
            reasoning_comparison=mode == "reasoning",
            model_comparison=mode == "model",
            validation_comparison=mode == "validation",
            mini_reasoning_comparison=True,
        )


@pytest.mark.asyncio
async def test_reasoning_profiles_are_required_before_any_model_or_budget_call() -> None:
    model, ledger = AsyncMock(), AsyncMock()
    with pytest.raises(EvaluationPreflightError, match="profile gateways"):
        await evaluate(prepare_requests(reasoning_comparison=True), model=model, ledger=ledger)
    assert model.reply.call_count == ledger.reserve.call_count == ledger.periods.call_count == 0


@pytest.mark.asyncio
async def test_comparison_refuses_a_changed_current_baseline_before_gateway_construction(
    monkeypatch: MonkeyPatch,
) -> None:
    settings = Settings(
        _env_file=None, openai_api_key="fake-baseline-key", openai_reasoning_effort="low"
    )
    monkeypatch.setattr(config, "get_settings", lambda: settings)

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("An unreviewed comparison baseline constructed a gateway")

    monkeypatch.setattr(chat_model, "OpenAIConversationModel", forbidden)
    with pytest.raises(EvaluationPreflightError, match="current none baseline"):
        await evaluation_module._live(
            prepare_requests(reasoning_comparison=True),
            approval_id="example-wrong-baseline",
            budget=Decimal("0.10"),
            context_bytes=24_000,
        )


@pytest.mark.asyncio
async def test_all_comparison_endpoints_are_checked_before_the_first_model_call(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    settings = Settings(_env_file=None, openai_api_key="fake-endpoint-key")
    monkeypatch.setattr(config, "get_settings", lambda: settings)
    monkeypatch.setattr(evaluation_module, "__file__", str(tmp_path / "scripts" / "evaluate.py"))
    clients: list[OpenAIConversationModel] = []
    parse = AsyncMock(return_value=response(settings))

    def gateway_factory(
        configured: Settings, *, ledger: SqlAlchemyCostLedger
    ) -> OpenAIConversationModel:
        gateway = OpenAIConversationModel(configured, ledger=ledger)
        if configured.effective_operation_chat_reasoning_effort == "low":
            gateway._client.base_url = "https://unapproved.example/v1/"
        monkeypatch.setattr(gateway._client.responses, "parse", parse)
        clients.append(gateway)
        return gateway

    monkeypatch.setattr(chat_model, "OpenAIConversationModel", gateway_factory)
    requests = prepare_requests(reasoning_comparison=True)
    with pytest.raises(EvaluationPreflightError, match="standard OpenAI endpoint"):
        await evaluation_module._live(
            requests,
            approval_id="example-low-endpoint",
            budget=Decimal("0.10"),
            context_bytes=24_000,
        )
    assert parse.call_count == 0
    assert len(clients) == 2 and all(client._client.is_closed() for client in clients)
    directory = tmp_path / "output/operation-chat-evaluation/example-low-endpoint"
    assert (
        directory.joinpath("plan.json").exists() and not directory.joinpath("results.json").exists()
    )
    database = OperationDatabase(f"sqlite+aiosqlite:///{directory / 'budget.db'}")
    try:
        ledger = SqlAlchemyCostLedger(
            database,
            clock=Clock(),
            limits=evaluation_limits(requests, approved_usd=Decimal("0.10")),
        )
        periods = await ledger.periods()
        assert len(periods) == 2 and all(period.usage == ResourceUsage() for period in periods)
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_comparison_uses_isolated_operational_baseline_not_public_model(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    rates = evaluation_module.RATES
    settings = Settings(
        _env_file=None,
        openai_api_key="fake-isolation-key",
        openai_model="public-reviewed-model",
        openai_reasoning_effort="high",
        operation_chat_model="gpt-5.4-nano",
        operation_chat_reasoning_effort="none",
        operation_chat_rate_model=rates.model,
        operation_chat_input_usd_per_million=rates.input_usd_per_million,
        operation_chat_cached_input_usd_per_million=rates.cached_input_usd_per_million,
        operation_chat_cache_write_usd_per_million=rates.cache_write_usd_per_million,
        operation_chat_output_usd_per_million=rates.output_usd_per_million,
    )
    monkeypatch.setattr(config, "get_settings", lambda: settings)
    monkeypatch.setattr(evaluation_module, "__file__", str(tmp_path / "scripts" / "evaluate.py"))
    clients: list[OpenAIConversationModel] = []
    parses: list[AsyncMock] = []

    def gateway_factory(
        configured: Settings, *, ledger: SqlAlchemyCostLedger
    ) -> OpenAIConversationModel:
        gateway = OpenAIConversationModel(configured, ledger=ledger)
        parse = AsyncMock(return_value=response(configured))
        monkeypatch.setattr(gateway._client.responses, "parse", parse)
        clients.append(gateway)
        parses.append(parse)
        return gateway

    async def forbidden_send(*args: object, **kwargs: object) -> httpx.Response:
        raise AssertionError("Isolated operational comparison reached the network")

    monkeypatch.setattr(chat_model, "OpenAIConversationModel", gateway_factory)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden_send)
    report = await evaluation_module._live(
        prepare_requests(model_comparison=True),
        approval_id="example-isolated-baseline",
        budget=Decimal("0.20"),
        context_bytes=24_000,
    )
    assert report["all_requests_completed"] is True
    assert len(clients) == 2 and all(client._client.is_closed() for client in clients)
    assert all(client._settings.openai_model == "public-reviewed-model" for client in clients)
    assert all(client._settings.openai_reasoning_effort == "high" for client in clients)
    assert parses[0].call_args.kwargs["model"] == "gpt-5.4-nano"
    assert parses[1].call_args.kwargs["model"] == "gpt-5.4-mini"
    assert all(parse.call_args.kwargs["reasoning"] == {"effort": "none"} for parse in parses)
    assert settings.effective_operation_chat_model == "gpt-5.4-nano"
    assert settings.effective_operation_chat_reasoning_effort == "none"
    assert settings.effective_audio_moderation_model == "public-reviewed-model"


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_candidate", [False, True])
@pytest.mark.parametrize("mode", ["reasoning", "model", "validation", "mini_reasoning"])
async def test_live_comparison_with_fake_sdk_preserves_settings_and_stops_on_error(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    fail_candidate: bool,
    mode: Literal["reasoning", "model", "validation", "mini_reasoning"],
) -> None:
    model_comparison = mode != "reasoning"
    mini_only = mode == "mini_reasoning"
    settings = Settings(_env_file=None, openai_api_key="fake-comparison-key")
    monkeypatch.setattr(config, "get_settings", lambda: settings)
    monkeypatch.setattr(evaluation_module, "__file__", str(tmp_path / "scripts" / "evaluate.py"))
    clients: list[OpenAIConversationModel] = []
    parses: list[AsyncMock] = []

    def gateway_factory(
        configured: Settings, *, ledger: SqlAlchemyCostLedger
    ) -> OpenAIConversationModel:
        gateway = OpenAIConversationModel(configured, ledger=ledger)
        parse = AsyncMock(
            return_value=response(configured),
            side_effect=TimeoutError("fake-comparison-secret")
            if fail_candidate and len(clients) == 1
            else None,
        )
        monkeypatch.setattr(gateway._client.responses, "parse", parse)
        clients.append(gateway)
        parses.append(parse)
        return gateway

    async def forbidden_send(*args: object, **kwargs: object) -> httpx.Response:
        raise AssertionError("Fake comparison reached the network")

    monkeypatch.setattr(chat_model, "OpenAIConversationModel", gateway_factory)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden_send)
    requests = prepare_requests(
        reasoning_comparison=mode == "reasoning",
        model_comparison=mode == "model",
        validation_comparison=mode == "validation",
        mini_reasoning_comparison=mini_only,
    )
    report = await evaluation_module._live(
        requests,
        approval_id="example-reasoning",
        budget=Decimal("0.35") if mini_only else Decimal("0.20"),
        context_bytes=24_000,
    )
    assert settings.openai_reasoning_effort == "none" and settings.openai_model == "gpt-5.4-nano"
    assert (
        settings.operation_chat_model is None and settings.operation_chat_reasoning_effort is None
    )
    assert len(clients) == 2 and all(client._client.is_closed() for client in clients)
    assert all(client._settings.openai_model == settings.openai_model for client in clients)
    assert all(
        client._settings.openai_reasoning_effort == settings.openai_reasoning_effort
        for client in clients
    )
    assert all(client._client.max_retries == 0 for client in clients)
    profiles = (
        [("gpt-5.4-mini", "none"), ("gpt-5.4-mini", "low")]
        if mini_only
        else [("gpt-5.4-nano", "none"), ("gpt-5.4-mini", "none")]
        if model_comparison
        else [("gpt-5.4-nano", "none"), ("gpt-5.4-nano", "low")]
    )
    for parse, (model, effort) in zip(parses, profiles, strict=True):
        assert parse.call_count == (1 if fail_candidate else 8)
        assert all(call.kwargs["reasoning"] == {"effort": effort} for call in parse.call_args_list)
        assert all(call.kwargs["model"] == model for call in parse.call_args_list)
        assert all(call.kwargs["store"] is False for call in parse.call_args_list)
    assert report["product_source_calls"] == report["operational_actions"] == 0
    assert report["all_requests_completed"] is (not fail_candidate)
    result_file = tmp_path / "output/operation-chat-evaluation/example-reasoning/results.json"
    saved = json.loads(result_file.read_text())
    assert "fake-comparison" not in result_file.read_text()
    assert len(saved["results"]) == (2 if fail_candidate else 16)
    assert saved["runtime_model_settings"]["comparison_reasoning_efforts"] == (
        ["none"] if model_comparison and not mini_only else ["none", "low"]
    )
    assert saved["runtime_model_settings"]["comparison_models"] == (
        ["gpt-5.4-mini"]
        if mini_only
        else ["gpt-5.4-mini", "gpt-5.4-nano"]
        if model_comparison
        else ["gpt-5.4-nano"]
    )
    assert saved["runtime_model_settings"]["working_baseline_model"] == "gpt-5.4-nano"
    if fail_candidate:
        assert saved["results"][-1]["failure_kind"] == "TimeoutError"
        rates = evaluation_module.MINI_RATES if mini_only else evaluation_module.RATES
        known = rates.actual_microusd(
            input_tokens=200, output_tokens=100, cached_tokens=40, cache_write_tokens=30
        )
        expected = known + requests[1].cost_reservation_microusd
        assert saved["periods"][-1]["usage"]["llm_microusd"] == expected


@pytest.mark.parametrize("arguments", [["--live"], ["--live", "--approval-id", "example-approved"]])
def test_live_opt_in_without_explicit_budget_never_reaches_preflight(arguments: list[str]) -> None:
    with pytest.raises(SystemExit) as failure:
        main(arguments)
    assert failure.value.code == 2


@pytest.mark.parametrize("budget", ["0", "-1", "0.01", "0.51", "NaN", "Infinity"])
def test_insufficient_invalid_or_excess_budget_is_refused_before_credentials(
    monkeypatch: MonkeyPatch, capsys: CaptureFixture[str], budget: str
) -> None:
    def forbidden() -> Settings:
        raise AssertionError("Rejected batch read settings before validating its budget")

    monkeypatch.setattr(config, "get_settings", forbidden)
    assert (
        main(["--live", "--approval-id", "example-rejected", "--approved-budget-usd", budget]) == 2
    )
    assert "Evaluation refused" in capsys.readouterr().err


def test_batch_reservation_has_no_product_source_allowance_and_attempt_is_one_use(
    tmp_path: Path,
) -> None:
    requests = prepare_requests()
    limits = evaluation_limits(requests, approved_usd=Decimal("0.50"))
    assert limits.daily == limits.monthly
    assert limits.daily.llm_calls == limits.daily.provider_requests == 16
    assert limits.daily.document_reads == limits.daily.data_microusd == 0
    assert limits.daily.llm_microusd == 500_000
    directory = tmp_path / "example-batch"
    _record_attempt(directory, requests, context_bytes=24_000)
    before = directory.joinpath("plan.json").read_bytes()
    with pytest.raises(FileExistsError):
        _record_attempt(directory, requests, context_bytes=24_000)
    assert directory.joinpath("plan.json").read_bytes() == before
    crashed = tmp_path / "example-crashed-before-manifest"
    crashed.mkdir()
    with pytest.raises(FileExistsError):
        _record_attempt(crashed, requests, context_bytes=24_000)


@pytest.mark.parametrize("approval_id", ["../escape", "unapproved/name", ""])
def test_unsafe_batch_identifier_is_refused_before_loading_credentials(
    monkeypatch: MonkeyPatch, capsys: CaptureFixture[str], approval_id: str
) -> None:
    def forbidden() -> Settings:
        raise AssertionError("Unsafe batch label reached settings")

    monkeypatch.setattr(config, "get_settings", forbidden)
    assert main(["--live", "--approval-id", approval_id, "--approved-budget-usd", "0.50"]) == 2
    assert "Approval identifier" in capsys.readouterr().err


def test_different_current_model_is_not_silently_selected_for_the_reviewed_batch(
    monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    settings = Settings(_env_file=None, openai_api_key="fake-qa-key", openai_model="fake-other")
    monkeypatch.setattr(config, "get_settings", lambda: settings)

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("An unreviewed model was constructed")

    monkeypatch.setattr(chat_model, "OpenAIConversationModel", forbidden)
    assert (
        main(["--live", "--approval-id", "example-other-model", "--approved-budget-usd", "0.50"])
        == 2
    )
    assert "does not match" in capsys.readouterr().err


def test_different_operational_effort_is_not_used_for_a_none_baseline_plan(
    monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    settings = Settings(
        _env_file=None,
        openai_api_key="fake-qa-key",
        operation_chat_reasoning_effort="low",
    )
    monkeypatch.setattr(config, "get_settings", lambda: settings)

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("An unreviewed reasoning profile constructed an SDK client")

    monkeypatch.setattr(chat_model, "OpenAIConversationModel", forbidden)
    assert (
        main(["--live", "--approval-id", "example-other-effort", "--approved-budget-usd", "0.49"])
        == 2
    )
    assert "does not match" in capsys.readouterr().err


@pytest.mark.asyncio
@pytest.mark.parametrize("approved_endpoint", [False, True])
async def test_complete_opt_in_path_with_fake_sdk_is_isolated_and_cannot_repeat(
    tmp_path: Path, monkeypatch: MonkeyPatch, approved_endpoint: bool
) -> None:
    settings = Settings(_env_file=None, openai_api_key="fake-qa-integration-key")
    monkeypatch.setattr(config, "get_settings", lambda: settings)
    # Relocate only this diagnostic script's generated artifacts to the fixture.
    monkeypatch.setattr(evaluation_module, "__file__", str(tmp_path / "scripts" / "evaluate.py"))
    parse = AsyncMock(return_value=response(settings))
    clients: list[OpenAIConversationModel] = []

    def gateway_factory(
        settings: Settings, *, ledger: SqlAlchemyCostLedger
    ) -> OpenAIConversationModel:
        gateway = OpenAIConversationModel(settings, ledger=ledger)
        if not approved_endpoint:
            gateway._client.base_url = "https://unapproved.example/v1/"
        monkeypatch.setattr(gateway._client.responses, "parse", parse)
        clients.append(gateway)
        return gateway

    async def forbidden_send(*args: object, **kwargs: object) -> httpx.Response:
        raise AssertionError("Synthetic end-to-end evaluation reached the network")

    monkeypatch.setattr(chat_model, "OpenAIConversationModel", gateway_factory)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden_send)
    requests = prepare_requests()
    directory = tmp_path / "output" / "operation-chat-evaluation" / "example-e2e"
    if approved_endpoint:
        report = await evaluation_module._live(
            requests, approval_id="example-e2e", budget=Decimal("0.50"), context_bytes=24_000
        )
        assert report["all_requests_completed"] is True
        assert report["quality_status"] == "manual_review_pending"
        assert report["product_source_calls"] == report["operational_actions"] == 0
        assert parse.call_count == 16
        assert directory.joinpath("results.json").is_file()
        assert "fake-qa-integration-key" not in directory.joinpath("results.json").read_text()
    else:
        with pytest.raises(EvaluationPreflightError, match="standard OpenAI endpoint"):
            await evaluation_module._live(
                requests, approval_id="example-e2e", budget=Decimal("0.50"), context_bytes=24_000
            )
        assert parse.call_count == 0
        assert not directory.joinpath("results.json").exists()
    assert directory.joinpath("plan.json").is_file()
    assert directory.joinpath("budget.db").is_file()
    assert len(clients) == 1 and clients[0]._client.is_closed()
    with pytest.raises(FileExistsError):
        await evaluation_module._live(
            requests, approval_id="example-e2e", budget=Decimal("0.50"), context_bytes=24_000
        )
    assert len(clients) == 1 and parse.call_count == (16 if approved_endpoint else 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("fail", [False, True])
async def test_paired_runner_uses_real_admission_with_fake_sdk_and_never_grades_quality(
    tmp_path: Path, monkeypatch: MonkeyPatch, fail: bool
) -> None:
    requests = prepare_requests()
    database = OperationDatabase(f"sqlite+aiosqlite:///{tmp_path / 'evaluation.db'}")
    await database.create_schema()
    ledger = SqlAlchemyCostLedger(
        database,
        clock=Clock(),
        limits=evaluation_limits(requests, approved_usd=Decimal("0.50")),
    )
    settings = Settings(_env_file=None, openai_api_key=SecretStr("fake-qa-key"))
    gateway = OpenAIConversationModel(settings, ledger=ledger)
    parse = AsyncMock(
        side_effect=TimeoutError("fake-provider-secret-never-log") if fail else None,
        return_value=response(settings),
    )
    monkeypatch.setattr(gateway._client.responses, "parse", parse)
    try:
        results = await evaluate(requests, model=gateway, ledger=ledger)
        assert all(result.quality_status == "manual_review_pending" for result in results)
        usage = (await ledger.periods())[-1].usage
        if fail:
            assert len(results) == 1 and results[0].status == "failed"
            assert results[0].failure_kind == "TimeoutError"
            assert "fake-provider-secret-never-log" not in results[0].model_dump_json()
            assert usage.llm_microusd == requests[0].cost_reservation_microusd
            assert parse.call_count == 1  # No retry and no next context variant.
        else:
            assert len(results) == parse.call_count == 16
            assert all(result.status == "completed" for result in results)
            assert usage.llm_microusd == 16 * 158  # Fake receipts, not live evaluation spend.
        assert usage.document_reads == 0 and usage.provider_requests == usage.llm_calls
        assert results[-1].current_month_reserved_or_known_microusd == usage.llm_microusd
        assert gateway._client.max_retries == 0
        assert all(call.kwargs["store"] is False for call in parse.call_args_list)
    finally:
        await gateway.close()
        await database.dispose()


@pytest.mark.asyncio
async def test_cancelled_evaluation_retains_first_attempt_and_does_not_continue(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    requests = prepare_requests()
    database = OperationDatabase(f"sqlite+aiosqlite:///{tmp_path / 'cancel-qa.db'}")
    await database.create_schema()
    ledger = SqlAlchemyCostLedger(
        database,
        clock=Clock(),
        limits=evaluation_limits(requests, approved_usd=Decimal("0.50")),
    )
    gateway = OpenAIConversationModel(
        Settings(_env_file=None, openai_api_key="fake-qa-key"), ledger=ledger
    )
    parse = AsyncMock(side_effect=asyncio.CancelledError())
    monkeypatch.setattr(gateway._client.responses, "parse", parse)
    try:
        with pytest.raises(asyncio.CancelledError):
            await evaluate(requests, model=gateway, ledger=ledger)
        assert parse.call_count == 1
        usage = (await ledger.periods())[-1].usage
        assert usage.llm_calls == 1
        assert usage.llm_microusd == requests[0].cost_reservation_microusd
    finally:
        await gateway.close()
        await database.dispose()


def test_unsupported_context_range_fails_locally() -> None:
    with pytest.raises(EvaluationPreflightError):
        prepare_requests(maximum_context_bytes=8191)
