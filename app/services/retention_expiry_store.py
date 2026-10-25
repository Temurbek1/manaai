"""Family v17: minimized profile facts -> exact single-chat reminder, no provider write."""

import asyncio
import hashlib
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.domain.chat import ParentChildContext, ResponseLanguage
from app.mana_ai.domain.retention_expiry import RetentionExpiryPolicy, RetentionTariffFact
from app.services.client_upsell_store import SqliteClientUpsellStore, SqliteClosedClientUpsellStore
from app.services.proactive_parent_store import _current_context

_TABLES = {
    "retention_expiry_policy",
    "retention_tariff_heads",
    "retention_tariff_changes",
    "retention_expiry_notices",
}


def _digest(fact: RetentionTariffFact | None) -> str:
    data = fact.model_dump_json(exclude={"collected_at"}) if fact else "null"
    return hashlib.sha256(data.encode()).hexdigest()


def _text(deadline: datetime, language: ResponseLanguage, timezone: str) -> str:
    local = deadline.astimezone(ZoneInfo(timezone))
    offset = local.strftime("%z")
    date = f"{local:%d.%m.%Y, %H:%M} (UTC{offset[:3]}:{offset[3:]})"
    return {
        "ru": f"В приложении указан срок текущего тарифа: до {date}. "
        "Если понадобится, помогу посмотреть доступные тарифы.",
        "uz-Latn": f"Ilovada amaldagi tarif muddati {date} gacha deb ko‘rsatilgan. "
        "Istasangiz, mavjud tariflarni ko‘rib chiqishga yordam beraman.",
        "uz-Cyrl": f"Иловада амалдаги тариф муддати {date} гача деб кўрсатилган. "
        "Истасангиз, мавжуд тарифларни кўриб чиқишга ёрдам бераман.",
        "en": f"The app shows the current tariff term ending on {date}. "
        "I can help you look at available tariffs if needed.",
    }[language]


class SqliteRetentionExpiryStore(SqliteClientUpsellStore):
    _schema_version = 17

    def __init__(
        self,
        path: Path,
        *,
        expiry_policy: RetentionExpiryPolicy,
        profile_binding: str,
        expiry_enabled: bool = True,
        **family: Any,
    ) -> None:
        if not profile_binding or len(profile_binding) > 256:
            raise ValueError("An explicit MANA profile source binding is required")
        self._expiry_policy = RetentionExpiryPolicy.model_validate(expiry_policy.model_dump())
        self._profile_binding = profile_binding
        self._expiry_enabled = expiry_enabled
        super().__init__(path, **family)

    def _supported_versions(self) -> set[int]:
        return super()._supported_versions() | {16}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | _TABLES

    def _extra_schema(self) -> str:
        return (
            super()._extra_schema()
            + """
        CREATE TABLE IF NOT EXISTS retention_expiry_policy(
          id INTEGER PRIMARY KEY,payload TEXT NOT NULL,binding TEXT NOT NULL,
          circuit_open INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS retention_tariff_heads(
          parent_id TEXT PRIMARY KEY,payload TEXT,digest TEXT NOT NULL,collected_at TEXT NOT NULL,
          is_paid INTEGER,valid_until TEXT);
        CREATE INDEX IF NOT EXISTS retention_expiry_due
          ON retention_tariff_heads(is_paid,valid_until,collected_at);
        CREATE TABLE IF NOT EXISTS retention_tariff_changes(
          position INTEGER PRIMARY KEY,parent_id TEXT NOT NULL,payload TEXT,
          digest TEXT NOT NULL,collected_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS retention_expiry_notices(
          notice_id TEXT PRIMARY KEY,parent_id TEXT NOT NULL,deadline TEXT NOT NULL,
          digest TEXT NOT NULL,admitted_at TEXT NOT NULL,turn_id INTEGER NOT NULL UNIQUE,
          profile_collected_at TEXT NOT NULL,
          UNIQUE(parent_id,deadline));
        CREATE INDEX IF NOT EXISTS retention_expiry_recent
          ON retention_expiry_notices(parent_id,admitted_at);
        """
        )

    def _initialize(self) -> None:
        expected = (self._expiry_policy.model_dump_json(), self._profile_binding)
        if self._path.exists():
            with self._connect() as db:
                if db.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='retention_expiry_policy'"
                ).fetchone():
                    row = db.execute(
                        "SELECT payload,binding FROM retention_expiry_policy WHERE id=1"
                    ).fetchone()
                    if row and tuple(row) != expected:
                        raise ValueError("Expiry source/policy cannot reset previous observations")
        super()._initialize()
        with self._transaction() as db:
            db.execute(
                "INSERT OR IGNORE INTO retention_expiry_policy(id,payload,binding) VALUES(1,?,?)",
                expected,
            )
            row = db.execute(
                "SELECT payload,binding FROM retention_expiry_policy WHERE id=1"
            ).fetchone()
            if tuple(row) != expected:
                raise ValueError("Expiry source/policy cannot reset previous observations")

    def _expiry_open(self, db: sqlite3.Connection) -> bool:
        return not bool(
            db.execute("SELECT circuit_open FROM retention_expiry_policy WHERE id=1").fetchone()[0]
        )

    async def observe_expiry_profile(
        self, parent_id: str, context: ParentChildContext, now: datetime
    ) -> None:
        checked = ParentChildContext.model_validate(context.model_dump())
        current = self._utc(now)
        if (
            checked.parent_id != parent_id
            or not current - timedelta(seconds=180) <= checked.collected_at <= current
        ):
            raise ParentChatError("expiry_profile_owner_or_date_invalid", 403)
        tariff = checked.tariff
        fact = (
            RetentionTariffFact(
                parent_id=parent_id,
                collected_at=checked.collected_at,
                is_paid=tariff.is_paid,
                valid_until=tariff.valid_until.astimezone(UTC) if tariff.valid_until else None,
            )
            if tariff and tariff.collected_at == checked.collected_at
            else None
        )
        await asyncio.to_thread(self._record, parent_id, fact, checked.collected_at.astimezone(UTC))

    async def invalidate_expiry_profile(self, parent_id: str, now: datetime) -> None:
        await asyncio.to_thread(self._record, parent_id, None, self._utc(now))

    async def close_expiry_source(self) -> None:
        def close() -> None:
            with self._transaction() as db:
                db.execute("UPDATE retention_expiry_policy SET circuit_open=1 WHERE id=1")

        await asyncio.to_thread(close)

    async def observe_inventory_tariffs(
        self, facts: tuple[RetentionTariffFact, ...], now: datetime
    ) -> bool:
        current = self._utc(now)
        checked = tuple(RetentionTariffFact.model_validate(f.model_dump()) for f in facts)
        if not 1 <= len(checked) <= 100 or len({f.parent_id for f in checked}) != len(checked):
            raise ValueError("A bounded unique-parent inventory batch is required")
        if any(not current - timedelta(seconds=180) <= f.collected_at <= current for f in checked):
            raise ValueError("An inventory batch must retain its actual fresh collection dates")
        normalized = tuple(
            f.model_copy(
                update={
                    "collected_at": f.collected_at.astimezone(UTC),
                    "valid_until": f.valid_until.astimezone(UTC) if f.valid_until else None,
                }
            )
            for f in checked
        )
        return await asyncio.to_thread(self._record_inventory, normalized)

    def _record_inventory(self, facts: tuple[RetentionTariffFact, ...]) -> bool:
        if not self._expiry_enabled:
            return False
        with self._transaction() as db:
            if not self._expiry_open(db):
                return False
            db.execute("SAVEPOINT inventory_facts")
            for fact in facts:
                self._put_fact(db, fact.parent_id, fact, fact.collected_at)
            if not self._expiry_open(db):
                db.execute("ROLLBACK TO inventory_facts")
                db.execute("RELEASE inventory_facts")
                db.execute("UPDATE retention_expiry_policy SET circuit_open=1 WHERE id=1")
                return False
            db.execute("RELEASE inventory_facts")
            return True

    def _record(self, parent: str, fact: RetentionTariffFact | None, collected: datetime) -> None:
        if not self._expiry_enabled:
            return
        with self._transaction() as db:
            self._put_fact(db, parent, fact, collected)

    def _put_fact(
        self,
        db: sqlite3.Connection,
        parent: str,
        fact: RetentionTariffFact | None,
        collected: datetime,
    ) -> None:
        if not self._expiry_open(db):
            return
        old = db.execute(
            "SELECT * FROM retention_tariff_heads WHERE parent_id=?", (parent,)
        ).fetchone()
        if old and datetime.fromisoformat(old["collected_at"]) > collected:
            return
        digest = _digest(fact)
        payload = fact.model_dump_json() if fact else None
        if (
            old is None
            and db.execute("SELECT COUNT(*) FROM retention_tariff_heads").fetchone()[0]
            >= self._expiry_policy.maximum_profiles
        ):
            db.execute("UPDATE retention_expiry_policy SET circuit_open=1 WHERE id=1")
            return
        changed = old is None or old["digest"] != digest
        if changed:
            if (
                db.execute("SELECT COUNT(*) FROM retention_tariff_changes").fetchone()[0]
                >= self._expiry_policy.maximum_changes
            ):
                db.execute("UPDATE retention_expiry_policy SET circuit_open=1 WHERE id=1")
                return
            db.execute(
                "INSERT INTO retention_tariff_changes(parent_id,payload,digest,coll"
                "ected_at) VALUES(?,?,?,?)",
                (parent, payload, digest, collected.isoformat()),
            )
        db.execute(
            "INSERT OR REPLACE INTO retention_tariff_heads VALUES(?,?,?,?,?,?)",
            (
                parent,
                payload,
                digest,
                collected.isoformat(),
                fact.is_paid if fact else None,
                fact.valid_until.isoformat() if fact and fact.valid_until else None,
            ),
        )

    def _retention_daily_count(self, db: sqlite3.Connection, now: datetime) -> int:
        return super()._retention_daily_count(db, now) + int(
            db.execute(
                "SELECT COUNT(*) FROM retention_expiry_notices WHERE admitted_at>?",
                ((now - timedelta(days=1)).isoformat(),),
            ).fetchone()[0]
        )

    def _retention_recent(self, db: sqlite3.Connection, parent: str, now: datetime) -> bool:
        cutoff = (
            now - timedelta(hours=self._expiry_policy.minimum_outreach_interval_hours)
        ).isoformat()
        return bool(
            db.execute(
                "SELECT 1 FROM retention_intents WHERE parent_id=? AND admitted_at>?",
                (parent, cutoff),
            ).fetchone()
            or db.execute(
                "SELECT 1 FROM retention_expiry_notices WHERE parent_id=? AND admitted_at>?",
                (parent, cutoff),
            ).fetchone()
        )

    async def publish_expiry(self, now: datetime) -> bool:
        return await asyncio.to_thread(self._publish_expiry, self._utc(now))

    def _publish_expiry(self, now: datetime) -> bool:
        if not self._expiry_enabled:
            return False
        with self._transaction() as db:
            if (
                not self._expiry_open(db)
                or self._retention_daily_count(db, now)
                >= self._retention_policy.daily_outreach_limit
            ):
                return False
            earliest = now - timedelta(seconds=self._expiry_policy.maximum_profile_age_seconds)
            latest = now + timedelta(hours=self._expiry_policy.notice_within_hours)
            rows = db.execute(
                "SELECT h.* FROM retention_tariff_heads h LEFT JOIN "
                "retention_expiry_notices n ON n.parent_id=h.parent_id AND "
                "n.deadline=h.valid_until WHERE h.is_paid=1 AND h.valid_until>? "
                "AND h.valid_until<=? AND h.collected_at>=? AND h.collected_at<=? "
                "AND n.notice_id IS NULL ORDER BY h.valid_until,h.collected_at "
                "LIMIT 100",
                (now.isoformat(), latest.isoformat(), earliest.isoformat(), now.isoformat()),
            ).fetchall()
            for row in rows:
                parent = row["parent_id"]
                if (
                    not self._contact_ready(db, parent, now)
                    or self._priority_waiting(db, parent, now)
                    or self._retention_recent(db, parent, now)
                ):
                    continue
                if db.execute(
                    "SELECT 1 FROM child_safety_jobs WHERE parent_id=? AND status IN "
                    "('queued','preparing','submitted','unknown')",
                    (parent,),
                ).fetchone():
                    continue
                if db.execute(
                    "SELECT 1 FROM family_notices WHERE parent_id=? AND kind='urgent' "
                    "AND created_at>?",
                    (
                        parent,
                        (
                            now - timedelta(hours=self._expiry_policy.urgent_notice_cooldown_hours)
                        ).isoformat(),
                    ),
                ).fetchone():
                    continue
                try:
                    fact = RetentionTariffFact.model_validate_json(row["payload"])
                    if (
                        fact.parent_id != parent
                        or _digest(fact) != row["digest"]
                        or fact.is_paid is not True
                        or fact.valid_until is None
                        or not now < fact.valid_until <= latest
                        or not earliest <= fact.collected_at <= now
                        or fact.collected_at.astimezone(UTC).isoformat() != row["collected_at"]
                        or fact.valid_until.astimezone(UTC).isoformat() != row["valid_until"]
                    ):
                        raise ValueError("Expiry projection integrity failed")
                except ValueError:
                    db.execute("UPDATE retention_expiry_policy SET circuit_open=1 WHERE id=1")
                    return False
                contact = _current_context(db, parent, now)
                assert contact is not None
                identity = uuid5(
                    NAMESPACE_URL, f"mana:retention:expiry-v1:{parent}:{row['valid_until']}"
                )
                result = self._host_reply(
                    db,
                    None,
                    parent,
                    uuid5(identity, "parent-touch"),
                    _text(fact.valid_until, contact.language, contact.timezone),
                    now,
                )
                db.execute(
                    "INSERT INTO retention_expiry_notices VALUES(?,?,?,?,?,?,?)",
                    (
                        str(identity),
                        parent,
                        row["valid_until"],
                        row["digest"],
                        now.isoformat(),
                        result.turn_id,
                        row["collected_at"],
                    ),
                )
                self._queue_push(db, parent, result.turn_id, "retention", now)
                return True
            return False

    def _push_delivery_ready(self, db: sqlite3.Connection, row: sqlite3.Row, now: datetime) -> bool:
        notice = db.execute(
            "SELECT n.*,h.digest AS current_digest,h.collected_at FROM "
            "retention_expiry_notices n LEFT JOIN retention_tariff_heads h ON "
            "h.parent_id=n.parent_id WHERE n.turn_id=?",
            (row["turn_id"],),
        ).fetchone()
        if notice is not None and (
            not self._expiry_enabled
            or not self._expiry_open(db)
            or notice["current_digest"] != notice["digest"]
            or datetime.fromisoformat(notice["deadline"]) <= now
            or notice["collected_at"] is None
            or datetime.fromisoformat(notice["collected_at"])
            < now - timedelta(seconds=self._expiry_policy.maximum_profile_age_seconds)
        ):
            return False
        return super()._push_delivery_ready(db, row, now)


class SqliteClosedRetentionExpiryStore(SqliteClosedClientUpsellStore):
    _schema_version = 17

    def _supported_versions(self) -> set[int]:
        return {17}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | _TABLES
