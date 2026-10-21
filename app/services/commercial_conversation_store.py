"""Private v9 immutable offer bindings and host-owned free-day result messages.

No implicit grant, billing mutation, source polling or model-authorized write.
Old turns keep their exact context absence. New grants require the proposal frozen
on the actual parent reply, in addition to current owning-policy validation.
"""

import asyncio
import hashlib
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import cast
from uuid import uuid5

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.application.conversion import OfferRenderer
from app.mana_ai.application.parent_languages import parent_language
from app.mana_ai.application.parent_touch_offers import (
    render_expired_parent_offer,
    render_trial_result,
)
from app.mana_ai.domain.chat import ParentChatRequest, ResponseLanguage
from app.mana_ai.domain.child_safety import ChildSafetyLimits
from app.mana_ai.domain.commercial_conversation import CommercialConversationContext
from app.mana_ai.domain.conversion import (
    ConversionOffer,
    ConversionPolicy,
    ConversionProposal,
    ConversionSnapshot,
    conversion_reason,
    elapsed_free_days,
)
from app.mana_ai.domain.conversion_grants import TrialAcceptance, TrialGrantState
from app.services.proactive_parent_store import (
    SqliteClosedProactiveParentStore,
    SqliteProactiveParentStore,
)

COMMERCIAL_TABLES = {"conversion_chat_contexts", "conversion_trial_result_messages"}


def _hash(payload: str) -> str:
    return hashlib.sha256(payload.encode()).hexdigest()


def _read_context(
    connection: sqlite3.Connection,
    parent_id: str,
    turn_id: int,
) -> CommercialConversationContext | None:
    row = connection.execute(
        "SELECT payload,digest FROM conversion_chat_contexts WHERE parent_id=? AND turn_id=?",
        (parent_id, turn_id),
    ).fetchone()
    if row is None:
        return None
    context = CommercialConversationContext.model_validate_json(row["payload"])
    if (
        context.parent_id != parent_id
        or context.turn_id != turn_id
        or _hash(row["payload"]) != row["digest"]
    ):
        raise ParentChatError("commercial_turn_context_changed", 503)
    return context


class SqliteCommercialConversationStore(SqliteProactiveParentStore):
    _schema_version = 9

    def __init__(
        self,
        path: Path,
        conversion_policy: ConversionPolicy,
        conversion_offers: tuple[ConversionOffer, ...],
        limits: ChildSafetyLimits,
        daily_limit: int,
        timezone: str,
        max_attempts: int = 20,
        question_limit: int = 100,
        push_queue_limit: int = 1000,
        push_max_age_seconds: int = 3600,
        push_daily_attempt_limit: int = 100,
        proactive_enabled: bool = True,
        push_enabled: bool = True,
        conversation_enabled: bool = True,
    ) -> None:
        super().__init__(
            path,
            conversion_policy=conversion_policy,
            conversion_offers=conversion_offers,
            limits=limits,
            daily_limit=daily_limit,
            timezone=timezone,
            max_attempts=max_attempts,
            question_limit=question_limit,
            push_queue_limit=push_queue_limit,
            push_max_age_seconds=push_max_age_seconds,
            push_daily_attempt_limit=push_daily_attempt_limit,
            proactive_enabled=proactive_enabled,
            push_enabled=push_enabled,
        )
        self._conversation_enabled = conversation_enabled

    def _supported_versions(self) -> set[int]:
        return super()._supported_versions() | {8, 9}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | COMMERCIAL_TABLES

    def _extra_schema(self) -> str:
        return (
            super()._extra_schema()
            + """
            CREATE TABLE IF NOT EXISTS conversion_chat_contexts (
                parent_id TEXT NOT NULL,
                turn_id INTEGER PRIMARY KEY,
                payload TEXT NOT NULL,
                digest TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS conversion_trial_result_messages (
                action_id TEXT PRIMARY KEY,
                parent_id TEXT NOT NULL,
                proposal_id TEXT NOT NULL,
                payload TEXT NOT NULL,
                digest TEXT NOT NULL,
                recorded_at TEXT NOT NULL,
                language TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('queued','published')),
                turn_id INTEGER UNIQUE
            );
            CREATE INDEX IF NOT EXISTS conversion_trial_result_due
                ON conversion_trial_result_messages(status,recorded_at);
        """
        )

    def _conversion_reason(self, snapshot: ConversionSnapshot, now: datetime) -> str:
        return conversion_reason(
            snapshot,
            self._conversion_policy,
            now,
            include_expired=self._conversation_enabled,
        )

    def _reason_eligible(self, reason: str) -> bool:
        return reason == "free_access_expired" or super()._reason_eligible(reason)

    def _offer_eligible(self, offer: ConversionOffer, reason: str) -> bool:
        return reason != "free_access_expired" or offer.kind == "paid_subscription"

    def _proposal_reason_matches(self, proposal: ConversionProposal, reason: str) -> bool:
        return proposal.reason == reason

    def _render_offer(
        self,
        proposal: ConversionProposal,
        snapshot: ConversionSnapshot,
        now: datetime,
        renderer: OfferRenderer,
    ) -> str:
        if proposal.reason == "free_access_expired":
            if proposal.offer.kind != "paid_subscription" or snapshot.free_access_ends_at is None:
                raise ParentChatError("expired_free_offer_invalid", 503)
            return render_expired_parent_offer(
                proposal.offer,
                elapsed_free_days(snapshot, now),
                snapshot.free_access_ends_at,
                snapshot.language,
            )
        return renderer(proposal.offer, elapsed_free_days(snapshot, now), snapshot.language)

    def _on_admitted(
        self,
        connection: sqlite3.Connection,
        request: ParentChatRequest,
        turn_id: int,
        now: datetime,
    ) -> None:
        super()._on_admitted(connection, request, turn_id, now)
        if not self._conversation_enabled or not request.message:
            return
        proposal_row = connection.execute(
            "SELECT payload FROM conversion_proposals WHERE parent_id=? AND turn_id<? "
            "AND published_at IS NOT NULL ORDER BY turn_id DESC LIMIT 1",
            (request.parent_id, turn_id),
        ).fetchone()
        proposal = (
            ConversionProposal.model_validate_json(proposal_row["payload"])
            if proposal_row
            else None
        )
        account = connection.execute(
            "SELECT snapshot,opted_out,converted FROM conversion_accounts WHERE parent_id=?",
            (request.parent_id,),
        ).fetchone()
        snapshot = ConversionSnapshot.model_validate_json(account["snapshot"]) if account else None
        grant_row = connection.execute(
            "SELECT payload FROM conversion_trial_grants WHERE parent_id=?",
            (request.parent_id,),
        ).fetchone()
        grant = TrialGrantState.model_validate_json(grant_row["payload"]) if grant_row else None
        if proposal is None and grant is None:
            return
        recorded = connection.execute(
            "SELECT recorded_at FROM conversion_trial_result_messages WHERE parent_id=?",
            (request.parent_id,),
        ).fetchone()
        language_row = connection.execute(
            "SELECT language_reference FROM family_turn_metadata WHERE parent_id=? AND turn_id=?",
            (request.parent_id, turn_id),
        ).fetchone()
        language = parent_language(language_row["language_reference"]) if language_row else None
        available = bool(
            proposal
            and snapshot
            and account
            and not account["opted_out"]
            and not account["converted"]
            and proposal.status in {"published", "interested"}
            and self._conversion_offers.get(proposal.offer.offer_id) == proposal.offer
            and proposal.offer.valid_from <= now < proposal.offer.valid_until
            and self._reason_eligible(self._conversion_reason(snapshot, now))
            and self._offer_eligible(proposal.offer, self._conversion_reason(snapshot, now))
            and not connection.execute(
                "SELECT 1 FROM conversion_opt_outs WHERE parent_id=?",
                (request.parent_id,),
            ).fetchone()
            and (
                proposal.offer.kind != "free_premium_days"
                or snapshot.agent_trial_given is False
                and grant is None
            )
        )
        context = CommercialConversationContext(
            parent_id=request.parent_id,
            turn_id=turn_id,
            captured_at=now,
            proposal=proposal,
            offer_available_at_capture=available,
            grant=grant,
            grant_recorded_at=recorded["recorded_at"] if recorded else None,
            language=language or (snapshot.language if snapshot else None),
        )
        payload = context.model_dump_json()
        connection.execute(
            "INSERT INTO conversion_chat_contexts(parent_id,turn_id,payload,digest) "
            "VALUES(?,?,?,?)",
            (request.parent_id, turn_id, payload, _hash(payload)),
        )

    async def commercial_context(
        self,
        parent_id: str,
        turn_id: int,
    ) -> CommercialConversationContext | None:
        def read() -> CommercialConversationContext | None:
            with self._connect() as connection:
                return _read_context(connection, parent_id, turn_id)

        return await asyncio.to_thread(read)

    def _validate_trial_reply(
        self,
        connection: sqlite3.Connection,
        acceptance: TrialAcceptance,
        proposal: ConversionProposal,
        now: datetime,
    ) -> None:
        context = _read_context(connection, acceptance.parent_id, acceptance.reply_turn_id)
        if (
            not self._conversation_enabled
            or context is None
            or context.proposal is None
            or context.proposal.proposal_id != proposal.proposal_id
            or context.proposal.offer != proposal.offer
            or not context.offer_available_at_capture
            or context.grant is not None
        ):
            raise ParentChatError("trial_reply_has_no_frozen_offer", 409)

    def _on_trial_grant_finished(
        self,
        connection: sqlite3.Connection,
        state: TrialGrantState,
        now: datetime,
    ) -> None:
        if state.status == "submitting":
            return
        row = connection.execute(
            "SELECT acceptance FROM conversion_trial_grants WHERE parent_id=?",
            (state.parent_id,),
        ).fetchone()
        assert row is not None
        acceptance = TrialAcceptance.model_validate_json(row["acceptance"])
        context = _read_context(connection, state.parent_id, acceptance.reply_turn_id)
        if context is None or context.language is None:
            # Historical actions have no invented recipient language or receipt date.
            return
        payload = state.model_dump_json()
        connection.execute(
            "INSERT INTO conversion_trial_result_messages(action_id,parent_id,proposal_id,payload,"
            "digest,recorded_at,language,status) VALUES(?,?,?,?,?,?,?,'queued')",
            (
                str(state.action_id),
                state.parent_id,
                str(state.proposal_id),
                payload,
                _hash(payload),
                now.isoformat(),
                context.language,
            ),
        )

    async def publish_trial_result(self, now: datetime) -> bool:
        if not self._conversation_enabled:
            return False

        def publish() -> bool:
            current = self._utc(now)
            with self._transaction() as connection:
                row = connection.execute(
                    "SELECT n.* FROM conversion_trial_result_messages n WHERE n.status='queued' "
                    "AND NOT EXISTS(SELECT 1 FROM parent_chat_turns t "
                    "WHERE t.parent_id=n.parent_id "
                    "AND t.status IN ('preparing','submitted','unknown')) "
                    "AND NOT EXISTS(SELECT 1 FROM child_safety_jobs j "
                    "WHERE j.parent_id=n.parent_id "
                    "AND j.status IN ('queued','preparing','submitted','unknown','metered')) "
                    "AND NOT EXISTS(SELECT 1 FROM family_notices f WHERE f.parent_id=n.parent_id "
                    "AND f.kind='urgent' AND f.status IN ('queued','offered','held') "
                    "AND f.expires_at>?) ORDER BY n.recorded_at,n.action_id LIMIT 1",
                    (current.isoformat(),),
                ).fetchone()
                if row is None:
                    return False
                state = TrialGrantState.model_validate_json(row["payload"])
                actual = connection.execute(
                    "SELECT payload FROM conversion_trial_grants WHERE parent_id=? AND action_id=?",
                    (row["parent_id"], row["action_id"]),
                ).fetchone()
                if (
                    _hash(row["payload"]) != row["digest"]
                    or actual is None
                    or actual["payload"] != row["payload"]
                    or state.status == "submitting"
                    or state.parent_id != row["parent_id"]
                    or str(state.action_id) != row["action_id"]
                    or str(state.proposal_id) != row["proposal_id"]
                ):
                    raise ParentChatError("trial_result_message_changed", 503)
                if row["language"] not in {"ru", "uz-Latn", "uz-Cyrl", "en"}:
                    raise ParentChatError("trial_result_language_invalid", 503)
                answer = render_trial_result(
                    state,
                    datetime.fromisoformat(row["recorded_at"]),
                    cast(ResponseLanguage, row["language"]),
                )
                day, _ = self._period(current)
                cursor = connection.execute(
                    "INSERT INTO parent_chat_turns(parent_id,request_id,message,request_digest,day,"
                    "status,reserved,created_at,updated_at,answer,model) "
                    "VALUES(?,?,'',?,?,'completed',0,?,?,?,'parent-touch-trial-result-v1')",
                    (
                        state.parent_id,
                        str(uuid5(state.action_id, "parent-touch-trial-result-v1")),
                        row["digest"],
                        day,
                        current.isoformat(),
                        current.isoformat(),
                        answer,
                    ),
                )
                connection.execute(
                    "UPDATE conversion_trial_result_messages SET status='published',turn_id=? "
                    "WHERE action_id=? AND status='queued'",
                    (cursor.lastrowid, row["action_id"]),
                )
                return True

        return await asyncio.to_thread(publish)


class SqliteClosedCommercialConversationStore(SqliteClosedProactiveParentStore):
    """Same-code history reader; no result dispatch, grant or historical recapture."""

    _schema_version = 9

    def _supported_versions(self) -> set[int]:
        return {9}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | COMMERCIAL_TABLES

    async def commercial_context(
        self,
        parent_id: str,
        turn_id: int,
    ) -> CommercialConversationContext | None:
        def read() -> CommercialConversationContext | None:
            with self._connect() as connection:
                return _read_context(connection, parent_id, turn_id)

        return await asyncio.to_thread(read)
