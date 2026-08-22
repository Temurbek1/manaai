import argparse
import asyncio
import hashlib
import json
import signal
from collections import Counter, defaultdict
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import cast

from pydantic import JsonValue

from app.core.config import get_settings
from app.mana_operation_ai.application.admin_service import ActorContext
from app.mana_operation_ai.application.growth.constants import (
    ADVERTISING_CAPABILITY_KEY,
    GROWTH_AGENT_ID,
)
from app.mana_operation_ai.application.marketing.analytics import aggregate_metrics
from app.mana_operation_ai.application.marketing.calibration import calibrate_account
from app.mana_operation_ai.domain.enums import (
    AgentRunStatus,
    IntegrationStatus,
    UserRole,
)
from app.mana_operation_ai.domain.marketing import (
    AdsSnapshot,
    CompatibilityStatus,
    InsightRow,
    MarketingAgentConfiguration,
)
from app.mana_operation_ai.domain.models import AgentReport, Finding, Recommendation
from app.services.meta_marketing_client import MetaMarketingClient

ARTIFACT_PATH = Path("docs/artifacts/meta-live-readonly-report.artifact.json")
REPORT_PATH = Path("docs/artifacts/meta-live-readonly-report.html")


async def run() -> dict[str, JsonValue]:
    settings = get_settings()
    _validate_safety(settings)

    from app.main import create_app

    application = create_app()
    async with application.router.lifespan_context(application):
        client: MetaMarketingClient = application.state.meta_marketing_client
        _install_cancellation(client)
        platforms = application.state.operation_ads_platforms
        admin = application.state.operation_admin_service
        repository = application.state.operation_repository
        meta = platforms.get("meta")
        health = await meta.health()
        account_count = health.diagnostics.get("account_count")
        if health.status is not IntegrationStatus.HEALTHY:
            raise RuntimeError(
                "Live Meta health did not pass; inspect the sanitized integration-health result",
            )
        if account_count != 1:
            raise RuntimeError(
                "Live validation requires exactly one accessible Meta ad account",
            )

        actor = ActorContext(actor_id="meta-live-readonly-verify", role=UserRole.ADMIN)
        latest = await repository.latest_configuration(
            GROWTH_AGENT_ID,
            ADVERTISING_CAPABILITY_KEY,
        )
        if latest is None:
            raise RuntimeError("Marketing Agent has no typed configuration")
        bootstrap = MarketingAgentConfiguration.model_validate(
            {
                **latest.values,
                "baseline_period_days": max(
                    settings.meta_live_initial_lookback_days // 2,
                    1,
                ),
                "comparison_period_days": max(
                    settings.meta_live_initial_lookback_days
                    - settings.meta_live_initial_lookback_days // 2,
                    1,
                ),
                "notification_channels": [],
            },
        )
        await admin.create_configuration(
            agent_id=GROWTH_AGENT_ID,
            capability_key=ADVERTISING_CAPABILITY_KEY,
            values=cast(dict[str, JsonValue], bootstrap.model_dump(mode="json")),
            actor=actor,
        )
        calibration_run = await admin.run_now(
            agent_id=GROWTH_AGENT_ID,
            capability_key=ADVERTISING_CAPABILITY_KEY,
            job_type="meta_sync",
            actor=actor,
            correlation_id=admin.new_identifier(),
            idempotency_key=None,
        )
        if calibration_run.status not in {
            AgentRunStatus.COMPLETED,
            AgentRunStatus.WAITING_APPROVAL,
        }:
            raise RuntimeError(
                f"Calibration collection ended in {calibration_run.status.value}",
            )
        source_records = await repository.list_snapshots(calibration_run.run_id)
        if len(source_records) != 1:
            raise RuntimeError("Calibration run did not persist exactly one snapshot")
        source_record = source_records[0]
        source_snapshot = AdsSnapshot.model_validate(source_record.payload)
        calibration = calibrate_account(
            snapshot=source_snapshot,
            source_snapshot_id=source_record.snapshot_id,
            objective=bootstrap.primary_objective,
            calibrated_at=datetime.now(UTC),
        )
        account = source_snapshot.accounts[0]
        calibrated = MarketingAgentConfiguration.model_validate(
            {
                **bootstrap.model_dump(),
                "account_ids": [account.provider_id],
                "account_calibrations": {
                    **bootstrap.account_calibrations,
                    account.provider_id: calibration.calibration,
                },
                "notification_channels": [],
            },
        )
        configuration = await admin.create_configuration(
            agent_id=GROWTH_AGENT_ID,
            capability_key=ADVERTISING_CAPABILITY_KEY,
            values=cast(dict[str, JsonValue], calibrated.model_dump(mode="json")),
            actor=actor,
        )
        nightly = await admin.run_now(
            agent_id=GROWTH_AGENT_ID,
            capability_key=ADVERTISING_CAPABILITY_KEY,
            job_type="nightly_report",
            actor=actor,
            correlation_id=admin.new_identifier(),
            idempotency_key=None,
        )
        if nightly.status is not AgentRunStatus.COMPLETED or nightly.report_id is None:
            raise RuntimeError(
                f"Live nightly report ended in {nightly.status.value}",
            )
        nightly_records = await repository.list_snapshots(nightly.run_id)
        if len(nightly_records) != 1:
            raise RuntimeError("Nightly run did not persist exactly one snapshot")
        nightly_snapshot = AdsSnapshot.model_validate(nightly_records[0].payload)
        findings, _ = await repository.list_findings(run_id=nightly.run_id)
        recommendations, _ = await repository.list_recommendations(run_id=nightly.run_id)
        proposals, _ = await repository.list_proposals(run_id=nightly.run_id)
        executions, _ = await repository.list_executions(
            agent_id=GROWTH_AGENT_ID,
            capability_key=ADVERTISING_CAPABILITY_KEY,
        )
        report = await repository.get_report(nightly.report_id)
        if report is None:
            raise RuntimeError("Nightly report record is unavailable")
        if any(not proposal.execution_forbidden for proposal in proposals):
            raise RuntimeError("A live proposal was persisted without execution_forbidden=true")
        if any(item.run_id == nightly.run_id for item in executions):
            raise RuntimeError("A live nightly run unexpectedly persisted an execution")

        account_alias = _alias(account.provider_id)
        evidence = _evidence(
            health=health.model_dump(mode="json"),
            snapshot=nightly_snapshot,
            account_alias=account_alias,
            calibration_version=configuration.version,
            calibration=calibration.model_dump(mode="json"),
            findings=findings,
            recommendations=recommendations,
            proposal_count=len(proposals),
            report=report,
        )
        _write_json(settings.meta_live_evidence_path, evidence)
        artifact = _artifact(
            evidence=evidence,
            snapshot=nightly_snapshot,
            findings=findings,
            report=report,
            generated_at=datetime.now(UTC),
        )
        _write_json(ARTIFACT_PATH, artifact)
        return {
            "status": "passed",
            "mode": "live_read_only",
            "account_alias": account_alias,
            "configuration_version": configuration.version,
            "findings_count": len(findings),
            "recommendations_count": len(recommendations),
            "proposals_count": len(proposals),
            "executions_count": 0,
            "nightly_report": "passed",
            "artifact_input": ARTIFACT_PATH.as_posix(),
            "report_output": REPORT_PATH.as_posix(),
        }


def _validate_safety(settings: object) -> None:
    from app.core.config import Settings

    if not isinstance(settings, Settings):
        raise RuntimeError("Invalid settings object")
    if not settings.meta_live_readonly_verify:
        raise RuntimeError("META_LIVE_READONLY_VERIFY=1 is required for live GET requests")
    if settings.meta_live_mode != "read_only":
        raise RuntimeError("META_LIVE_MODE must be read_only")
    if settings.meta_real_writes_enabled:
        raise RuntimeError("META_REAL_WRITES_ENABLED must remain false")
    if not settings.operation_dry_run:
        raise RuntimeError("OPERATION_DRY_RUN must remain true")
    if settings.operation_ads_provider != "meta":
        raise RuntimeError("OPERATION_ADS_PROVIDER must be meta for live verification")
    if not settings.is_meta_configured:
        raise RuntimeError("META_ACCESS_TOKEN is not configured")


def _install_cancellation(client: MetaMarketingClient) -> None:
    loop = asyncio.get_running_loop()
    try:
        loop.add_signal_handler(signal.SIGINT, client.cancel_active_run)
        loop.add_signal_handler(signal.SIGTERM, client.cancel_active_run)
    except NotImplementedError:
        return


def _evidence(
    *,
    health: dict[str, JsonValue],
    snapshot: AdsSnapshot,
    account_alias: str,
    calibration_version: int,
    calibration: dict[str, JsonValue],
    findings: list[Finding],
    recommendations: list[Recommendation],
    proposal_count: int,
    report: AgentReport,
) -> dict[str, JsonValue]:
    health_diagnostics = health.get("diagnostics")
    safe_health = health_diagnostics if isinstance(health_diagnostics, dict) else {}
    credential = safe_health.get("token")
    safe_credential = credential if isinstance(credential, dict) else {}
    request_budget = (
        snapshot.request_budget.model_dump(mode="json")
        if snapshot.request_budget is not None
        else None
    )
    if request_budget is not None:
        request_budget.pop("correlation_id", None)
        request_budget.pop("run_id", None)
    compatibility_counts = Counter(item.status.value for item in snapshot.compatibility_matrix)
    finding_counts = Counter(item.finding_type for item in findings)
    recommendation_counts = Counter(item.action_type.value for item in recommendations)
    calibration_item = calibration.get("calibration")
    safe_calibration_item = calibration_item if isinstance(calibration_item, dict) else {}
    safe_calibration = {
        "base_row_count": calibration.get("base_row_count"),
        "represented_days": calibration.get("represented_days"),
        "unavailable_thresholds": calibration.get("unavailable_thresholds", []),
        "thresholds": safe_calibration_item.get("thresholds", {}),
        "rationale": safe_calibration_item.get("rationale", []),
    }
    return cast(
        dict[str, JsonValue],
        {
            "schema_version": "1",
            "generated_at": datetime.now(UTC).isoformat(),
            "provider_mode": snapshot.provider_mode.value,
            "api_version": snapshot.api_version,
            "write_operations_available": False,
            "account_alias": account_alias,
            "credential_health": {
                "is_valid": safe_credential.get("is_valid"),
                "expires_at": safe_credential.get("expires_at"),
                "data_access_expires_at": safe_credential.get("data_access_expires_at"),
                "permissions": safe_credential.get("scopes", []),
                "granular_permission_names": safe_credential.get(
                    "granular_scope_names",
                    [],
                ),
            },
            "account_context": {
                "currency": snapshot.accounts[0].currency,
                "timezone": snapshot.accounts[0].timezone,
                "attribution_identity": snapshot.attribution_window,
            },
            "period": {
                "start": snapshot.period_start.isoformat(),
                "end": snapshot.period_end.isoformat(),
                "completed_period_only": True,
            },
            "inventory_counts": {
                "campaigns": len(snapshot.campaigns),
                "ad_sets": len(snapshot.ad_sets),
                "ads": len(snapshot.ads),
                "creatives": len(snapshot.creatives),
                "audiences": len(snapshot.audiences),
                "insight_rows": len(snapshot.insights),
            },
            "compatibility_counts": dict(sorted(compatibility_counts.items())),
            "request_budget": request_budget,
            "observability": snapshot.observability.model_dump(mode="json"),
            "calibration": {
                "configuration_version": calibration_version,
                "summary": safe_calibration,
            },
            "finding_counts": dict(sorted(finding_counts.items())),
            "recommendations_count": len(recommendations),
            "recommendation_counts": dict(sorted(recommendation_counts.items())),
            "proposals_count": proposal_count,
            "executions_count": 0,
            "nightly_report": {
                "report_id_alias": _alias(report.report_id),
                "status": "persisted",
                "structured": True,
                "human_readable": True,
                "workflow_observability": report.structured.get("workflow_observability", {}),
            },
            "limitations": sorted(snapshot.data_quality_notes),
        },
    )


def _artifact(
    *,
    evidence: dict[str, JsonValue],
    snapshot: AdsSnapshot,
    findings: list[Finding],
    report: AgentReport,
    generated_at: datetime,
) -> dict[str, object]:
    title = "Meta live read-only validation"
    source_id = "normalized_meta_snapshot"
    structured = report.structured
    raw_kpis = structured.get("kpis")
    kpis = raw_kpis if isinstance(raw_kpis, dict) else {}
    numeric_kpis: dict[str, float] = {}
    for name, value in kpis.items():
        parsed = _number(value)
        if parsed is not None:
            numeric_kpis[str(name)] = parsed
    datasets: dict[str, list[dict[str, object]]] = {
        "kpis": [cast(dict[str, object], numeric_kpis)],
        "compatibility": [
            {
                "operation": item.operation,
                "level": item.level or "not_applicable",
                "breakdowns": ", ".join(item.breakdowns) or "none",
                "scope": _compatibility_scope(item.level, item.breakdowns),
                "status": item.status.value,
                "rows": item.row_count,
                "reason": item.reason_code or "none",
            }
            for item in snapshot.compatibility_matrix
        ],
        "finding_counts": [
            {"finding_type": key, "count": value}
            for key, value in sorted(Counter(item.finding_type for item in findings).items())
        ],
        "calibration": _calibration_rows(evidence),
        "request_budget_utilization": _request_budget_rows(evidence),
    }
    daily_rows = _daily_rows(snapshot)
    if daily_rows:
        datasets["daily_performance"] = daily_rows

    cards: list[dict[str, object]] = []
    for name in ("spend", "impressions", "clicks", "leads", "conversions", "ctr"):
        if name not in numeric_kpis:
            continue
        cards.append(
            {
                "id": f"kpi_{name}",
                "description": f"Observed {name} for the completed analysis period.",
                "dataset": "kpis",
                "sourceId": source_id,
                "metrics": [
                    {
                        "label": name.replace("_", " ").title(),
                        "field": name,
                        "format": "number",
                    },
                ],
            },
        )

    compatibility_counts = Counter(item.status.value for item in snapshot.compatibility_matrix)
    unavailable_calibration_count = sum(
        row["value"] == "unavailable" for row in datasets["calibration"]
    )
    recommendation_count = int(_number(evidence.get("recommendations_count")) or 0)
    proposal_count = int(_number(evidence.get("proposals_count")) or 0)
    inventory_count = sum(
        len(items)
        for items in (
            snapshot.campaigns,
            snapshot.ad_sets,
            snapshot.ads,
            snapshot.creatives,
            snapshot.audiences,
            snapshot.insights,
        )
    )
    charts: list[dict[str, object]] = []
    blocks: list[dict[str, object]] = [
        {"id": "title", "type": "markdown", "body": f"# {title}"},
        {
            "id": "executive_summary",
            "type": "markdown",
            "sourceId": source_id,
            "body": (
                "## Executive Summary\n\n"
                "Bounded GET-only validation passed; writes remain forbidden at every layer. "
                f"Period: {inventory_count} delivery entities or insight rows; "
                f"{compatibility_counts.get('empty', 0)} compatibility queries explicitly "
                f"empty; {unavailable_calibration_count} account overrides inherit defaults. "
                f"Persisted: {len(findings)} finding, {recommendation_count} advisory "
                f"recommendations, {proposal_count} proposals, and 0 executions. UI "
                "reconciliation remains manual; POST reporting was excluded."
            ),
        },
    ]
    if cards:
        blocks.append(
            {
                "id": "headline_metrics",
                "type": "metric-strip",
                "cardIds": [item["id"] for item in cards],
            },
        )
    charts.append(
        {
            "id": "request_budget_utilization",
            "title": "Bounded live-read request utilization",
            "subtitle": "Actual use as a share of each configured per-run safety limit.",
            "type": "bar",
            "dataset": "request_budget_utilization",
            "sourceId": source_id,
            "valueFormat": "percent",
            "encodings": {
                "x": {"field": "budget", "type": "nominal"},
                "y": {
                    "field": "utilization",
                    "type": "quantitative",
                },
                "tooltip": [
                    {"field": "used", "type": "quantitative", "label": "Used"},
                    {"field": "limit", "type": "quantitative", "label": "Limit"},
                ],
            },
        },
    )
    blocks.append(
        {
            "id": "request_budget_utilization_block",
            "type": "chart",
            "chartId": "request_budget_utilization",
        },
    )
    if len(daily_rows) >= 8 and "spend" in numeric_kpis:
        charts.append(
            {
                "id": "daily_spend",
                "title": "Daily spend",
                "subtitle": (
                    f"Completed days in {snapshot.accounts[0].currency or 'unavailable'}; "
                    "base ad-level rows only."
                ),
                "type": "line",
                "dataset": "daily_performance",
                "sourceId": source_id,
                "valueFormat": "number",
                "encodings": {
                    "x": {"field": "date", "type": "temporal", "label": "Date"},
                    "y": {"field": "spend", "type": "quantitative", "label": "Spend"},
                    "tooltip": [
                        {"field": "impressions", "type": "quantitative", "label": "Impressions"},
                        {"field": "clicks", "type": "quantitative", "label": "Clicks"},
                    ],
                },
            },
        )
        blocks.append({"id": "daily_spend_block", "type": "chart", "chartId": "daily_spend"})
    tables: list[dict[str, object]] = []
    blocking_statuses = {
        CompatibilityStatus.PERMISSION_DENIED,
        CompatibilityStatus.UNAVAILABLE,
        CompatibilityStatus.PARTIAL,
        CompatibilityStatus.RATE_LIMITED,
        CompatibilityStatus.INVALID_COMBINATION,
    }
    issues = [
        {
            "id": f"compatibility_{index}",
            "dataset": "compatibility",
            "message": (
                f"{item.operation} ({item.level or 'not_applicable'}) is {item.status.value}."
            ),
        }
        for index, item in enumerate(snapshot.compatibility_matrix)
        if item.status in blocking_statuses
    ]
    generated = generated_at.isoformat()
    source = {
        "id": source_id,
        "label": "Persisted normalized Meta read-only snapshot",
        "path": "operation_database.ads_snapshots",
        "query": {
            "engine": "SQLAlchemy repository / SQL",
            "sql": (
                "SELECT 'snapshot' AS record_type, payload\n"
                "FROM operation_data_snapshots\n"
                "WHERE run_id = :nightly_run_id\n"
                "UNION ALL\n"
                "SELECT 'configuration', payload\n"
                "FROM operation_agent_configurations\n"
                "WHERE agent_id = 'marketing-agent'\n"
                "  AND version = :configuration_version\n"
                "UNION ALL\n"
                "SELECT 'finding', payload\n"
                "FROM operation_findings\n"
                "WHERE run_id = :nightly_run_id\n"
                "UNION ALL\n"
                "SELECT 'recommendation', payload\n"
                "FROM operation_recommendations\n"
                "WHERE run_id = :nightly_run_id\n"
                "UNION ALL\n"
                "SELECT 'report', payload\n"
                "FROM operation_agent_reports\n"
                "WHERE run_id = :nightly_run_id"
            ),
            "description": (
                "Reconstructs the persisted source records reviewed by the live verification "
                "script. Bind values remain private; only hashed account aliases are exported."
            ),
            "tables_used": [
                "operation_data_snapshots",
                "operation_agent_configurations",
                "operation_findings",
                "operation_recommendations",
                "operation_agent_reports",
            ],
            "filters": [
                "nightly run identifier",
                "marketing-agent configuration version",
                "completed reporting dates only",
            ],
            "metric_definitions": {
                "utilization": "used / configured per-run limit",
                "finding count": "count of persisted findings grouped by finding_type",
                "compatibility rows": "normalized provider rows returned by each GET query",
            },
        },
    }
    return {
        "surface": "report",
        "manifest": {
            "version": 1,
            "surface": "report",
            "title": title,
            "description": "Sanitized live validation, calibration, and nightly-report evidence.",
            "generatedAt": generated,
            "cards": cards,
            "charts": charts,
            "tables": tables,
            "sources": [source],
            "blocks": blocks,
        },
        "snapshot": {
            "version": 1,
            "generatedAt": generated,
            "status": "partial" if issues else "ready",
            "datasets": datasets,
            **({"accessIssues": issues} if issues else {}),
        },
        "sources": [source],
    }


def _daily_rows(snapshot: AdsSnapshot) -> list[dict[str, object]]:
    grouped: dict[str, list[InsightRow]] = defaultdict(list)
    for row in snapshot.insights:
        if row.dimensions.get("_query_scope") == "base":
            grouped[row.date_stop.isoformat()].append(row)
    result: list[dict[str, object]] = []
    for day, rows in sorted(grouped.items()):
        metrics = aggregate_metrics(rows)
        result.append(
            {
                "date": day,
                "spend": _decimal_number(metrics.spend.value),
                "impressions": _decimal_number(metrics.impressions.value),
                "clicks": _decimal_number(metrics.clicks.value),
                "leads": _decimal_number(metrics.leads.value),
                "conversions": _decimal_number(metrics.conversions.value),
            },
        )
    return result


def _compatibility_scope(level: str | None, breakdowns: list[str]) -> str:
    breakdown_labels = {
        "hourly_stats_aggregated_by_advertiser_time_zone": "hourly (account time zone)",
        "publisher_platform": "publisher",
        "platform_position": "placement",
    }
    scope = level or "entity"
    if not breakdowns:
        return scope
    return f"{scope}: {', '.join(breakdown_labels.get(item, item) for item in breakdowns)}"


def _calibration_rows(evidence: dict[str, JsonValue]) -> list[dict[str, object]]:
    calibration = evidence.get("calibration")
    if not isinstance(calibration, dict):
        return []
    summary = calibration.get("summary")
    if not isinstance(summary, dict):
        return []
    thresholds = summary.get("thresholds")
    if not isinstance(thresholds, dict):
        return []
    return [
        {"threshold": str(key), "value": "unavailable" if value is None else str(value)}
        for key, value in sorted(thresholds.items())
    ]


def _request_budget_rows(evidence: dict[str, JsonValue]) -> list[dict[str, object]]:
    budget = evidence.get("request_budget")
    if not isinstance(budget, dict):
        return []
    pairs = (
        ("Requests", "requests_used", "max_requests"),
        ("Pages", "pages_fetched", "max_pages"),
        ("Retries", "retries_used", "max_total_retries"),
        ("Time", "elapsed_ms", "max_duration_seconds"),
    )
    rows: list[dict[str, object]] = []
    for label, used_key, limit_key in pairs:
        used = _number(budget.get(used_key))
        limit = _number(budget.get(limit_key))
        if label == "Time" and limit is not None:
            limit *= 1000
        if used is None or limit is None or limit <= 0:
            continue
        rows.append(
            {
                "budget": label,
                "used": used,
                "limit": limit,
                "utilization": used / limit,
            },
        )
    return rows


def _number(value: object) -> float | None:
    if value in {None, "unavailable"}:
        return None
    try:
        return float(Decimal(str(value)))
    except (InvalidOperation, ValueError):
        return None


def _decimal_number(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def _alias(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:10]


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


async def rebuild_artifact() -> dict[str, JsonValue]:
    settings = get_settings()
    if not settings.meta_live_evidence_path.exists():
        raise RuntimeError("Sanitized live evidence is unavailable")

    from app.main import create_app

    application = create_app()
    async with application.router.lifespan_context(application):
        repository = application.state.operation_repository
        reports, _ = await repository.list_reports(
            agent_id=GROWTH_AGENT_ID,
            capability_key=ADVERTISING_CAPABILITY_KEY,
            limit=25,
        )
        report = next(
            (item for item in reports if item.structured.get("provider_mode") == "live_read_only"),
            None,
        )
        if report is None:
            raise RuntimeError("No persisted live read-only report is available")
        records = await repository.list_snapshots(report.run_id)
        if len(records) != 1:
            raise RuntimeError("The persisted live report must have exactly one snapshot")
        snapshot = AdsSnapshot.model_validate(records[0].payload)
        findings, _ = await repository.list_findings(run_id=report.run_id)
        evidence = cast(
            dict[str, JsonValue],
            json.loads(settings.meta_live_evidence_path.read_text(encoding="utf-8")),
        )
        artifact = _artifact(
            evidence=evidence,
            snapshot=snapshot,
            findings=findings,
            report=report,
            generated_at=datetime.now(UTC),
        )
        _write_json(ARTIFACT_PATH, artifact)
        return {
            "status": "rebuilt",
            "mode": "offline_from_persisted_live_snapshot",
            "artifact_input": ARTIFACT_PATH.as_posix(),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Bounded Meta live read-only verification")
    parser.add_argument(
        "--rebuild-artifact-only",
        action="store_true",
        help=(
            "Rebuild the portable artifact from persisted sanitized live evidence without Meta I/O."
        ),
    )
    arguments = parser.parse_args()
    try:
        result = asyncio.run(rebuild_artifact() if arguments.rebuild_artifact_only else run())
    except (RuntimeError, ValueError) as exc:
        raise SystemExit(f"meta_live_readonly_verify failed: {exc}") from exc
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
