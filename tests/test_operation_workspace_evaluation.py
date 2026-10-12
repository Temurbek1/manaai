"""The workspace quality harness is offline by default and cannot resume a paid party."""

import json
import sys
from pathlib import Path

import pytest
from pytest import MonkeyPatch

from scripts import operation_workspace_evaluate as benchmark


def test_pinned_workspace_cases_cover_routing_grounding_and_full_objective() -> None:
    cases = benchmark.cases()
    assert len(cases) == 8 and len({case.case_id for case in cases}) == 8
    assert sum(case.expected_action == "start_goal" for case in cases) == 2
    full = [case for case in cases if case.full_goal]
    assert len(full) == 1 and "Нужен полный анализ" in full[0].message
    assert "verified payment" in full[0].report_text
    assert any("not complete the full objective" in check for check in full[0].review_checks)
    assert sum(case.product == "360rec" for case in cases) == 1
    assert all(case.review_checks for case in cases)


def test_cli_defaults_to_pinned_plan_without_settings_sdk_or_io(
    monkeypatch: MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def forbidden() -> None:
        raise AssertionError("Offline inspection must not load credentials or SDK clients")

    monkeypatch.setattr(benchmark, "get_settings", forbidden)
    monkeypatch.setattr(sys, "argv", ["operation_workspace_evaluate.py"])
    benchmark.main()
    result = json.loads(capsys.readouterr().out)
    assert len(result["cases"]) == 8
    assert result["max_calls"] == 16 and result["cap_microusd"] == 490000
    assert result["sources"] == 0


async def test_an_attempted_paid_output_cannot_be_restarted(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    def forbidden() -> None:
        raise AssertionError("An existing attempt must stop before model construction")

    monkeypatch.setattr(benchmark, "get_settings", forbidden)
    with pytest.raises(FileExistsError):
        await benchmark.evaluate(tmp_path)
