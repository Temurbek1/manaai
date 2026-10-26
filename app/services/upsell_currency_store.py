"""Family v31: a frozen tariff enquiry and one exact, host-owned currency answer."""

import asyncio
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from app.mana_ai.application.chat_ports import ChatModelReceipt, ParentChatError
from app.mana_ai.application.upsell_text import upsell_ack, upsell_language
from app.mana_ai.domain.chat import ParentChatRequest, StoredChatTurn
from app.mana_ai.domain.client_upsell import (
    UpsellChoice,
    UpsellEnquiry,
    UpsellIntent,
    UpsellScope,
    UpsellWork,
)
from app.mana_ai.domain.family_agents import (
    FamilyQuestion,
    ParentTouchMessageRequest,
    ParentTouchMessageState,
    ParentTouchReviewedTurn,
)
from app.services.usage_comparison_safety_store import (
    SqliteClosedUsageComparisonSafetyStore,
    SqliteUsageComparisonSafetyStore,
)

_TABLES = {"upsell_currency_admissions", "upsell_currency_questions"}
_QUESTIONS = {
    "ru": "В какой валюте показать тарифы: UZS или USD?",
    "uz-Latn": "Tariflarni qaysi valyutada ko‘rsatay: UZS yoki USD?",
    "uz-Cyrl": "Тарифларни қайси валютада кўрсатай: UZS ёки USD?",
    "en": "Which currency should I use for the tariffs: UZS or USD?",
}


class SqliteUpsellCurrencyStore(SqliteUsageComparisonSafetyStore):
    _schema_version = 31

    def __init__(self, path: Path, *, currency_enabled: bool = False, **family: Any) -> None:
        self._currency_enabled = currency_enabled
        super().__init__(path, **family)

    def _supported_versions(self) -> set[int]:
        return super()._supported_versions() | {30}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | _TABLES

    def _extra_schema(self) -> str:
        return (
            super()._extra_schema()
            + """
        CREATE TABLE IF NOT EXISTS upsell_currency_admissions(
            turn_id INTEGER PRIMARY KEY,parent_id TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS upsell_currency_questions(
            origin_turn_id INTEGER PRIMARY KEY,parent_id TEXT NOT NULL,
            question_id TEXT NOT NULL UNIQUE,terms TEXT NOT NULL,language TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('waiting','resolved','abandoned')),
            answer_turn_id INTEGER UNIQUE);
        CREATE INDEX IF NOT EXISTS upsell_currency_parent
            ON upsell_currency_questions(parent_id,status);
        """
        )

    def _on_admitted(
        self, db: sqlite3.Connection, request: ParentChatRequest, turn_id: int, now: datetime
    ) -> None:
        if (
            isinstance(request, ParentTouchReviewedTurn)
            and request.reply_to_question_id
            and not self._currency_enabled
            and db.execute(
                "SELECT 1 FROM upsell_currency_questions WHERE parent_id=? AND question_id=?",
                (request.parent_id, str(request.reply_to_question_id)),
            ).fetchone()
        ):
            raise ParentChatError("upsell_currency_disabled", 503)
        super()._on_admitted(db, request, turn_id, now)
        if isinstance(request, ParentTouchReviewedTurn) and request.reply_to_question_id:
            # Other answers continue through the manager; they never silently
            # complete, reinterpret or resurrect the frozen commercial enquiry.
            db.execute(
                "UPDATE upsell_currency_questions SET status='abandoned',answer_turn_id=? "
                "WHERE parent_id=? AND question_id=? AND status='waiting'",
                (turn_id, request.parent_id, str(request.reply_to_question_id)),
            )
        if (
            self._currency_enabled
            and db.execute(
                "SELECT 1 FROM upsell_turns WHERE parent_id=? AND turn_id=?",
                (request.parent_id, turn_id),
            ).fetchone()
        ):
            db.execute(
                "INSERT INTO upsell_currency_admissions VALUES(?,?)", (turn_id, request.parent_id)
            )

    def _question_reply_needs_safety(
        self, db: sqlite3.Connection, request: ParentTouchReviewedTurn, turn_id: int
    ) -> bool:
        if (
            request.reply_to_question_id
            and db.execute(
                "SELECT 1 FROM upsell_currency_questions WHERE parent_id=? AND question_id=?",
                (request.parent_id, str(request.reply_to_question_id)),
            ).fetchone()
        ):
            return False
        return super()._question_reply_needs_safety(db, request, turn_id)

    def _defer_initial_review(
        self,
        db: sqlite3.Connection,
        request: ParentTouchReviewedTurn,
        turn_id: int,
        now: datetime,
        context: str,
    ) -> bool:
        deferred = super()._defer_initial_review(db, request, turn_id, now, context)
        if deferred and self._currency_enabled:
            row = db.execute(
                "SELECT language FROM parent_touch_manager_turns WHERE turn_id=? AND parent_id=?",
                (turn_id, request.parent_id),
            ).fetchone()
            # The owning tariff helper already recognizes domain-specific RU/UZ/EN
            # wording. Freeze that same presentation at admission, not a contact
            # preference fallback or a later short currency answer. Old captures
            # never revisit this hook.
            language = upsell_language(request.message, row[0])
            db.execute(
                "UPDATE parent_touch_manager_turns SET language=? WHERE turn_id=? AND parent_id=?",
                (language, turn_id, request.parent_id),
            )
        return deferred

    async def upsell_scope(self, parent_id: str, turn_id: int) -> UpsellScope | None:
        scope = await super().upsell_scope(parent_id, turn_id)
        if scope is None:
            return None

        def captured() -> bool:
            with self._connect() as db:
                return bool(
                    db.execute(
                        "SELECT 1 FROM upsell_currency_admissions WHERE parent_id=? AND turn_id=?",
                        (parent_id, turn_id),
                    ).fetchone()
                )

        if not await asyncio.to_thread(captured):
            return scope
        if not self._currency_enabled:
            raise ParentChatError("upsell_currency_disabled", 503)
        return UpsellScope(protocol="catalog-currency-v2")

    def _valid_decision(
        self, db: sqlite3.Connection, turn: StoredChatTurn, receipt: ChatModelReceipt, now: datetime
    ) -> bool:
        enquiry = receipt.upsell_enquiry
        if (
            not self._currency_enabled
            and db.execute(
                "SELECT 1 FROM upsell_currency_admissions WHERE turn_id=? AND parent_id=?",
                (turn.turn_id, turn.parent_id),
            ).fetchone()
        ):
            return False
        if enquiry is None:
            return super()._valid_decision(db, turn, receipt, now)
        if (
            not self._currency_enabled
            or enquiry.currency is not None
            or receipt.upsell_choice
            or receipt.reminder_candidate
            or receipt.clarification_question
            or receipt.question_id
            or receipt.notice_id
            or receipt.manager_handoff
            or not turn.message
            or enquiry.parent_quote not in turn.message
        ):
            return False
        captured = db.execute(
            "SELECT 1 FROM upsell_currency_admissions a JOIN parent_touch_manager_turns m "
            "ON m.turn_id=a.turn_id AND m.parent_id=a.parent_id WHERE a.turn_id=? "
            "AND a.parent_id=? AND m.phase='cap_running' AND m.choice='upsell'",
            (turn.turn_id, turn.parent_id),
        ).fetchone()
        pending = db.execute(
            "SELECT COUNT(*),SUM(parent_id=?) FROM family_questions WHERE status IN "
            "('queued','offered','awaiting_reply','held') AND expires_at>?",
            (turn.parent_id, now.isoformat()),
        ).fetchone()
        return (
            bool(captured)
            and pending[0] < self._upsell_policy.maximum_pending_global
            and (pending[1] or 0) < self._question_limit
        ) and super()._valid_decision(db, turn, replace(receipt, upsell_enquiry=None), now)

    def _on_settled(
        self,
        db: sqlite3.Connection,
        turn: StoredChatTurn,
        receipt: ChatModelReceipt,
        *,
        valid: bool,
    ) -> None:
        super()._on_settled(db, turn, replace(receipt, upsell_enquiry=None), valid=valid)
        if not valid or receipt.upsell_enquiry is None:
            return
        row = db.execute(
            "SELECT t.updated_at,m.language FROM parent_chat_turns t "
            "JOIN parent_touch_manager_turns m ON m.turn_id=t.id AND m.parent_id=t.parent_id "
            "WHERE t.id=? AND t.parent_id=?",
            (turn.turn_id, turn.parent_id),
        ).fetchone()
        now, language = datetime.fromisoformat(row[0]), row[1]
        identity = uuid5(NAMESPACE_URL, f"mana:tariff-currency:{turn.parent_id}:{turn.request_id}")
        question = FamilyQuestion(
            question_id=identity,
            parent_id=turn.parent_id,
            child_id=None,
            scope="parent",
            information_key="parent.tariff_currency",
            question=_QUESTIONS[language],
            reason="Currency for the exact parent-requested tariff enquiry, not an action grant.",
            priority=1,
            status="awaiting_reply",
            observed_at=now,
            created_at=now,
            expires_at=now + timedelta(days=1),
            offered_turn_id=turn.turn_id,
        )
        db.execute(
            "INSERT INTO family_questions(question_id,parent_id,child_id,information_key,status,"
            "payload,created_at,expires_at,priority,offered_turn_id) "
            "VALUES(?,?,NULL,?,'awaiting_reply',?,?,?,?,?)",
            (
                str(identity),
                turn.parent_id,
                question.information_key,
                question.model_dump_json(),
                now.isoformat(),
                question.expires_at.isoformat(),
                question.priority,
                turn.turn_id,
            ),
        )
        db.execute(
            "INSERT INTO upsell_currency_questions VALUES(?,?,?,?,?,'waiting',NULL)",
            (
                turn.turn_id,
                turn.parent_id,
                str(identity),
                receipt.upsell_enquiry.model_dump_json(),
                language,
            ),
        )
        db.execute(
            "UPDATE family_turn_metadata SET published_question_id=? "
            "WHERE parent_id=? AND turn_id=?",
            (str(identity), turn.parent_id, turn.turn_id),
        )
        self._rewrite_answer(db, turn.turn_id, turn.parent_id, question.question)
        self._upsell_event(db, None, "currency_question_published", now)

    async def upsell_currency_control(
        self, request: ParentTouchMessageRequest, now: datetime
    ) -> ParentTouchMessageState | None:
        if request.reply_to_question_id is None:
            return None
        return await asyncio.to_thread(self._currency_answer, request, self._utc(now))

    def _currency_answer(
        self, request: ParentTouchMessageRequest, now: datetime
    ) -> ParentTouchMessageState | None:
        with self._transaction() as db:
            prior = db.execute(
                "SELECT request_digest FROM parent_chat_turns WHERE parent_id=? AND request_id=?",
                (request.parent_id, str(request.request_id)),
            ).fetchone()
            if prior:
                if prior[0] != self._digest(ParentTouchReviewedTurn(**request.model_dump())):
                    raise ParentChatError("request_id_conflict", 409)
                return None  # Existing history owns replay, even after deactivation.
            row = db.execute(
                "SELECT c.*,q.status AS question_status,q.expires_at "
                "FROM upsell_currency_questions c "
                "JOIN family_questions q ON q.question_id=c.question_id "
                "AND q.parent_id=c.parent_id "
                "WHERE c.parent_id=? AND c.question_id=?",
                (request.parent_id, str(request.reply_to_question_id)),
            ).fetchone()
            if row is None:
                return None
            if not self._currency_enabled:
                raise ParentChatError("upsell_currency_disabled", 503)
            if (
                row["status"] != "waiting"
                or row["question_status"] != "awaiting_reply"
                or now >= datetime.fromisoformat(row["expires_at"])
            ):
                raise ParentChatError("upsell_currency_question_not_active", 409)
            currency = request.message.strip().upper()
            if currency not in {"UZS", "USD"} or self._manager_priority(
                db, request.parent_id, row["origin_turn_id"], now
            ):
                return None  # New intent or urgent Safety follows the normal manager path.
            if request.reply_to_confirmation_id is not None:
                raise ParentChatError("upsell_currency_reply_conflict", 409)
            waiting = db.execute(
                "SELECT COUNT(*),SUM(parent_id=?) FROM upsell_intents WHERE status "
                "IN ('queued','checking','ready')",
                (request.parent_id,),
            ).fetchone()
            if (
                waiting[0] >= self._upsell_policy.maximum_pending_global
                or (waiting[1] or 0) >= self._upsell_policy.maximum_pending_per_parent
            ):
                raise ParentChatError("upsell_queue_full", 429)
            recent = db.execute(
                "SELECT COUNT(*),SUM(parent_id=?) FROM assistant_events WHERE "
                "kind='host_message_published' AND at>?",
                (request.parent_id, (now - timedelta(days=1)).isoformat()),
            ).fetchone()
            if (
                recent[0] >= self._reminder_policy.global_commands_per_24h
                or (recent[1] or 0) >= self._reminder_policy.parent_commands_per_24h
            ):
                raise ParentChatError("assistant_command_limit_exceeded", 429)
            terms = UpsellEnquiry.model_validate_json(row["terms"])
            choice = UpsellChoice.model_validate({**terms.model_dump(), "currency": currency})
            result = self._host_reply(
                db, request, request.parent_id, request.request_id, upsell_ack(row["language"]), now
            )
            self._bind_answer(db, ParentTouchReviewedTurn(**request.model_dump()), result.turn_id)
            intent = UpsellIntent(
                intent_id=uuid5(request.request_id, "resolved-tariff-currency"),
                parent_id=request.parent_id,
                origin_turn_id=result.turn_id,
                choice=choice,
                language=row["language"],
                created_at=now,
            )
            db.execute(
                "INSERT INTO upsell_intents(intent_id,parent_id,origin_turn_id,status,payload) "
                "VALUES(?,?,?,'queued',?)",
                (
                    str(intent.intent_id),
                    request.parent_id,
                    result.turn_id,
                    intent.model_dump_json(),
                ),
            )
            db.execute(
                "UPDATE upsell_currency_questions SET status='resolved',answer_turn_id=? "
                "WHERE origin_turn_id=?",
                (result.turn_id, row["origin_turn_id"]),
            )
            self._upsell_event(db, str(intent.intent_id), "currency_answer_bound", now)
            return result

    async def claim_upsell(self, now: datetime) -> UpsellWork | None:
        if not self._currency_enabled:

            def stop() -> None:
                with self._transaction() as db:
                    db.execute(
                        "UPDATE upsell_intents SET status='cancelled' "
                        "WHERE status IN ('queued','ready') "
                        "AND origin_turn_id IN (SELECT answer_turn_id "
                        "FROM upsell_currency_questions "
                        "WHERE status='resolved')"
                    )

            await asyncio.to_thread(stop)
        return await super().claim_upsell(now)

    async def upsell_active(self, work: UpsellWork, now: datetime) -> bool:
        if not self._currency_enabled:

            def captured() -> bool:
                with self._connect() as db:
                    return bool(
                        db.execute(
                            "SELECT 1 FROM upsell_currency_questions WHERE answer_turn_id=? "
                            "AND parent_id=? AND status='resolved'",
                            (work.intent.origin_turn_id, work.intent.parent_id),
                        ).fetchone()
                    )

            if await asyncio.to_thread(captured):
                return False
        return await super().upsell_active(work, now)

    def _publish_quote(self, db: sqlite3.Connection, identity: str, now: datetime) -> bool:
        if (
            not self._currency_enabled
            and db.execute(
                "SELECT 1 FROM upsell_currency_questions c JOIN upsell_intents i "
                "ON i.origin_turn_id=c.answer_turn_id AND i.parent_id=c.parent_id "
                "WHERE i.intent_id=? AND c.status='resolved'",
                (identity,),
            ).fetchone()
        ):
            db.execute(
                "UPDATE upsell_intents SET status='cancelled' WHERE intent_id=?", (identity,)
            )
            return True
        return super()._publish_quote(db, identity, now)


class SqliteClosedUpsellCurrencyStore(SqliteClosedUsageComparisonSafetyStore):
    _schema_version = 31

    def _supported_versions(self) -> set[int]:
        return {31}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | _TABLES
