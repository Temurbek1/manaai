"""Family v13: one metered specialist review per immutable source bundle."""

import asyncio
import sqlite3
from datetime import datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.domain.child_safety import (
    SafetyContextSnapshot,
    SafetyJob,
    SafetyJobView,
    SafetyStoredResult,
)
from app.mana_ai.domain.enums import AnalysisStatus, AnalysisVerdict, ManaAICapability
from app.mana_ai.domain.family_agents import FamilyNotice, ParentTouchAssessment
from app.mana_ai.domain.source_reviews import (
    SourceAnalysisOwner,
    SourceReviewBundle,
    SourceReviewWork,
)
from app.services.proactive_parent_store import _current_context
from app.services.source_tool_safety_store import (
    SqliteClosedObservationToolSafetyStore,
    SqliteObservationToolSafetyStore,
)

_TABLE = "source_review_capture"


class SqliteSourceReviewSafetyStore(SqliteObservationToolSafetyStore):
    _schema_version = 13

    def _push_delivery_ready(
        self, connection: sqlite3.Connection, row: sqlite3.Row, now: datetime
    ) -> bool:
        notices = connection.execute(
            "SELECT capability,kind FROM family_notices WHERE parent_id=? AND delivered_turn_id=?",
            (row["parent_id"], row["turn_id"]),
        ).fetchall()
        if any(n["kind"] == "urgent" for n in notices):
            return True
        source_question = connection.execute(
            "SELECT 1 FROM family_turn_metadata m JOIN child_safety_jobs j "
            "ON json_extract(j.result,'$.question_id')=m.offered_question_id "
            "AND j.parent_id=m.parent_id WHERE m.parent_id=? AND m.turn_id=? "
            "AND j.kind='source_review'",
            (row["parent_id"], row["turn_id"]),
        ).fetchone()
        if not source_question and not any(n["capability"] == "source-review" for n in notices):
            return True
        context = _current_context(connection, row["parent_id"], now)
        if context is None:
            return False
        hour = now.astimezone(ZoneInfo(context.timezone)).hour
        start, end = (
            self._conversion_policy.quiet_start_hour,
            self._conversion_policy.quiet_end_hour,
        )
        quiet = hour >= start or hour < end if start > end else start <= hour < end
        return not quiet

    def _supported_versions(self) -> set[int]:
        return super()._supported_versions() | {12}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | {_TABLE}

    def _extra_schema(self) -> str:
        return super()._extra_schema() + (
            "CREATE TABLE IF NOT EXISTS source_review_capture (parent_id TEXT NOT NULL,"
            "turn_id INTEGER NOT NULL UNIQUE,PRIMARY KEY(parent_id,turn_id));"
        )

    def _on_admitted(
        self, connection: sqlite3.Connection, request: object, turn_id: int, now: datetime
    ) -> None:
        from app.mana_ai.domain.chat import ParentChatRequest

        assert isinstance(request, ParentChatRequest)
        super()._on_admitted(connection, request, turn_id, now)
        if request.message:
            connection.execute(
                "INSERT INTO source_review_capture VALUES(?,?)", (request.parent_id, turn_id)
            )

    async def source_review_owner(self, job: SafetyJob) -> SourceAnalysisOwner | None:
        def read() -> SourceAnalysisOwner | None:
            with self._connect() as db:
                if job.view.kind != "parent_message":
                    return None
                # Attribution is observation, not a new tool grant. A historical
                # captured invocation retains its original protocol and exact
                # call pairing while suppressing a duplicate background review.
                self._native(db, job)
                return SourceAnalysisOwner(parent_id=job.view.parent_id, job_id=job.view.job_id)

        return await asyncio.to_thread(read)

    async def admit_source_review(
        self, work: SourceReviewWork, now: datetime, *, allow_new: bool
    ) -> SafetyJobView:
        return await asyncio.to_thread(self._admit_source_review, work, self._utc(now), allow_new)

    def _admit_source_review(
        self, work: SourceReviewWork, now: datetime, allow_new: bool
    ) -> SafetyJobView:
        bundle = SourceReviewBundle.model_validate(work.bundle.model_dump())
        if (
            work.profile_collected_at is None
            or work.child_age is None
            or not (now - timedelta(seconds=180) <= work.profile_collected_at <= now)
        ):
            raise ParentChatError("source_review_ownership_denied", 403)
        parent, child, digest = bundle.parent_id, bundle.child_id, bundle.digest()
        request_digest = self._hash(
            {"review": str(work.review_id), "bundle": bundle.model_dump(mode="json")}
        )
        with self._transaction() as db:
            alias = db.execute(
                "SELECT * FROM child_safety_requests WHERE parent_id=? AND request_id=?",
                (parent, str(work.review_id)),
            ).fetchone()
            if alias is not None:
                if alias["digest"] != request_digest:
                    raise ParentChatError("request_id_conflict", 409)
                return self._observe(db, parent, alias["job_id"])
            prior = db.execute(
                "SELECT * FROM child_safety_jobs WHERE parent_id=? AND child_key=? "
                "AND kind='source_review' AND data_digest=?",
                (parent, child, digest),
            ).fetchone()
            if prior is None:
                if not allow_new or not self._capacity(db, parent):
                    raise ParentChatError("safety_queue_full", 429)
                cutoff = db.execute(
                    "SELECT COALESCE(MAX(id),0) FROM parent_chat_turns WHERE parent_id=?", (parent,)
                ).fetchone()[0]
                context = self._snapshot(db, parent, cutoff)
                snapshot = SafetyContextSnapshot.model_validate(
                    context.model_dump()
                    | {
                        "version": 3,
                        "review_first": False,
                        "source_review": bundle.model_dump(mode="json"),
                    }
                )
                payload = snapshot.model_dump_json()
                if len(payload.encode()) > self._safety_limits.max_context_bytes:
                    raise ParentChatError("safety_context_too_large", 422)
                identity = str(uuid4())
                db.execute(
                    "INSERT INTO child_safety_jobs(job_id,parent_id,child_key,capability_key,kind,"
                    "source_revision,data_digest,parent_turn_cutoff,context,status,"
                    "created_at,updated_at) "
                    "VALUES(?,?,?,'','source_review',?,?,?,?,'queued',?,?)",
                    (
                        identity,
                        parent,
                        child,
                        digest,
                        digest,
                        cutoff,
                        payload,
                        now.isoformat(),
                        now.isoformat(),
                    ),
                )
            else:
                identity = prior["job_id"]
            db.execute(
                "INSERT INTO child_safety_requests VALUES(?,?,?,?)",
                (
                    parent,
                    str(work.review_id),
                    request_digest,
                    identity,
                ),
            )
            return self._observe(db, parent, identity)

    async def observe_source_review(self, work: SourceReviewWork) -> SafetyJobView | None:
        digest = self._hash(
            {"review": str(work.review_id), "bundle": work.bundle.model_dump(mode="json")}
        )

        def observe() -> SafetyJobView | None:
            with self._connect() as db:
                row = db.execute(
                    "SELECT * FROM child_safety_requests WHERE parent_id=? AND request_id=?",
                    (work.bundle.parent_id, str(work.review_id)),
                ).fetchone()
                if row is None:
                    return None
                if row["digest"] != digest:
                    raise ParentChatError("request_id_conflict", 409)
                return self._observe(db, work.bundle.parent_id, row["job_id"])

        return await asyncio.to_thread(observe)

    @classmethod
    def _job(cls, row: sqlite3.Row) -> SafetyJob:
        job = super()._job(row)
        if (job.view.kind == "source_review") != (job.context.source_review is not None):
            raise ParentChatError("source_review_state_invalid", 503)
        if job.view.kind == "source_review" and (
            job.analysis is not None
            or row["capability_key"]
            or job.context.source_review is None
            or job.context.source_review.parent_id != job.view.parent_id
            or job.context.source_review.child_id != job.view.child_id
            or job.context.source_review.digest() != job.data_digest
        ):
            raise ParentChatError("source_review_state_invalid", 503)
        return job

    @staticmethod
    def _projection(row: sqlite3.Row) -> ParentTouchAssessment:
        if row["kind"] != "source_review":
            return SqliteObservationToolSafetyStore._projection(row)
        result = SafetyStoredResult.model_validate_json(row["result"])
        bundle = SafetyContextSnapshot.model_validate_json(row["context"]).source_review
        if bundle is None or result.followup_summary is None:
            raise ParentChatError("source_review_state_invalid", 503)
        return ParentTouchAssessment(
            assessment_id=row["job_id"],
            child_id=bundle.child_id,
            capability=ManaAICapability.FAMILY_DIGEST,
            status=AnalysisStatus.COMPLETED,
            verdict=AnalysisVerdict.INSUFFICIENT_DATA,
            summary=result.followup_summary,
            data_quality_notes=[
                "Source snapshots are partial; collection/review is not observation. "
                "App counter period/timezone and current device connectivity remain unknown."
            ],
            evaluated_at=bundle.frozen_at,
            signal_first_observed_at=None,
            signal_last_observed_at=None,
            processed_at=row["updated_at"],
        )

    def _notice_from_assessment(
        self, connection: sqlite3.Connection, job_id: str, now: datetime
    ) -> None:
        row = connection.execute(
            "SELECT * FROM child_safety_jobs WHERE job_id=? AND status='completed'", (job_id,)
        ).fetchone()
        if row is None or row["kind"] != "source_review":
            return super()._notice_from_assessment(connection, job_id, now)
        result = SafetyStoredResult.model_validate_json(row["result"])
        if result.source_review_notify is not True:
            return
        job = self._job(row)
        bundle = job.context.source_review
        assert bundle is not None and result.followup_summary is not None
        report = self._projection(row)
        notice = FamilyNotice(
            notice_id=uuid4(),
            parent_id=bundle.parent_id,
            agent_id="child-safety",
            kind="assessment",
            assessment=report,
            expires_at=now + timedelta(days=1),
            source_observations=tuple(s.facts for s in bundle.snapshots),
        )
        connection.execute(
            "UPDATE family_notices SET status='superseded' WHERE parent_id=? AND child_id=? "
            "AND capability='source-review' AND status IN ('queued','deferred')",
            (bundle.parent_id, bundle.child_id),
        )
        connection.execute(
            "INSERT INTO family_notices(notice_id,parent_id,child_id,source_job_id,capability,"
            "kind,status,payload,created_at,expires_at) "
            "VALUES(?,?,?,?,'source-review','assessment',"
            "'queued',?,?,?)",
            (
                str(notice.notice_id),
                bundle.parent_id,
                bundle.child_id,
                job_id,
                notice.model_dump_json(),
                now.isoformat(),
                notice.expires_at.isoformat(),
            ),
        )


class SqliteClosedSourceReviewSafetyStore(SqliteClosedObservationToolSafetyStore):
    _schema_version = 13

    def _supported_versions(self) -> set[int]:
        return {13}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | {_TABLE}
