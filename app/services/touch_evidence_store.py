"""Minimized dated report memory and delivery owned exclusively by Parent-Touch."""

import asyncio
import hashlib
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta
from uuid import UUID, uuid4, uuid5

from app.mana_ai.application.chat_ports import ChatModelReceipt, ParentChatError
from app.mana_ai.domain.chat import ParentChatRequest, StoredChatTurn
from app.mana_ai.domain.child_safety import SafetyStoredResult
from app.mana_ai.domain.enums import AnalysisVerdict, ManaAICapability, RiskLevel
from app.mana_ai.domain.family_agents import (
    FamilyNotice,
    FamilyQuestion,
    ParentTouchAssessment,
    ParentTouchDeliveryRequest,
    ParentTouchEvidence,
    ParentTouchFinding,
    ParentTouchHistory,
    ParentTouchNotice,
)
from app.services.family_agent_store import SqliteFamilyAgentStore


class SqliteTouchEvidenceStore(SqliteFamilyAgentStore):
    _schema_version = 5
    evidence_tables = frozenset(
        {"family_notices", "family_touch_evidence", "family_evidence_epoch"}
    )

    def _supported_versions(self) -> set[int]:
        return super()._supported_versions() | {3, 4}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | set(self.evidence_tables)

    def _extra_schema(self) -> str:
        return (
            super()._extra_schema()
            + """
            CREATE TABLE IF NOT EXISTS family_notices (
                position INTEGER PRIMARY KEY AUTOINCREMENT,
                notice_id TEXT NOT NULL UNIQUE,
                parent_id TEXT NOT NULL,
                child_id INTEGER NOT NULL,
                source_job_id TEXT NOT NULL UNIQUE,
                capability TEXT NOT NULL,
                kind TEXT NOT NULL,
                status TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                offered_turn_id INTEGER,
                delivered_turn_id INTEGER
            );
            CREATE UNIQUE INDEX IF NOT EXISTS family_one_pending_notice
                ON family_notices(parent_id) WHERE status IN ('offered','held');
            CREATE INDEX IF NOT EXISTS family_notice_queue
                ON family_notices(parent_id,status,kind,position);
            CREATE TABLE IF NOT EXISTS family_touch_evidence (
                parent_id TEXT NOT NULL,
                turn_id INTEGER NOT NULL UNIQUE,
                payload TEXT NOT NULL,
                digest TEXT NOT NULL,
                PRIMARY KEY(parent_id,turn_id)
            );
            CREATE TABLE IF NOT EXISTS family_evidence_epoch (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                through_turn_id INTEGER NOT NULL
            );
            INSERT OR IGNORE INTO family_evidence_epoch
                SELECT 1,COALESCE(MAX(id),0) FROM parent_chat_turns;
        """
        )

    @staticmethod
    def _projection(row: sqlite3.Row) -> ParentTouchAssessment:
        result = SafetyStoredResult.model_validate_json(row["result"])
        if result.analysis is None:
            raise ParentChatError("touch_assessment_unavailable", 503)
        ranks = list(RiskLevel)
        significant = sorted(
            result.analysis.findings,
            key=lambda finding: ranks.index(finding.risk_level),
            reverse=True,
        )[:1]
        return ParentTouchAssessment(
            assessment_id=row["job_id"],
            child_id=row["child_key"],
            capability=row["capability_key"],
            status=result.analysis.status,
            verdict=result.analysis.verdict,
            summary=result.analysis.summary,
            data_quality_notes=result.analysis.data_quality_notes,
            evaluated_at=row["evaluated_at"],
            signal_first_observed_at=row["signal_first_at"],
            signal_last_observed_at=row["signal_last_at"],
            processed_at=result.analysis.processed_at,
            significant_findings=[
                ParentTouchFinding(
                    category=finding.category,
                    risk_level=finding.risk_level,
                    summary=finding.summary,
                    recommendation=finding.recommendation,
                )
                for finding in significant
            ],
            available_finding_count=len(result.analysis.findings),
        )

    def _notice_from_assessment(
        self, connection: sqlite3.Connection, job_id: str, now: datetime
    ) -> None:
        row = connection.execute(
            "SELECT * FROM child_safety_jobs WHERE job_id=? "
            "AND status='completed' AND kind='child_data'",
            (job_id,),
        ).fetchone()
        if row is None:
            return
        report = self._projection(row)
        if report.verdict in {AnalysisVerdict.ALERT, AnalysisVerdict.BLOCK}:
            kind = "urgent"
        elif (
            report.verdict == AnalysisVerdict.WARN
            or report.capability == ManaAICapability.FAMILY_DIGEST
        ):
            kind = "assessment"
        else:
            return  # Saved context remains available without noisy unsolicited messages.
        if kind == "assessment":
            connection.execute(
                "UPDATE family_notices SET status='superseded' WHERE parent_id=? AND child_id=? "
                "AND capability=? AND kind='assessment' AND status IN ('queued','deferred')",
                (row["parent_id"], row["child_key"], row["capability_key"]),
            )
        notice = FamilyNotice(
            notice_id=uuid4(),
            parent_id=row["parent_id"],
            agent_id="child-safety",
            kind=kind,
            assessment=report,
            expires_at=now + timedelta(days=1),
        )
        connection.execute(
            "INSERT INTO family_notices(notice_id,parent_id,child_id,source_job_id,capability,"
            "kind,status,payload,created_at,expires_at) VALUES(?,?,?,?,?,?,'queued',?,?,?)",
            (
                str(notice.notice_id),
                notice.parent_id,
                report.child_id,
                job_id,
                report.capability.value,
                kind,
                notice.model_dump_json(),
                now.isoformat(),
                notice.expires_at.isoformat(),
            ),
        )

    def _admit_extra_context(
        self,
        connection: sqlite3.Connection,
        request: ParentChatRequest,
        turn_id: int,
        selected: FamilyQuestion | None,
        now: datetime,
    ) -> str | None:
        connection.execute(
            "UPDATE family_notices SET status='expired' WHERE parent_id=? "
            "AND status IN ('queued','deferred') AND expires_at<=?",
            (request.parent_id, now.isoformat()),
        )
        row = connection.execute(
            "SELECT * FROM family_notices n WHERE parent_id=? AND status IN ('queued','deferred') "
            "AND (kind='urgent' OR NOT EXISTS (SELECT 1 FROM family_questions q WHERE "
            "q.parent_id=n.parent_id AND q.status IN ('awaiting_reply','held'))) "
            "ORDER BY CASE kind WHEN 'urgent' THEN 0 ELSE 1 END,position LIMIT 1",
            (request.parent_id,),
        ).fetchone()
        notice = FamilyNotice.model_validate_json(row["payload"]) if row else None
        if notice is not None:
            if notice.parent_id != request.parent_id or str(notice.notice_id) != row["notice_id"]:
                raise ParentChatError("touch_notice_scope_mismatch", 503)
            connection.execute(
                "UPDATE family_notices SET status='offered',offered_turn_id=? WHERE notice_id=?",
                (turn_id, str(notice.notice_id)),
            )
        latest = connection.execute(
            "SELECT * FROM child_safety_jobs WHERE parent_id=? AND status='completed' "
            "AND kind IN ('child_data','source_review') ORDER BY position DESC LIMIT 1",
            (request.parent_id,),
        ).fetchone()
        total = connection.execute(
            "SELECT COUNT(*) FROM child_safety_jobs WHERE parent_id=? "
            "AND status='completed' AND kind IN ('child_data','source_review')",
            (request.parent_id,),
        ).fetchone()[0]
        context = ParentTouchEvidence(
            assessments=[notice.assessment]
            if notice
            else ([self._projection(latest)] if latest else []),
            available_assessment_count=total,
            notice=notice,
        )
        payload = context.model_dump_json()
        connection.execute(
            "INSERT INTO family_touch_evidence VALUES(?,?,?,?)",
            (
                request.parent_id,
                turn_id,
                payload,
                self._bound_digest(request.parent_id, turn_id, payload),
            ),
        )
        return (
            f"notice:{notice.notice_id}"
            if notice
            else super()._admit_extra_context(connection, request, turn_id, selected, now)
        )

    @staticmethod
    def _bound_digest(parent_id: str, turn_id: int, payload: str) -> str:
        return hashlib.sha256(f"{parent_id}:{turn_id}:{payload}".encode()).hexdigest()

    async def evidence_for_turn(
        self, parent_id: str, turn_id: int, connected: tuple[int, ...]
    ) -> ParentTouchEvidence | None:
        def read() -> ParentTouchEvidence | None:
            with self._transaction() as connection:
                row = connection.execute(
                    "SELECT * FROM family_touch_evidence WHERE parent_id=? AND turn_id=?",
                    (parent_id, turn_id),
                ).fetchone()
                if row is None:
                    epoch = connection.execute(
                        "SELECT through_turn_id FROM family_evidence_epoch WHERE singleton=1"
                    ).fetchone()[0]
                    if turn_id > epoch:
                        raise ParentChatError("touch_context_missing", 503)
                    return None
                if row["digest"] != self._bound_digest(parent_id, turn_id, row["payload"]):
                    raise ParentChatError("touch_context_changed", 503)
                context = ParentTouchEvidence.model_validate_json(row["payload"])
                # Before generation, revoke only this turn's unpublished choices.
                # Never dispatch another choice or release an unknown paid call.
                for question in connection.execute(
                    "SELECT * FROM family_questions WHERE parent_id=? "
                    "AND offered_turn_id=? AND status='offered'",
                    (parent_id, turn_id),
                ).fetchall():
                    if question["child_id"] is not None and question["child_id"] not in connected:
                        connection.execute(
                            "UPDATE family_questions SET status='cancelled' WHERE question_id=?",
                            (question["question_id"],),
                        )
                notice = context.notice
                if notice is not None and notice.parent_id != parent_id:
                    raise ParentChatError("touch_notice_scope_mismatch", 503)
                if notice is not None and notice.assessment.child_id not in connected:
                    connection.execute(
                        "UPDATE family_notices SET status='cancelled' WHERE parent_id=? "
                        "AND notice_id=? AND status='offered'",
                        (parent_id, str(notice.notice_id)),
                    )
                    notice = None
                return context.model_copy(
                    update={
                        "assessments": [a for a in context.assessments if a.child_id in connected],
                        "notice": notice,
                    }
                )

        return await asyncio.to_thread(read)

    def _valid_decision(
        self,
        connection: sqlite3.Connection,
        turn: StoredChatTurn,
        receipt: ChatModelReceipt,
        now: datetime,
    ) -> bool:
        if not super()._valid_decision(connection, turn, replace(receipt, notice_id=None), now):
            return False
        row = connection.execute(
            "SELECT notice_id,kind FROM family_notices WHERE parent_id=? AND offered_turn_id=? "
            "AND status IN ('offered','held') AND expires_at>?",
            (turn.parent_id, turn.turn_id, now.isoformat()),
        ).fetchone()
        if row and row["kind"] == "assessment" and receipt.notice_id is None:
            return True
        return (str(receipt.notice_id) if receipt.notice_id else None) == (row[0] if row else None)

    def _on_settled(
        self,
        connection: sqlite3.Connection,
        turn: StoredChatTurn,
        receipt: ChatModelReceipt,
        *,
        valid: bool,
    ) -> None:
        super()._on_settled(connection, turn, receipt, valid=valid)
        connection.execute(
            "UPDATE family_notices SET status=?,delivered_turn_id=? WHERE parent_id=? "
            "AND offered_turn_id=? AND status IN ('offered','held')",
            (
                "delivered" if valid and receipt.notice_id else "deferred" if valid else "queued",
                turn.turn_id if valid and receipt.notice_id else None,
                turn.parent_id,
                turn.turn_id,
            ),
        )

    def _on_failed(
        self, connection: sqlite3.Connection, turn: StoredChatTurn, *, unknown: bool
    ) -> None:
        super()._on_failed(connection, turn, unknown=unknown)
        connection.execute(
            "UPDATE family_notices SET status=? WHERE parent_id=? "
            "AND offered_turn_id=? AND status='offered'",
            ("held" if unknown else "queued", turn.parent_id, turn.turn_id),
        )

    @staticmethod
    def _recover_pre_dispatch(
        connection: sqlite3.Connection, parent_id: str, now: datetime
    ) -> None:
        SqliteFamilyAgentStore._recover_pre_dispatch(connection, parent_id, now)
        connection.execute(
            "UPDATE family_notices SET status='queued' WHERE parent_id=? AND status='offered' "
            "AND offered_turn_id IN (SELECT id FROM parent_chat_turns WHERE parent_id=? "
            "AND status='failed')",
            (parent_id, parent_id),
        )
        connection.execute(
            "UPDATE family_notices SET status='held' WHERE parent_id=? AND status='offered' "
            "AND offered_turn_id IN (SELECT id FROM parent_chat_turns WHERE parent_id=? "
            "AND status='unknown')",
            (parent_id, parent_id),
        )

    @staticmethod
    def _public_notice(row: sqlite3.Row) -> ParentTouchNotice:
        return ParentTouchNotice(
            notice_id=row["notice_id"],
            child_id=row["child_id"],
            turn_id=row["delivered_turn_id"],
            kind=row["kind"],
        )

    async def delivered_notice(self, parent_id: str, request_id: UUID) -> ParentTouchNotice | None:
        def read() -> ParentTouchNotice | None:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT n.* FROM family_notices n JOIN parent_chat_turns t "
                    "ON t.id=n.delivered_turn_id AND t.parent_id=n.parent_id "
                    "WHERE n.parent_id=? AND t.request_id=? AND n.status='delivered'",
                    (parent_id, str(request_id)),
                ).fetchone()
                return self._public_notice(row) if row else None

        return await asyncio.to_thread(read)

    def _enrich_history(
        self, connection: sqlite3.Connection, history: ParentTouchHistory
    ) -> ParentTouchHistory:
        ids = {m.turn_id for m in history.messages if m.role == "assistant"}
        notices = []
        for turn_id in sorted(ids):
            row = connection.execute(
                "SELECT * FROM family_notices WHERE parent_id=? "
                "AND status='delivered' AND delivered_turn_id=?",
                (history.parent_id, turn_id),
            ).fetchone()
            if row is not None:
                notices.append(self._public_notice(row))
        pending = connection.execute(
            "SELECT COUNT(*) FROM family_notices WHERE parent_id=? "
            "AND status IN ('queued','deferred','offered','held')",
            (history.parent_id,),
        ).fetchone()[0]
        return history.model_copy(update={"message_notices": notices, "pending_notices": pending})

    async def notice_delivery(self, now: datetime) -> ParentTouchDeliveryRequest | None:
        def read() -> ParentTouchDeliveryRequest | None:
            day, _ = self._period(now)
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT n.*, (SELECT MAX(t.id) FROM parent_chat_turns t "
                    "WHERE t.parent_id=n.parent_id AND t.message!='') AS language_turn "
                    "FROM family_notices n LEFT JOIN parent_chat_quota b "
                    "ON b.parent_id=n.parent_id AND b.day=? "
                    "WHERE n.status='queued' AND n.expires_at>? AND language_turn IS NOT NULL "
                    "AND COALESCE(b.used,0)<? AND COALESCE(b.attempts,0)<? "
                    "AND NOT EXISTS (SELECT 1 FROM parent_chat_turns t "
                    "WHERE t.parent_id=n.parent_id "
                    "AND t.status IN ('preparing','submitted','unknown')) "
                    "AND (n.kind='urgent' OR NOT EXISTS (SELECT 1 FROM family_questions q "
                    "WHERE q.parent_id=n.parent_id "
                    "AND q.status IN ('offered','awaiting_reply','held'))) "
                    "AND NOT EXISTS (SELECT 1 FROM family_turn_metadata m "
                    "WHERE m.parent_id=n.parent_id "
                    "AND m.offered_question_id='notice:'||n.notice_id "
                    "AND m.language_turn_id=language_turn) "
                    "ORDER BY CASE n.kind WHEN 'urgent' THEN 0 ELSE 1 END,n.position LIMIT 1",
                    (day, self._utc(now).isoformat(), self._limit - 31, self._max_attempts),
                ).fetchone()
                return (
                    ParentTouchDeliveryRequest(
                        parent_id=row["parent_id"],
                        request_id=uuid5(
                            UUID(row["notice_id"]), f"delivery:{row['language_turn']}"
                        ),
                    )
                    if row
                    else None
                )

        return await asyncio.to_thread(read)
