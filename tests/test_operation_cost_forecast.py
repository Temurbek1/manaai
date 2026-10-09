import json
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.mana_operation_ai.application.cost_forecast import ForecastWorkload, forecast
from app.mana_operation_ai.domain.cost_control import LlmRateCard
from scripts.operation_cost_forecast import main


def test_forecast_reproduces_planning_workload_without_activating_anything() -> None:
    report = forecast(ForecastWorkload())
    assert report["live_provider_calls"] == 0
    assert report["llm_calls_per_day_capacity"] == 53
    assert report["data_only_usd"] == {
        "daily": "0.058610",
        "monthly_30_days": "1.758307",
        "yearly_365_days": "21.392734",
    }
    assert report["data_only_with_reserve_usd"] == {
        "daily": "0.073263",
        "monthly_30_days": "2.197884",
        "yearly_365_days": "26.740917",
    }
    assert report["total_without_reserve_usd"] == {
        "daily": "2.278610",
        "monthly_30_days": "68.358307",
        "yearly_365_days": "831.692734",
    }
    assert report["total_with_reserve_usd"] == {
        "daily": "2.848263",
        "monthly_30_days": "85.447884",
        "yearly_365_days": "1039.615917",
    }


def test_forecast_one_application_reduces_only_scheduled_capacity() -> None:
    report = forecast(ForecastWorkload(products=1))
    items = report["line_items_usd"]
    assert isinstance(items, dict)
    assert items["scheduled_analysis_capacity"]["monthly_30_days"] == "16.800000"
    assert items["interactive_analysis_capacity"]["monthly_30_days"] == "24.000000"
    assert report["data_only_usd"] == forecast(ForecastWorkload())["data_only_usd"]


def test_forecast_read_and_transfer_components_scale_independently() -> None:
    report = forecast(ForecastWorkload(average_response_bytes_per_document=0))
    items = report["line_items_usd"]
    assert isinstance(items, dict)
    assert Decimal(items["firestore_payload_transfer"]["daily"]) == 0
    assert Decimal(items["firestore_document_reads"]["daily"]) == Decimal("0.03")
    with pytest.raises(ValidationError):
        ForecastWorkload(firestore_reads_per_day=-1)


def test_explicit_chat_profile_has_no_invented_scheduled_llm_calls_or_cache_discount() -> None:
    rates = LlmRateCard(
        model="gpt-5.4",
        input_usd_per_million="2.50",
        cached_input_usd_per_million="0.25",
        cache_write_usd_per_million="2.50",
        output_usd_per_million="15.00",
    )
    report = forecast(
        ForecastWorkload(
            analyses_per_product_refresh=0,
            complex_calls_per_day=0,
            chat_output_tokens=1536,
        ),
        ordinary_rate_card=rates,
    )
    assert report["live_provider_calls"] == 0
    assert report["llm_calls_per_day_capacity"] == 20
    assert report["ordinary_rate_card_basis"] == "explicit_input_not_independently_verified"
    items = report["line_items_usd"]
    assert isinstance(items, dict)
    assert items["scheduled_analysis_capacity"]["daily"] == "0.000000"
    assert items["complex_analysis_capacity"]["daily"] == "0.000000"
    assert items["interactive_analysis_capacity"] == {
        "daily": "0.860800",
        "monthly_30_days": "25.824000",
        "yearly_365_days": "314.192000",
    }
    assert report["total_with_reserve_usd"] == {
        "daily": "1.149263",
        "monthly_30_days": "34.477884",
        "yearly_365_days": "419.480917",
    }
    assert forecast(ForecastWorkload())["llm_calls_per_day_capacity"] == 53


def test_forecast_cli_profile_is_fully_offline(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import httpx

    import app.core.config as config

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("Offline forecast touched credentials or network")

    monkeypatch.setattr(config, "get_settings", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)
    main(
        [
            "--analyses-per-product-refresh",
            "0",
            "--complex-calls-per-day",
            "0",
            "--chat-output-tokens",
            "1536",
            "--ordinary-rate-card",
            '{"model":"hypothetical","input_usd_per_million":"2.50",'
            '"cached_input_usd_per_million":"0.25","cache_write_usd_per_million":"2.50",'
            '"output_usd_per_million":"15.00"}',
        ]
    )
    result = json.loads(capsys.readouterr().out)
    assert result["live_provider_calls"] == 0 and result["llm_calls_per_day_capacity"] == 20
    assert result["rate_cards_not_runtime_configuration"]["ordinary"]["model"] == "hypothetical"
    assert result["total_with_reserve_usd"]["monthly_30_days"] == "34.477884"


def test_full_profile_at_original_future_capacity_exceeds_the_planning_reference() -> None:
    rates = LlmRateCard(
        model="gpt-5.4",
        input_usd_per_million="2.50",
        cached_input_usd_per_million="0.25",
        cache_write_usd_per_million="2.50",
        output_usd_per_million="15.00",
    )
    report = forecast(ForecastWorkload(chat_output_tokens=1536), ordinary_rate_card=rates)
    assert report["llm_calls_per_day_capacity"] == 53
    assert report["total_with_reserve_usd"] == {
        "daily": "3.324263",
        "monthly_30_days": "99.727884",
        "yearly_365_days": "1213.355917",
    }
    total = report["total_with_reserve_usd"]
    assert isinstance(total, dict)
    assert Decimal(total["monthly_30_days"]) > Decimal("90")


@pytest.mark.parametrize(
    "scheduled,complex_calls,call_count,daily,monthly,yearly",
    [
        (0, 0, 20, "1.085263", "32.557884", "396.120917"),
        (4, 1, 53, "2.860263", "85.807884", "1043.995917"),
    ],
)
def test_sol_forecast_preserves_explicit_load_and_does_not_hide_data_reserve(
    scheduled: int, complex_calls: int, call_count: int, daily: str, monthly: str, yearly: str
) -> None:
    rates = LlmRateCard(
        model="gpt-6.1-sol",
        input_usd_per_million="2.00",
        cached_input_usd_per_million="0.10",
        cache_write_usd_per_million="2.50",
        output_usd_per_million="10.00",
    )
    report = forecast(
        ForecastWorkload(
            analyses_per_product_refresh=scheduled,
            complex_calls_per_day=complex_calls,
            chat_output_tokens=2048,
        ),
        ordinary_rate_card=rates,
    )
    assert report["live_provider_calls"] == 0
    assert report["llm_calls_per_day_capacity"] == call_count
    assert report["total_with_reserve_usd"] == {
        "daily": daily,
        "monthly_30_days": monthly,
        "yearly_365_days": yearly,
    }
    data = report["data_only_with_reserve_usd"]
    assert isinstance(data, dict)
    assert data["monthly_30_days"] == "2.197884"
    assert Decimal(data["monthly_30_days"]) > Decimal("2")
    models = report["rate_cards_not_runtime_configuration"]
    assert isinstance(models, dict)
    assert models["ordinary"] == rates.model_dump(mode="json")


def test_goals_add_steps_without_inventing_new_data_reads_or_changing_legacy_load() -> None:
    original = forecast(ForecastWorkload())
    report = forecast(ForecastWorkload(goals_per_day=1))
    assert report["schema_version"] == "operation-cost-forecast-v2"
    assert report["live_provider_calls"] == 0
    assert report["llm_calls_per_day_capacity"] == 59
    assert report["data_only_usd"] == original["data_only_usd"]
    items = report["line_items_usd"]
    assert isinstance(items, dict)
    old_items = original["line_items_usd"]
    assert isinstance(old_items, dict)
    for key, value in old_items.items():
        if key != "goal_analysis_capacity":
            assert items[key] == value
    assert items["goal_analysis_capacity"] == {
        "daily": "0.365760",
        "monthly_30_days": "10.972800",
        "yearly_365_days": "133.502400",
    }
    assert report["total_with_reserve_usd"] == {
        "daily": "3.305463",
        "monthly_30_days": "99.163884",
        "yearly_365_days": "1206.493917",
    }
    assert report["goal_capacity"] == {
        "calls_per_day": 6,
        "cost_per_step_microusd": 60_960,
        "cost_per_goal_microusd": 365_760,
        "fits_per_goal_admission_budget": True,
        "goal_admission_envelope_usd": {
            "daily": "0.500000",
            "monthly_30_days": "15.000000",
            "yearly_365_days": "182.500000",
        },
        "input_tokens_per_day": 48_000,
        "output_tokens_per_day": 24_576,
    }
    assert report["planning_reference_comparison"] == {
        "data_with_reserve_fits_2_usd": False,
        "total_with_reserve_fits_90_usd": False,
    }


def test_goal_capacity_is_not_clipped_to_an_insufficient_budget() -> None:
    report = forecast(
        ForecastWorkload(
            goals_per_day=2,
            goal_input_tokens_per_step=64_000,
            chat_calls_per_day=0,
            analyses_per_product_refresh=0,
            complex_calls_per_day=0,
            firestore_reads_per_day=0,
        )
    )
    capacity = report["goal_capacity"]
    assert isinstance(capacity, dict)
    assert capacity["cost_per_goal_microusd"] == 1_205_760
    assert capacity["fits_per_goal_admission_budget"] is False
    items = report["line_items_usd"]
    assert isinstance(items, dict)
    assert items["goal_analysis_capacity"]["daily"] == "2.411520"
    assert report["total_without_reserve_usd"] == {
        "daily": "2.411520",
        "monthly_30_days": "72.345600",
        "yearly_365_days": "880.204800",
    }


def test_goal_rate_card_is_separate_and_envelope_is_not_added_twice() -> None:
    rates = LlmRateCard(
        model="hypothetical-goal",
        input_usd_per_million="1",
        cached_input_usd_per_million="0.1",
        cache_write_usd_per_million="1.5",
        output_usd_per_million="3",
    )
    report = forecast(
        ForecastWorkload(
            goals_per_day=2,
            goal_steps_per_goal=3,
            goal_input_tokens_per_step=1000,
            goal_output_tokens_per_step=500,
            chat_calls_per_day=0,
            analyses_per_product_refresh=0,
            complex_calls_per_day=0,
            firestore_reads_per_day=0,
        ),
        goal_rate_card=rates,
    )
    assert report["llm_calls_per_day_capacity"] == 6
    assert report["goal_rate_card_basis"] == "explicit_input_not_independently_verified"
    cards = report["rate_cards_not_runtime_configuration"]
    assert isinstance(cards, dict)
    assert cards["goals"] == rates.model_dump(mode="json")
    assert cards["ordinary"]["model"] == "gpt-6.1-sol"
    assert report["total_without_reserve_usd"] == {
        "daily": "0.018000",
        "monthly_30_days": "0.540000",
        "yearly_365_days": "6.570000",
    }
    assert report["total_with_reserve_usd"] == {
        "daily": "0.022500",
        "monthly_30_days": "0.675000",
        "yearly_365_days": "8.212500",
    }
    assert report["planning_reference_comparison"] == {
        "data_with_reserve_fits_2_usd": True,
        "total_with_reserve_fits_90_usd": True,
    }


@pytest.mark.parametrize(
    "goals,calls,daily,monthly,yearly,fits_reference",
    [
        (0, 37, "2.148263", "64.447884", "784.115917", True),
        (1, 43, "2.605463", "78.163884", "950.993917", True),
        (3, 55, "3.519863", "105.595884", "1284.749917", False),
    ],
)
def test_mana_only_capacity_preserves_data_volume_and_all_per_request_work(
    goals: int, calls: int, daily: str, monthly: str, yearly: str, fits_reference: bool
) -> None:
    report = forecast(ForecastWorkload(products=1, goals_per_day=goals))
    baseline = forecast(ForecastWorkload(goals_per_day=goals))
    assert report["live_provider_calls"] == 0
    assert report["llm_calls_per_day_capacity"] == calls
    assert report["total_with_reserve_usd"] == {
        "daily": daily,
        "monthly_30_days": monthly,
        "yearly_365_days": yearly,
    }
    assert report["data_only_with_reserve_usd"] == baseline["data_only_with_reserve_usd"]
    assert report["goal_capacity"] == baseline["goal_capacity"]
    items = report["line_items_usd"]
    old_items = baseline["line_items_usd"]
    assert isinstance(items, dict) and isinstance(old_items, dict)
    assert items["scheduled_analysis_capacity"]["monthly_30_days"] == "16.800000"
    assert items["interactive_analysis_capacity"] == old_items["interactive_analysis_capacity"]
    assert items["complex_analysis_capacity"] == old_items["complex_analysis_capacity"]
    assert report["planning_reference_comparison"] == {
        "data_with_reserve_fits_2_usd": False,
        "total_with_reserve_fits_90_usd": fits_reference,
    }


def test_saved_aggregate_and_ga4_only_capacity_does_not_price_disabled_firestore_reads() -> None:
    report = forecast(
        ForecastWorkload(
            products=1,
            firestore_reads_per_day=0,
            analyses_per_product_refresh=0,
            complex_calls_per_day=0,
            chat_output_tokens=2048,
            goals_per_day=1,
        )
    )
    assert report["llm_calls_per_day_capacity"] == 26
    items = report["line_items_usd"]
    assert isinstance(items, dict)
    for name in (
        "firestore_document_reads",
        "firestore_payload_transfer",
        "scheduled_analysis_capacity",
        "complex_analysis_capacity",
    ):
        assert items[name]["daily"] == "0.000000"
    data_cost = report["data_only_with_reserve_usd"]
    assert isinstance(data_cost, dict)
    assert data_cost["monthly_30_days"] == "0.000000"
    assert report["total_with_reserve_usd"] == {
        "daily": "1.469200",
        "monthly_30_days": "44.076000",
        "yearly_365_days": "536.258000",
    }
    goal_capacity = report["goal_capacity"]
    assert isinstance(goal_capacity, dict)
    assert goal_capacity["fits_per_goal_admission_budget"] is True
    assert "Backend database work" in str(report["excluded_costs"])


def test_goal_cli_forecast_never_loads_settings_or_connects_to_providers(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import httpx
    import openai

    import app.core.config as config

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("Offline Goals forecast touched credentials or network")

    monkeypatch.setattr(config, "get_settings", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)
    monkeypatch.setattr(openai, "AsyncOpenAI", forbidden)
    main(
        [
            "--goals-per-day",
            "1",
            "--goal-steps-per-goal",
            "3",
            "--goal-input-tokens-per-step",
            "1000",
            "--goal-output-tokens-per-step",
            "500",
            "--goal-budget-microusd",
            "100000",
            "--goal-rate-card",
            '{"model":"hypothetical-goal","input_usd_per_million":"1",'
            '"cached_input_usd_per_million":"0.1","cache_write_usd_per_million":"1.5",'
            '"output_usd_per_million":"3"}',
        ]
    )
    result = json.loads(capsys.readouterr().out)
    assert result["live_provider_calls"] == 0
    assert result["llm_calls_per_day_capacity"] == 56
    assert result["goal_capacity"]["cost_per_goal_microusd"] == 9000
    assert result["goal_capacity"]["goal_admission_envelope_usd"]["daily"] == "0.100000"


@pytest.mark.parametrize(
    "arguments",
    [
        ["--ordinary-rate-card", "not-json"],
        ["--ordinary-rate-card", '{"model":"incomplete"}'],
        ["--analyses-per-product-refresh", "5"],
        ["--chat-output-tokens", "-1"],
        ["--goals-per-day", "-1"],
        ["--goal-steps-per-goal", "2"],
        ["--goal-steps-per-goal", "13"],
        ["--goal-input-tokens-per-step", "272001"],
        ["--goal-output-tokens-per-step", "8193"],
        ["--goal-budget-microusd", "0"],
        ["--goal-rate-card", "not-json"],
        ["--goal-rate-card", '{"model":"incomplete"}'],
    ],
)
def test_invalid_forecast_inputs_are_controlled_errors(arguments: list[str]) -> None:
    with pytest.raises(SystemExit) as error:
        main(arguments)
    assert error.value.code == 2
