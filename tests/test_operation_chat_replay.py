import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from pytest import CaptureFixture, MonkeyPatch

import app.core.config as config
import app.mana_operation_ai.infrastructure.chat_model as chat_model
import scripts.operation_chat_replay as replay_module
from app.mana_operation_ai.application.chat_service import INSTRUCTIONS
from scripts.operation_chat_evaluate import prepare_requests
from scripts.operation_chat_replay import ReplayError, main, replay_archive

ARCHIVE = "synthetic-offline-replay"


def archive_fixture(
    directory: Path, *, paired: bool = False
) -> tuple[dict[str, Any], dict[str, Any]]:
    requests = (
        prepare_requests(fresh_comparison=True) if paired else prepare_requests(sol_quality=True)
    )
    plan = {
        "instructions": INSTRUCTIONS,
        "instructions_sha256": hashlib.sha256(INSTRUCTIONS.encode()).hexdigest(),
        "requests": [item.model_dump(mode="json") for item in requests],
    }
    results = {
        "approval_id": ARCHIVE,
        "all_requests_completed": True,
        "product_source_calls": 0,
        "operational_actions": 0,
        "results": [
            {
                "case_id": item.case_id,
                "variant": item.variant,
                "requested_model": item.requested_model,
                "requested_reasoning_effort": item.requested_reasoning_effort,
                "max_output_tokens": item.max_output_tokens,
                "context_sha256": item.context_sha256,
                "status": "completed",
                "answer": "Recorded synthetic reply; no semantic grade implied.",
                "plan": [],
                "next_action": "mana_parents"
                if "parent_confirmation" in item.case_id
                else "approvals"
                if "growth_approval" in item.case_id
                else "none",
                "latency_ms": 123.0,
                "model": item.requested_model,
                "input_tokens": 11,
                "output_tokens": 8,
                "current_month_reserved_or_known_microusd": 42,
                "review_checks": item.review_checks,
            }
            for item in requests
        ],
    }
    write_archive(directory, plan, results)
    return plan, results


def write_archive(directory: Path, plan: dict[str, Any], results: dict[str, Any]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    (directory / "results.json").write_text(json.dumps(results), encoding="utf-8")


@pytest.mark.parametrize("paired", [False, True])
@pytest.mark.parametrize("interval", [21600, 21601, 86400])
def test_replay_only_projects_current_policy_without_settings_io_or_archive_edits(
    tmp_path: Path, monkeypatch: MonkeyPatch, paired: bool, interval: int
) -> None:
    _, recorded = archive_fixture(tmp_path, paired=paired)
    original = {name: (tmp_path / name).read_bytes() for name in ("plan.json", "results.json")}

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("Offline replay touched credentials or a provider")

    monkeypatch.setattr(config, "get_settings", forbidden)
    monkeypatch.setattr(chat_model, "OpenAIConversationModel", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)
    report = asyncio.run(
        replay_archive(tmp_path, archive_id=ARCHIVE, parent_minimum_interval_seconds=interval)
    )
    assert (
        report["new_model_calls"]
        == report["product_source_calls"]
        == report["operational_actions"]
        == 0
    )
    assert report["new_cost_usd"] == "0"
    assert report["quality_status"] == "manual_review_pending"
    assert report["covered_boundary_records"] == (16 if paired else 8)
    assert report["plan_sha256"] == hashlib.sha256(original["plan.json"]).hexdigest()
    assert report["results_sha256"] == hashlib.sha256(original["results.json"]).hexdigest()
    records = report["records"]
    assert isinstance(records, list)
    for source, delivered in zip(recorded["results"], records, strict=True):
        turn = delivered["delivered_turn"]
        for key in ("answer", "plan", "next_action", "model", "input_tokens", "output_tokens"):
            assert turn[key] == source[key]
        assert delivered["recorded_latency_ms"] == source["latency_ms"]
        assert turn["analysis_requested"] is False
        if "parent_confirmation" in delivered["case_id"]:
            assert turn["read_confirmation"] == {
                "kind": "mana_parents",
                "product": "mana",
                "capability_key": "retention.parents.analyze",
                "confirmation_required": True,
                "admission_checks": ["access", "product_scope", "cooldown", "budget"],
                "minimum_interval_seconds": interval,
            }
        else:
            assert turn["read_confirmation"] is None
        if delivered["case_id"] == "fresh_changed_denominator":
            assert [item["refresh_status"] for item in turn["sources"]] == ["stale", "cached"]
        if delivered["case_id"] == "fresh_unknown_observation_time":
            assert turn["sources"][0]["collected_at"] is None
            assert turn["sources"][0]["refresh_status"] == "unknown"
    assert report == asyncio.run(
        replay_archive(tmp_path, archive_id=ARCHIVE, parent_minimum_interval_seconds=interval)
    )
    assert {name: (tmp_path / name).read_bytes() for name in original} == original


@pytest.mark.parametrize(
    "mutation",
    [
        "incomplete",
        "calls",
        "actions",
        "approval",
        "instruction",
        "partial",
        "duplicate",
        "order",
        "context_hash",
        "context_bytes",
        "context_changed",
        "review_checks",
        "model",
        "actual_model",
        "reasoning",
        "output_limit",
        "failed",
        "blank",
        "missing_usage",
        "invalid_usage",
        "negative_latency",
        "failure_kind",
    ],
)
def test_replay_refuses_incomplete_or_mismatched_boundary_evidence(
    tmp_path: Path, mutation: str
) -> None:
    plan, recorded = archive_fixture(tmp_path)
    request, result = plan["requests"][0], recorded["results"][0]
    if mutation == "incomplete":
        recorded["all_requests_completed"] = False
    elif mutation in {"calls", "actions"}:
        recorded["product_source_calls" if mutation == "calls" else "operational_actions"] = 1
    elif mutation == "approval":
        recorded["approval_id"] = "different-archive"
    elif mutation == "instruction":
        plan["instructions"] += "Changed prompt"
        plan["instructions_sha256"] = hashlib.sha256(plan["instructions"].encode()).hexdigest()
    elif mutation == "partial":
        plan["requests"].pop()
        recorded["results"].pop()
    elif mutation == "duplicate":
        plan["requests"][1] = request
        recorded["results"][1] = result
    elif mutation == "order":
        recorded["results"] = list(reversed(recorded["results"]))
    elif mutation == "context_hash":
        result["context_sha256"] = "bad-hash"
    elif mutation == "context_bytes":
        request["context_bytes"] += 1
    elif mutation == "context_changed":
        context = json.loads(request["context"])
        context["message"] = "Unreviewed self-consistent change"
        request["context"] = json.dumps(context)
        request["context_bytes"] = len(request["context"].encode())
        request["context_sha256"] = hashlib.sha256(request["context"].encode()).hexdigest()
        result["context_sha256"] = request["context_sha256"]
    elif mutation == "review_checks":
        request["review_checks"] = result["review_checks"] = ["Watered-down rubric"]
    elif mutation in {"model", "actual_model"}:
        result["requested_model" if mutation == "model" else "model"] = "gpt-5.4-mini"
    elif mutation == "reasoning":
        result["requested_reasoning_effort"] = "none"
    elif mutation == "output_limit":
        result["max_output_tokens"] = 1536
    elif mutation == "failed":
        result["status"] = "failed"
    elif mutation == "blank":
        result["answer"] = " "
    elif mutation == "missing_usage":
        result["input_tokens"] = None
    elif mutation == "invalid_usage":
        result["output_tokens"] = request["max_output_tokens"] + 1
    elif mutation == "negative_latency":
        result["latency_ms"] = -1
    elif mutation == "failure_kind":
        result["failure_kind"] = "APITimeoutError"
    write_archive(tmp_path, plan, recorded)
    with pytest.raises(ReplayError):
        asyncio.run(replay_archive(tmp_path, archive_id=ARCHIVE))


@pytest.mark.parametrize("interval", [21599, 86401])
def test_replay_refuses_out_of_range_interval_before_reading_files(
    tmp_path: Path, interval: int
) -> None:
    with pytest.raises(ReplayError, match="interval"):
        asyncio.run(
            replay_archive(tmp_path, archive_id=ARCHIVE, parent_minimum_interval_seconds=interval)
        )


def test_replay_refuses_oversize_and_linked_archive_files(tmp_path: Path) -> None:
    archive_fixture(tmp_path)
    (tmp_path / "plan.json").write_bytes(b" " * (replay_module.MAX_FILE_BYTES + 1))
    with pytest.raises(ReplayError, match="bounded"):
        asyncio.run(replay_archive(tmp_path, archive_id=ARCHIVE))
    archive_fixture(tmp_path)
    (tmp_path / "plan.json").rename(tmp_path / "original.json")
    (tmp_path / "plan.json").symlink_to(tmp_path / "original.json")
    with pytest.raises(ReplayError, match="linked"):
        asyncio.run(replay_archive(tmp_path, archive_id=ARCHIVE))


def test_cli_only_reads_local_safe_archive_and_sanitizes_errors(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        replay_module, "__file__", str(tmp_path / "scripts/operation_chat_replay.py")
    )
    directory = tmp_path / "output/operation-chat-evaluation" / ARCHIVE
    archive_fixture(directory)
    assert main(["--archive", ARCHIVE]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["covered_boundary_records"] == 8
    (directory / "results.json").write_text("private-invalid-archive-content", encoding="utf-8")
    assert main(["--archive", ARCHIVE]) == 2
    assert capsys.readouterr().err == "Replay refused: ValidationError\n"
    for arguments in (["--archive", "../../escape"], ["--archive", ARCHIVE, "--live"]):
        with pytest.raises(SystemExit) as error:
            main(arguments)
        assert error.value.code == 2


def test_cli_refuses_archive_directory_link_escape(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setattr(
        replay_module, "__file__", str(tmp_path / "scripts/operation_chat_replay.py")
    )
    outside = tmp_path / "different-location"
    archive_fixture(outside)
    root = tmp_path / "output/operation-chat-evaluation"
    root.mkdir(parents=True)
    (root / ARCHIVE).symlink_to(outside, target_is_directory=True)
    with pytest.raises(SystemExit) as error:
        main(["--archive", ARCHIVE])
    assert error.value.code == 2
