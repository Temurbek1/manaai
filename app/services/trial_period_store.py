"""Family v22: new grant receipts can support one independently permitted expiry notice."""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.mana_ai.domain.chat import ResponseLanguage
from app.mana_ai.domain.conversion_grants import TrialGrantState
from app.mana_ai.domain.retention_expiry import RetentionTariffFact
from app.mana_ai.domain.trial_periods import KnownTrialPeriod, TrialPeriodMetadata
from app.services.parent_touch_manager_store import (
    SqliteClosedParentTouchManagerStore,
    SqliteParentTouchManagerStore,
)

_TABLES = {
    "trial_period_admissions",
    "trial_period_facts",
    "trial_period_notices",
    "trial_period_state",
}


def _text(period: KnownTrialPeriod, language: ResponseLanguage, timezone: str) -> str:
    local = period.valid_until.astimezone(ZoneInfo(timezone))
    offset = local.strftime("%z")
    deadline = f"{local:%d.%m.%Y, %H:%M} (UTC{offset[:3]}:{offset[3:]})"
    return {
        "ru": f"Выданный бесплатный доступ на {period.days} дн. действует до {deadline}. "
        "Если понадобится, помогу посмотреть доступные тарифы.",
        "uz-Latn": f"Berilgan {period.days} kunlik bepul foydalanish muddati {deadline} gacha. "
        "Istasangiz, mavjud tariflarni ko‘rib chiqishga yordam beraman.",
        "uz-Cyrl": f"Берилган {period.days} кунлик бепул фойдаланиш муддати {deadline} гача. "
        "Истасангиз, мавжуд тарифларни кўриб чиқишга ёрдам бераман.",
        "en": f"Your granted {period.days}-day free access ends on {deadline}. "
        "I can help you look at available tariffs if needed.",
    }[language]


class SqliteTrialPeriodStore(SqliteParentTouchManagerStore):
    _schema_version = 22

    def __init__(self, path: Path, *, trial_periods_enabled: bool = False, **family: Any) -> None:
        self._trial_periods_enabled = trial_periods_enabled
        super().__init__(path, **family)

    def _supported_versions(self) -> set[int]:
        return super()._supported_versions() | {21}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | _TABLES

    def _extra_schema(self) -> str:
        return (
            super()._extra_schema()
            + """
        CREATE TABLE IF NOT EXISTS trial_period_admissions(
          action_id TEXT PRIMARY KEY,parent_id TEXT NOT NULL UNIQUE,
          enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),admitted_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS trial_period_facts(
          action_id TEXT PRIMARY KEY,parent_id TEXT NOT NULL UNIQUE,payload TEXT NOT NULL,
          digest TEXT NOT NULL,deadline TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS trial_period_notices(
          turn_id INTEGER PRIMARY KEY,action_id TEXT NOT NULL,digest TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS trial_period_state(
          id INTEGER PRIMARY KEY CHECK(id=1),closed INTEGER NOT NULL CHECK(closed IN (0,1)));
        INSERT OR IGNORE INTO trial_period_state VALUES(1,0);
        """
        )

    def _on_trial_grant_claimed(
        self, db: sqlite3.Connection, state: TrialGrantState, now: datetime
    ) -> None:
        super()._on_trial_grant_claimed(db, state, now)
        admitted = (
            self._trial_periods_enabled
            and db.execute(
                "SELECT COUNT(*) FROM trial_period_admissions WHERE enabled=1"
            ).fetchone()[0]
            < self._expiry_policy.maximum_profiles
        )
        db.execute(
            "INSERT INTO trial_period_admissions VALUES(?,?,?,?)",
            (str(state.action_id), state.parent_id, int(admitted), now.isoformat()),
        )

    def _on_trial_grant_finished(
        self, db: sqlite3.Connection, state: TrialGrantState, now: datetime
    ) -> None:
        super()._on_trial_grant_finished(db, state, now)
        capture = db.execute(
            "SELECT * FROM trial_period_admissions WHERE action_id=? AND parent_id=?",
            (str(state.action_id), state.parent_id),
        ).fetchone()
        if (
            not capture
            or not capture["enabled"]
            or state.status != "granted"
            or state.result is None
            or state.result.period_metadata is None
        ):
            return
        metadata = TrialPeriodMetadata.model_validate(vars(state.result.period_metadata))
        period = KnownTrialPeriod(
            action_id=state.action_id,
            parent_id=state.parent_id,
            purchase_id=state.result.purchase_id,
            days=state.days,
            started_at=metadata.created_at,
            valid_until=state.result.valid_until,
            recorded_at=now,
        )
        admitted = datetime.fromisoformat(capture["admitted_at"])
        if (
            not admitted - timedelta(seconds=300)
            <= period.started_at
            <= now + timedelta(seconds=300)
        ):
            db.execute("UPDATE trial_period_state SET closed=1 WHERE id=1")
            return
        db.execute(
            "INSERT INTO trial_period_facts VALUES(?,?,?,?,?)",
            (
                str(period.action_id),
                period.parent_id,
                period.model_dump_json(),
                period.digest(),
                self._utc(period.valid_until).isoformat(),
            ),
        )

    def _known_period(
        self, db: sqlite3.Connection, parent: str, now: datetime
    ) -> KnownTrialPeriod | None:
        if (
            not self._trial_periods_enabled
            or db.execute("SELECT closed FROM trial_period_state WHERE id=1").fetchone()[0]
        ):
            return None
        row = db.execute("SELECT * FROM trial_period_facts WHERE parent_id=?", (parent,)).fetchone()
        if row is None:
            return None
        try:
            period = KnownTrialPeriod.model_validate_json(row["payload"])
            capture = db.execute(
                "SELECT * FROM trial_period_admissions WHERE action_id=? AND parent_id=?",
                (row["action_id"], parent),
            ).fetchone()
            grant = db.execute(
                "SELECT payload FROM conversion_trial_grants WHERE action_id=? AND parent_id=?",
                (row["action_id"], parent),
            ).fetchone()
            state = TrialGrantState.model_validate_json(grant[0]) if grant else None
            if (
                period.parent_id != parent
                or str(period.action_id) != row["action_id"]
                or period.digest() != row["digest"]
                or self._utc(period.valid_until).isoformat() != row["deadline"]
                or period.recorded_at > now
                or capture is None
                or not capture["enabled"]
                or state is None
                or state.status != "granted"
                or state.result is None
                or state.parent_id != parent
                or state.action_id != period.action_id
                or state.days != period.days
                or state.result.purchase_id != period.purchase_id
                or state.result.tariff != "Maxsus"
                or state.result.valid_until != period.valid_until
                or not datetime.fromisoformat(capture["admitted_at"]) - timedelta(seconds=300)
                <= period.started_at
                <= period.recorded_at + timedelta(seconds=300)
            ):
                raise ValueError("Trial period proof is inconsistent")
        except (ValueError, TypeError):
            db.execute("UPDATE trial_period_state SET closed=1 WHERE id=1")
            return None
        return period if period.started_at <= now else None

    def _expiry_selection(self) -> str:
        original = super()._expiry_selection()
        if not self._trial_periods_enabled:
            return original
        return (
            original + " OR (h.is_paid=0 AND (SELECT closed FROM trial_period_state WHERE id=1)=0 "
            "AND EXISTS(SELECT 1 FROM trial_period_facts p "
            "WHERE p.parent_id=h.parent_id AND p.deadline=h.valid_until))"
        )

    def _expiry_message(
        self,
        db: sqlite3.Connection,
        fact: RetentionTariffFact,
        language: ResponseLanguage,
        timezone: str,
        now: datetime,
    ) -> str | None:
        if fact.is_paid is True:
            return super()._expiry_message(db, fact, language, timezone, now)
        period = self._known_period(db, fact.parent_id, now)
        if period is None or fact.is_paid is not False or fact.valid_until != period.valid_until:
            return None
        return _text(period, language, timezone)

    def _on_expiry_published(
        self, db: sqlite3.Connection, fact: RetentionTariffFact, turn_id: int, now: datetime
    ) -> None:
        super()._on_expiry_published(db, fact, turn_id, now)
        if fact.is_paid is False:
            period = self._known_period(db, fact.parent_id, now)
            assert period is not None
            db.execute(
                "INSERT INTO trial_period_notices VALUES(?,?,?)",
                (turn_id, str(period.action_id), period.digest()),
            )

    def _push_delivery_ready(self, db: sqlite3.Connection, row: sqlite3.Row, now: datetime) -> bool:
        proof = db.execute(
            "SELECT * FROM trial_period_notices WHERE turn_id=?", (row["turn_id"],)
        ).fetchone()
        if proof is not None:
            period = self._known_period(db, row["parent_id"], now)
            if (
                period is None
                or str(period.action_id) != proof["action_id"]
                or period.digest() != proof["digest"]
            ):
                return False
        elif db.execute(
            "SELECT 1 FROM retention_expiry_notices n JOIN retention_tariff_heads h "
            "ON h.parent_id=n.parent_id WHERE n.turn_id=? AND h.is_paid=0",
            (row["turn_id"],),
        ).fetchone():
            return False
        return super()._push_delivery_ready(db, row, now)


class SqliteClosedTrialPeriodStore(SqliteClosedParentTouchManagerStore):
    _schema_version = 22

    def _supported_versions(self) -> set[int]:
        return {22}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | _TABLES
