"""Typed push boundary; a caller must durably claim each non-retriable send."""

from typing import Literal, Protocol

from app.mana_ai.domain.parent_notifications import ParentPushMessage, ParentPushReceipt

ParentPushRejectionCode = Literal[
    "parent_push_auth_rejected",
    "parent_push_not_authorized",
    "parent_push_invalid_message",
    "parent_push_parent_not_found",
]
ParentPushUnknownCode = Literal["parent_push_auth_unavailable", "parent_push_outcome_unknown"]


class ParentPushRejected(Exception):
    """A documented HTTP refusal, without raw upstream text or recipient data."""

    def __init__(
        self, code: ParentPushRejectionCode, status_code: Literal[400, 401, 403, 404]
    ) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


class ParentPushUnknown(Exception):
    """An unverified outcome; it must not cause automatic send replay."""

    def __init__(self, code: ParentPushUnknownCode) -> None:
        super().__init__(code)
        self.code = code


class ParentPushGateway(Protocol):
    async def send(self, message: ParentPushMessage) -> ParentPushReceipt: ...
