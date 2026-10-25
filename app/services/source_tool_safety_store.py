"""Private family v11: captured native reviews and per-call shared safety accounting."""

import asyncio
import hashlib
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal, cast
from uuid import uuid4

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.domain.chat import ChatTokens, ParentChatRequest
from app.mana_ai.domain.child_safety import ChildSafetyLimits, SafetyJob
from app.mana_ai.domain.conversion import ConversionOffer, ConversionPolicy
from app.mana_ai.domain.conversion_accounts import ConversionAccountReadLimits
from app.mana_ai.domain.family_agents import ParentTouchReviewedTurn, ParentTouchReviewGuidance
from app.mana_ai.domain.family_day_usage import DAY_USAGE_SOURCE, DayUsageReceipt, DayUsageTarget
from app.mana_ai.domain.family_sources import FamilySourceReceipt, FamilySourceTarget
from app.mana_ai.domain.source_reviews import SourceAnalysisOwner
from app.mana_ai.domain.source_tools import (
    SourceToolContinuation,
    SourceToolModelProfile,
    SourceToolPreparedInput,
    source_call_alias,
    source_call_day,
    source_call_key,
)
from app.services.conversion_account_store import (
    SqliteClosedConversionAccountStore,
    SqliteConversionAccountStore,
)

_TABLES = {"source_tool_turns", "source_tool_jobs", "source_tool_receipts"}


def _target(payload: str) -> FamilySourceTarget | DayUsageTarget:
    return (
        DayUsageTarget
        if json.loads(payload).get("source") == DAY_USAGE_SOURCE
        else FamilySourceTarget
    ).model_validate_json(payload)


def _receipt(payload: str) -> FamilySourceReceipt | DayUsageReceipt:
    return (
        DayUsageReceipt
        if json.loads(payload).get("source") == DAY_USAGE_SOURCE
        else FamilySourceReceipt
    ).model_validate_json(payload)


def _matches(
    receipt: FamilySourceReceipt | DayUsageReceipt, target: FamilySourceTarget | DayUsageTarget
) -> bool:
    return all(
        getattr(receipt, key) == getattr(target, key)
        for key in ("parent_id", "child_id", "request_id", "source")
    ) and (getattr(receipt, "requested_day", None) == getattr(target, "requested_day", None))


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _validate_existing_native_schema(path: Path) -> None:
    if path.is_symlink():
        raise RuntimeError("Native family storage cannot use a symbolic link")
    if not path.exists():
        return
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as connection:
        if connection.execute("PRAGMA user_version").fetchone()[0] in {
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
        }:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(source_tool_turns)")}
            if columns != {"parent_id", "turn_id", "profile"}:
                raise RuntimeError(
                    "Unsupported native profile schema; preserve the existing ledger"
                )


class SqliteSourceToolSafetyStore(SqliteConversionAccountStore):
    _schema_version = 11
    _source_contract = 1

    async def source_review_owner(self, job: SafetyJob) -> SourceAnalysisOwner | None:
        return None  # Historical captures cannot acquire the new shared-review protocol.

    def _initialize(self) -> None:
        _validate_existing_native_schema(self._path)
        super()._initialize()

    def __init__(
        self,
        path: Path,
        *,
        native_model: str,
        native_reasoning_effort: Literal["none", "low", "medium", "high", "xhigh"] = "none",
        native_verbosity: Literal["low", "medium", "high"] = "low",
        native_wall_timeout_seconds: float = 40,
        native_max_output_tokens: int = 512,
        limits: ChildSafetyLimits,
        daily_limit: int,
        timezone: str,
        conversion_policy: ConversionPolicy,
        conversion_offers: tuple[ConversionOffer, ...],
        account_read_limits: ConversionAccountReadLimits,
        max_attempts: int = 20,
        question_limit: int = 100,
        push_queue_limit: int = 1000,
        push_max_age_seconds: int = 3600,
        push_daily_attempt_limit: int = 100,
        proactive_enabled: bool = False,
        push_enabled: bool = False,
        conversation_enabled: bool = False,
        account_source_enabled: bool = False,
    ) -> None:
        if not 0 < len(native_model) <= 128:
            raise ValueError("An explicit native safety model is required")
        if (
            type(native_max_output_tokens) is not int
            or not 32 <= native_max_output_tokens < limits.job_tokens
        ):
            raise ValueError("Native output must fit inside its captured job allowance")
        super().__init__(
            path,
            conversion_policy=conversion_policy,
            conversion_offers=conversion_offers,
            limits=limits,
            daily_limit=daily_limit,
            timezone=timezone,
            account_source_enabled=account_source_enabled,
            account_read_limits=account_read_limits,
            max_attempts=max_attempts,
            question_limit=question_limit,
            push_queue_limit=push_queue_limit,
            push_max_age_seconds=push_max_age_seconds,
            push_daily_attempt_limit=push_daily_attempt_limit,
            proactive_enabled=proactive_enabled,
            push_enabled=push_enabled,
            conversation_enabled=conversation_enabled,
        )
        self._native_profile = SourceToolModelProfile(
            model_name=native_model,
            reasoning_effort=native_reasoning_effort,
            verbosity=native_verbosity,
            wall_timeout_seconds=native_wall_timeout_seconds,
        )
        self._native_max_output = native_max_output_tokens
        self._native_policy = json.dumps(
            {
                "profile": self._native_profile.model_dump(mode="json"),
                "limits": limits.model_dump(mode="json"),
                "max_output_tokens": native_max_output_tokens,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        self._legacy_native_policy = self._native_policy
        self._observation_native_policy = json.dumps(
            json.loads(self._native_policy) | {"source_contract": 2},
            sort_keys=True,
            separators=(",", ":"),
        )
        if self._source_contract >= 2:
            self._native_policy = json.dumps(
                json.loads(self._native_policy) | {"source_contract": self._source_contract},
                sort_keys=True,
                separators=(",", ":"),
            )

    def _supported_versions(self) -> set[int]:
        return super()._supported_versions() | {10, 11}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | _TABLES

    def _extra_schema(self) -> str:
        return (
            super()._extra_schema()
            + """
            CREATE TABLE IF NOT EXISTS source_tool_turns (
                parent_id TEXT NOT NULL, turn_id INTEGER NOT NULL, profile TEXT NOT NULL,
                PRIMARY KEY(parent_id,turn_id)
            );
            CREATE TABLE IF NOT EXISTS source_tool_jobs (
                job_id TEXT PRIMARY KEY, parent_id TEXT NOT NULL, claim_id TEXT NOT NULL,
                prepared TEXT NOT NULL, prepared_hash TEXT NOT NULL, cap INTEGER NOT NULL,
                phase TEXT NOT NULL CHECK(phase IN (
                    'prepared','first_submitted','first_metered','source_submitting',
                    'source_completed','second_submitted','final_metered','closed')),
                continuation TEXT, continuation_hash TEXT, target TEXT,
                source_result TEXT, source_result_hash TEXT
            );
            CREATE TABLE IF NOT EXISTS source_tool_receipts (
                job_id TEXT NOT NULL, position INTEGER NOT NULL CHECK(position IN (0,1)),
                input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL,
                model TEXT NOT NULL, recorded_at TEXT NOT NULL,
                PRIMARY KEY(job_id,position)
            );
        """
        )

    def _on_admitted(
        self,
        connection: sqlite3.Connection,
        request: ParentChatRequest,
        turn_id: int,
        now: datetime,
    ) -> None:
        super()._on_admitted(connection, request, turn_id, now)
        if isinstance(request, ParentTouchReviewedTurn):
            connection.execute(
                "INSERT INTO source_tool_turns VALUES(?,?,?)",
                (request.parent_id, turn_id, self._native_policy),
            )

    async def native_captured(self, job: SafetyJob) -> bool:
        def read() -> bool:
            with self._connect() as connection:
                return (
                    connection.execute(
                        "SELECT 1 FROM source_tool_turns WHERE parent_id=? AND turn_id=?",
                        (job.view.parent_id, job.view.parent_turn_cutoff),
                    ).fetchone()
                    is not None
                    and job.view.kind == "parent_message"
                )

        return await asyncio.to_thread(read)

    def _captured_protocol(self, payload: str) -> int:
        if payload == self._legacy_native_policy:
            return 1
        if self._source_contract >= 2 and payload == self._observation_native_policy:
            return 2
        if self._source_contract == 3 and payload == self._native_policy:
            return 3
        raise ParentChatError("native_source_preparation_denied", 409)

    async def native_protocol(self, job: SafetyJob) -> Literal[1, 2, 3]:
        def read() -> Literal[1, 2, 3]:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT profile FROM source_tool_turns WHERE parent_id=? AND turn_id=?",
                    (job.view.parent_id, job.view.parent_turn_cutoff),
                ).fetchone()
                if row is None:
                    raise ParentChatError("native_source_preparation_denied", 409)
                return cast(Literal[1, 2, 3], self._captured_protocol(row[0]))

        return await asyncio.to_thread(read)

    async def review_guidance(
        self, parent_id: str, turn_id: int, connected: tuple[int, ...]
    ) -> ParentTouchReviewGuidance:
        guidance = await super().review_guidance(parent_id, turn_id, connected)

        def source() -> ParentTouchReviewGuidance:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT j.* FROM child_safety_jobs j "
                    "JOIN source_tool_jobs n ON n.job_id=j.job_id "
                    "WHERE j.parent_id=? AND j.parent_turn_cutoff=? AND j.kind='parent_message' "
                    "AND j.status='completed' AND n.source_result IS NOT NULL",
                    (parent_id, turn_id),
                ).fetchone()
                if row is None:
                    return guidance
                native = self._native(connection, self._job(row))
                receipt = _receipt(native["source_result"])
                if (
                    receipt.status
                    not in (
                        {"completed", "unavailable"}
                        if isinstance(receipt, DayUsageReceipt)
                        else {"completed"}
                    )
                    or receipt.child_id not in connected
                    or receipt.child_id not in guidance.authorized_child_ids
                ):
                    raise ParentChatError("native_source_guidance_not_authorized", 403)
                updates: dict[str, object] = {
                    "source_observations": (receipt.facts,) if receipt.facts is not None else ()
                }
                if isinstance(receipt, DayUsageReceipt):
                    updates["day_usage_query"] = receipt.requested_day
                    updates["day_usage_child_returned"] = receipt.child_returned
                return guidance.model_copy(update=updates)

        return await asyncio.to_thread(source)

    def _claim_next(self, now: datetime) -> SafetyJob | None:
        ordinary = super()._claim_next(now)
        if ordinary is not None:
            return ordinary
        # Only newly captured native reviews may use the remaining allowance.
        # Historical jobs retain their original full-job reservation contract.
        with self._transaction() as connection:
            self._recover(connection, now)
            remaining = self._budget(connection, None, now).server_remaining_tokens
            day, _ = self._period(now)
            attempts = connection.execute(
                "SELECT COUNT(*) FROM child_safety_jobs WHERE day=? AND claim_id IS NOT NULL",
                (day,),
            ).fetchone()[0]
            if remaining < 64 or attempts >= self._safety_limits.server_daily_attempts:
                return None
            row = connection.execute(
                "SELECT j.* FROM child_safety_jobs j JOIN source_tool_turns n "
                "ON n.parent_id=j.parent_id AND n.turn_id=j.parent_turn_cutoff "
                "WHERE j.status='queued' AND j.kind='parent_message' AND NOT EXISTS "
                "(SELECT 1 FROM child_safety_jobs p WHERE p.parent_id=j.parent_id "
                "AND p.status IN ('preparing','submitted','unknown','metered')) "
                "AND (SELECT COALESCE(SUM(p.input_tokens+p.output_tokens),0) "
                "FROM child_safety_jobs p WHERE p.parent_id=j.parent_id AND p.day=?)<=? "
                "AND (SELECT COUNT(*) FROM child_safety_jobs p WHERE p.parent_id=j.parent_id "
                "AND p.day=? AND p.claim_id IS NOT NULL)<? ORDER BY j.position LIMIT 1",
                (
                    day,
                    self._safety_limits.parent_daily_tokens - 64,
                    day,
                    self._safety_limits.parent_daily_attempts,
                ),
            ).fetchone()
            if row is None:
                return None
            own = self._budget(connection, row["parent_id"], now).parent_remaining_tokens
            reserve = min(self._safety_limits.job_tokens, remaining, own)
            connection.execute(
                "UPDATE child_safety_jobs SET status='preparing',claim_id=?,lease_expires_at=?,"
                "day=?,reserved=?,updated_at=? WHERE job_id=? AND status='queued'",
                (
                    str(uuid4()),
                    (now + timedelta(seconds=self._safety_limits.lease_seconds)).isoformat(),
                    day,
                    reserve,
                    now.isoformat(),
                    row["job_id"],
                ),
            )
            return self._job(
                connection.execute(
                    "SELECT * FROM child_safety_jobs WHERE job_id=?", (row["job_id"],)
                ).fetchone()
            )

    @staticmethod
    def _native(connection: sqlite3.Connection, job: SafetyJob) -> sqlite3.Row:
        row = cast(
            sqlite3.Row | None,
            connection.execute(
                "SELECT * FROM source_tool_jobs WHERE job_id=? AND parent_id=? AND claim_id=?",
                (str(job.view.job_id), job.view.parent_id, str(job.claim_id)),
            ).fetchone(),
        )
        if row is None or _hash(row["prepared"]) != row["prepared_hash"]:
            raise ParentChatError("native_source_state_invalid", 503)
        prepared = SourceToolPreparedInput.model_validate_json(row["prepared"])
        if (
            (row["continuation"] is None) != (row["continuation_hash"] is None)
            or ((row["continuation"] is None) != (row["target"] is None))
            or (row["source_result"] is None) != (row["source_result_hash"] is None)
        ):
            raise ParentChatError("native_source_state_invalid", 503)
        if (
            prepared.scope.parent_id != job.view.parent_id
            or prepared.scope.invocation_id != job.view.job_id
        ):
            raise ParentChatError("native_source_state_invalid", 503)
        if row["continuation"] is not None:
            if _hash(row["continuation"]) != row["continuation_hash"]:
                raise ParentChatError("native_source_state_invalid", 503)
            choice = SourceToolContinuation.model_validate_json(row["continuation"])
            target = _target(row["target"])
            prepared.scope.validate_call(choice.call)
            child = next(
                (c for c in prepared.scope.children if c.alias == source_call_alias(choice.call)),
                None,
            )
            if (
                child is None
                or target.parent_id != prepared.scope.parent_id
                or target.child_id != child.child_id
                or choice.input_digest != prepared.input_digest
                or target.request_id != prepared.scope.request_id_for(choice.call)
                or target.source != source_call_key(choice.call)
                or choice.version != prepared.scope.protocol
                or getattr(target, "requested_day", None) != source_call_day(choice.call)
            ):
                raise ParentChatError("native_source_state_invalid", 503)
        elif row["phase"] in {"source_submitting", "source_completed", "second_submitted"}:
            raise ParentChatError("native_source_state_invalid", 503)
        if row["source_result"] is not None:
            if _hash(row["source_result"]) != row["source_result_hash"]:
                raise ParentChatError("native_source_state_invalid", 503)
            receipt = _receipt(row["source_result"])
            target = _target(row["target"])
            if not _matches(receipt, target):
                raise ParentChatError("native_source_state_invalid", 503)
        elif row["phase"] in {"source_completed", "second_submitted"} or (
            row["phase"] == "final_metered" and row["continuation"] is not None
        ):
            raise ParentChatError("native_source_state_invalid", 503)
        return row

    def _validate_safety_completion(self, connection: sqlite3.Connection, row: sqlite3.Row) -> None:
        captured = connection.execute(
            "SELECT 1 FROM source_tool_turns WHERE parent_id=? AND turn_id=?",
            (row["parent_id"], row["parent_turn_cutoff"]),
        ).fetchone()
        if row["kind"] != "parent_message" or captured is None:
            return
        native = self._native(connection, self._job(row))
        totals = connection.execute(
            "SELECT COUNT(*),SUM(input_tokens),SUM(output_tokens) "
            "FROM source_tool_receipts WHERE job_id=?",
            (row["job_id"],),
        ).fetchone()
        if (
            native["phase"] != "final_metered"
            or totals[0] != (2 if native["continuation"] else 1)
            or totals[1] != row["input_tokens"]
            or totals[2] != row["output_tokens"]
            or totals[1] + totals[2] > native["cap"]
        ):
            raise ParentChatError("native_source_completion_unverified", 503)

    async def prepare_native(
        self,
        job: SafetyJob,
        prepared: SourceToolPreparedInput,
        profile: SourceToolModelProfile,
        now: datetime,
    ) -> None:
        def prepare() -> None:
            with self._transaction() as connection:
                row = self._claimed(connection, job)
                capture = connection.execute(
                    "SELECT profile FROM source_tool_turns WHERE parent_id=? AND turn_id=?",
                    (job.view.parent_id, job.view.parent_turn_cutoff),
                ).fetchone()
                allowed = row["allowed_child_ids"]
                if (
                    capture is None
                    or self._captured_protocol(capture[0]) != prepared.scope.protocol
                    or self._native_profile != profile
                    or row["kind"] != "parent_message"
                    or row["status"] != "preparing"
                    or row["input_tokens"] is not None
                    or allowed is None
                    or prepared.scope.parent_id != job.view.parent_id
                    or prepared.scope.invocation_id != job.view.job_id
                    or set(child.child_id for child in prepared.scope.children)
                    != set(json.loads(allowed))
                    or row["lease_expires_at"] <= self._utc(now).isoformat()
                ):
                    raise ParentChatError("native_source_preparation_denied", 409)
                self._validate_safety_publication(connection, row, self._utc(now))
                payload = SourceToolPreparedInput.model_validate(
                    prepared.model_dump()
                ).model_dump_json()
                connection.execute(
                    "INSERT INTO source_tool_jobs(job_id,parent_id,claim_id,prepared,"
                    "prepared_hash,cap,phase) "
                    "VALUES(?,?,?,?,?,?,'prepared')",
                    (
                        str(job.view.job_id),
                        job.view.parent_id,
                        str(job.claim_id),
                        payload,
                        _hash(payload),
                        row["reserved"],
                    ),
                )

        await asyncio.to_thread(prepare)

    async def submit_native(
        self, job: SafetyJob, position: int, count: int, output: int, now: datetime
    ) -> None:
        def submit() -> None:
            with self._transaction() as connection:
                row, native = self._claimed(connection, job), self._native(connection, job)
                if (
                    type(position) is not int
                    or position not in {0, 1}
                    or type(count) is not int
                    or count < 0
                    or type(output) is not int
                    or output < 32
                    or output > self._native_max_output
                    or count + output > row["reserved"]
                    or row["status"] != "preparing"
                    or native["phase"] != ("prepared" if position == 0 else "source_completed")
                    or row["lease_expires_at"] <= self._utc(now).isoformat()
                ):
                    raise ParentChatError("native_source_submission_denied", 409)
                self._validate_safety_publication(connection, row, self._utc(now))
                connection.execute(
                    "UPDATE source_tool_jobs SET phase=? WHERE job_id=?",
                    (
                        "first_submitted" if position == 0 else "second_submitted",
                        str(job.view.job_id),
                    ),
                )
                # Keep the entire remaining original claim; no second job/budget.
                connection.execute(
                    "UPDATE child_safety_jobs SET status='submitted',updated_at=? WHERE job_id=?",
                    (self._utc(now).isoformat(), str(job.view.job_id)),
                )

        await asyncio.to_thread(submit)

    async def record_native_usage(
        self, job: SafetyJob, position: int, usage: ChatTokens, model: str, now: datetime
    ) -> int | None:
        def record() -> int | None:
            with self._transaction() as connection:
                row, native = self._claimed(connection, job), self._native(connection, job)
                if (
                    position not in {0, 1}
                    or native["phase"]
                    != ("first_submitted" if position == 0 else "second_submitted")
                    or row["status"] not in {"submitted", "unknown"}
                    or not 0 < len(model) <= 128
                ):
                    raise ParentChatError("native_source_receipt_not_admitted", 409)
                checked = ChatTokens.model_validate(usage.model_dump())
                over = checked.total > row["reserved"]
                late = row["lease_expires_at"] <= self._utc(now).isoformat()
                stopped = row["status"] == "unknown"
                remaining = max(0, row["reserved"] - checked.total)
                eligible = not over and not late and not stopped
                connection.execute(
                    "INSERT INTO source_tool_receipts VALUES(?,?,?,?,?,?)",
                    (
                        str(job.view.job_id),
                        position,
                        checked.input_tokens,
                        checked.output_tokens,
                        model,
                        self._utc(now).isoformat(),
                    ),
                )
                connection.execute(
                    "UPDATE child_safety_jobs SET status=?,reserved=?,"
                    "input_tokens=?,output_tokens=?,"
                    "model=?,updated_at=?,error_code=? WHERE job_id=?",
                    (
                        "unknown"
                        if over
                        else "failed"
                        if late or stopped
                        else "preparing"
                        if position == 0
                        else "metered",
                        remaining if eligible and position == 0 else 0,
                        (row["input_tokens"] or 0) + checked.input_tokens,
                        (row["output_tokens"] or 0) + checked.output_tokens,
                        model,
                        self._utc(now).isoformat(),
                        "safety_usage_exceeded_hold"
                        if over
                        else "safety_late_receipt_discarded"
                        if late
                        else "native_source_stopped_receipt_discarded"
                        if stopped
                        else None,
                        str(job.view.job_id),
                    ),
                )
                connection.execute(
                    "UPDATE source_tool_jobs SET phase=? WHERE job_id=?",
                    (
                        "closed"
                        if not eligible
                        else "first_metered"
                        if position == 0
                        else "final_metered",
                        str(job.view.job_id),
                    ),
                )
                return remaining if eligible else None

        return await asyncio.to_thread(record)

    async def claim_native_source(
        self, job: SafetyJob, continuation: SourceToolContinuation, now: datetime
    ) -> FamilySourceTarget | DayUsageTarget:
        def claim() -> FamilySourceTarget | DayUsageTarget:
            with self._transaction() as connection:
                row, native = self._claimed(connection, job), self._native(connection, job)
                if (
                    native["phase"] != "first_metered"
                    or row["status"] != "preparing"
                    or row["lease_expires_at"] <= self._utc(now).isoformat()
                ):
                    raise ParentChatError("native_source_choice_not_admitted", 409)
                self._validate_safety_publication(connection, row, self._utc(now))
                prepared = SourceToolPreparedInput.model_validate_json(native["prepared"])
                choice = SourceToolContinuation.model_validate(continuation.model_dump())
                if choice.input_digest != prepared.input_digest:
                    raise ParentChatError("native_source_input_mismatch", 409)
                if choice.version != prepared.scope.protocol:
                    raise ParentChatError("native_source_input_mismatch", 409)
                prepared.scope.validate_call(choice.call)
                alias = source_call_alias(choice.call)
                child = next((c for c in prepared.scope.children if c.alias == alias), None)
                if child is None:
                    raise ParentChatError("native_source_child_not_admitted", 403)
                data = dict(
                    parent_id=prepared.scope.parent_id,
                    child_id=child.child_id,
                    request_id=prepared.scope.request_id_for(choice.call),
                    source=source_call_key(choice.call),
                )
                day = source_call_day(choice.call)
                target = (
                    DayUsageTarget.model_validate(data | {"requested_day": day})
                    if day is not None
                    else FamilySourceTarget.model_validate(data)
                )
                payload = choice.model_dump_json()
                connection.execute(
                    "UPDATE source_tool_jobs SET phase='source_submitting',continuation=?,"
                    "continuation_hash=?,target=? WHERE job_id=?",
                    (payload, _hash(payload), target.model_dump_json(), str(job.view.job_id)),
                )
                return target

        return await asyncio.to_thread(claim)

    async def record_native_source(
        self, job: SafetyJob, receipt: FamilySourceReceipt | DayUsageReceipt, now: datetime
    ) -> bool:
        def record() -> bool:
            with self._transaction() as connection:
                row, native = self._claimed(connection, job), self._native(connection, job)
                if native["phase"] != "source_submitting":
                    raise ParentChatError("native_source_result_not_admitted", 409)
                target = _target(native["target"])
                checked = _receipt(receipt.model_dump_json())
                if not _matches(checked, target):
                    raise ParentChatError("native_source_result_mismatch", 409)
                eligible = (
                    checked.status
                    in (
                        {"completed", "unavailable"}
                        if isinstance(checked, DayUsageReceipt)
                        else {"completed"}
                    )
                    and row["status"] == "preparing"
                    and row["lease_expires_at"] > self._utc(now).isoformat()
                )
                payload = checked.model_dump_json()
                connection.execute(
                    "UPDATE source_tool_jobs SET phase=?,source_result=?,source_result_hash=? "
                    "WHERE job_id=?",
                    (
                        "source_completed" if eligible else "closed",
                        payload,
                        _hash(payload),
                        str(job.view.job_id),
                    ),
                )
                return eligible

        return await asyncio.to_thread(record)

    async def finalize_native_without_source(self, job: SafetyJob, now: datetime) -> None:
        def finish() -> None:
            with self._transaction() as connection:
                row, native = self._claimed(connection, job), self._native(connection, job)
                if (
                    native["phase"] != "first_metered"
                    or row["status"] != "preparing"
                    or row["lease_expires_at"] <= self._utc(now).isoformat()
                ):
                    raise ParentChatError("native_source_final_not_admitted", 409)
                self._validate_safety_publication(connection, row, self._utc(now))
                connection.execute(
                    "UPDATE child_safety_jobs SET status='metered',reserved=0 WHERE job_id=?",
                    (str(job.view.job_id),),
                )
                connection.execute(
                    "UPDATE source_tool_jobs SET phase='final_metered' WHERE job_id=?",
                    (str(job.view.job_id),),
                )

        await asyncio.to_thread(finish)

    async def submit_safety(self, job: SafetyJob, reserved_tokens: int, now: datetime) -> None:
        if await self.native_captured(job):
            raise ParentChatError("native_source_protocol_required", 409)
        await super().submit_safety(job, reserved_tokens, now)

    async def fail_safety(
        self, job: SafetyJob, code: str, now: datetime, *, definite_model_rejection: bool = False
    ) -> None:
        if code == "safety_model_receipt_unknown":
            observed = await self.assessment(job.view.parent_id, job.view.job_id)
            if observed.status in {"preparing", "metered"} and observed.usage is not None:
                code = "native_source_receipt_processing_interrupted"
        await super().fail_safety(job, code, now, definite_model_rejection=definite_model_rejection)

    async def record_usage(
        self, job: SafetyJob, usage: ChatTokens, model: str, now: datetime
    ) -> bool:
        if await self.native_captured(job):
            raise ParentChatError("native_source_protocol_required", 409)
        return await super().record_usage(job, usage, model, now)


class SqliteClosedSourceToolSafetyStore(SqliteClosedConversionAccountStore):
    _schema_version = 11

    def _initialize(self) -> None:
        _validate_existing_native_schema(self._path)
        super()._initialize()

    def _supported_versions(self) -> set[int]:
        return {11}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | _TABLES


class SqliteObservationToolSafetyStore(SqliteSourceToolSafetyStore):
    """V12 captures observation-v2 only for new turns; queued v11 keeps battery-v1."""

    _schema_version = 12
    _source_contract = 2


class SqliteClosedObservationToolSafetyStore(SqliteClosedSourceToolSafetyStore):
    _schema_version = 12

    def _supported_versions(self) -> set[int]:
        return {12}
