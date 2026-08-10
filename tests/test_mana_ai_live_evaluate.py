import json
from datetime import UTC, datetime

from app.core.config import Settings
from app.mana_ai.application.deterministic import analyze_deterministically, required_checks
from app.mana_ai.domain.enums import ManaAICapability
from app.services.mana_ai_openai_gateway import build_safety_identifier
from app.services.mana_ai_prompts import build_system_instructions
from app.services.mana_ai_provider_payload import build_provider_payload
from app.services.openai_service import ModelAccessMetadata
from scripts.mana_ai_live_evaluate import (
    EvaluationResult,
    ModelAccessResult,
    build_all_evaluation_requests,
    render_report,
)


def test_live_evaluation_builds_all_capability_requests_without_private_provider_fields() -> None:
    requests = build_all_evaluation_requests()

    assert {request.input.capability for request in requests} == set(ManaAICapability)
    for request in requests:
        deterministic = analyze_deterministically(
            request.input,
            evaluated_at=request.occurred_at,
        )
        payload = build_provider_payload(
            request,
            deterministic_findings=deterministic.findings,
            required_checks=required_checks(request.input),
        )
        serialized = json.dumps(payload, ensure_ascii=False)

        assert request.subject.subject_id not in serialized
        assert "latitude" not in serialized
        assert "longitude" not in serialized
        assert "synthetic-secret" not in serialized
        assert "#fragment" not in serialized


def test_live_evaluation_report_omits_openai_key_and_keeps_manual_review_fields() -> None:
    settings = Settings(_env_file=None, openai_api_key="sk-test-secret-value-123456789")
    request = build_all_evaluation_requests()[0]
    deterministic = analyze_deterministically(
        request.input,
        evaluated_at=request.occurred_at,
    )
    payload = build_provider_payload(
        request,
        deterministic_findings=deterministic.findings,
        required_checks=required_checks(request.input),
    )
    result = EvaluationResult(
        capability=request.input.capability,
        endpoint="/api/v1/mana-ai/safety-monitor",
        api_request=request.model_dump(mode="json"),
        system_instructions=build_system_instructions(request.input.capability),
        provider_payload=payload,
        safety_identifier=build_safety_identifier(request.subject.subject_id),
        provider_sent=False,
        latency_ms=None,
        raw_output=None,
        final_response=None,
        response_metadata=None,
        provider_failure=None,
        skip_reason="Synthetic unit-test skip.",
        checks=(),
    )
    report = render_report(
        run_id="test-run",
        generated_at=datetime(2026, 8, 10, tzinfo=UTC),
        settings=settings,
        model_access=ModelAccessResult(
            sent=True,
            latency_ms=12.5,
            metadata=ModelAccessMetadata(
                model_id="gpt-5.4-nano",
                owned_by="system",
                created_at=1_786_334_400,
            ),
        ),
        results=[result],
    )

    assert "sk-test-secret-value-123456789" not in report
    assert "API request" in report
    assert "OpenAI user payload after minimization" in report
    assert "Оценка качества: `__/5`" in report
