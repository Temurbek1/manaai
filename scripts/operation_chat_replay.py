"""Offline recorded-output delivery replay; never invokes a model or product source."""

import argparse
import asyncio
import hashlib
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, Mock
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, JsonValue

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.mana_operation_ai.application.admin_service import OperationAdminService  # noqa: E402
from app.mana_operation_ai.application.chat_ports import (  # noqa: E402
    ChatRepository,
    ChatTurnOutput,
)
from app.mana_operation_ai.application.chat_service import (  # noqa: E402
    INSTRUCTIONS,
    OperationChatService,
    _report_source,
    _verified_report_product,
)
from app.mana_operation_ai.application.growth.constants import (
    ADVERTISING_CAPABILITY_KEY,  # noqa: E402
)
from app.mana_operation_ai.application.retention.constants import (  # noqa: E402
    ENGAGEMENT_CAPABILITY_KEY,
    PARENTS_CAPABILITY_KEY,
)
from app.mana_operation_ai.domain.chat import (  # noqa: E402
    ChatAvailability,
    ChatTopic,
    ChatTurn,
    TopicCreate,
)
from app.mana_operation_ai.domain.models import AgentReport  # noqa: E402
from scripts.operation_chat_evaluate import (  # noqa: E402
    EvaluationResult,
    PreparedRequest,
    prepare_requests,
)

MAX_FILE_BYTES = 1_048_576
MAX_RECORDS = 16


class ReplayError(ValueError):
    """Safe provenance refusal; do not expose arbitrary archive contents."""


class RecordedPlan(BaseModel):
    # Retain compatibility with ancillary metadata, not extra model-output fields.
    model_config = ConfigDict(extra="ignore")
    instructions: str
    instructions_sha256: str
    requests: list[PreparedRequest]


class RecordedResults(BaseModel):
    model_config = ConfigDict(extra="ignore")
    approval_id: str
    all_requests_completed: bool
    product_source_calls: int
    operational_actions: int
    results: list[EvaluationResult]


class ReplayClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


class ForbiddenModel:
    async def reply(self, *, instructions: str, context: str, owner: str) -> ChatTurnOutput:
        raise ReplayError("Replay must not generate another response")


def _read_file(path: Path) -> bytes:
    if path.is_symlink():
        raise ReplayError("Replay refuses linked archive files")
    with path.open("rb") as stream:
        content = stream.read(MAX_FILE_BYTES + 1)
    if len(content) > MAX_FILE_BYTES:
        raise ReplayError("Archive exceeds the bounded replay input")
    return content


def _time(value: object) -> datetime:
    if not isinstance(value, str):
        raise ReplayError("Archive observation time is missing")
    parsed = datetime.fromisoformat(value)
    if parsed.utcoffset() is None:
        raise ReplayError("Archive observation time must be aware")
    return parsed.astimezone(UTC)


def _sources(context: dict[str, JsonValue], topic: ChatTopic, now: datetime) -> list[AgentReport]:
    packets = context.get("saved_reports")
    if not isinstance(packets, list) or len(packets) > 2:
        raise ReplayError("Replay requires bounded synthetic aggregate packets")
    reports: list[AgentReport] = []
    for packet in packets:
        if not isinstance(packet, dict):
            raise ReplayError("Invalid aggregate packet")
        identifier = packet.get("id")
        if not isinstance(identifier, str) or not identifier.startswith("synthetic-"):
            raise ReplayError("Replay accepts synthetic report identifiers only")
        # The archive omitted scope_basis/full rows. This is explicitly fixture
        # reconstruction, not an observed fresh report or owner confirmation.
        basis = (
            "owner_confirmed_parent_api"
            if packet.get("capability_key") == PARENTS_CAPABILITY_KEY
            else "approved_source_binding"
        )
        report = AgentReport.model_validate(
            {
                "report_id": identifier,
                "agent_id": topic.agent_id,
                "capability_key": packet.get("capability_key"),
                "run_id": f"replay-only-{identifier}",
                "report_type": packet.get("report_type"),
                "period_start": now,
                "period_end": now,
                "created_at": _time(packet.get("report_created_at")),
                "human_readable": packet.get("summary"),
                "data_quality_notes": packet.get("limitations"),
                "structured": {
                    key: packet.get(key)
                    for key in (
                        "product",
                        "scope_verified",
                        "collected_at",
                        "fresh_until",
                        "refresh_status",
                    )
                }
                | {"scope_basis": basis},
            }
        )
        if _verified_report_product(report) != topic.product:
            raise ReplayError("Archive report does not match its synthetic topic")
        reports.append(report)
    return reports


async def replay_archive(
    directory: Path, *, archive_id: str, parent_minimum_interval_seconds: int = 21600
) -> dict[str, object]:
    if re.fullmatch(r"[a-z0-9][a-z0-9_-]{2,79}", archive_id) is None:
        raise ReplayError("Replay requires a safe explicit archive label")
    if not 21600 <= parent_minimum_interval_seconds <= 86400:
        raise ReplayError("Replay Parent interval is outside the configured bounds")
    plan_bytes, result_bytes = (
        _read_file(directory / "plan.json"),
        _read_file(directory / "results.json"),
    )
    plan = RecordedPlan.model_validate_json(plan_bytes)
    recorded = RecordedResults.model_validate_json(result_bytes)
    current_hash = hashlib.sha256(INSTRUCTIONS.encode()).hexdigest()
    if (
        hashlib.sha256(plan.instructions.encode()).hexdigest() != plan.instructions_sha256
        or plan.instructions_sha256 != current_hash
        or recorded.approval_id != archive_id
        or not recorded.all_requests_completed
        or recorded.product_source_calls != 0
        or recorded.operational_actions != 0
        or not 1 <= len(plan.requests) <= MAX_RECORDS
        or len(recorded.results) != len(plan.requests)
    ):
        raise ReplayError("Replay provenance or coverage does not match its reviewed scope")
    templates = {item.case_id: item for item in prepare_requests(sol_quality=True)}
    first_case = plan.requests[0].case_id
    variants = [item.variant for item in plan.requests if item.case_id == first_case]
    if not 1 <= len(variants) <= 2 or [(item.case_id, item.variant) for item in plan.requests] != [
        (case, variant) for case in templates for variant in variants
    ]:
        raise ReplayError("Replay must cover all eight fixed cases in their recorded order")
    identities: set[tuple[str, str]] = set()
    delivered: list[dict[str, object]] = []
    for request, result in zip(plan.requests, recorded.results, strict=True):
        identity = (request.case_id, request.variant)
        context_hash = hashlib.sha256(request.context.encode()).hexdigest()
        if (
            identity in identities
            or not request.case_id.startswith("fresh_")
            or request.context != templates[request.case_id].context
            or request.context_bytes != len(request.context.encode())
            or request.review_checks != templates[request.case_id].review_checks
            or identity != (result.case_id, result.variant)
            or request.context_sha256 != context_hash
            or result.context_sha256 != context_hash
            or result.review_checks != request.review_checks
            or result.requested_model != request.requested_model
            or result.requested_reasoning_effort != request.requested_reasoning_effort
            or result.max_output_tokens != request.max_output_tokens
            or result.status != "completed"
            or not result.answer.strip()
            or result.failure_kind is not None
            or result.model is None
            or not (
                result.model == request.requested_model
                or result.model.startswith(f"{request.requested_model}-")
            )
            or result.input_tokens is None
            or result.input_tokens < 0
            or result.output_tokens is None
            or not 0 <= result.output_tokens <= request.max_output_tokens
            or result.latency_ms < 0
        ):
            raise ReplayError("Replay boundary record is duplicate, incomplete or mismatched")
        identities.add(identity)
        context = cast(dict[str, JsonValue], json.loads(request.context))
        topic_create = TopicCreate.model_validate(context.get("topic"))
        now = _time(context.get("evaluation_time"))
        parent_enabled = context.get("parent_summary_enabled")
        if not isinstance(parent_enabled, bool):
            raise ReplayError("Synthetic source availability is missing")
        topic = ChatTopic(
            **topic_create.model_dump(),
            topic_id=f"replay-{request.case_id}",
            created_at=now,
            updated_at=now,
        )
        reports = _sources(context, topic, now)
        stored = ChatTurn(
            turn_id=f"replay-{request.case_id}-{request.variant}",
            topic_id=topic.topic_id,
            request_id=uuid5(NAMESPACE_URL, f"synthetic-replay:{archive_id}:{identity}"),
            message=cast(str, context["message"]),
            status="completed",
            created_at=now,
            answer=result.answer,
            plan=result.plan,
            next_action=result.next_action,
            model=result.model,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            sources=[_report_source(report, now=now) for report in reports],
        )
        repository = Mock(spec=ChatRepository)
        repository.topic = AsyncMock(return_value=topic)
        repository.turns = AsyncMock(return_value=[stored])
        admin = Mock(spec=OperationAdminService)
        admin.default_capability_key.side_effect = lambda agent: {
            "growth-agent": ADVERTISING_CAPABILITY_KEY,
            "retention-agent": ENGAGEMENT_CAPABILITY_KEY,
        }[agent]
        service = OperationChatService(
            repository=cast(ChatRepository, repository),
            admin=cast(OperationAdminService, admin),
            model=ForbiddenModel(),
            availability=ChatAvailability(
                enabled=True, hourly_limit=1, daily_limit=1, parent_summary_enabled=parent_enabled
            ),
            clock=ReplayClock(now),
            parent_minimum_interval_seconds=parent_minimum_interval_seconds,
        )
        detail = await service.detail("synthetic-replay-owner", topic.topic_id)
        turn = detail.turns[0]
        if turn.model_dump(exclude={"read_confirmation"}) != stored.model_dump(
            exclude={"read_confirmation"}
        ):
            raise ReplayError("Delivery replay altered the recorded model response")
        for method in ("create", "reserve", "update", "cancel", "topics"):
            getattr(repository, method).assert_not_called()
        for method in ("validate_run", "run_in_background", "list_reports"):
            getattr(admin, method).assert_not_called()
        delivered.append(
            {
                "case_id": request.case_id,
                "variant": request.variant,
                "context_sha256": context_hash,
                "review_checks": request.review_checks,
                "delivered_turn": turn.model_dump(mode="json"),
                "recorded_latency_ms": result.latency_ms,
                "quality_status": "manual_review_pending",
            }
        )
    return {
        "status": "offline_recorded_delivery_replay_not_new_model_evaluation",
        "archive_id": archive_id,
        "plan_sha256": hashlib.sha256(plan_bytes).hexdigest(),
        "results_sha256": hashlib.sha256(result_bytes).hexdigest(),
        "instructions_sha256": current_hash,
        "parent_minimum_interval_seconds": parent_minimum_interval_seconds,
        "covered_boundary_records": len(delivered),
        "new_model_calls": 0,
        "product_source_calls": 0,
        "operational_actions": 0,
        "new_cost_usd": "0",
        "quality_status": "manual_review_pending",
        "limitations": [
            "Reused recorded outputs; does not measure future model variability or quality.",
            "Saved-output/history-delivery boundary only; not a fresh HTTP/model/executor trace.",
            "Full report rows/scope_basis reconstructed as synthetic fixtures, "
            "not observed ownership.",
            "No original latency, token usage, charges or raw model grades are rewritten.",
        ],
        "records": delivered,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True)
    parser.add_argument("--parent-minimum-interval-seconds", type=int, default=21600)
    args = parser.parse_args(argv)
    if re.fullmatch(r"[a-z0-9][a-z0-9_-]{2,79}", args.archive) is None:
        parser.error("Archive must be a safe local label, not an arbitrary path")
    root = Path(__file__).resolve().parents[1] / "output/operation-chat-evaluation"
    directory = root / args.archive
    if directory.resolve().parent != root.resolve():
        parser.error("Replay refuses archives outside the local evidence directory")
    try:
        report = asyncio.run(
            replay_archive(
                directory,
                archive_id=args.archive,
                parent_minimum_interval_seconds=args.parent_minimum_interval_seconds,
            )
        )
    except Exception as exc:
        # Config/archive exceptions can include arbitrary text; print only the safe class.
        print(f"Replay refused: {type(exc).__name__}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
