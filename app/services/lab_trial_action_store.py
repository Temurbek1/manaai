"""Lab v25: a new published trial can capture a button-bound owning grant claim."""

import asyncio
import hashlib
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.application.trial_action_cards import TrialButtonGrantService
from app.mana_ai.domain.chat import ResponseLanguage
from app.mana_ai.domain.chat_actions import (
    ChatActionButton,
    ChatActionCard,
    ChatActionClaim,
    ChatActionClick,
    ChatActionResult,
    TrialCardTerms,
    TrialChatActionResult,
)
from app.mana_ai.domain.conversion import ConversionProposal, ConversionSnapshot
from app.mana_ai.domain.conversion_grants import (
    TrialAcceptance,
    TrialButtonAcceptance,
    TrialGrantState,
)
from app.mana_ai.domain.trial_action_cards import TrialCardDefinition
from app.services.lab_chat_action_store import (
    SimulatedChatActionExecutor,
    SqliteLabChatActionStore,
)
from app.services.location_safety_store import SqliteClosedLocationSafetyStore
from app.services.proactive_parent_store import _current_context


def _presentation(days: int, language: ResponseLanguage) -> tuple[str, str, str, str]:
    return {
        "ru": (
            f"Бесплатный Maxsus на {days} дн.",
            f"Могу предложить бесплатный Maxsus на {days} дн. один раз для вашего аккаунта. "
            "Подтвердите кнопкой ниже. Платёж, транзакция и автосписание не создаются.",
            "Активировать бесплатно",
            "Не сейчас",
        ),
        "uz-Latn": (
            f"{days} kunlik bepul Maxsus",
            f"Hisobingiz uchun bir marta {days} kunlik bepul Maxsus taklif qilaman. "
            "Quyidagi tugma bilan tasdiqlang. "
            "To‘lov, tranzaksiya yoki avtomatik yechish yaratilmaydi.",
            "Bepul faollashtirish",
            "Hozir emas",
        ),
        "uz-Cyrl": (
            f"{days} кунлик бепул Maxsus",
            f"Ҳисобингиз учун бир марта {days} кунлик бепул Maxsus таклиф қиламан. "
            "Қуйидаги тугма билан тасдиқланг. Тўлов, транзакция ёки автоматик ечиш яратилмайди.",
            "Бепул фаоллаштириш",
            "Ҳозир эмас",
        ),
        "en": (
            f"{days} free Maxsus days",
            f"I can offer {days} free Maxsus days once for your account. "
            "Confirm with the button below. "
            "No payment, transaction or automatic charge is created.",
            "Activate free days",
            "Not now",
        ),
    }[language]


class SqliteLabTrialActionStore(SqliteLabChatActionStore):
    _schema_version = 25

    def __init__(self, path: Path, *, trial_cards_enabled: bool = False, **family: Any) -> None:
        self._trial_cards_enabled = trial_cards_enabled
        super().__init__(path, **family)

    def _supported_versions(self) -> set[int]:
        return super()._supported_versions() | {24}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | {
            "trial_card_admissions",
            "trial_card_bindings",
            "trial_button_dispatches",
        }

    def _extra_schema(self) -> str:
        return (
            super()._extra_schema()
            + """
        CREATE TABLE IF NOT EXISTS trial_card_admissions(
          proposal_id TEXT PRIMARY KEY,parent_id TEXT NOT NULL,enabled INTEGER NOT NULL
          CHECK(enabled IN (0,1)),snapshot_revision INTEGER NOT NULL,offer_digest TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS trial_card_bindings(
          card_id TEXT PRIMARY KEY,parent_id TEXT NOT NULL,proposal_id TEXT NOT NULL UNIQUE);
        CREATE TABLE IF NOT EXISTS trial_button_dispatches(
          card_id TEXT PRIMARY KEY,parent_id TEXT NOT NULL,acceptance TEXT NOT NULL,
          phase TEXT NOT NULL CHECK(phase IN ('ready','submitted','settled')));
        """
        )

    def _on_conversion_created(
        self,
        db: sqlite3.Connection,
        proposal: ConversionProposal,
        snapshot: ConversionSnapshot,
        now: datetime,
    ) -> None:
        super()._on_conversion_created(db, proposal, snapshot, now)
        if proposal.offer.kind == "free_premium_days":
            db.execute(
                "INSERT INTO trial_card_admissions VALUES(?,?,?,?,?)",
                (
                    str(proposal.proposal_id),
                    proposal.parent_id,
                    int(self._trial_cards_enabled),
                    snapshot.revision,
                    hashlib.sha256(proposal.offer.model_dump_json().encode()).hexdigest(),
                ),
            )

    def _can_attach(
        self,
        db: sqlite3.Connection,
        proposal: ConversionProposal,
        snapshot: ConversionSnapshot,
        now: datetime,
    ) -> bool:
        context = _current_context(db, proposal.parent_id, now)
        captured = db.execute(
            "SELECT * FROM trial_card_admissions WHERE proposal_id=?", (str(proposal.proposal_id),)
        ).fetchone()
        return bool(
            self._trial_cards_enabled
            and captured
            and captured["enabled"]
            and captured["parent_id"] == proposal.parent_id
            and captured["snapshot_revision"] == snapshot.revision
            and captured["offer_digest"]
            == hashlib.sha256(proposal.offer.model_dump_json().encode()).hexdigest()
            and proposal.offer.kind == "free_premium_days"
            and context
            and context.language == snapshot.language
            and context.timezone == snapshot.timezone
            and min(
                proposal.offer.valid_until,
                snapshot.observed_at
                + timedelta(seconds=self._conversion_policy.snapshot_max_age_seconds),
            )
            >= now + timedelta(seconds=60)
            and not self._action_pending(db, proposal.parent_id, now)
            and db.execute("SELECT count(*) FROM lab_action_cards").fetchone()[0] < 500
            and db.execute(
                "SELECT count(*) FROM lab_action_cards WHERE parent_id=? AND created_at>=?",
                (proposal.parent_id, (now - timedelta(days=1)).isoformat()),
            ).fetchone()[0]
            < 20
            and not db.execute(
                "SELECT 1 FROM conversion_trial_grants WHERE parent_id=?", (proposal.parent_id,)
            ).fetchone()
        )

    def _chat_busy(self, connection: sqlite3.Connection, parent_id: str, now: datetime) -> bool:
        return self._action_pending(connection, parent_id, now) or super()._chat_busy(
            connection, parent_id, now
        )

    def _action_pending(self, db: sqlite3.Connection, parent: str, now: datetime) -> bool:
        rows = db.execute(
            "SELECT * FROM lab_action_cards WHERE parent_id=? AND "
            "((status='pending' AND expires_at>?) OR status IN ('executing','unknown'))",
            (parent, now.isoformat()),
        ).fetchall()
        return any(
            self._card(row, now, db).status in {"pending", "executing", "unknown"} for row in rows
        )

    def _opt_out(self, db: sqlite3.Connection, parent_id: str, now: datetime) -> None:
        super()._opt_out(db, parent_id, now)
        rows = db.execute(
            "SELECT c.card_id FROM lab_action_cards c JOIN trial_card_bindings b "
            "ON b.card_id=c.card_id AND b.parent_id=c.parent_id "
            "WHERE c.parent_id=? AND c.status='pending' AND c.selected_button IS NULL",
            (parent_id,),
        ).fetchall()
        for row in rows:
            db.execute("UPDATE lab_action_cards SET status='cancelled' WHERE card_id=?", (row[0],))
            self._action_event(db, UUID(row[0]), "cancelled_by_opt_out", now)

    def _on_conversion_published(
        self, db: sqlite3.Connection, proposal: ConversionProposal, now: datetime
    ) -> None:
        row = db.execute(
            "SELECT snapshot FROM conversion_accounts WHERE parent_id=?", (proposal.parent_id,)
        ).fetchone()
        snapshot = ConversionSnapshot.model_validate_json(row[0])
        if not self._can_attach(db, proposal, snapshot, now):
            super()._on_conversion_published(db, proposal, now)
            return
        assert proposal.offer.kind == "free_premium_days" and proposal.turn_id is not None
        title, text, confirm, cancel = _presentation(proposal.offer.grant_days, snapshot.language)
        card_id = uuid5(proposal.proposal_id, "trial-confirmation-card-v1")
        definition = TrialCardDefinition(
            parent_id=proposal.parent_id,
            request_id=uuid5(card_id, "create"),
            proposal=proposal,
            title=title,
            text=text,
            language=snapshot.language,
            timezone=snapshot.timezone,
            snapshot_revision=snapshot.revision,
            buttons=(
                ChatActionButton(id="confirm", label=confirm),
                ChatActionButton(id="cancel", label=cancel),
            ),
            created_at=now,
            expires_at=min(
                now + timedelta(seconds=900),
                proposal.offer.valid_until,
                snapshot.observed_at
                + timedelta(seconds=self._conversion_policy.snapshot_max_age_seconds),
            ),
        )
        payload = definition.model_dump_json()
        db.execute(
            "INSERT INTO lab_action_cards(card_id,parent_id,request_id,definition,"
            "definition_hash,turn_id,created_at,expires_at,status) "
            "VALUES(?,?,?,?,?,?,?,?,'pending')",
            (
                str(card_id),
                proposal.parent_id,
                str(definition.request_id),
                payload,
                hashlib.sha256(payload.encode()).hexdigest(),
                proposal.turn_id,
                now.isoformat(),
                definition.expires_at.isoformat(),
            ),
        )
        db.execute(
            "INSERT INTO trial_card_bindings VALUES(?,?,?)",
            (str(card_id), proposal.parent_id, str(proposal.proposal_id)),
        )
        self._action_event(db, card_id, "created", now)
        # Publication has not committed yet. The existing single assistant turn
        # receives the exact card wording atomically with its proof and outbox.
        db.execute(
            "UPDATE parent_chat_turns SET answer=? WHERE id=? AND parent_id=?",
            (text, proposal.turn_id, proposal.parent_id),
        )
        super()._on_conversion_published(db, proposal, now)

    def _definition(self, db: sqlite3.Connection, row: sqlite3.Row) -> TrialCardDefinition:
        value = TrialCardDefinition.model_validate_json(row["definition"])
        captured = db.execute(
            "SELECT * FROM trial_card_admissions WHERE proposal_id=?",
            (str(value.proposal.proposal_id),),
        ).fetchone()
        binding = db.execute(
            "SELECT * FROM trial_card_bindings WHERE card_id=?", (row["card_id"],)
        ).fetchone()
        if (
            hashlib.sha256(row["definition"].encode()).hexdigest() != row["definition_hash"]
            or not captured
            or not captured["enabled"]
            or captured["parent_id"] != row["parent_id"]
            or captured["snapshot_revision"] != value.snapshot_revision
            or captured["offer_digest"]
            != hashlib.sha256(value.proposal.offer.model_dump_json().encode()).hexdigest()
            or not binding
            or binding["parent_id"] != row["parent_id"]
            or binding["proposal_id"] != str(value.proposal.proposal_id)
            or value.parent_id != row["parent_id"]
            or value.proposal.turn_id != row["turn_id"]
            or value.created_at != datetime.fromisoformat(row["created_at"])
            or value.expires_at != datetime.fromisoformat(row["expires_at"])
        ):
            raise ParentChatError("trial_card_proof_changed", 503)
        assert value.proposal.offer.kind == "free_premium_days"
        title, text, confirm, cancel = _presentation(
            value.proposal.offer.grant_days, value.language
        )
        if (
            value.title != title
            or value.text != text
            or value.buttons
            != (
                ChatActionButton(id="confirm", label=confirm),
                ChatActionButton(id="cancel", label=cancel),
            )
        ):
            raise ParentChatError("trial_card_proof_changed", 503)
        message = db.execute(
            "SELECT answer FROM parent_chat_turns WHERE parent_id=? AND id=?",
            (row["parent_id"], row["turn_id"]),
        ).fetchone()
        if not message or message[0] != value.text:
            raise ParentChatError("trial_card_proof_changed", 503)
        return value

    def _verified_result(
        self,
        db: sqlite3.Connection,
        row: sqlite3.Row,
        definition: TrialCardDefinition,
    ) -> TrialChatActionResult | None:
        own = db.execute(
            "SELECT acceptance,payload FROM conversion_trial_grants WHERE parent_id=?",
            (row["parent_id"],),
        ).fetchone()
        if own is None or row["selected_button"] != "confirm":
            if row["result"]:
                raise ParentChatError("trial_card_receipt_changed", 503)
            return None
        acceptance = self._parse_trial_acceptance(own["acceptance"])
        state = TrialGrantState.model_validate_json(own["payload"])
        assert definition.proposal.offer.kind == "free_premium_days"
        if (
            not isinstance(acceptance, TrialButtonAcceptance)
            or str(acceptance.confirmation_card_id) != row["card_id"]
            or str(acceptance.execution_id) != row["execution_id"]
            or str(acceptance.click_request_id) != row["click_id"]
            or acceptance.definition_hash != row["definition_hash"]
            or state.parent_id != row["parent_id"]
            or state.proposal_id != definition.proposal.proposal_id
            or state.days != definition.proposal.offer.grant_days
        ):
            raise ParentChatError("trial_card_receipt_changed", 503)
        if state.status == "submitting":
            if row["result"]:
                raise ParentChatError("trial_card_receipt_changed", 503)
            return None
        expected = TrialChatActionResult.model_validate(
            {
                "execution_id": acceptance.execution_id,
                "outcome": {
                    "granted": "trial_granted",
                    "rejected": "trial_rejected",
                    "unknown": "trial_unknown",
                }[state.status],
                "grant": state,
            }
        )
        if row["result"] and TrialChatActionResult.model_validate_json(row["result"]) != expected:
            raise ParentChatError("trial_card_receipt_changed", 503)
        return expected

    def _card(
        self, row: sqlite3.Row, now: datetime, db: sqlite3.Connection | None = None
    ) -> ChatActionCard:
        if json.loads(row["definition"]).get("action_type") != "free_trial_days":
            return super()._card(row, now, db)
        if db is None:
            with self._connect() as connection:
                return self._card(row, now, connection)
        definition = self._definition(db, row)
        assert definition.proposal.offer.kind == "free_premium_days"
        result = self._verified_result(db, row, definition)
        status = row["status"]
        if result is not None:
            status = "unknown" if result.outcome == "trial_unknown" else "completed"
        elif status == "pending" and definition.expires_at <= now:
            status = "expired"
        return ChatActionCard(
            sequence=row["sequence"],
            card_id=row["card_id"],
            parent_id=row["parent_id"],
            request_id=row["request_id"],
            turn_id=row["turn_id"],
            action_type="free_trial_days",
            title=definition.title,
            text=definition.text,
            buttons=definition.buttons,
            definition_hash=row["definition_hash"],
            created_at=definition.created_at,
            expires_at=definition.expires_at,
            status=status,
            selected_button=row["selected_button"],
            trial=TrialCardTerms(
                proposal_id=definition.proposal.proposal_id,
                grant_days=definition.proposal.offer.grant_days,
            ),
            result=result,
        )

    def _parse_trial_acceptance(self, payload: str) -> TrialAcceptance | TrialButtonAcceptance:
        if "confirmation_card_id" in json.loads(payload):
            return TrialButtonAcceptance.model_validate_json(payload)
        return super()._parse_trial_acceptance(payload)

    def _validate_trial_confirmation(
        self,
        db: sqlite3.Connection,
        acceptance: TrialAcceptance | TrialButtonAcceptance,
        proposal: ConversionProposal,
        current: datetime,
    ) -> None:
        if isinstance(acceptance, TrialAcceptance):
            super()._validate_trial_confirmation(db, acceptance, proposal, current)
            return
        if not self._trial_cards_enabled:
            raise ParentChatError("trial_cards_disabled", 503)
        row = db.execute(
            "SELECT * FROM lab_action_cards WHERE parent_id=? AND card_id=?",
            (acceptance.parent_id, str(acceptance.confirmation_card_id)),
        ).fetchone()
        if row is None:
            raise ParentChatError("trial_card_not_found", 404)
        definition = self._definition(db, row)
        context = _current_context(db, acceptance.parent_id, current)
        latest = db.execute(
            "SELECT proposal_id FROM conversion_proposals WHERE parent_id=? "
            "AND published_at IS NOT NULL ORDER BY turn_id DESC LIMIT 1",
            (acceptance.parent_id,),
        ).fetchone()
        if (
            row["status"] != "executing"
            or row["selected_button"] != "confirm"
            or row["execution_id"] != str(acceptance.execution_id)
            or row["click_id"] != str(acceptance.click_request_id)
            or row["definition_hash"] != acceptance.definition_hash
            or not definition.created_at <= current < definition.expires_at
            or definition.proposal.proposal_id != acceptance.proposal_id
            or definition.proposal.offer != proposal.offer
            or definition.proposal.turn_id != proposal.turn_id
            or not latest
            or latest[0] != str(acceptance.proposal_id)
            or not context
            or context.language != definition.language
            or context.timezone != definition.timezone
            or self._card_priority(db, acceptance.parent_id, current)
        ):
            raise ParentChatError("trial_card_confirmation_not_bound", 409)

    def _on_card_decided(
        self,
        db: sqlite3.Connection,
        card: ChatActionCard,
        click: ChatActionClick,
        execution: UUID | None,
        now: datetime,
    ) -> None:
        super()._on_card_decided(db, card, click, execution, now)
        if card.action_type != "free_trial_days" or execution is None:
            return
        assert card.trial is not None
        acceptance = TrialButtonAcceptance(
            parent_id=card.parent_id,
            event_id=uuid5(execution, "trial-button-acceptance-v1"),
            proposal_id=card.trial.proposal_id,
            confirmation_card_id=card.card_id,
            execution_id=execution,
            click_request_id=click.request_id,
            definition_hash=card.definition_hash,
        )
        _, dispatch = self._claim_trial_grant_in_transaction(db, acceptance, now)
        if not dispatch:
            raise ParentChatError("trial_grant_already_admitted", 409)
        db.execute(
            "INSERT INTO trial_button_dispatches VALUES(?,?,?,'ready')",
            (str(card.card_id), card.parent_id, acceptance.model_dump_json()),
        )

    async def button_acceptance(self, claim: ChatActionClaim) -> TrialButtonAcceptance:
        def read() -> TrialButtonAcceptance:
            with self._connect() as db:
                row = db.execute(
                    "SELECT acceptance FROM trial_button_dispatches WHERE card_id=? "
                    "AND parent_id=?",
                    (str(claim.card.card_id), claim.card.parent_id),
                ).fetchone()
                if row is None:
                    raise ParentChatError("trial_button_claim_missing", 409)
                value = TrialButtonAcceptance.model_validate_json(row[0])
                if value.execution_id != claim.execution_id:
                    raise ParentChatError("trial_button_claim_mismatch", 409)
                return value

        return await asyncio.to_thread(read)

    async def claim_button_trial(
        self, acceptance: TrialButtonAcceptance, now: datetime
    ) -> tuple[TrialGrantState, bool]:
        def claim() -> tuple[TrialGrantState, bool]:
            current = self._utc(now)
            with self._transaction() as db:
                dispatch = db.execute(
                    "SELECT * FROM trial_button_dispatches WHERE card_id=? AND parent_id=?",
                    (str(acceptance.confirmation_card_id), acceptance.parent_id),
                ).fetchone()
                row = db.execute(
                    "SELECT acceptance,payload FROM conversion_trial_grants WHERE parent_id=?",
                    (acceptance.parent_id,),
                ).fetchone()
                if (
                    not dispatch
                    or not row
                    or dispatch["acceptance"] != acceptance.model_dump_json()
                    or self._parse_trial_acceptance(row["acceptance"]) != acceptance
                ):
                    raise ParentChatError("trial_button_claim_mismatch", 409)
                state = TrialGrantState.model_validate_json(row["payload"])
                if dispatch["phase"] != "ready" or state.status != "submitting":
                    return state, False
                try:
                    proposal = self._eligible_trial_proposal(db, acceptance, current)
                    self._validate_trial_confirmation(db, acceptance, proposal, current)
                except ParentChatError as error:
                    refused = state.model_copy(
                        update={"status": "rejected", "error_code": error.code}
                    )
                    return self._finish_trial_grant_in_transaction(db, refused, current), False
                db.execute(
                    "UPDATE trial_button_dispatches SET phase='submitted' WHERE card_id=?",
                    (str(acceptance.confirmation_card_id),),
                )
                return state, True

        return await asyncio.to_thread(claim)

    def _trial_grant_language(
        self,
        db: sqlite3.Connection,
        parent: str,
        acceptance_payload: str,
    ) -> ResponseLanguage | None:
        acceptance = self._parse_trial_acceptance(acceptance_payload)
        if isinstance(acceptance, TrialAcceptance):
            return super()._trial_grant_language(db, parent, acceptance_payload)
        row = db.execute(
            "SELECT * FROM lab_action_cards WHERE card_id=? AND parent_id=?",
            (str(acceptance.confirmation_card_id), parent),
        ).fetchone()
        try:
            return self._definition(db, row).language if row else None
        except (ParentChatError, ValueError):
            return None  # Preserve the known grant, without an unverified recipient notice.

    def _on_trial_grant_finished(
        self,
        db: sqlite3.Connection,
        state: TrialGrantState,
        now: datetime,
    ) -> None:
        super()._on_trial_grant_finished(db, state, now)
        if state.status != "submitting":
            db.execute(
                "UPDATE trial_button_dispatches SET phase='settled' WHERE parent_id=?",
                (state.parent_id,),
            )


class LabTrialActionExecutor:
    """This adapter is mounted only alongside LabTrialGrantGateway, never live grants."""

    def __init__(self, store: SqliteLabTrialActionStore, grants: TrialButtonGrantService) -> None:
        self._store, self._grants = store, grants
        self.demo = SimulatedChatActionExecutor()

    async def execute(self, claim: ChatActionClaim) -> ChatActionResult | TrialChatActionResult:
        if claim.card.action_type == "sandbox_demo":
            return await self.demo.execute(claim)
        acceptance = await self._store.button_acceptance(claim)
        state = await self._grants.accept_button(acceptance)
        outcomes = {
            "granted": "trial_granted",
            "rejected": "trial_rejected",
            "unknown": "trial_unknown",
        }
        return TrialChatActionResult.model_validate(
            {
                "execution_id": claim.execution_id,
                "outcome": outcomes.get(state.status),
                "grant": state,
            }
        )


class SqliteClosedLabTrialActionStore(SqliteClosedLocationSafetyStore):
    """History-only v25 reader: no action service, migration or dispatch authority."""

    _schema_version = 25

    def _supported_versions(self) -> set[int]:
        return {25}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | {
            "lab_action_cards",
            "lab_action_events",
            "trial_card_bindings",
            "trial_card_admissions",
            "trial_button_dispatches",
        }
