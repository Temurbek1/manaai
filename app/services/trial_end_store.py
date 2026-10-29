"""Family v26: fresh selected-term evidence can confirm a known free period ended."""

import asyncio
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid5
from zoneinfo import ZoneInfo

from app.mana_ai.domain.chat import ResponseLanguage
from app.mana_ai.domain.conversion_grants import TrialGrantState
from app.mana_ai.domain.retention_expiry import RetentionTariffFact
from app.mana_ai.domain.trial_end import TrialEndPolicy
from app.mana_ai.domain.trial_periods import KnownTrialPeriod
from app.services.location_safety_store import (
    SqliteClosedLocationSafetyStore,
    SqliteLocationSafetyStore,
)
from app.services.proactive_parent_store import _current_context
from app.services.retention_expiry_store import _digest

_TABLES = {"trial_end_policy", "trial_end_admissions", "trial_end_notices"}


def trial_end_text(period: KnownTrialPeriod, language: ResponseLanguage, timezone: str) -> str:
    ended = period.valid_until.astimezone(ZoneInfo(timezone))
    offset = ended.strftime("%z")
    date = f"{ended:%d.%m.%Y, %H:%M} (UTC{offset[:3]}:{offset[3:]})"
    return {
        "ru": f"Выданный бесплатный период на {period.days} дн. завершился {date}. "
        "Если понадобится, помогу посмотреть доступные тарифы.",
        "uz-Latn": f"Berilgan {period.days} kunlik bepul foydalanish muddati {date} da tugagan. "
        "Istasangiz, mavjud tariflarni ko‘rib chiqishga yordam beraman.",
        "uz-Cyrl": f"Берилган {period.days} кунлик бепул фойдаланиш муддати {date} да тугаган. "
        "Истасангиз, мавжуд тарифларни кўриб чиқишга ёрдам бераман.",
        "en": f"The {period.days}-day free period we granted ended on {date}. "
        "I can help you look at available tariffs if needed.",
    }[language]


class SqliteTrialEndStore(SqliteLocationSafetyStore):
    _schema_version = 26

    def __init__(
        self,
        path: Path,
        *,
        trial_end_enabled: bool = False,
        trial_end_policy: TrialEndPolicy | None = None,
        **family: Any,
    ) -> None:
        self._trial_end_enabled = trial_end_enabled
        self._trial_end_policy = TrialEndPolicy.model_validate(
            (trial_end_policy or TrialEndPolicy()).model_dump()
        )
        super().__init__(path, **family)

    def _supported_versions(self) -> set[int]:
        return super()._supported_versions() | {23}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | _TABLES

    def _extra_schema(self) -> str:
        return (
            super()._extra_schema()
            + """
        CREATE TABLE IF NOT EXISTS trial_end_policy(
          id INTEGER PRIMARY KEY CHECK(id=1),payload TEXT NOT NULL,
          closed INTEGER NOT NULL DEFAULT 0,scan_after TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS trial_end_admissions(
          action_id TEXT PRIMARY KEY,parent_id TEXT NOT NULL UNIQUE,
          enabled INTEGER NOT NULL CHECK(enabled IN (0,1)));
        CREATE TABLE IF NOT EXISTS trial_end_notices(
          action_id TEXT PRIMARY KEY,parent_id TEXT NOT NULL,period_digest TEXT NOT NULL,
          fact_digest TEXT NOT NULL,admitted_at TEXT NOT NULL,turn_id INTEGER NOT NULL UNIQUE);
        """
        )

    def _initialize(self) -> None:
        expected = self._trial_end_policy.model_dump_json()
        if self._path.exists():
            with self._connect() as db:
                if db.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='trial_end_policy'"
                ).fetchone():
                    row = db.execute("SELECT payload FROM trial_end_policy WHERE id=1").fetchone()
                    if row and row[0] != expected:
                        raise ValueError(
                            "Trial-end policy cannot reset existing captures or notices"
                        )
        super()._initialize()
        with self._transaction() as db:
            db.execute(
                "INSERT OR IGNORE INTO trial_end_policy(id,payload) VALUES(1,?)", (expected,)
            )
            if (
                db.execute("SELECT payload FROM trial_end_policy WHERE id=1").fetchone()[0]
                != expected
            ):
                raise ValueError("Trial-end policy changed during initialization")

    def _trial_end_open(self, db: sqlite3.Connection) -> bool:
        return not db.execute("SELECT closed FROM trial_end_policy WHERE id=1").fetchone()[0]

    def _on_trial_grant_claimed(
        self,
        db: sqlite3.Connection,
        state: TrialGrantState,
        now: datetime,
    ) -> None:
        super()._on_trial_grant_claimed(db, state, now)
        period = db.execute(
            "SELECT enabled FROM trial_period_admissions WHERE action_id=?", (str(state.action_id),)
        ).fetchone()
        capacity = db.execute(
            "SELECT count(*) FROM trial_end_admissions WHERE enabled=1"
        ).fetchone()[0]
        if self._trial_end_enabled and capacity >= self._trial_end_policy.maximum_captures:
            db.execute("UPDATE trial_end_policy SET closed=1 WHERE id=1")
        admitted = bool(
            self._trial_end_enabled and self._trial_end_open(db) and period and period[0]
        )
        db.execute(
            "INSERT INTO trial_end_admissions VALUES(?,?,?)",
            (str(state.action_id), state.parent_id, int(admitted)),
        )

    def _ended_fact(
        self,
        db: sqlite3.Connection,
        row: sqlite3.Row,
        now: datetime,
    ) -> tuple[KnownTrialPeriod, RetentionTariffFact] | None:
        period = self._known_period(db, row["parent_id"], now)
        if period is None or str(period.action_id) != row["action_id"]:
            return None
        try:
            fact = RetentionTariffFact.model_validate_json(row["payload"])
            if (
                fact.parent_id != row["parent_id"]
                or fact.is_paid is not False
                or fact.valid_until != period.valid_until
                or row["is_paid"] != 0
                or _digest(fact) != row["digest"]
                or self._utc(fact.collected_at).isoformat() != row["collected_at"]
                or self._utc(period.valid_until).isoformat() != row["valid_until"]
            ):
                raise ValueError("Trial-end source projection changed")
        except (ValueError, TypeError):
            db.execute("UPDATE trial_end_policy SET closed=1 WHERE id=1")
            return None
        if (
            not now - timedelta(days=self._trial_end_policy.maximum_age_days)
            <= period.valid_until
            <= now
            or not max(
                period.valid_until,
                now - timedelta(seconds=self._expiry_policy.maximum_profile_age_seconds),
            )
            <= fact.collected_at
            <= now
        ):
            return None
        return period, fact

    def _retention_daily_count(self, db: sqlite3.Connection, now: datetime) -> int:
        return super()._retention_daily_count(db, now) + int(
            db.execute(
                "SELECT count(*) FROM trial_end_notices WHERE admitted_at>?",
                ((now - timedelta(days=1)).isoformat(),),
            ).fetchone()[0]
        )

    def _retention_recent(self, db: sqlite3.Connection, parent: str, now: datetime) -> bool:
        return super()._retention_recent(db, parent, now) or bool(
            db.execute(
                "SELECT 1 FROM trial_end_notices WHERE parent_id=? AND admitted_at>?",
                (
                    parent,
                    (
                        now - timedelta(hours=self._expiry_policy.minimum_outreach_interval_hours)
                    ).isoformat(),
                ),
            ).fetchone()
        )

    async def publish_expiry(self, now: datetime) -> bool:
        if await asyncio.to_thread(self._publish_trial_end, self._utc(now)):
            return True
        return await super().publish_expiry(now)

    def _on_commercial_refusal(self, db: sqlite3.Connection, parent: str, now: datetime) -> None:
        super()._on_commercial_refusal(db, parent, now)
        db.execute(
            "UPDATE parent_push_outbox SET status='suppressed',"
            "error_code='parent_push_marketing_opted_out',updated_at=? "
            "WHERE parent_id=? AND purpose='retention' AND status='queued' "
            "AND turn_id IN(SELECT turn_id FROM trial_end_notices WHERE parent_id=?)",
            (now.isoformat(), parent, parent),
        )

    def _publish_trial_end(self, now: datetime) -> bool:
        if not self._trial_end_enabled or not self._expiry_enabled:
            return False
        with self._transaction() as db:
            if (
                not self._trial_end_open(db)
                or not self._expiry_open(db)
                or self._retention_daily_count(db, now)
                >= self._retention_policy.daily_outreach_limit
            ):
                return False
            cursor = db.execute("SELECT scan_after FROM trial_end_policy WHERE id=1").fetchone()[0]
            rows = db.execute(
                "SELECT a.action_id,h.* FROM trial_end_admissions a "
                "JOIN retention_tariff_heads h ON h.parent_id=a.parent_id "
                "LEFT JOIN trial_end_notices n ON n.action_id=a.action_id "
                "WHERE a.enabled=1 AND n.action_id IS NULL AND a.action_id>? "
                "AND h.is_paid=0 AND h.valid_until<=? AND h.valid_until>=? "
                "AND h.collected_at>=? AND h.collected_at<=? ORDER BY a.action_id LIMIT 100",
                (
                    cursor,
                    now.isoformat(),
                    (now - timedelta(days=self._trial_end_policy.maximum_age_days)).isoformat(),
                    (
                        now - timedelta(seconds=self._expiry_policy.maximum_profile_age_seconds)
                    ).isoformat(),
                    now.isoformat(),
                ),
            ).fetchall()
            if not rows:
                db.execute("UPDATE trial_end_policy SET scan_after='' WHERE id=1")
            for row in rows:
                db.execute(
                    "UPDATE trial_end_policy SET scan_after=? WHERE id=1", (row["action_id"],)
                )
                parent = row["parent_id"]
                if (
                    not self._contact_ready(db, parent, now)
                    or self._commercial_contact_blocked(db, parent)
                    or not self._expiry_parent_ready(db, parent, now)
                    or self._manager_priority(db, parent, 0, now)
                    or self._retention_recent(db, parent, now)
                    or db.execute(
                        "SELECT 1 FROM family_notices WHERE parent_id=? AND kind='urgent' "
                        "AND created_at>?",
                        (
                            parent,
                            (
                                now
                                - timedelta(hours=self._expiry_policy.urgent_notice_cooldown_hours)
                            ).isoformat(),
                        ),
                    ).fetchone()
                ):
                    continue
                known = self._ended_fact(db, row, now)
                if known is None:
                    if not self._trial_end_open(db):
                        return False
                    continue
                period, fact = known
                contact = _current_context(db, parent, now)
                assert contact
                result = self._host_reply(
                    db,
                    None,
                    parent,
                    uuid5(period.action_id, "trial-end-notice-v1"),
                    trial_end_text(period, contact.language, contact.timezone),
                    now,
                )
                db.execute(
                    "INSERT INTO trial_end_notices VALUES(?,?,?,?,?,?)",
                    (
                        str(period.action_id),
                        parent,
                        period.digest(),
                        _digest(fact),
                        now.isoformat(),
                        result.turn_id,
                    ),
                )
                self._retention_event(
                    db, parent, str(period.action_id), "trial_end_published", now, result.turn_id
                )
                self._queue_push(db, parent, result.turn_id, "retention", now)
                return True
            if len(rows) < 100:
                db.execute("UPDATE trial_end_policy SET scan_after='' WHERE id=1")
            return False

    def _push_delivery_ready(self, db: sqlite3.Connection, row: sqlite3.Row, now: datetime) -> bool:
        notice = db.execute(
            "SELECT * FROM trial_end_notices WHERE turn_id=? AND parent_id=?",
            (row["turn_id"], row["parent_id"]),
        ).fetchone()
        event = db.execute(
            "SELECT intent_id FROM retention_events WHERE turn_id=? AND parent_id=? "
            "AND kind='trial_end_published'",
            (row["turn_id"], row["parent_id"]),
        ).fetchone()
        if bool(notice) != bool(event):
            return False
        if notice:
            if (
                event["intent_id"] != notice["action_id"]
                or row["purpose"] != "retention"
                or not self._trial_end_enabled
                or self._commercial_contact_blocked(db, row["parent_id"])
                or not self._trial_end_open(db)
                or not self._expiry_open(db)
            ):
                return False
            source = db.execute(
                "SELECT ? AS action_id,h.* FROM retention_tariff_heads h WHERE parent_id=?",
                (notice["action_id"], row["parent_id"]),
            ).fetchone()
            known = self._ended_fact(db, source, now) if source else None
            if (
                known is None
                or known[0].digest() != notice["period_digest"]
                or _digest(known[1]) != notice["fact_digest"]
            ):
                return False
        return super()._push_delivery_ready(db, row, now)


class SqliteClosedTrialEndStore(SqliteClosedLocationSafetyStore):
    _schema_version = 26

    def _supported_versions(self) -> set[int]:
        return {26}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | _TABLES
