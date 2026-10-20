"""Event outbox and explicit safety budget inside the private family SQLite DB.

No provider I/O occurs here. A claim is durable before any source/count/model call.
Unknown submissions retain holds across restart and midnight and never requeue.
"""

import asyncio
import hashlib
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4, uuid5

from pydantic import BaseModel

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.domain.chat import ChatTokens, ParentChatRequest
from app.mana_ai.domain.child_safety import (
    ChildSafetyLimits,
    SafetyAssessmentPage,
    SafetyBudget,
    SafetyChatMessage,
    SafetyContextSnapshot,
    SafetyJob,
    SafetyJobView,
    SafetyStoredResult,
    SafetyTarget,
)
from app.mana_ai.domain.enums import ManaAICapability
from app.mana_ai.domain.family_agents import AgentQuestionRequest, ParentTouchDeliveryRequest
from app.mana_ai.domain.requests import (
    AdaptiveScreenTimeRequest,
    AIGamingSafetyRequest,
    BehaviourAnomalyRequest,
    ChildSafetyAssistantRequest,
    FamilyAgreementRequest,
    FamilyDigestRequest,
    LocationIntelligenceRequest,
    ManaAIRequest,
    SafetyMonitorRequest,
    ScamPrivacyShieldRequest,
    SmartContentFilterRequest,
)
from app.services.touch_evidence_store import SqliteTouchEvidenceStore


class SqliteChildSafetyStore(SqliteTouchEvidenceStore):
    _schema_version = 5
    child_tables = frozenset(
        {"child_safety_jobs", "child_safety_requests", "child_safety_parent_events"}
    )

    def __init__(
        self,
        path: Path,
        *,
        limits: ChildSafetyLimits,
        daily_limit: int,
        timezone: str,
        max_attempts: int = 20,
        question_limit: int = 100,
    ) -> None:
        super().__init__(
            path,
            daily_limit=daily_limit,
            timezone=timezone,
            max_attempts=max_attempts,
            question_limit=question_limit,
        )
        self._safety_limits = limits

    def _supported_versions(self) -> set[int]:
        return super()._supported_versions() | {3, 4}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | set(self.child_tables)

    def _extra_schema(self) -> str:
        return (
            super()._extra_schema()
            + """
            CREATE TABLE IF NOT EXISTS child_safety_jobs (
                position INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL UNIQUE,
                parent_id TEXT NOT NULL,
                child_key INTEGER NOT NULL,
                capability_key TEXT NOT NULL,
                kind TEXT NOT NULL,
                source_revision TEXT NOT NULL,
                data_digest TEXT NOT NULL,
                parent_turn_cutoff INTEGER NOT NULL,
                context TEXT NOT NULL,
                analysis TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                evaluated_at TEXT,
                signal_first_at TEXT,
                signal_last_at TEXT,
                claim_id TEXT,
                lease_expires_at TEXT,
                day TEXT,
                reserved INTEGER NOT NULL DEFAULT 0 CHECK(reserved>=0),
                input_tokens INTEGER,
                output_tokens INTEGER,
                model TEXT,
                allowed_child_ids TEXT,
                result TEXT,
                error_code TEXT,
                UNIQUE(parent_id,kind,child_key,capability_key,data_digest,parent_turn_cutoff)
            );
            CREATE UNIQUE INDEX IF NOT EXISTS child_safety_one_active_parent
                ON child_safety_jobs(parent_id)
                WHERE status IN ('preparing','submitted','unknown','metered');
            CREATE UNIQUE INDEX IF NOT EXISTS child_safety_one_observed_input
                ON child_safety_jobs(parent_id,child_key,capability_key,data_digest)
                WHERE kind='child_data';
            CREATE INDEX IF NOT EXISTS child_safety_dispatch
                ON child_safety_jobs(status,position);
            CREATE INDEX IF NOT EXISTS child_safety_cost_day
                ON child_safety_jobs(day,parent_id);
            CREATE TABLE IF NOT EXISTS child_safety_requests (
                parent_id TEXT NOT NULL,
                request_id TEXT NOT NULL,
                digest TEXT NOT NULL,
                job_id TEXT NOT NULL,
                PRIMARY KEY(parent_id,request_id)
            );
            CREATE TABLE IF NOT EXISTS child_safety_parent_events (
                turn_id INTEGER NOT NULL UNIQUE,
                parent_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                context TEXT NOT NULL,
                job_id TEXT,
                PRIMARY KEY(parent_id,turn_id)
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
        if request.message:
            snapshot = self._snapshot(connection, request.parent_id, turn_id)
            connection.execute(
                "INSERT INTO child_safety_parent_events(turn_id,parent_id,created_at,context) "
                "VALUES(?,?,?,?)",
                (turn_id, request.parent_id, now.isoformat(), snapshot.model_dump_json()),
            )

    @staticmethod
    def _hash(value: object) -> str:
        return hashlib.sha256(
            json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
        ).hexdigest()

    @classmethod
    def _facts(cls, value: object) -> object:
        if isinstance(value, BaseModel):
            return {field: cls._facts(getattr(value, field)) for field in type(value).model_fields}
        if isinstance(value, datetime):
            return cls._utc(value).isoformat()
        if isinstance(value, list | tuple):
            return [cls._facts(item) for item in value]
        return value

    def _snapshot(
        self,
        connection: sqlite3.Connection,
        parent_id: str,
        cutoff: int,
    ) -> SafetyContextSnapshot:
        rows = connection.execute(
            "SELECT * FROM parent_chat_turns WHERE parent_id=? AND id<=? ORDER BY id DESC LIMIT ?",
            (parent_id, cutoff, self._safety_limits.history_turns),
        ).fetchall()
        messages = []
        for row in reversed(rows):
            if row["message"]:
                messages.append(
                    SafetyChatMessage(
                        role="user", content=row["message"], created_at=row["created_at"]
                    )
                )
            if row["status"] == "completed" and row["answer"]:
                messages.append(
                    SafetyChatMessage(
                        role="assistant", content=row["answer"], created_at=row["updated_at"]
                    )
                )
        # Latest immutable result per child/capability. The explicit preview bound
        # is not a claim to have read all assessments or the entire conversation.
        saved = connection.execute(
            "SELECT job_id FROM child_safety_jobs WHERE parent_id=? AND status='completed' "
            "AND kind='child_data' AND position IN (SELECT MAX(position) FROM child_safety_jobs "
            "WHERE parent_id=? AND status='completed' AND kind='child_data' "
            "GROUP BY child_key,capability_key) ORDER BY position DESC",
            (parent_id, parent_id),
        ).fetchall()
        return SafetyContextSnapshot(
            chat_turn_cutoff=cutoff,
            messages=messages,
            saved_assessment_ids=[row[0] for row in saved[:20]],
            saved_assessment_total=len(saved),
        )

    @staticmethod
    def _view(row: sqlite3.Row) -> SafetyJobView:
        return SafetyJobView(
            data_revision=row["data_digest"],
            job_id=row["job_id"],
            parent_id=row["parent_id"],
            child_id=row["child_key"] or None,
            kind=row["kind"],
            capability=row["capability_key"] or None,
            status=row["status"],
            parent_turn_cutoff=row["parent_turn_cutoff"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            evaluated_at=row["evaluated_at"],
            signal_first_observed_at=row["signal_first_at"],
            signal_last_observed_at=row["signal_last_at"],
            error_code=row["error_code"],
            model=row["model"],
            usage=ChatTokens(input_tokens=row["input_tokens"], output_tokens=row["output_tokens"])
            if row["input_tokens"] is not None
            else None,
            result=SafetyStoredResult.model_validate_json(row["result"]) if row["result"] else None,
        )

    @classmethod
    def _job(cls, row: sqlite3.Row) -> SafetyJob:
        # ClassVar capability identities are not serialized/discriminated in the
        # existing input JSON. Select the exact stored contract, not a union's
        # first structurally compatible request (battery fits multiple inputs).
        contracts: dict[str, type[ManaAIRequest]] = {
            ManaAICapability.SAFETY_MONITOR.value: SafetyMonitorRequest,
            ManaAICapability.FAMILY_DIGEST.value: FamilyDigestRequest,
            ManaAICapability.ADAPTIVE_SCREEN_TIME.value: AdaptiveScreenTimeRequest,
            ManaAICapability.LOCATION_INTELLIGENCE.value: LocationIntelligenceRequest,
            ManaAICapability.SMART_CONTENT_FILTER.value: SmartContentFilterRequest,
            ManaAICapability.SCAM_PRIVACY_SHIELD.value: ScamPrivacyShieldRequest,
            ManaAICapability.AI_GAMING_SAFETY.value: AIGamingSafetyRequest,
            ManaAICapability.CHILD_SAFETY_ASSISTANT.value: ChildSafetyAssistantRequest,
            ManaAICapability.FAMILY_AGREEMENT.value: FamilyAgreementRequest,
            ManaAICapability.BEHAVIOUR_ANOMALY.value: BehaviourAnomalyRequest,
        }
        analysis = (
            contracts[row["capability_key"]].model_validate_json(row["analysis"])
            if row["analysis"]
            else None
        )
        if (row["kind"] == "child_data" and analysis is None) or (
            row["kind"] == "parent_message"
            and (analysis is not None or row["child_key"] != 0 or row["capability_key"])
        ):
            raise ParentChatError("safety_job_state_unavailable", 503)
        if analysis is not None and (
            analysis.input.capability.value != row["capability_key"]
            or analysis.subject.subject_id != str(row["child_key"])
        ):
            raise ParentChatError("safety_job_state_unavailable", 503)
        return SafetyJob(
            view=cls._view(row),
            source_revision=row["source_revision"],
            data_digest=row["data_digest"],
            analysis=analysis,
            context=SafetyContextSnapshot.model_validate_json(row["context"]),
            claim_id=UUID(row["claim_id"]) if row["claim_id"] else None,
            reserved_tokens=row["reserved"],
            lease_expires_at=datetime.fromisoformat(row["lease_expires_at"])
            if row["lease_expires_at"]
            else None,
        )

    def _capacity(self, connection: sqlite3.Connection, parent_id: str) -> bool:
        pending = "('queued','preparing','submitted','unknown','metered')"
        total = connection.execute(
            f"SELECT COUNT(*) FROM child_safety_jobs WHERE status IN {pending}"
        ).fetchone()[0]
        own = connection.execute(
            f"SELECT COUNT(*) FROM child_safety_jobs WHERE parent_id=? AND status IN {pending}",
            (parent_id,),
        ).fetchone()[0]
        return bool(
            total < self._safety_limits.max_pending_jobs
            and own < self._safety_limits.max_parent_pending_jobs
        )

    async def admit_analysis(
        self,
        *,
        target: SafetyTarget,
        analysis: ManaAIRequest,
        now: datetime,
        allow_new: bool = True,
    ) -> SafetyJobView:
        return await asyncio.to_thread(
            self._admit_analysis,
            target.parent_id,
            target.child_id,
            target.request_id,
            target.source_revision,
            analysis,
            self._utc(now),
            allow_new,
        )

    @classmethod
    def _signal_times(cls, value: object) -> list[datetime]:
        if isinstance(value, BaseModel):
            observed = getattr(value, "observed_at", None)
            times = [cls._utc(observed)] if isinstance(observed, datetime) else []
            for field in type(value).model_fields:
                if field != "observed_at":
                    times.extend(cls._signal_times(getattr(value, field)))
            return times
        if isinstance(value, list | tuple):
            return [time for item in value for time in cls._signal_times(item)]
        return []

    def _admit_analysis(
        self,
        parent_id: str,
        child_id: int,
        request_id: UUID,
        source_revision: str,
        analysis: ManaAIRequest,
        now: datetime,
        allow_new: bool,
    ) -> SafetyJobView:
        if analysis.input.capability == ManaAICapability.PARENT_COPILOT:
            raise ParentChatError("safety_capability_not_owned", 403)
        if analysis.subject.subject_id != str(child_id):
            raise ParentChatError("safety_subject_mismatch", 422)
        digest = self._hash(
            {
                "child_id": child_id,
                "source_revision": source_revision,
                "analysis": analysis.model_dump(mode="json"),
            }
        )
        # Provider request IDs, presentation language, evaluation time and revision
        # labels cannot turn unchanged observed facts into another paid analysis.
        data_digest = self._hash(
            {
                "input": self._facts(analysis.input),
                "subject": analysis.subject.model_dump(mode="json", exclude={"subject_id"}),
            }
        )
        capability = analysis.input.capability.value
        with self._transaction() as connection:
            alias = connection.execute(
                "SELECT * FROM child_safety_requests WHERE parent_id=? AND request_id=?",
                (parent_id, str(request_id)),
            ).fetchone()
            if alias:
                if alias["digest"] != digest:
                    raise ParentChatError("request_id_conflict", 409)
                return self._observe(connection, parent_id, alias["job_id"])
            cutoff = connection.execute(
                "SELECT COALESCE(MAX(id),0) FROM parent_chat_turns "
                "WHERE parent_id=? AND message!=''",
                (parent_id,),
            ).fetchone()[0]
            row = connection.execute(
                "SELECT * FROM child_safety_jobs WHERE parent_id=? AND kind='child_data' "
                "AND child_key=? AND capability_key=? AND data_digest=?",
                (parent_id, child_id, capability, data_digest),
            ).fetchone()
            if row is None:
                if not allow_new:
                    raise ParentChatError("child_safety_worker_unavailable", 503)
                signal_times = self._signal_times(analysis.input)
                if max([analysis.occurred_at, *signal_times]) > now + timedelta(minutes=5):
                    raise ParentChatError("safety_observation_in_future", 422)
                if not self._capacity(connection, parent_id):
                    raise ParentChatError("safety_queue_full", 429)
                chat_cutoff = connection.execute(
                    "SELECT COALESCE(MAX(id),0) FROM parent_chat_turns WHERE parent_id=?",
                    (parent_id,),
                ).fetchone()[0]
                snapshot = self._snapshot(connection, parent_id, chat_cutoff)
                payload, context = analysis.model_dump_json(), snapshot.model_dump_json()
                if (
                    len(payload.encode()) + len(context.encode())
                    > self._safety_limits.max_context_bytes
                ):
                    raise ParentChatError("safety_context_too_large", 422)
                job_id = str(uuid4())
                connection.execute(
                    "INSERT INTO child_safety_jobs(job_id,parent_id,child_key,capability_key,kind,"
                    "source_revision,data_digest,parent_turn_cutoff,context,analysis,status,"
                    "created_at,updated_at,evaluated_at,signal_first_at,signal_last_at) "
                    "VALUES(?,?,?,?,'child_data',?,?,?,?,?,'queued',?,?,?,?,?)",
                    (
                        job_id,
                        parent_id,
                        child_id,
                        capability,
                        source_revision,
                        data_digest,
                        cutoff,
                        context,
                        payload,
                        now.isoformat(),
                        now.isoformat(),
                        self._utc(analysis.occurred_at).isoformat(),
                        min(signal_times).isoformat() if signal_times else None,
                        max(signal_times).isoformat() if signal_times else None,
                    ),
                )
            else:
                job_id = row["job_id"]
            connection.execute(
                "INSERT INTO child_safety_requests VALUES(?,?,?,?)",
                (parent_id, str(request_id), digest, job_id),
            )
            return self._observe(connection, parent_id, job_id)

    def _observe(
        self, connection: sqlite3.Connection, parent_id: str, job_id: str
    ) -> SafetyJobView:
        row = connection.execute(
            "SELECT * FROM child_safety_jobs WHERE parent_id=? AND job_id=?", (parent_id, job_id)
        ).fetchone()
        if row is None:
            raise ParentChatError("safety_assessment_not_found", 404)
        return self._view(row)

    async def assessment(self, parent_id: str, job_id: UUID) -> SafetyJobView:
        def read() -> SafetyJobView:
            with self._connect() as connection:
                return self._observe(connection, parent_id, str(job_id))

        return await asyncio.to_thread(read)

    async def saved_assessments(self, job: SafetyJob) -> list[SafetyJobView]:
        def read() -> list[SafetyJobView]:
            with self._connect() as connection:
                result = []
                for job_id in job.context.saved_assessment_ids:
                    row = connection.execute(
                        "SELECT * FROM child_safety_jobs WHERE parent_id=? AND job_id=? "
                        "AND status='completed' AND kind='child_data'",
                        (job.view.parent_id, str(job_id)),
                    ).fetchone()
                    if row is None:
                        raise ParentChatError("safety_saved_evidence_unavailable", 503)
                    result.append(self._view(row))
                return result

        return await asyncio.to_thread(read)

    async def materialize_parent_event(self, now: datetime) -> SafetyJobView | None:
        def materialize() -> SafetyJobView | None:
            with self._transaction() as connection:
                events = connection.execute(
                    "SELECT e.* FROM child_safety_parent_events e WHERE e.job_id IS NULL "
                    "AND (SELECT COUNT(*) FROM child_safety_jobs j WHERE j.parent_id=e.parent_id "
                    "AND j.status IN ('queued','preparing','submitted','unknown','metered'))<? "
                    "ORDER BY e.turn_id LIMIT 1",
                    (self._safety_limits.max_parent_pending_jobs,),
                ).fetchall()
                for event in events:
                    parent_id = event["parent_id"]
                    if not self._capacity(connection, parent_id):
                        continue
                    job_id = str(uuid4())
                    context = event["context"]
                    oversized = len(context.encode()) > self._safety_limits.max_context_bytes
                    connection.execute(
                        "INSERT INTO child_safety_jobs(job_id,parent_id,child_key,capability_key,"
                        "kind,source_revision,data_digest,parent_turn_cutoff,context,status,"
                        "created_at,updated_at,error_code) "
                        "VALUES(?,?,0,'','parent_message',?,?,?,?,?,?,?,?)",
                        (
                            job_id,
                            parent_id,
                            f"parent-turn:{event['turn_id']}",
                            self._hash(event["turn_id"]),
                            event["turn_id"],
                            context,
                            "failed" if oversized else "queued",
                            event["created_at"],
                            self._utc(now).isoformat(),
                            "safety_context_too_large" if oversized else None,
                        ),
                    )
                    connection.execute(
                        "UPDATE child_safety_parent_events SET job_id=? "
                        "WHERE parent_id=? AND turn_id=?",
                        (job_id, parent_id, event["turn_id"]),
                    )
                    return self._observe(connection, parent_id, job_id)
                return None

        return await asyncio.to_thread(materialize)

    def _recover(self, connection: sqlite3.Connection, now: datetime) -> None:
        connection.execute(
            "UPDATE child_safety_jobs SET status='failed',reserved=0,analysis=NULL,"
            "error_code='safety_preparation_abandoned',updated_at=? "
            "WHERE status='preparing' AND lease_expires_at<=?",
            (now.isoformat(), now.isoformat()),
        )
        connection.execute(
            "UPDATE child_safety_jobs SET status='unknown',"
            "error_code='safety_model_receipt_unknown',updated_at=? "
            "WHERE status='submitted' AND lease_expires_at<=?",
            (now.isoformat(), now.isoformat()),
        )
        connection.execute(
            "UPDATE child_safety_jobs SET status='failed',analysis=NULL,"
            "error_code='safety_result_processing_abandoned',updated_at=? "
            "WHERE status='metered' AND lease_expires_at<=?",
            (now.isoformat(), now.isoformat()),
        )
        connection.execute(
            "UPDATE child_safety_jobs SET status='failed',analysis=NULL,"
            "error_code='safety_queue_expired',updated_at=? "
            "WHERE status='queued' AND created_at<=?",
            (
                now.isoformat(),
                (now - timedelta(seconds=self._safety_limits.max_queue_age_seconds)).isoformat(),
            ),
        )

    def _budget(
        self, connection: sqlite3.Connection, parent_id: str | None, now: datetime
    ) -> SafetyBudget:
        day, reset = self._period(now)
        used, own_used = connection.execute(
            "SELECT COALESCE(SUM(input_tokens+output_tokens),0), "
            "COALESCE(SUM(CASE WHEN parent_id=? THEN input_tokens+output_tokens ELSE 0 END),0) "
            "FROM child_safety_jobs WHERE day=?",
            (parent_id, day),
        ).fetchone()
        reserved, own_reserved = connection.execute(
            "SELECT COALESCE(SUM(reserved),0),"
            "COALESCE(SUM(CASE WHEN parent_id=? THEN reserved ELSE 0 END),0) "
            "FROM child_safety_jobs WHERE status IN ('preparing','submitted','unknown')",
            (parent_id,),
        ).fetchone()
        return SafetyBudget(
            server_daily_limit=self._safety_limits.server_daily_tokens,
            server_used_tokens=used,
            server_reserved_tokens=reserved,
            server_remaining_tokens=max(
                0, self._safety_limits.server_daily_tokens - used - reserved
            ),
            parent_daily_limit=self._safety_limits.parent_daily_tokens,
            parent_used_tokens=own_used,
            parent_reserved_tokens=own_reserved,
            parent_remaining_tokens=max(
                0, self._safety_limits.parent_daily_tokens - own_used - own_reserved
            ),
            parent_blocked_by_unknown=connection.execute(
                "SELECT 1 FROM child_safety_jobs WHERE parent_id=? AND status='unknown'",
                (parent_id,),
            ).fetchone()
            is not None,
            resets_at=reset,
            timezone=self._zone.key,
        )

    async def safety_budget(self, parent_id: str, now: datetime) -> SafetyBudget:
        def read() -> SafetyBudget:
            with self._connect() as connection:
                return self._budget(connection, parent_id, now)

        return await asyncio.to_thread(read)

    async def claim_next(self, now: datetime) -> SafetyJob | None:
        return await asyncio.to_thread(self._claim_next, self._utc(now))

    def _claim_next(self, now: datetime) -> SafetyJob | None:
        with self._transaction() as connection:
            self._recover(connection, now)
            reserve = self._safety_limits.job_tokens
            if self._budget(connection, None, now).server_remaining_tokens < reserve:
                return None
            day, _ = self._period(now)
            attempts = connection.execute(
                "SELECT COUNT(*) FROM child_safety_jobs WHERE day=? AND claim_id IS NOT NULL",
                (day,),
            ).fetchone()[0]
            if attempts >= self._safety_limits.server_daily_attempts:
                return None
            # Filter eligibility in SQL before the bounded result page. A prefix
            # of exhausted parents must not starve eligible families behind it.
            row = connection.execute(
                "SELECT * FROM child_safety_jobs j WHERE status='queued' AND NOT EXISTS "
                "(SELECT 1 FROM child_safety_jobs p WHERE p.parent_id=j.parent_id "
                "AND p.status IN ('preparing','submitted','unknown','metered')) "
                "AND (SELECT COALESCE(SUM(p.input_tokens+p.output_tokens),0) "
                "FROM child_safety_jobs p WHERE p.parent_id=j.parent_id AND p.day=?)<=? "
                "AND (SELECT COUNT(*) FROM child_safety_jobs p WHERE p.parent_id=j.parent_id "
                "AND p.day=? AND p.claim_id IS NOT NULL)<? ORDER BY position LIMIT 1",
                (
                    day,
                    self._safety_limits.parent_daily_tokens - reserve,
                    day,
                    self._safety_limits.parent_daily_attempts,
                ),
            ).fetchone()
            if row is None:
                return None
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
    def _claimed(connection: sqlite3.Connection, job: SafetyJob) -> sqlite3.Row:
        row = cast(
            sqlite3.Row | None,
            connection.execute(
                "SELECT * FROM child_safety_jobs WHERE parent_id=? AND job_id=? AND claim_id=?",
                (job.view.parent_id, str(job.view.job_id), str(job.claim_id)),
            ).fetchone(),
        )
        if row is None:
            raise ParentChatError("safety_job_no_longer_claimed", 409)
        return row

    async def authorize_children(
        self, job: SafetyJob, child_ids: tuple[int, ...], now: datetime
    ) -> None:
        def authorize() -> None:
            if (
                any(type(i) is not int or i <= 0 for i in child_ids)
                or len(set(child_ids)) != len(child_ids)
                or len(child_ids) > 20
            ):
                raise ParentChatError("safety_child_context_invalid", 503)
            with self._transaction() as connection:
                row = self._claimed(connection, job)
                if (
                    row["status"] != "preparing"
                    or row["lease_expires_at"] <= self._utc(now).isoformat()
                ):
                    raise ParentChatError("safety_job_no_longer_claimed", 409)
                if job.view.child_id is not None and job.view.child_id not in child_ids:
                    raise ParentChatError("safety_child_not_authorized", 403)
                encoded = json.dumps(child_ids)
                if row["allowed_child_ids"] is not None and row["allowed_child_ids"] != encoded:
                    raise ParentChatError("safety_child_context_already_frozen", 409)
                connection.execute(
                    "UPDATE child_safety_jobs SET allowed_child_ids=? WHERE job_id=?",
                    (encoded, str(job.view.job_id)),
                )

        await asyncio.to_thread(authorize)

    async def submit_safety(self, job: SafetyJob, reserved_tokens: int, now: datetime) -> None:
        def submit() -> None:
            if type(reserved_tokens) is not int or reserved_tokens < 1:
                raise ParentChatError("safety_token_count_invalid", 503)
            with self._transaction() as connection:
                row = self._claimed(connection, job)
                if (
                    row["status"] != "preparing"
                    or row["lease_expires_at"] <= self._utc(now).isoformat()
                    or row["allowed_child_ids"] is None
                    or reserved_tokens > row["reserved"]
                ):
                    raise ParentChatError("safety_job_no_longer_claimed", 409)
                connection.execute(
                    "UPDATE child_safety_jobs SET status='submitted',reserved=?,updated_at=? "
                    "WHERE job_id=?",
                    (reserved_tokens, self._utc(now).isoformat(), str(job.view.job_id)),
                )

        await asyncio.to_thread(submit)

    async def record_usage(
        self, job: SafetyJob, usage: ChatTokens, model: str, now: datetime
    ) -> bool:
        def record() -> bool:
            with self._transaction() as connection:
                row = self._claimed(connection, job)
                if row["status"] not in {"submitted", "unknown"} or row["input_tokens"] is not None:
                    raise ParentChatError("safety_receipt_already_settled", 409)
                over = usage.total > row["reserved"]
                late = row["lease_expires_at"] <= self._utc(now).isoformat()
                error = (
                    "safety_usage_exceeded_hold"
                    if over
                    else ("safety_late_receipt_discarded" if late else None)
                )
                connection.execute(
                    "UPDATE child_safety_jobs SET status=?,reserved=0,"
                    "input_tokens=?,output_tokens=?,"
                    "model=?,updated_at=?,error_code=?,"
                    "analysis=CASE WHEN ? THEN NULL ELSE analysis END WHERE job_id=?",
                    (
                        "unknown" if over else ("failed" if late else "metered"),
                        usage.input_tokens,
                        usage.output_tokens,
                        model if 0 < len(model) <= 128 else None,
                        self._utc(now).isoformat(),
                        error,
                        late and not over,
                        str(job.view.job_id),
                    ),
                )
                return not over and not late

        return await asyncio.to_thread(record)

    async def fail_safety(
        self,
        job: SafetyJob,
        code: str,
        now: datetime,
        *,
        definite_model_rejection: bool = False,
    ) -> None:
        def fail() -> None:
            with self._transaction() as connection:
                row = self._claimed(connection, job)
                if row["status"] not in {"preparing", "submitted", "metered"}:
                    return
                unknown = row["status"] == "submitted" and not definite_model_rejection
                if definite_model_rejection and code != "model_request_rejected":
                    raise ParentChatError("safety_rejection_not_classified", 503)
                connection.execute(
                    "UPDATE child_safety_jobs SET status=?,"
                    "reserved=CASE WHEN ? THEN reserved ELSE 0 END,"
                    "analysis=CASE WHEN ? THEN analysis ELSE NULL END,error_code=?,"
                    "updated_at=? WHERE job_id=?",
                    (
                        "unknown" if unknown else "failed",
                        unknown,
                        unknown,
                        "safety_model_receipt_unknown" if unknown else code,
                        self._utc(now).isoformat(),
                        str(job.view.job_id),
                    ),
                )

        await asyncio.to_thread(fail)

    async def finish_safety(
        self,
        job: SafetyJob,
        result: SafetyStoredResult,
        now: datetime,
        *,
        question: AgentQuestionRequest | None = None,
    ) -> SafetyJobView:
        def finish() -> SafetyJobView:
            with self._transaction() as connection:
                row = self._claimed(connection, job)
                if (
                    row["status"] != "metered"
                    or row["lease_expires_at"] <= self._utc(now).isoformat()
                ):
                    raise ParentChatError("safety_job_no_longer_claimed", 409)
                if row["kind"] == "child_data":
                    if (
                        result.analysis is None
                        or result.analysis.capability.value != row["capability_key"]
                        or result.analysis.request_id != json.loads(row["analysis"])["request_id"]
                    ):
                        raise ParentChatError("safety_result_mismatch", 503)
                elif result.analysis is not None:
                    raise ParentChatError("safety_result_mismatch", 503)
                if result.question_id is not None:
                    raise ParentChatError("safety_question_identity_not_host_owned", 503)
                saved = result
                if question is not None:
                    allowed = json.loads(row["allowed_child_ids"])
                    if (
                        question.parent_id != row["parent_id"]
                        or question.child_id not in allowed
                        or question.agent_id != "child-safety"
                    ):
                        raise ParentChatError("safety_question_scope_mismatch", 403)
                    receipt = self._enqueue_in_transaction(connection, question, self._utc(now))
                    saved = result.model_copy(update={"question_id": receipt.question.question_id})
                connection.execute(
                    "UPDATE child_safety_jobs SET status='completed',analysis=NULL,"
                    "result=?,updated_at=? "
                    "WHERE job_id=?",
                    (saved.model_dump_json(), self._utc(now).isoformat(), str(job.view.job_id)),
                )
                self._notice_from_assessment(connection, str(job.view.job_id), self._utc(now))
                return self._observe(connection, row["parent_id"], row["job_id"])

        return await asyncio.to_thread(finish)

    async def assessments(self, parent_id: str, *, after: int, limit: int) -> SafetyAssessmentPage:
        if after < 0 or not 1 <= limit <= 100:
            raise ParentChatError("invalid_safety_cursor", 422)

        def read() -> SafetyAssessmentPage:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT * FROM child_safety_jobs WHERE parent_id=? AND position>? "
                    "ORDER BY position LIMIT ?",
                    (parent_id, after, limit + 1),
                ).fetchall()
                selected = rows[:limit]
                return SafetyAssessmentPage(
                    parent_id=parent_id,
                    assessments=[self._view(r) for r in selected],
                    next_after=selected[-1]["position"] if len(rows) > limit else None,
                )

        return await asyncio.to_thread(read)

    async def next_delivery(self, now: datetime) -> ParentTouchDeliveryRequest | None:
        notice = await self.notice_delivery(now)
        if notice is not None:
            return notice

        def read() -> ParentTouchDeliveryRequest | None:
            day, _ = self._period(now)
            with self._transaction() as connection:
                stale = connection.execute(
                    "SELECT DISTINCT parent_id FROM parent_chat_turns WHERE status IN "
                    "('preparing','submitted') AND updated_at<? LIMIT 100",
                    ((self._utc(now) - timedelta(minutes=5)).isoformat(),),
                ).fetchall()
                for item in stale:
                    self._recover_pre_dispatch(connection, item[0], self._utc(now))
                row = connection.execute(
                    "SELECT q.*, (SELECT MAX(t.id) FROM parent_chat_turns t WHERE "
                    "t.parent_id=q.parent_id AND t.message!='') AS language_turn "
                    "FROM family_questions q "
                    "LEFT JOIN parent_chat_quota b ON b.parent_id=q.parent_id AND b.day=? "
                    "WHERE q.status='queued' AND q.expires_at>? AND language_turn IS NOT NULL "
                    "AND COALESCE(b.used,0)<? AND COALESCE(b.attempts,0)<? "
                    "AND NOT EXISTS (SELECT 1 FROM parent_chat_turns t "
                    "WHERE t.parent_id=q.parent_id "
                    "AND t.status IN ('preparing','submitted','unknown')) "
                    "AND NOT EXISTS (SELECT 1 FROM family_questions a "
                    "WHERE a.parent_id=q.parent_id "
                    "AND a.status IN ('offered','awaiting_reply','held')) "
                    "AND NOT EXISTS (SELECT 1 FROM family_turn_metadata m "
                    "WHERE m.parent_id=q.parent_id "
                    "AND m.kind='delivery' AND m.offered_question_id=q.question_id "
                    "AND m.language_turn_id=language_turn) "
                    "ORDER BY q.priority DESC,q.position LIMIT 1",
                    (day, self._utc(now).isoformat(), self._limit - 31, self._max_attempts),
                ).fetchone()
                return (
                    ParentTouchDeliveryRequest(
                        parent_id=row["parent_id"],
                        request_id=uuid5(
                            UUID(row["question_id"]), f"delivery:{row['language_turn']}"
                        ),
                    )
                    if row
                    else None
                )

        return await asyncio.to_thread(read)
