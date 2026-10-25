"""Source v5: one family/day page, shared admissions and durable ownership holds."""

import asyncio
import hashlib
import json
import sqlite3
from datetime import datetime, timedelta
from uuid import UUID, uuid4, uuid5
from zoneinfo import ZoneInfo

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.domain.family_day_usage import (
    DAY_USAGE_SOURCE,
    DayUsageClaim,
    DayUsageReceipt,
    DayUsageTarget,
    FamilyDayUsagePage,
)
from app.mana_ai.domain.family_sources import FamilySourceReceipt, FamilySourceTarget
from app.mana_ai.domain.source_reviews import SourceAnalysisOwner
from app.services.source_review_cache import SqliteSourceReviewCache


def day_page_fingerprint(page: FamilyDayUsagePage) -> str:
    payload = page.model_dump(mode="json", exclude={"collected_at", "ownership_collected_at"})
    children = []
    for child in sorted(page.children, key=lambda item: item.child_id):
        item = child.model_dump(mode="json", exclude={"collected_at"})
        item["entries"] = sorted(
            item["entries"], key=lambda entry: (entry["app_name"], entry["provider_recorded_at"])
        )
        children.append(item)
    payload["children"] = children
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class SqliteDayUsageCache(SqliteSourceReviewCache):
    _schema_version = 5
    _extra_tables = SqliteSourceReviewCache._extra_tables | frozenset(
        {
            "day_usage_policy",
            "day_usage_snapshots",
            "day_usage_heads",
            "day_usage_ownership",
            "day_usage_owners",
        }
    )

    def _day_admitted(self, db: sqlite3.Connection, target: DayUsageTarget) -> None:
        """Optional consumers capture new admission policy before external I/O."""

    def _day_finalized(
        self,
        db: sqlite3.Connection,
        target: DayUsageTarget,
        result: DayUsageReceipt,
        page: FamilyDayUsagePage | None,
        checked_at: datetime | None,
    ) -> None:
        """Optional change journal shares the verified source completion transaction."""

    def _upgrade_versions(self) -> set[int]:
        return super()._upgrade_versions() | {4}

    def _version_tables(self, version: int) -> set[str]:
        result = super()._version_tables(version)
        return result | set(SqliteSourceReviewCache._extra_tables) if version == 4 else result

    def _extra_schema(self) -> tuple[str, ...]:
        return super()._extra_schema() + (
            "CREATE TABLE IF NOT EXISTS day_usage_policy (id INTEGER PRIMARY KEY "
            "CHECK(id=1),blocked INTEGER NOT NULL DEFAULT 0)",
            "INSERT OR IGNORE INTO day_usage_policy(id) VALUES(1)",
            "CREATE TABLE IF NOT EXISTS day_usage_snapshots (snapshot_id TEXT PRIMARY "
            "KEY,parent_id TEXT NOT NULL,day TEXT NOT NULL,fingerprint TEXT NOT NULL,payload "
            "TEXT NOT NULL,UNIQUE(parent_id,day,fingerprint))",
            "CREATE TABLE IF NOT EXISTS day_usage_heads (parent_id TEXT NOT NULL,day TEXT "
            "NOT NULL,snapshot_id TEXT NOT NULL,checked_at TEXT NOT NULL,PRIMARY "
            "KEY(parent_id,day))",
            "CREATE TABLE IF NOT EXISTS day_usage_ownership (parent_id TEXT PRIMARY "
            "KEY,request_id TEXT NOT NULL,status TEXT NOT NULL CHECK(status IN "
            "('pending','unknown','closed')))",
            "CREATE TABLE IF NOT EXISTS day_usage_owners (parent_id TEXT NOT NULL,request_id "
            "TEXT NOT NULL,job_id TEXT NOT NULL,PRIMARY KEY(parent_id,request_id))",
        )

    def _known(
        self, connection: sqlite3.Connection, target: FamilySourceTarget
    ) -> FamilySourceReceipt | None:
        row = connection.execute(
            "SELECT payload FROM source_reads WHERE parent_id=? AND request_id=?",
            (target.parent_id, str(target.request_id)),
        ).fetchone()
        if (
            row is not None
            and json.loads(row[0]).get("source", "firebase.child_battery.v1") != target.source
        ):
            raise ParentChatError("family_source_request_conflict", 409)
        return super()._known(connection, target)

    @staticmethod
    def _day_known(db: sqlite3.Connection, target: DayUsageTarget) -> DayUsageReceipt | None:
        row = db.execute(
            "SELECT * FROM source_reads WHERE parent_id=? AND request_id=?",
            (target.parent_id, str(target.request_id)),
        ).fetchone()
        if row is None:
            return None
        if json.loads(row["payload"]).get("source") != DAY_USAGE_SOURCE:
            raise ParentChatError("family_source_request_conflict", 409)
        receipt = DayUsageReceipt.model_validate_json(row["payload"])
        if any(
            getattr(receipt, name) != getattr(target, name) for name in DayUsageTarget.model_fields
        ):
            raise ParentChatError("family_source_request_conflict", 409)
        status = "completed" if receipt.status == "unavailable" else receipt.status
        if (
            row["status"] != status
            or row["child_id"] != target.child_id
            or row["units"] != 0
            or row["started_at"] != receipt.started_at.isoformat()
        ):
            raise ParentChatError("family_source_cache_invalid", 503)
        if receipt.family_snapshot_id is not None:
            snapshot = db.execute(
                "SELECT payload,fingerprint FROM day_usage_snapshots "
                "WHERE snapshot_id=? AND parent_id=? AND day=?",
                (
                    str(receipt.family_snapshot_id),
                    target.parent_id,
                    target.requested_day.isoformat(),
                ),
            ).fetchone()
            if snapshot is None:
                raise ParentChatError("family_source_cache_invalid", 503)
            page = FamilyDayUsagePage.model_validate_json(snapshot["payload"])
            facts = next((c for c in page.children if c.child_id == target.child_id), None)
            if (
                page.parent_id != target.parent_id
                or page.requested_day != target.requested_day
                or day_page_fingerprint(page) != snapshot["fingerprint"]
                or receipt.snapshot_id != uuid5(receipt.family_snapshot_id, str(target.child_id))
                or receipt.facts != facts
                or page.collected_at > (receipt.finished_at or receipt.started_at)
            ):
                raise ParentChatError("family_source_cache_invalid", 503)
        return receipt

    @staticmethod
    def _save_day(db: sqlite3.Connection, receipt: DayUsageReceipt) -> None:
        receipt = DayUsageReceipt.model_validate(receipt.model_dump())
        db.execute(
            "UPDATE source_reads SET status=?,payload=? WHERE parent_id=? AND request_id=?",
            (
                "completed" if receipt.status == "unavailable" else receipt.status,
                receipt.model_dump_json(),
                receipt.parent_id,
                str(receipt.request_id),
            ),
        )

    async def observe_day(self, target: DayUsageTarget) -> DayUsageReceipt:
        def observe() -> DayUsageReceipt:
            with self._connection() as db:
                result = self._day_known(db, target)
                if result is None:
                    raise ParentChatError("family_source_request_not_found", 404)
                return result

        return await asyncio.to_thread(observe)

    async def claim_day(
        self, target: DayUsageTarget, now: datetime, owner: SourceAnalysisOwner | None = None
    ) -> DayUsageClaim:
        return await asyncio.to_thread(
            self._claim_day,
            DayUsageTarget.model_validate(target.model_dump()),
            self._time(now),
            owner,
        )

    def _claim_day(
        self, target: DayUsageTarget, now: datetime, owner: SourceAnalysisOwner | None
    ) -> DayUsageClaim:
        if owner is not None and owner.parent_id != target.parent_id:
            raise ParentChatError("source_review_owner_mismatch", 403)
        with self._connection() as db:
            known = self._day_known(db, target)
            if known is not None:
                saved_owner = db.execute(
                    "SELECT job_id FROM day_usage_owners WHERE parent_id=? AND request_id=?",
                    (target.parent_id, str(target.request_id)),
                ).fetchone()
                if (saved_owner[0] if saved_owner else None) != (
                    str(owner.job_id) if owner else None
                ):
                    raise ParentChatError("source_review_owner_mismatch", 409)
                return DayUsageClaim(receipt=known, admitted=False, read_provider=False)
            if (
                not 1
                <= (now.astimezone(ZoneInfo("Asia/Tashkent")).date() - target.requested_day).days
                <= 31
            ):
                raise ParentChatError("family_day_usage_day_outside_window", 422)
            if db.execute("SELECT blocked FROM day_usage_policy WHERE id=1").fetchone()[0]:
                raise ParentChatError("family_source_circuit_open", 503)
            if (
                db.execute(
                    "SELECT 1 FROM day_usage_ownership WHERE parent_id=? AND status!='closed'",
                    (target.parent_id,),
                ).fetchone()
                or db.execute(
                    "SELECT 1 FROM source_reads WHERE child_id=? AND "
                    "json_extract(payload,'$.source')=? AND status IN ('pending','unknown')",
                    (target.child_id, DAY_USAGE_SOURCE),
                ).fetchone()
            ):
                raise ParentChatError("family_source_read_unresolved", 409)
            count = db.execute(
                "SELECT COUNT(*) FROM source_reads WHERE started_at>?",
                ((now - timedelta(days=1)).isoformat(),),
            ).fetchone()[0]
            if count >= self._limits.requests_per_24h:
                raise ParentChatError("family_source_request_limit", 429)
            head = db.execute(
                "SELECT s.*,h.checked_at FROM day_usage_heads h LEFT JOIN "
                "day_usage_snapshots s ON s.snapshot_id=h.snapshot_id AND "
                "s.parent_id=h.parent_id AND s.day=h.day WHERE h.parent_id=? AND h.day=?",
                (target.parent_id, target.requested_day.isoformat()),
            ).fetchone()
            page = None
            if head is not None:
                if head["payload"] is None:
                    raise ParentChatError("family_source_cache_invalid", 503)
                page = FamilyDayUsagePage.model_validate_json(head["payload"])
                if (
                    page.parent_id != target.parent_id
                    or page.requested_day != target.requested_day
                    or day_page_fingerprint(page) != head["fingerprint"]
                    or not page.collected_at <= datetime.fromisoformat(head["checked_at"]) <= now
                ):
                    raise ParentChatError("family_source_cache_invalid", 503)
            cache = (
                head is not None
                and now - timedelta(seconds=self._limits.minimum_interval_seconds)
                < datetime.fromisoformat(head["checked_at"])
                <= now
            )
            if not cache:
                previous = db.execute(
                    "SELECT started_at FROM source_reads WHERE parent_id=? AND "
                    "json_extract(payload,'$.source')=? AND "
                    "json_extract(payload,'$.cache_hit')=0 ORDER BY started_at DESC LIMIT 1",
                    (target.parent_id, DAY_USAGE_SOURCE),
                ).fetchone()
                if previous is not None and now < datetime.fromisoformat(previous[0]) + timedelta(
                    seconds=self._limits.minimum_interval_seconds
                ):
                    raise ParentChatError("family_source_read_cooldown", 429)
            facts = (
                next((c for c in page.children if c.child_id == target.child_id), None)
                if cache and page
                else None
            )
            family_id = UUID(head["snapshot_id"]) if cache else None
            receipt = DayUsageReceipt(
                **target.model_dump(),
                status="pending",
                started_at=now,
                cache_hit=cache,
                family_snapshot_id=family_id,
                snapshot_id=uuid5(family_id, str(target.child_id)) if family_id else None,
                child_returned=(facts is not None) if cache else None,
                facts=facts,
            )
            db.execute(
                "INSERT INTO source_reads VALUES(?,?,?,?,?,?,?)",
                (
                    target.parent_id,
                    str(target.request_id),
                    target.child_id,
                    now.isoformat(),
                    "pending",
                    0,
                    receipt.model_dump_json(),
                ),
            )
            db.execute(
                "INSERT INTO day_usage_ownership VALUES(?,?,'pending') ON "
                "CONFLICT(parent_id) DO UPDATE SET "
                "request_id=excluded.request_id,status='pending'",
                (target.parent_id, str(target.request_id)),
            )
            if owner:
                db.execute(
                    "INSERT INTO day_usage_owners VALUES(?,?,?)",
                    (target.parent_id, str(target.request_id), str(owner.job_id)),
                )
            self._day_admitted(db, target)
            return DayUsageClaim(receipt=receipt, admitted=True, read_provider=not cache)

    async def complete_day(
        self, target: DayUsageTarget, page: FamilyDayUsagePage | None, now: datetime
    ) -> DayUsageReceipt:
        return await asyncio.to_thread(self._complete_day, target, page, self._time(now))

    def _complete_day(
        self, target: DayUsageTarget, page: FamilyDayUsagePage | None, now: datetime
    ) -> DayUsageReceipt:
        with self._connection() as db:
            receipt = self._day_known(db, target)
            if receipt is None:
                raise ParentChatError("family_source_request_not_found", 404)
            if receipt.status != "pending":
                return receipt
            if now < receipt.started_at:
                raise ValueError("Day completion cannot precede admission")
            if receipt.cache_hit:
                if page is not None:
                    raise ValueError("Cached family facts must retain their original snapshot")
                facts, family_id = receipt.facts, receipt.family_snapshot_id
                checked_at = None
            else:
                if page is None:
                    raise ValueError("A submitted family read needs its verified page")
                page = FamilyDayUsagePage.model_validate(page.model_dump())
                if (
                    page.parent_id != target.parent_id
                    or page.requested_day != target.requested_day
                    or not receipt.started_at
                    <= page.ownership_collected_at
                    <= page.collected_at
                    <= now
                ):
                    raise ParentChatError("family_source_snapshot_mismatch", 503)
                fingerprint = day_page_fingerprint(page)
                known = db.execute(
                    "SELECT snapshot_id,payload FROM day_usage_snapshots WHERE parent_id=? "
                    "AND day=? AND fingerprint=?",
                    (target.parent_id, target.requested_day.isoformat(), fingerprint),
                ).fetchone()
                family_id = UUID(known[0]) if known else uuid4()
                checked_at = page.collected_at
                if known:
                    page = FamilyDayUsagePage.model_validate_json(known[1])
                    if day_page_fingerprint(page) != fingerprint:
                        raise ParentChatError("family_source_cache_invalid", 503)
                else:
                    db.execute(
                        "INSERT INTO day_usage_snapshots VALUES(?,?,?,?,?)",
                        (
                            str(family_id),
                            target.parent_id,
                            target.requested_day.isoformat(),
                            fingerprint,
                            page.model_dump_json(),
                        ),
                    )
                db.execute(
                    "INSERT INTO day_usage_heads VALUES(?,?,?,?) ON CONFLICT(parent_id,day) "
                    "DO UPDATE SET "
                    "snapshot_id=excluded.snapshot_id,checked_at=excluded.checked_at",
                    (
                        target.parent_id,
                        target.requested_day.isoformat(),
                        str(family_id),
                        checked_at.isoformat(),
                    ),
                )
                facts = next((c for c in page.children if c.child_id == target.child_id), None)
            assert family_id is not None
            result = DayUsageReceipt.model_validate(
                receipt.model_dump()
                | {
                    "status": "completed" if facts is not None else "unavailable",
                    "finished_at": now,
                    "facts": facts,
                    "child_returned": facts is not None,
                    "family_snapshot_id": family_id,
                    "snapshot_id": uuid5(family_id, str(target.child_id)),
                    "error_code": None if facts is not None else "family_day_child_not_returned",
                }
            )
            self._save_day(db, result)
            self._day_finalized(db, target, result, page, checked_at)
            db.execute(
                "UPDATE day_usage_ownership SET status='closed' WHERE parent_id=? AND request_id=?",
                (target.parent_id, str(target.request_id)),
            )
            return result

    async def fail_day(
        self, target: DayUsageTarget, now: datetime, *, code: str, unknown: bool, close_source: bool
    ) -> DayUsageReceipt:
        def fail() -> DayUsageReceipt:
            with self._connection() as db:
                receipt = self._day_known(db, target)
                if receipt is None:
                    raise ParentChatError("family_source_request_not_found", 404)
                if receipt.status != "pending":
                    return receipt
                result = DayUsageReceipt.model_validate(
                    receipt.model_dump()
                    | {
                        "status": "unknown" if unknown else "failed",
                        "finished_at": self._time(now),
                        "error_code": code,
                        "facts": None,
                        "child_returned": None,
                        "snapshot_id": None,
                        "family_snapshot_id": None,
                    }
                )
                self._save_day(db, result)
                db.execute(
                    "UPDATE day_usage_ownership SET status=? WHERE parent_id=? AND request_id=?",
                    ("unknown" if unknown else "closed", target.parent_id, str(target.request_id)),
                )
                if close_source:
                    db.execute("UPDATE day_usage_policy SET blocked=1 WHERE id=1")
                return result

        return await asyncio.to_thread(fail)
