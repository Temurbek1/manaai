"""Two explicitly fictional adult fixtures, with no application data or transport client."""

import hashlib
from datetime import datetime, timedelta

from app.mana_operation_ai.application.ports import Clock, ProviderPermanentError
from app.mana_operation_ai.domain.retention_contact import (
    RetentionContactDelivery,
    RetentionContactMessage,
    RetentionContactParameters,
    RetentionContactTarget,
)
from app.mana_operation_ai.domain.retention_risk import (
    ActivityRiskEvidence,
    CustomerRetentionFacts,
    FeedbackRiskEvidence,
    SubscriptionRiskEvidence,
)
from app.mana_operation_ai.domain.workspace_retention_contacts import (
    SandboxRecipient,
    WorkspaceContactRecipient,
)
from app.mana_operation_ai.infrastructure.retention.contact_fake import FakeRetentionContactExecutor


def sandbox_account_ref(recipient: SandboxRecipient) -> str:
    # No real account identifier is hashed; these are public fictional fixture names.
    return "acct_" + hashlib.sha256(f"retention-contact:fictional:{recipient}".encode()).hexdigest()


class FakeRetentionContactCatalog:
    provider_name = "fake_retention_contact"
    recipients = (
        WorkspaceContactRecipient(key="sample_ru", language="ru"),
        WorkspaceContactRecipient(key="sample_uz", language="uz"),
    )

    def __init__(self, clock: Clock) -> None:
        now = clock.now()
        self.executors: dict[str, FakeRetentionContactExecutor] = {}
        for recipient in self.recipients:
            account = sandbox_account_ref(recipient.key)
            facts = CustomerRetentionFacts(
                account_ref=account,
                collected_at=now,
                mode="sandbox",
                subscription=SubscriptionRiskEvidence(
                    source="sandbox",
                    evidence_ref="fictional-billing",
                    observed_at=now,
                    status="active",
                    paid_until=now + timedelta(hours=20),
                    auto_renew=False,
                ),
                activity=ActivityRiskEvidence(
                    source="sandbox",
                    evidence_ref="fictional-parent-activity",
                    observed_at=now,
                    window_start=now - timedelta(days=7),
                    window_end=now,
                    coverage="complete",
                    last_open_at=now - timedelta(days=6),
                    active_days=1,
                    distinct_features=2,
                    push_opens=0,
                    cancellation_page_views=0,
                    uninstall_signal=False,
                ),
                feedback=FeedbackRiskEvidence(
                    source="sandbox",
                    evidence_ref="fictional-feedback",
                    observed_at=now,
                    rating_known=True,
                    rating=4,
                    open_complaints=0,
                ),
            )
            target = RetentionContactTarget(
                facts=facts,
                observed_at=now,
                consent=True,
                consent_channel="push",
                consent_purpose="retention_support",
                consent_evidence_ref="fictional-consent",
                preferred_language=recipient.language,
                consent_observed_at=now,
                consent_expires_at=now + timedelta(hours=6),
                suppressed=False,
                timezone="UTC",
                contact_history_complete=True,
            )
            self.executors[account] = FakeRetentionContactExecutor(clock=clock, target=target)

    def _executor(self, account_ref: str) -> FakeRetentionContactExecutor:
        executor = self.executors.get(account_ref)
        if executor is None:
            raise ProviderPermanentError("Only the explicitly fictional recipients exist")
        return executor

    async def target(self, account_ref: str) -> RetentionContactTarget:
        return await self._executor(account_ref).target(account_ref)

    async def send(
        self,
        *,
        action_id: str,
        parameters: RetentionContactParameters,
        message: RetentionContactMessage,
        expected_target_sha256: str,
        valid_until: datetime,
    ) -> RetentionContactDelivery:
        return await self._executor(parameters.account_ref).send(
            action_id=action_id,
            parameters=parameters,
            message=message,
            expected_target_sha256=expected_target_sha256,
            valid_until=valid_until,
        )

    async def receipt(self, action_id: str) -> RetentionContactDelivery | None:
        matches = [
            receipt
            for executor in self.executors.values()
            if (receipt := await executor.receipt(action_id)) is not None
        ]
        if len(matches) > 1:
            raise ProviderPermanentError("A fictional action receipt is ambiguous")
        return matches[0] if matches else None
