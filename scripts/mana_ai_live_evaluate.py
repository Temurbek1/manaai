from __future__ import annotations

import asyncio
import json
import os
import re
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any, cast

from openai import APIStatusError

from app.api.mana_ai_examples import request_examples
from app.api.routes.mana_ai import public_capability_path
from app.core.config import Settings
from app.mana_ai.application.details import details_match_input
from app.mana_ai.application.deterministic import analyze_deterministically, required_checks
from app.mana_ai.application.evidence import collect_evidence_ids
from app.mana_ai.application.service import ManaAIAnalysisService
from app.mana_ai.domain.enums import ManaAICapability
from app.mana_ai.domain.requests import (
    AdaptiveScreenTimeRequest,
    AIGamingSafetyRequest,
    BehaviourAnomalyRequest,
    ChildSafetyAssistantRequest,
    FamilyAgreementRequest,
    FamilyDigestRequest,
    LocationIntelligenceRequest,
    ManaAIRequest,
    ManaAIRequestBase,
    ParentCopilotRequest,
    SafetyMonitorRequest,
    ScamPrivacyShieldRequest,
    SmartContentFilterRequest,
)
from app.mana_ai.domain.responses import (
    AdaptiveScreenTimeResponse,
    AIGamingSafetyResponse,
    BehaviourAnomalyResponse,
    CheckResult,
    ChildSafetyAssistantResponse,
    FamilyAgreementResponse,
    FamilyDigestResponse,
    FindingDraft,
    LocationIntelligenceResponse,
    ManaAIResponse,
    ManaAIResponseBase,
    ModelAnalysis,
    ParentCopilotResponse,
    SafetyMonitorResponse,
    ScamPrivacyShieldResponse,
    SmartContentFilterResponse,
)
from app.services.mana_ai_openai_gateway import build_safety_identifier
from app.services.mana_ai_prompts import build_system_instructions
from app.services.mana_ai_provider_payload import build_provider_payload
from app.services.openai_service import (
    AIProviderError,
    ModelAccessMetadata,
    OpenAIService,
    StructuredResponseMetadata,
)

DEFAULT_REPORT_PATH = Path("docs/artifacts/mana-ai-live-evaluation.md")
LIVE_EVAL_ENV = "MANA_AI_LIVE_EVAL"
REPORT_PATH_ENV = "MANA_AI_LIVE_EVAL_REPORT_PATH"
SECRET_PATTERN = re.compile(r"sk-[A-Za-z0-9_-]{12,}")
CYRILLIC_PATTERN = re.compile(r"[А-Яа-яЁё]")

REQUEST_TYPE_BY_CAPABILITY: dict[
    ManaAICapability,
    type[ManaAIRequestBase[Any]],
] = {
    ManaAICapability.SAFETY_MONITOR: SafetyMonitorRequest,
    ManaAICapability.FAMILY_DIGEST: FamilyDigestRequest,
    ManaAICapability.ADAPTIVE_SCREEN_TIME: AdaptiveScreenTimeRequest,
    ManaAICapability.LOCATION_INTELLIGENCE: LocationIntelligenceRequest,
    ManaAICapability.SMART_CONTENT_FILTER: SmartContentFilterRequest,
    ManaAICapability.SCAM_PRIVACY_SHIELD: ScamPrivacyShieldRequest,
    ManaAICapability.AI_GAMING_SAFETY: AIGamingSafetyRequest,
    ManaAICapability.PARENT_COPILOT: ParentCopilotRequest,
    ManaAICapability.CHILD_SAFETY_ASSISTANT: ChildSafetyAssistantRequest,
    ManaAICapability.FAMILY_AGREEMENT: FamilyAgreementRequest,
    ManaAICapability.BEHAVIOUR_ANOMALY: BehaviourAnomalyRequest,
}

RESPONSE_TYPE_BY_CAPABILITY: dict[ManaAICapability, type[ManaAIResponseBase]] = {
    ManaAICapability.SAFETY_MONITOR: SafetyMonitorResponse,
    ManaAICapability.FAMILY_DIGEST: FamilyDigestResponse,
    ManaAICapability.ADAPTIVE_SCREEN_TIME: AdaptiveScreenTimeResponse,
    ManaAICapability.LOCATION_INTELLIGENCE: LocationIntelligenceResponse,
    ManaAICapability.SMART_CONTENT_FILTER: SmartContentFilterResponse,
    ManaAICapability.SCAM_PRIVACY_SHIELD: ScamPrivacyShieldResponse,
    ManaAICapability.AI_GAMING_SAFETY: AIGamingSafetyResponse,
    ManaAICapability.PARENT_COPILOT: ParentCopilotResponse,
    ManaAICapability.CHILD_SAFETY_ASSISTANT: ChildSafetyAssistantResponse,
    ManaAICapability.FAMILY_AGREEMENT: FamilyAgreementResponse,
    ManaAICapability.BEHAVIOUR_ANOMALY: BehaviourAnomalyResponse,
}


@dataclass(frozen=True, slots=True)
class QualityCheck:
    name: str
    passed: bool
    details: str


@dataclass(frozen=True, slots=True)
class ProviderFailure:
    status_code: int | None
    request_id: str | None
    error_type: str
    code: str | None
    message: str
    response_body: Any

    @property
    def is_credit_exhausted(self) -> bool:
        return self.code == "credit_balance_exhausted" or self.error_type == "insufficient_quota"


@dataclass(frozen=True, slots=True)
class ModelAccessResult:
    sent: bool
    latency_ms: float
    metadata: ModelAccessMetadata | None = None
    failure: ProviderFailure | None = None


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    capability: ManaAICapability
    endpoint: str
    api_request: dict[str, Any]
    system_instructions: str
    provider_payload: dict[str, Any]
    safety_identifier: str
    provider_sent: bool
    latency_ms: float | None
    raw_output: dict[str, Any] | None
    final_response: dict[str, Any] | None
    response_metadata: StructuredResponseMetadata | None
    provider_failure: ProviderFailure | None
    skip_reason: str | None
    checks: tuple[QualityCheck, ...]

    @property
    def completed(self) -> bool:
        return self.final_response is not None and self.provider_failure is None


@dataclass(frozen=True, slots=True)
class FixedClock:
    value: datetime

    def now(self) -> datetime:
        return self.value


@dataclass(frozen=True, slots=True)
class ReplayGateway:
    model_name: str
    output: ModelAnalysis

    async def analyze(
        self,
        request: ManaAIRequest,
        *,
        deterministic_findings: list[FindingDraft],
        required_checks: list[CheckResult],
    ) -> ModelAnalysis:
        return self.output


def build_evaluation_request(capability: ManaAICapability) -> ManaAIRequest:
    data = deepcopy(request_examples(capability)["default"]["value"])
    data["request_id"] = f"live-eval-{capability.value}-v1"
    input_data = cast(dict[str, Any], data["input"])

    if capability is ManaAICapability.SAFETY_MONITOR:
        notification = cast(dict[str, Any], input_data["notifications"][0])
        resource = cast(dict[str, Any], input_data["resources"][0])
        notification.update(
            excerpt="Срочно отправь пароль и номер банковской карты, иначе аккаунт заблокируют.",
            sender_is_known=False,
            link_evidence_ids=[resource["evidence_id"]],
        )
        _make_resource_malicious(resource)
    elif capability is ManaAICapability.FAMILY_DIGEST:
        _make_usage_excessive(cast(dict[str, Any], input_data["app_usage"][0]))
    elif capability is ManaAICapability.ADAPTIVE_SCREEN_TIME:
        usage = cast(dict[str, Any], input_data["app_usage"][0])
        _make_usage_excessive(usage)
        input_data["limits"] = [
            {"package_name": usage["package_name"], "daily_limit_seconds": 3_600}
        ]
    elif capability is ManaAICapability.LOCATION_INTELLIGENCE:
        route = cast(dict[str, Any], input_data["route"])
        route.update(stopped_duration_seconds=5_400, long_stop_threshold_seconds=3_600)
    elif capability is ManaAICapability.SMART_CONTENT_FILTER:
        resource = cast(dict[str, Any], input_data["resource"])
        _make_resource_malicious(resource)
        input_data["blocked_categories"] = ["phishing"]
    elif capability is ManaAICapability.SCAM_PRIVACY_SHIELD:
        notification = cast(dict[str, Any], input_data["notifications"][0])
        resource = _malicious_resource()
        notification.update(
            excerpt="Вы выиграли приз. Для получения отправьте пароль и данные банковской карты.",
            sender_is_known=False,
            link_evidence_ids=[resource["evidence_id"]],
        )
        input_data["resources"] = [resource]
    elif capability is ManaAICapability.AI_GAMING_SAFETY:
        usage = cast(dict[str, Any], input_data["app_usage"][0])
        _make_usage_excessive(usage)
        input_data["limits"] = [
            {"package_name": usage["package_name"], "daily_limit_seconds": 3_600}
        ]
    elif capability is ManaAICapability.PARENT_COPILOT:
        input_data["message"] = (
            "Объясни, почему игровое время выросло ночью, и предложи безопасный следующий шаг."
        )
        usage = _excessive_usage()
        input_data["app_usage"] = [usage]
        input_data["allowed_action_kinds"] = ["propose_limit_change", "generate_family_report"]
    elif capability is ManaAICapability.CHILD_SAFETY_ASSISTANT:
        input_data["message"] = "Почему эта ссылка заблокирована и что мне делать?"
        input_data["current_resource"] = _malicious_resource()
    elif capability is ManaAICapability.FAMILY_AGREEMENT:
        input_data["preferences"] = {
            "goals": ["Не играть во время сна", "Обсуждать изменения правил вместе"],
            "night_window": {"starts_at": "22:00:00", "ends_at": "07:00:00"},
            "parent_visible_data": ["daily_totals", "safety_events"],
            "control_relaxation_notes": "Ослаблять ограничения постепенно с возрастом.",
        }

    request_type = REQUEST_TYPE_BY_CAPABILITY[capability]
    return cast(ManaAIRequest, request_type.model_validate(data))


def build_all_evaluation_requests() -> list[ManaAIRequest]:
    return [build_evaluation_request(capability) for capability in ManaAICapability]


async def run_evaluation(settings: Settings) -> tuple[ModelAccessResult, list[EvaluationResult]]:
    service = OpenAIService(settings)
    model_access = await _check_model_access(service)
    results: list[EvaluationResult] = []
    billing_blocked = False

    for request in build_all_evaluation_requests():
        result = await _evaluate_case(
            service,
            settings,
            request,
            skip_for_billing=billing_blocked,
        )
        results.append(result)
        if result.provider_failure is not None and result.provider_failure.is_credit_exhausted:
            billing_blocked = True
    return model_access, results


async def _check_model_access(service: OpenAIService) -> ModelAccessResult:
    started = perf_counter()
    try:
        metadata = await service.retrieve_configured_model()
    except AIProviderError as exc:
        return ModelAccessResult(
            sent=True,
            latency_ms=_elapsed_ms(started),
            failure=_extract_provider_failure(exc),
        )
    return ModelAccessResult(
        sent=True,
        latency_ms=_elapsed_ms(started),
        metadata=metadata,
    )


async def _evaluate_case(
    service: OpenAIService,
    settings: Settings,
    request: ManaAIRequest,
    *,
    skip_for_billing: bool,
) -> EvaluationResult:
    capability = request.input.capability
    deterministic = analyze_deterministically(
        request.input,
        evaluated_at=request.occurred_at,
    )
    checks = required_checks(request.input)
    provider_payload = build_provider_payload(
        request,
        deterministic_findings=deterministic.findings,
        required_checks=checks,
    )
    system_instructions = build_system_instructions(capability)
    safety_identifier = build_safety_identifier(request.subject.subject_id)
    preflight_checks = _preflight_checks(request, provider_payload)

    if skip_for_billing:
        return EvaluationResult(
            capability=capability,
            endpoint=public_capability_path(capability),
            api_request=request.model_dump(mode="json"),
            system_instructions=system_instructions,
            provider_payload=provider_payload,
            safety_identifier=safety_identifier,
            provider_sent=False,
            latency_ms=None,
            raw_output=None,
            final_response=None,
            response_metadata=None,
            provider_failure=None,
            skip_reason=(
                "Not sent after credit_balance_exhausted was confirmed; redundant paid-provider "
                "requests were stopped."
            ),
            checks=tuple(preflight_checks),
        )

    started = perf_counter()
    try:
        provider_result = await service.create_structured_response_with_metadata(
            text_format=ModelAnalysis,
            system_prompt=system_instructions,
            user_input=json.dumps(provider_payload, ensure_ascii=False, separators=(",", ":")),
            safety_identifier=safety_identifier,
        )
    except AIProviderError as exc:
        return EvaluationResult(
            capability=capability,
            endpoint=public_capability_path(capability),
            api_request=request.model_dump(mode="json"),
            system_instructions=system_instructions,
            provider_payload=provider_payload,
            safety_identifier=safety_identifier,
            provider_sent=True,
            latency_ms=_elapsed_ms(started),
            raw_output=None,
            final_response=None,
            response_metadata=None,
            provider_failure=_extract_provider_failure(exc),
            skip_reason=None,
            checks=tuple(preflight_checks),
        )

    raw_output = provider_result.output
    gateway = ReplayGateway(model_name=provider_result.metadata.model, output=raw_output)
    analysis_service = ManaAIAnalysisService(
        gateway=gateway,
        clock=FixedClock(datetime.now(UTC)),
    )
    analysis = await analysis_service.analyze(request)
    response_type = RESPONSE_TYPE_BY_CAPABILITY[capability]
    final_response_model = cast(
        ManaAIResponse,
        response_type.model_validate(analysis.model_dump()),
    )
    final_response = final_response_model.model_dump(mode="json")
    completed_checks = [
        *preflight_checks,
        *_output_checks(
            request,
            deterministic.findings,
            raw_output,
            final_response_model,
        ),
    ]
    return EvaluationResult(
        capability=capability,
        endpoint=public_capability_path(capability),
        api_request=request.model_dump(mode="json"),
        system_instructions=system_instructions,
        provider_payload=provider_payload,
        safety_identifier=safety_identifier,
        provider_sent=True,
        latency_ms=_elapsed_ms(started),
        raw_output=raw_output.model_dump(mode="json"),
        final_response=final_response,
        response_metadata=provider_result.metadata,
        provider_failure=None,
        skip_reason=None,
        checks=tuple(completed_checks),
    )


def _preflight_checks(
    request: ManaAIRequest,
    provider_payload: dict[str, Any],
) -> list[QualityCheck]:
    serialized = json.dumps(provider_payload, ensure_ascii=False)
    subject_omitted = request.subject.subject_id not in serialized
    coordinates_omitted = "latitude" not in serialized and "longitude" not in serialized
    url_secrets_omitted = "synthetic-secret" not in serialized and "#fragment" not in serialized
    return [
        QualityCheck(
            "API request schema", True, "The capability-specific Pydantic model validated."
        ),
        QualityCheck(
            "Opaque subject ID omitted from provider payload",
            subject_omitted,
            "The stable subject ID is replaced by a one-way safety identifier.",
        ),
        QualityCheck(
            "Exact coordinates omitted from provider payload",
            coordinates_omitted,
            "latitude and longitude fields must not cross the provider boundary.",
        ),
        QualityCheck(
            "URL query and fragment omitted from provider payload",
            url_secrets_omitted,
            "Synthetic query and fragment markers must be removed before provider dispatch.",
        ),
    ]


def _output_checks(
    request: ManaAIRequest,
    deterministic_findings: list[FindingDraft],
    raw_output: ModelAnalysis,
    final_response: ManaAIResponse,
) -> list[QualityCheck]:
    final_json = json.dumps(final_response.model_dump(mode="json"), ensure_ascii=False)
    raw_evidence_ids = {
        evidence_id for finding in raw_output.findings for evidence_id in finding.evidence_ids
    }
    valid_evidence_ids = collect_evidence_ids(request.input)
    deterministic_keys = {
        (finding.category, tuple(sorted(finding.evidence_ids)))
        for finding in deterministic_findings
    }
    final_keys = {
        (finding.category, tuple(sorted(finding.evidence_ids)))
        for finding in final_response.findings
    }
    full_previews = _notification_previews(request)
    return [
        QualityCheck(
            "Raw Structured Output schema",
            True,
            "OpenAI SDK parsed the response as ModelAnalysis.",
        ),
        QualityCheck(
            "Capability-specific raw details",
            details_match_input(request.input, raw_output.details),
            "The raw details type must match the requested capability.",
        ),
        QualityCheck(
            "Raw finding evidence references",
            raw_evidence_ids.issubset(valid_evidence_ids),
            "Every model finding must reference an evidence_id from the request.",
        ),
        QualityCheck(
            "Endpoint response schema",
            True,
            "The guardrailed result validated against the endpoint-specific response model.",
        ),
        QualityCheck(
            "Requested locale",
            bool(CYRILLIC_PATTERN.search(final_response.summary)),
            "The Russian evaluation expects Cyrillic in the final summary.",
        ),
        QualityCheck(
            "Correct capability",
            final_response.capability is request.input.capability,
            "The response capability must equal the endpoint capability.",
        ),
        QualityCheck(
            "Read-only contract",
            final_response.read_only
            and not final_response.privacy.application_data_mutated
            and not final_response.privacy.raw_input_returned
            and final_response.privacy.provider_store_disabled,
            "No application mutation or raw-input return is allowed; provider store is disabled.",
        ),
        QualityCheck(
            "No action execution",
            all(not proposal.executed for proposal in final_response.proposed_actions),
            "Every action is a non-executed proposal.",
        ),
        QualityCheck(
            "Deterministic findings preserved",
            deterministic_keys.issubset(final_keys),
            "Trusted deterministic findings must survive semantic reconciliation.",
        ),
        QualityCheck(
            "Full notification previews not echoed",
            all(preview not in final_json for preview in full_previews),
            "The final response must not reproduce a complete private notification preview.",
        ),
    ]


def render_report(
    *,
    run_id: str,
    generated_at: datetime,
    settings: Settings,
    model_access: ModelAccessResult,
    results: list[EvaluationResult],
) -> str:
    completed = sum(result.completed for result in results)
    sent = sum(result.provider_sent for result in results)
    skipped = sum(not result.provider_sent for result in results)
    failed_checks = sum(
        not check.passed for result in results if result.completed for check in result.checks
    )
    billing_blocked = any(
        result.provider_failure is not None and result.provider_failure.is_credit_exhausted
        for result in results
    )
    status = (
        "BLOCKED_BY_BILLING"
        if billing_blocked
        else "PASS"
        if completed == len(results) and failed_checks == 0
        else "FAIL"
    )
    sections = [
        f"## Run `{run_id}`",
        "",
        f"- Generated at (UTC): `{generated_at.isoformat()}`",
        f"- Overall status: **{status}**",
        "- Data source: synthetic fixtures only; no Firebase or application database was read.",
        "- Database mutations: **0**.",
        "- Latency includes OpenAI SDK retries, if any.",
        "- Secrets and HTTP headers are intentionally excluded.",
        "",
        "### Runtime configuration",
        "",
        "| Setting | Value |",
        "| --- | --- |",
        f"| Model | `{settings.openai_model}` |",
        f"| Timeout | `{settings.openai_timeout_seconds}` seconds |",
        f"| Max output tokens | `{settings.openai_max_output_tokens}` |",
        f"| Reasoning effort | `{settings.openai_reasoning_effort}` |",
        f"| Verbosity | `{settings.openai_verbosity}` |",
        "| Provider storage | `false` |",
        "| OpenAI key | configured; value omitted |",
        "",
        "### Provider access",
        "",
        *_render_model_access(model_access, settings.openai_model),
        "",
        "### Run summary",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Capability endpoints planned | {len(results)} |",
        f"| Structured-output requests sent | {sent} |",
        f"| Completed through guardrails | {completed} |",
        f"| Not sent after billing failure | {skipped} |",
        f"| Failed automatic checks on completed cases | {failed_checks} |",
        "",
    ]
    for index, result in enumerate(results, start=1):
        sections.extend(_render_case(index, result, settings))
    return "\n".join(sections).rstrip() + "\n"


def append_report(path: Path, report: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = "# MANA AI live evaluation log\n\n"
    with path.open("a", encoding="utf-8") as destination:
        if path.stat().st_size == 0:
            destination.write(header)
        destination.write(report)
        destination.write("\n")


def _render_model_access(result: ModelAccessResult, configured_model: str) -> list[str]:
    lines = [
        f"- Operation: `GET /v1/models/{configured_model}`",
        f"- Request sent: `{str(result.sent).lower()}`",
        f"- Latency: `{result.latency_ms:.2f} ms`",
    ]
    if result.metadata is not None:
        lines.extend(
            [
                "- Result: **PASS**",
                f"- Retrieved model ID: `{result.metadata.model_id}`",
                f"- Model owner: `{result.metadata.owned_by}`",
                f"- Model created timestamp: `{result.metadata.created_at}`",
            ]
        )
    elif result.failure is not None:
        lines.extend(["- Result: **FAIL**", *_render_failure_summary(result.failure)])
    return lines


def _render_case(index: int, result: EvaluationResult, settings: Settings) -> list[str]:
    status = (
        "COMPLETED"
        if result.completed
        else "PROVIDER_ERROR"
        if result.provider_failure is not None
        else "NOT_SENT"
    )
    lines = [
        f"### {index}. `{result.capability.value}`",
        "",
        f"- Endpoint: `POST {result.endpoint}`",
        f"- Status: **{status}**",
        "- Provider operation: `POST /v1/responses`",
        f"- OpenAI request sent: `{str(result.provider_sent).lower()}`",
        (
            f"- OpenAI latency: `{result.latency_ms:.2f} ms`"
            if result.latency_ms is not None
            else "- OpenAI latency: not available; request was not sent"
        ),
        f"- Model: `{settings.openai_model}`",
        f"- Safety identifier: `{result.safety_identifier}` (derived from a synthetic subject ID)",
    ]
    if result.response_metadata is not None:
        metadata = result.response_metadata
        lines.extend(
            [
                f"- OpenAI response ID: `{metadata.response_id}`",
                f"- OpenAI response status: `{metadata.status}`",
                f"- Input tokens: `{metadata.input_tokens}`",
                f"- Cached input tokens: `{metadata.cached_input_tokens}`",
                f"- Output tokens: `{metadata.output_tokens}`",
                f"- Reasoning output tokens: `{metadata.reasoning_output_tokens}`",
                f"- Total tokens: `{metadata.total_tokens}`",
            ]
        )
    if result.provider_failure is not None:
        lines.extend(_render_failure_summary(result.provider_failure))
    if result.skip_reason is not None:
        lines.append(f"- Skip reason: {result.skip_reason}")

    lines.extend(
        [
            "",
            "#### API request",
            "",
            _json_block(result.api_request),
            "",
            "#### OpenAI transport settings",
            "",
            "```json",
            json.dumps(
                {
                    "model": settings.openai_model,
                    "max_output_tokens": settings.openai_max_output_tokens,
                    "reasoning": {"effort": settings.openai_reasoning_effort},
                    "text": {
                        "verbosity": settings.openai_verbosity,
                        "format": "ModelAnalysis Structured Output JSON schema",
                    },
                    "store": False,
                    "safety_identifier": result.safety_identifier,
                },
                ensure_ascii=False,
                indent=2,
            ),
            "```",
            "",
            "#### OpenAI system instructions",
            "",
            "```text",
            result.system_instructions,
            "```",
            "",
            "#### OpenAI user payload after minimization",
            "",
            _json_block(result.provider_payload),
            "",
            "#### Raw parsed Structured Output",
            "",
        ]
    )
    if result.raw_output is None:
        lines.append("No structured model output was received.")
    else:
        lines.append(_json_block(result.raw_output))
    lines.extend(["", "#### Final API response after guardrails", ""])
    if result.final_response is None:
        lines.append(
            "No final API response was produced because semantic generation did not complete."
        )
    else:
        lines.append(_json_block(result.final_response))

    lines.extend(
        [
            "",
            "#### Automatic checks",
            "",
            "| Check | Result | Details |",
            "| --- | --- | --- |",
        ]
    )
    lines.extend(
        f"| {_markdown_cell(check.name)} | {'PASS' if check.passed else 'FAIL'} | "
        f"{_markdown_cell(check.details)} |"
        for check in result.checks
    )
    lines.extend(
        [
            "",
            "#### Manual review",
            "",
            "- [ ] Факты не выдуманы и опираются только на входные evidence.",
            "- [ ] Уровень риска и итоговый verdict соразмерны сценарию.",
            "- [ ] Русский текст понятен, нейтрален и подходит возрастной группе.",
            (
                "- [ ] Рекомендации практически полезны и не выдают предложение "
                "за выполненное действие."
            ),
            "- [ ] Приватные данные и полный текст уведомлений не воспроизведены.",
            "- Оценка качества: `__/5`",
            "- Комментарий проверяющего: `________________________________________`",
            "",
        ]
    )
    return lines


def _render_failure_summary(failure: ProviderFailure) -> list[str]:
    return [
        f"- HTTP status: `{failure.status_code}`",
        f"- Provider request ID: `{failure.request_id}`",
        f"- Error type: `{failure.error_type}`",
        f"- Error code: `{failure.code}`",
        f"- Error message: `{_markdown_cell(failure.message)}`",
        "- Sanitized provider error body:",
        _json_block(failure.response_body),
    ]


def _extract_provider_failure(error: AIProviderError) -> ProviderFailure:
    cause = error.__cause__
    if isinstance(cause, APIStatusError):
        body = _json_safe(cause.body)
        body_mapping = body if isinstance(body, dict) else {}
        nested_error = body_mapping.get("error")
        details = nested_error if isinstance(nested_error, dict) else body_mapping
        return ProviderFailure(
            status_code=cause.status_code,
            request_id=cause.request_id,
            error_type=_string_value(details.get("type"), type(cause).__name__),
            code=_optional_string(details.get("code")),
            message=_string_value(details.get("message"), str(cause)),
            response_body=body,
        )
    return ProviderFailure(
        status_code=None,
        request_id=None,
        error_type=type(cause).__name__ if cause is not None else type(error).__name__,
        code=None,
        message=_redact(str(cause or error)),
        response_body=None,
    )


def _notification_previews(request: ManaAIRequest) -> list[str]:
    input_data = request.input.model_dump(mode="json")
    notifications = input_data.get("notifications", [])
    if not isinstance(notifications, list):
        return []
    return [
        excerpt
        for item in notifications
        if isinstance(item, dict)
        if isinstance((excerpt := item.get("excerpt")), str)
    ]


def _make_resource_malicious(resource: dict[str, Any]) -> None:
    resource.update(
        normalized_value=("https://malicious.example/login?session=synthetic-secret#fragment"),
        reputation="malicious",
        category="phishing",
    )


def _malicious_resource() -> dict[str, Any]:
    resource = {
        "evidence_id": "resource-live-eval",
        "observed_at": "2026-08-07T14:20:00+05:00",
        "source": "link_check",
        "kind": "url",
        "normalized_value": "https://malicious.example/login",
        "reputation": "malicious",
        "category": "phishing",
    }
    return resource


def _make_usage_excessive(usage: dict[str, Any]) -> None:
    usage.update(
        package_name="org.example.game",
        display_name="Example Game",
        category="game",
        foreground_seconds=10_800,
        night_seconds=7_200,
        configured_limit_seconds=3_600,
        launch_count=24,
    )


def _excessive_usage() -> dict[str, Any]:
    usage = {
        "evidence_id": "usage-live-eval",
        "observed_at": "2026-08-07T14:20:00+05:00",
        "source": "app_usage",
    }
    _make_usage_excessive(usage)
    return usage


def _json_safe(value: object) -> Any:
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return _redact(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(item) for item in value]
    return _redact(str(value))


def _string_value(value: object, fallback: str) -> str:
    return _redact(value if isinstance(value, str) else fallback)


def _optional_string(value: object) -> str | None:
    return _redact(value) if isinstance(value, str) else None


def _redact(value: str) -> str:
    return SECRET_PATTERN.sub("[REDACTED_OPENAI_KEY]", value)


def _json_block(value: Any) -> str:
    return f"```json\n{json.dumps(value, ensure_ascii=False, indent=2)}\n```"


def _markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _elapsed_ms(started: float) -> float:
    return round((perf_counter() - started) * 1_000, 2)


def _require_opt_in() -> None:
    if os.getenv(LIVE_EVAL_ENV) != "1":
        raise SystemExit(
            f"Live evaluation is disabled. Set {LIVE_EVAL_ENV}=1 to allow bounded OpenAI requests."
        )


async def async_main() -> int:
    _require_opt_in()
    settings = Settings()
    generated_at = datetime.now(UTC)
    run_id = generated_at.strftime("%Y%m%dT%H%M%SZ")
    model_access, results = await run_evaluation(settings)
    report = render_report(
        run_id=run_id,
        generated_at=generated_at,
        settings=settings,
        model_access=model_access,
        results=results,
    )
    report_path = Path(os.getenv(REPORT_PATH_ENV, str(DEFAULT_REPORT_PATH)))
    append_report(report_path, report)
    print(f"MANA AI live evaluation report: {report_path}")

    if any(
        result.provider_failure is not None and result.provider_failure.is_credit_exhausted
        for result in results
    ):
        return 3
    if any(result.provider_failure is not None for result in results):
        return 1
    if any(not check.passed for result in results for check in result.checks):
        return 1
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
