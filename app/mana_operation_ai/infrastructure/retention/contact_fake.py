"""Fictional receiver only: no tokens, addresses, HTTP clients or real notifications."""

import asyncio
from datetime import datetime
from uuid import uuid4

from app.mana_operation_ai.application.ports import (
    Clock,
    ProviderPermanentError,
    ProviderWriteUncertainError,
)
from app.mana_operation_ai.application.retention.contact_policy import (
    contact_fingerprint,
    evaluate_contact,
)
from app.mana_operation_ai.application.retention.contact_templates import (
    contact_dispatch_fingerprint,
    contact_message,
)
from app.mana_operation_ai.domain.retention_contact import (
    RetentionContactDelivery,
    RetentionContactMessage,
    RetentionContactParameters,
    RetentionContactTarget,
)


class FakeRetentionContactExecutor:
    provider_name = "fake_retention_contact"

    def __init__(self, *, clock: Clock, target: RetentionContactTarget) -> None:
        self._clock = clock
        self._target = RetentionContactTarget.model_validate(target.model_dump(mode="json"))
        self._receipts = {item.action_id: item for item in self._target.deliveries}
        self._lock = asyncio.Lock()
        self.dispatch_count = 0
        self.accepted_messages: list[str] = []
        self.target_reads = 0
        self.receipt_reads = 0
        self.lose_ack = False
        self.receipt_unavailable = False

    def replace_target(self, target: RetentionContactTarget) -> None:
        self._target = RetentionContactTarget.model_validate(target.model_dump(mode="json"))

    async def target(self, account_ref: str) -> RetentionContactTarget:
        self.target_reads += 1
        if account_ref != self._target.facts.account_ref:
            raise ProviderPermanentError("The fictional recipient is not configured")
        return self._target.model_copy(deep=True)

    async def send(
        self,
        *,
        action_id: str,
        parameters: RetentionContactParameters,
        message: RetentionContactMessage,
        expected_target_sha256: str,
        valid_until: datetime,
    ) -> RetentionContactDelivery:
        async with self._lock:
            previous = self._receipts.get(action_id)
            if previous is not None:
                if previous.parameters_sha256 != contact_dispatch_fingerprint(parameters, message):
                    raise ProviderPermanentError("The idempotent request changed")
                return previous.model_copy(deep=True)
            if (
                self._clock.now() >= valid_until
                or message != contact_message(parameters)
                or contact_fingerprint(self._target) != expected_target_sha256
                or not evaluate_contact(
                    parameters,
                    self._target,
                    now=self._clock.now(),
                ).eligible_for_review
            ):
                raise ProviderPermanentError("The fictional target is no longer eligible")
            receipt = RetentionContactDelivery(
                action_id=action_id,
                parameters_sha256=contact_dispatch_fingerprint(parameters, message),
                accepted_at=self._clock.now(),
                provider_receipt_id=f"fake-contact-{uuid4().hex}",
            )
            self._target = RetentionContactTarget.model_validate(
                {
                    **self._target.model_dump(mode="json"),
                    "observed_at": self._clock.now(),
                    "deliveries": [
                        *[item.model_dump(mode="json") for item in self._target.deliveries],
                        receipt.model_dump(mode="json"),
                    ],
                }
            )
            self._receipts[action_id] = receipt
            self.accepted_messages.append(message.text)
            self.dispatch_count += 1
            if self.lose_ack:
                raise ProviderWriteUncertainError("The sandbox acceptance response was lost")
            return receipt.model_copy(deep=True)

    async def receipt(self, action_id: str) -> RetentionContactDelivery | None:
        self.receipt_reads += 1
        if self.receipt_unavailable:
            raise ProviderPermanentError("The sandbox receipt is unavailable")
        value = self._receipts.get(action_id)
        return value.model_copy(deep=True) if value is not None else None
