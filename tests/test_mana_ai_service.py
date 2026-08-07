from datetime import datetime

import pytest

from app.mana_ai.application.deterministic import required_checks
from app.mana_ai.application.policy import build_action_proposals
from app.mana_ai.application.ports import ModelGatewayError
from app.mana_ai.application.service import ManaAIAnalysisService
from app.mana_ai.domain.enums import (
    ActionKind,
    AnalysisStatus,
    AnalysisVerdict,
    CheckStatus,
    ExecutionPolicy,
    FindingCategory,
    ManaAICapability,
    RiskLevel,
)
from app.mana_ai.domain.requests import ManaAIRequest
from app.mana_ai.domain.responses import (
    Action,
    ActionValue,
    AIGamingSafetyDetails,
    CheckResult,
    FindingDraft,
    GeofenceAction,
    LimitChangeAction,
    ModelAnalysis,
    NotifyParentAction,
    SmartContentFilterDetails,
)
from tests.mana_ai_fixtures import NOW, details_for, request_for


class FixedClock:
    def now(self) -> datetime:
        return NOW


class FakeGateway:
    def __init__(self, response: ModelAnalysis | None = None, *, fails: bool = False) -> None:
        self.response = response
        self.fails = fails

    @property
    def model_name(self) -> str:
        return "fake-model"

    async def analyze(
        self,
        request: ManaAIRequest,
        *,
        deterministic_findings: list[FindingDraft],
        required_checks: list[CheckResult],
    ) -> ModelAnalysis:
        capability = request.input.capability
        del deterministic_findings, required_checks
        if self.fails:
            raise ModelGatewayError("provider unavailable")
        return self.response or ModelAnalysis(
            verdict=AnalysisVerdict.NO_RISK_DETECTED,
            summary="No risk was detected in the available signals.",
            details=details_for(capability),
        )


@pytest.mark.parametrize("capability", list(ManaAICapability))
async def test_every_capability_runs_through_the_analysis_service(
    capability: ManaAICapability,
) -> None:
    service = ManaAIAnalysisService(gateway=FakeGateway(), clock=FixedClock())

    response = await service.analyze(request_for(capability))

    assert response.capability is capability
    assert isinstance(response.details, type(details_for(capability)))
    assert response.read_only is True
    assert all(proposal.executed is False for proposal in response.proposed_actions)


async def test_known_malicious_resource_returns_read_only_block_proposal() -> None:
    request = request_for(ManaAICapability.SMART_CONTENT_FILTER)
    raw = request.model_dump(mode="json")
    raw["input"]["resource"]["reputation"] = "malicious"
    request = type(request).model_validate(raw)
    service = ManaAIAnalysisService(gateway=FakeGateway(), clock=FixedClock())

    response = await service.analyze(request)

    assert response.verdict is AnalysisVerdict.BLOCK
    assert response.status is AnalysisStatus.DEGRADED
    assert "риск не обнаружен" not in response.summary.lower()
    assert isinstance(response.details, SmartContentFilterDetails)
    assert response.details.decision == "block"
    assert response.details.reputation.value == "malicious"
    assert response.read_only is True
    assert response.privacy.application_data_mutated is False
    assert any(item.category is FindingCategory.UNSAFE_LINK_OR_SITE for item in response.findings)
    proposal = next(
        item
        for item in response.proposed_actions
        if item.action.kind is ActionKind.PROPOSE_RESOURCE_BLOCK
    )
    assert proposal.execution_policy is ExecutionPolicy.APPLICATION_POLICY_REQUIRED
    assert proposal.proposal_only is True
    assert proposal.executed is False


async def test_unknown_evidence_and_disallowed_action_are_removed() -> None:
    semantic = ModelAnalysis(
        verdict=AnalysisVerdict.ALERT,
        summary="Untrusted model result",
        details=details_for(ManaAICapability.SCAM_PRIVACY_SHIELD),
        findings=[
            FindingDraft(
                category=FindingCategory.THREAT,
                risk_level=RiskLevel.HIGH,
                confidence=90,
                title="Unsupported",
                summary="References evidence that does not exist.",
                evidence_ids=["hallucinated-evidence"],
                recommendation="Review.",
            )
        ],
        proposed_actions=[
            GeofenceAction(
                kind=ActionKind.PROPOSE_GEOFENCE,
                label="Unsupported",
                center_evidence_id="notification-1",
                radius_meters=100,
                rationale="Not allowed for this capability.",
            )
        ],
    )
    service = ManaAIAnalysisService(gateway=FakeGateway(semantic), clock=FixedClock())

    response = await service.analyze(request_for(ManaAICapability.SCAM_PRIVACY_SHIELD))

    assert response.status is AnalysisStatus.DEGRADED
    assert response.findings == []
    assert response.proposed_actions == []
    assert any("unknown evidence" in note for note in response.data_quality_notes)
    assert any("Unsupported action" in note for note in response.data_quality_notes)


async def test_action_for_unknown_application_is_removed() -> None:
    semantic = ModelAnalysis(
        verdict=AnalysisVerdict.WARN,
        summary="Review the supplied usage pattern.",
        details=details_for(ManaAICapability.ADAPTIVE_SCREEN_TIME),
        proposed_actions=[
            LimitChangeAction(
                kind=ActionKind.PROPOSE_LIMIT_CHANGE,
                target_kind="application",
                target="hallucinated.package",
                proposed_daily_limit_minutes=15,
                rationale="Limit an application that was not supplied.",
            )
        ],
    )
    service = ManaAIAnalysisService(gateway=FakeGateway(semantic), clock=FixedClock())

    response = await service.analyze(request_for(ManaAICapability.ADAPTIVE_SCREEN_TIME))

    assert response.status is AnalysisStatus.DEGRADED
    assert response.proposed_actions == []
    assert any("unknown target" in note for note in response.data_quality_notes)


async def test_model_failure_never_becomes_a_false_all_clear() -> None:
    service = ManaAIAnalysisService(gateway=FakeGateway(fails=True), clock=FixedClock())

    response = await service.analyze(request_for(ManaAICapability.SAFETY_MONITOR))

    assert response.status is AnalysisStatus.DEGRADED
    assert response.verdict is AnalysisVerdict.INSUFFICIENT_DATA
    assert any(check.status is CheckStatus.INSUFFICIENT_DATA for check in response.checks)
    assert "недоступен" in response.summary


async def test_missing_signal_type_cannot_be_reported_as_all_clear() -> None:
    request = request_for(ManaAICapability.SAFETY_MONITOR)
    checks = [
        check.model_copy(
            update={
                "status": CheckStatus.NO_RISK_DETECTED,
                "explanation": "No risk detected.",
            }
        )
        for check in required_checks(request.input)
    ]
    semantic = ModelAnalysis(
        verdict=AnalysisVerdict.NO_RISK_DETECTED,
        summary="No risk was detected.",
        details=details_for(ManaAICapability.SAFETY_MONITOR),
        checks=checks,
    )
    service = ManaAIAnalysisService(gateway=FakeGateway(semantic), clock=FixedClock())

    response = await service.analyze(request)

    phishing = next(
        check for check in response.checks if check.category is FindingCategory.PHISHING
    )
    assert phishing.status is CheckStatus.INSUFFICIENT_DATA
    assert response.verdict is AnalysisVerdict.INSUFFICIENT_DATA


async def test_parent_confirmation_policy_is_computed_outside_the_model() -> None:
    action: Action = LimitChangeAction(
        kind=ActionKind.PROPOSE_LIMIT_CHANGE,
        target_kind="application",
        target="org.example.learning",
        proposed_daily_limit_minutes=60,
        rationale="Review the current limit with the family.",
    )
    semantic = ModelAnalysis(
        verdict=AnalysisVerdict.WARN,
        summary="Review the supplied usage pattern.",
        details=details_for(ManaAICapability.ADAPTIVE_SCREEN_TIME),
        proposed_actions=[action],
    )
    service = ManaAIAnalysisService(gateway=FakeGateway(semantic), clock=FixedClock())

    response = await service.analyze(request_for(ManaAICapability.ADAPTIVE_SCREEN_TIME))

    assert response.proposed_actions[0].requires_parent_confirmation is True
    assert response.proposed_actions[0].execution_policy is (
        ExecutionPolicy.PARENT_CONFIRMATION_REQUIRED
    )


def test_proposal_ids_are_stable_when_action_order_changes() -> None:
    actions: list[ActionValue] = [
        LimitChangeAction(
            kind=ActionKind.PROPOSE_LIMIT_CHANGE,
            target_kind="application",
            target="org.example.learning",
            proposed_daily_limit_minutes=60,
            rationale="Review the current limit with the family.",
        ),
        NotifyParentAction(
            kind=ActionKind.NOTIFY_PARENT,
            urgency=RiskLevel.MEDIUM,
            message="Review the supplied signal.",
            evidence_ids=["usage-1"],
        ),
    ]

    first = build_action_proposals("request-stable", actions)
    second = build_action_proposals("request-stable", list(reversed(actions)))

    first_ids = {item.action.model_dump_json(): item.proposal_id for item in first}
    second_ids = {item.action.model_dump_json(): item.proposal_id for item in second}
    assert first_ids == second_ids


async def test_model_cannot_return_hallucinated_affected_packages() -> None:
    details = details_for(ManaAICapability.AI_GAMING_SAFETY)
    assert isinstance(details, AIGamingSafetyDetails)
    semantic = ModelAnalysis(
        verdict=AnalysisVerdict.NO_RISK_DETECTED,
        summary="No risk was detected in the available signals.",
        details=details.model_copy(
            update={"affected_packages": ["org.example.learning", "hallucinated.package"]}
        ),
    )
    service = ManaAIAnalysisService(gateway=FakeGateway(semantic), clock=FixedClock())

    response = await service.analyze(request_for(ManaAICapability.AI_GAMING_SAFETY))

    assert isinstance(response.details, AIGamingSafetyDetails)
    assert response.details.affected_packages == ["org.example.learning"]


async def test_wrong_capability_details_are_replaced_with_the_endpoint_details_type() -> None:
    semantic = ModelAnalysis(
        verdict=AnalysisVerdict.NO_RISK_DETECTED,
        summary="No risk was detected in the available signals.",
        details=details_for(ManaAICapability.PARENT_COPILOT),
    )
    service = ManaAIAnalysisService(gateway=FakeGateway(semantic), clock=FixedClock())

    response = await service.analyze(request_for(ManaAICapability.LOCATION_INTELLIGENCE))

    assert response.status is AnalysisStatus.DEGRADED
    assert response.capability is ManaAICapability.LOCATION_INTELLIGENCE
    assert type(response.details) is type(details_for(ManaAICapability.LOCATION_INTELLIGENCE))
    assert any("did not match" in note for note in response.data_quality_notes)
