from app.mana_ai.application.details import (
    details_match_input,
    fallback_details,
    reconcile_details,
)
from app.mana_ai.application.deterministic import (
    analyze_deterministically,
    required_checks,
    unavailable_check_categories,
    verdict_from,
)
from app.mana_ai.application.evidence import (
    collect_evidence_ids,
    validate_action_evidence,
    validate_finding_evidence,
)
from app.mana_ai.application.policy import (
    build_action_proposals,
    build_findings,
    filter_actions,
)
from app.mana_ai.application.ports import Clock, ManaAIModelGateway, ModelGatewayError
from app.mana_ai.domain.enums import (
    AnalysisStatus,
    AnalysisVerdict,
    CheckStatus,
    FindingCategory,
)
from app.mana_ai.domain.requests import ManaAIRequest
from app.mana_ai.domain.responses import (
    CheckResult,
    FindingDraft,
    ManaAIAnalysisResult,
    ModelAnalysis,
)


class ManaAIAnalysisService:
    def __init__(self, *, gateway: ManaAIModelGateway, clock: Clock) -> None:
        self._gateway = gateway
        self._clock = clock

    async def analyze(self, request: ManaAIRequest) -> ManaAIAnalysisResult:
        deterministic = analyze_deterministically(
            request.input,
            evaluated_at=request.occurred_at,
        )
        requirements = required_checks(request.input)
        status = AnalysisStatus.COMPLETED
        try:
            semantic = await self._gateway.analyze(
                request,
                deterministic_findings=deterministic.findings,
                required_checks=requirements,
            )
        except ModelGatewayError:
            status = AnalysisStatus.DEGRADED
            fallback_summary = _fallback_summary(request.locale, bool(deterministic.findings))
            semantic = ModelAnalysis(
                verdict=AnalysisVerdict.INSUFFICIENT_DATA,
                summary=fallback_summary,
                details=fallback_details(
                    request.input,
                    summary=fallback_summary,
                    findings=deterministic.findings,
                    evaluated_at=request.occurred_at,
                ),
                data_quality_notes=[
                    "Semantic analysis was unavailable; only deterministic checks were applied."
                ],
            )

        evidence_ids = collect_evidence_ids(request.input)
        model_findings, evidence_notes = validate_finding_evidence(
            semantic.findings,
            evidence_ids,
        )
        unavailable_categories = unavailable_check_categories(request.input)
        model_findings, coverage_finding_notes = _filter_unavailable_findings(
            model_findings,
            unavailable_categories,
        )
        model_actions, action_evidence_notes = validate_action_evidence(
            semantic.proposed_actions,
            evidence_ids,
        )
        findings = _merge_findings(deterministic.findings, model_findings)
        actions, policy_notes = filter_actions(
            request,
            [*deterministic.proposed_actions, *model_actions],
        )
        checks, check_notes = _merge_checks(
            requirements,
            deterministic.checks,
            semantic.checks,
            findings,
            unavailable_categories,
        )
        notes = _deduplicate(
            [
                *deterministic.data_quality_notes,
                *semantic.data_quality_notes,
                *evidence_notes,
                *coverage_finding_notes,
                *action_evidence_notes,
                *policy_notes,
                *check_notes,
            ]
        )
        if (
            evidence_notes
            or coverage_finding_notes
            or action_evidence_notes
            or policy_notes
            or check_notes
        ):
            status = AnalysisStatus.DEGRADED

        verdict = verdict_from(findings, actions)
        if not findings:
            verdict = _empty_finding_verdict(semantic.verdict, checks)

        summary = _reconcile_summary(request.locale, semantic, verdict)
        if summary != semantic.summary:
            notes.append("Model summary conflicted with the validated verdict and was replaced.")
            status = AnalysisStatus.DEGRADED

        details = semantic.details
        if not details_match_input(request.input, details):
            details = fallback_details(
                request.input,
                summary=summary,
                findings=findings,
                evaluated_at=request.occurred_at,
                verdict=verdict,
            )
            notes.append("Capability-specific model details did not match the request capability.")
            status = AnalysisStatus.DEGRADED
        details = reconcile_details(
            request.input,
            details,
            summary=summary,
            findings=findings,
            checks=checks,
            evaluated_at=request.occurred_at,
            verdict=verdict,
        )

        return ManaAIAnalysisResult(
            request_id=request.request_id,
            capability=request.input.capability,
            processed_at=self._clock.now(),
            status=status,
            verdict=verdict,
            summary=summary,
            details=details,
            findings=build_findings(request.request_id, findings),
            checks=checks,
            proposed_actions=build_action_proposals(request.request_id, actions),
            data_quality_notes=notes,
            model_name=self._gateway.model_name,
        )


def _merge_findings(
    deterministic: list[FindingDraft],
    semantic: list[FindingDraft],
) -> list[FindingDraft]:
    merged: list[FindingDraft] = []
    seen: set[tuple[FindingCategory, tuple[str, ...]]] = set()
    for finding in [*deterministic, *semantic]:
        key = (finding.category, tuple(sorted(finding.evidence_ids)))
        if key in seen:
            continue
        seen.add(key)
        merged.append(finding)
    return merged


def _merge_checks(
    requirements: list[CheckResult],
    deterministic: list[CheckResult],
    semantic: list[CheckResult],
    findings: list[FindingDraft],
    unavailable_categories: set[FindingCategory],
) -> tuple[list[CheckResult], list[str]]:
    notes: list[str] = []
    by_category = {check.category: check for check in requirements}
    for check in [*semantic, *deterministic]:
        if (
            check.category in unavailable_categories
            and check.status is not CheckStatus.INSUFFICIENT_DATA
        ):
            notes.append(f"A check without the required signal was ignored: {check.category.value}")
            continue
        by_category[check.category] = check

    finding_categories = {finding.category for finding in findings}
    for category in finding_categories:
        by_category[category] = CheckResult(
            category=category,
            status=CheckStatus.RISK_DETECTED,
            explanation="One or more validated findings support this check.",
        )

    for category, check in list(by_category.items()):
        if check.status is CheckStatus.RISK_DETECTED and category not in finding_categories:
            by_category[category] = CheckResult(
                category=category,
                status=CheckStatus.INSUFFICIENT_DATA,
                explanation="The model reported risk without a validated evidence-backed finding.",
            )
            notes.append(f"Unsupported risk check was downgraded: {category.value}")
    return list(by_category.values()), notes


def _filter_unavailable_findings(
    findings: list[FindingDraft],
    unavailable_categories: set[FindingCategory],
) -> tuple[list[FindingDraft], list[str]]:
    accepted: list[FindingDraft] = []
    notes: list[str] = []
    for finding in findings:
        if finding.category in unavailable_categories:
            notes.append(
                f"A finding without the required signal type was removed: {finding.category.value}"
            )
            continue
        accepted.append(finding)
    return accepted, notes


def _empty_finding_verdict(
    model_verdict: AnalysisVerdict,
    checks: list[CheckResult],
) -> AnalysisVerdict:
    if checks and any(check.status is CheckStatus.INSUFFICIENT_DATA for check in checks):
        return AnalysisVerdict.INSUFFICIENT_DATA
    if model_verdict in {
        AnalysisVerdict.ALERT,
        AnalysisVerdict.BLOCK,
        AnalysisVerdict.WARN,
    }:
        return AnalysisVerdict.OBSERVE
    return model_verdict


def _deduplicate(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _fallback_summary(locale: str, has_findings: bool) -> str:
    language = locale.split("-", maxsplit=1)[0]
    messages = {
        "ru": (
            "Семантический анализ недоступен; возвращены только детерминированные находки."
            if has_findings
            else (
                "Семантический анализ недоступен; данных недостаточно для вывода "
                "об отсутствии риска."
            )
        ),
        "uz": (
            "Semantik tahlil mavjud emas; faqat deterministik topilmalar qaytarildi."
            if has_findings
            else (
                "Semantik tahlil mavjud emas; xavf yo'qligi haqida xulosa uchun "
                "ma'lumot yetarli emas."
            )
        ),
        "en": (
            "Semantic analysis is unavailable; only deterministic findings are returned."
            if has_findings
            else "Semantic analysis is unavailable; there is not enough data to claim no risk."
        ),
    }
    return messages.get(language, messages["en"])


def _reconcile_summary(
    locale: str,
    semantic: ModelAnalysis,
    verdict: AnalysisVerdict,
) -> str:
    if semantic.verdict is verdict:
        return semantic.summary

    summaries = {
        "ru": {
            AnalysisVerdict.NO_RISK_DETECTED: (
                "В доступных и успешно проверенных сигналах риск не обнаружен."
            ),
            AnalysisVerdict.OBSERVE: (
                "В доступных сигналах есть изменение, которое следует наблюдать."
            ),
            AnalysisVerdict.WARN: (
                "В доступных сигналах обнаружено событие, требующее предупреждения."
            ),
            AnalysisVerdict.ALERT: (
                "В доступных сигналах обнаружено значимое событие, требующее внимания."
            ),
            AnalysisVerdict.BLOCK: ("Проверенные сигналы требуют блокирующего решения приложения."),
            AnalysisVerdict.INSUFFICIENT_DATA: (
                "Для надёжного вывода недостаточно доступных сигналов."
            ),
        },
        "uz": {
            AnalysisVerdict.NO_RISK_DETECTED: (
                "Mavjud va tekshirilgan signallarda xavf aniqlanmadi."
            ),
            AnalysisVerdict.OBSERVE: "Mavjud signallardagi o'zgarishni kuzatish kerak.",
            AnalysisVerdict.WARN: "Mavjud signallarda ogohlantirish talab qiluvchi holat bor.",
            AnalysisVerdict.ALERT: "Mavjud signallarda e'tibor talab qiluvchi muhim holat bor.",
            AnalysisVerdict.BLOCK: "Tekshirilgan signallar ilovada bloklash qarorini talab qiladi.",
            AnalysisVerdict.INSUFFICIENT_DATA: (
                "Ishonchli xulosa uchun mavjud signallar yetarli emas."
            ),
        },
    }
    language = locale.split("-", maxsplit=1)[0]
    localized = summaries.get(language)
    if localized is not None:
        return localized[verdict]
    return {
        AnalysisVerdict.NO_RISK_DETECTED: (
            "No risk was detected in the available, successfully checked signals."
        ),
        AnalysisVerdict.OBSERVE: "A change in the available signals should be observed.",
        AnalysisVerdict.WARN: "The available signals contain an event requiring a warning.",
        AnalysisVerdict.ALERT: "The available signals contain a significant event to review.",
        AnalysisVerdict.BLOCK: "Validated signals require a blocking decision by the application.",
        AnalysisVerdict.INSUFFICIENT_DATA: (
            "The available signals are insufficient for a reliable conclusion."
        ),
    }[verdict]
