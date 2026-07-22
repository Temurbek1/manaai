from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Mutation:
    name: str
    path: str
    original: str
    mutated: str
    tests: tuple[str, ...]


MUTATIONS = (
    Mutation(
        "self_approval",
        "app/mana_operation_ai/application/action_lifecycle.py",
        "if not self._allow_self_approval and approval.requested_by == actor_id:",
        "if False and not self._allow_self_approval and approval.requested_by == actor_id:",
        (
            "tests/test_operation_api.py::test_self_approval_is_rejected_and_dry_run_does_not_change_provider",
        ),
    ),
    Mutation(
        "global_kill_switch",
        "app/mana_operation_ai/application/action_lifecycle.py",
        """if await self._repository.get_control(
            "global_kill_switch",
            default=self._global_kill_switch_default,
        ):""",
        """if False and await self._repository.get_control(
            "global_kill_switch",
            default=self._global_kill_switch_default,
        ):""",
        (
            "tests/test_operation_api.py::test_policy_change_after_approval_blocks_delayed_execution",
        ),
    ),
    Mutation(
        "float_financial_math",
        "app/mana_operation_ai/application/marketing/metrics.py",
        "return available((numerator / denominator) * multiplier)",
        ("return available(Decimal(str(float(numerator) / float(denominator))) * multiplier)"),
        (
            "tests/test_marketing_reference.py::test_metric_engine_matches_independent_decimal_reference",
        ),
    ),
    Mutation(
        "duplicate_provider_write",
        "app/mana_operation_ai/infrastructure/ads/fake_meta.py",
        "if previous_result is not None:",
        "if False and previous_result is not None:",
        (
            "tests/test_operation_domain.py::test_fake_provider_action_idempotency_prevents_duplicate_budget_change",
        ),
    ),
    Mutation(
        "expired_proposal",
        "app/mana_operation_ai/application/action_lifecycle.py",
        "if approval.expires_at <= now or proposal.expires_at <= now:",
        "if False and (approval.expires_at <= now or proposal.expires_at <= now):",
        ("tests/test_operation_api.py::test_expired_proposal_cannot_execute",),
    ),
    Mutation(
        "stale_provider_state",
        "app/mana_operation_ai/application/action_lifecycle.py",
        "if before.state_hash != proposal.current_state_hash:",
        "if False and before.state_hash != proposal.current_state_hash:",
        ("tests/test_operation_api.py::test_stale_proposal_is_failed_before_provider_write",),
    ),
    Mutation(
        "provider_object_lock",
        "app/mana_operation_ai/application/action_lifecycle.py",
        "if not acquired:\n            raise ActionSafetyError(",
        "if False and not acquired:\n            raise ActionSafetyError(",
        (
            "tests/test_operation_api.py::test_provider_object_lock_blocks_concurrent_approved_action",
        ),
    ),
    Mutation(
        "maximum_budget_delta",
        "app/mana_operation_ai/application/policy.py",
        "if abs(change) > configuration.maximum_absolute_daily_budget_change:",
        "if False and abs(change) > configuration.maximum_absolute_daily_budget_change:",
        (
            "tests/test_operation_domain.py::test_budget_policy_enforces_absolute_delta_independently_of_factor",
        ),
    ),
    Mutation(
        "missing_policy",
        "app/mana_operation_ai/application/action_lifecycle.py",
        "if configuration_record is None:",
        "if False and configuration_record is None:",
        (
            "tests/test_operation_api.py::test_approved_action_without_active_policy_never_reaches_provider",
        ),
    ),
    Mutation(
        "token_in_diagnostics",
        "app/services/meta_marketing_client.py",
        "message=type(exc).__name__,",
        "message=str(exc),",
        (
            "tests/test_meta_operation_adapter.py::test_meta_transport_exception_text_cannot_enter_diagnostics",
        ),
    ),
    Mutation(
        "missing_verification_commit",
        "app/mana_operation_ai/application/action_lifecycle.py",
        """await self._repository.finalize_action_state(
            proposal=completed_proposal,
            execution=completed,
            verification=verification,""",
        """await self._repository.finalize_action_state(
            proposal=completed_proposal,
            execution=completed,
            verification=None,""",
        ("tests/test_operation_e2e.py::test_fake_meta_complete_marketing_agent_lifecycle",),
    ),
    Mutation(
        "invalid_state_transition",
        "app/mana_operation_ai/domain/state_machine.py",
        "{AgentRunStatus.COLLECTING, AgentRunStatus.CANCELLED, AgentRunStatus.FAILED}",
        "{AgentRunStatus.CANCELLED, AgentRunStatus.FAILED}",
        ("tests/test_operation_domain.py::test_state_machine_rejects_arbitrary_transitions",),
    ),
    Mutation(
        "duplicate_scheduler_occurrence",
        "app/mana_operation_ai/background/scheduler.py",
        "if not acquired:\n                continue",
        "if False and not acquired:\n                continue",
        (
            "tests/test_scheduler_concurrency.py::test_two_scheduler_instances_execute_one_occurrence_once",
        ),
    ),
    Mutation(
        "viewer_can_approve",
        "app/mana_operation_ai/api/router.py",
        """async def decide_approval(
    proposal_id: str,
    payload: ApprovalDecisionRequest,
    admin: OperationAdminServiceDep,
    actor: ActorDep,
) -> ApprovalLifecycleResponse:
    require_role(actor, UserRole.APPROVER)""",
        """async def decide_approval(
    proposal_id: str,
    payload: ApprovalDecisionRequest,
    admin: OperationAdminServiceDep,
    actor: ActorDep,
) -> ApprovalLifecycleResponse:
    actor = actor.__class__(actor_id=actor.actor_id, role=UserRole.APPROVER)""",
        (
            "tests/test_operation_api.py::test_self_approval_is_rejected_and_dry_run_does_not_change_provider",
        ),
    ),
    Mutation(
        "mana_ai_repository_import",
        "app/mana_ai/api/router.py",
        "from fastapi import APIRouter",
        (
            "from fastapi import APIRouter\n"
            "from app.mana_operation_ai.infrastructure.persistence.repository import "
            "SqlAlchemyOperationRepository"
        ),
        ("tests/test_architecture_boundaries.py",),
    ),
)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    pytest = root / ".venv" / "bin" / "pytest"
    if not pytest.exists():
        raise SystemExit("Run make install before the mutation audit")
    failures: list[str] = []
    for mutation in MUTATIONS:
        with tempfile.TemporaryDirectory(prefix=f"manaai-mutation-{mutation.name}-") as temp:
            target_root = Path(temp) / "repo"
            shutil.copytree(
                root,
                target_root,
                ignore=shutil.ignore_patterns(
                    ".git",
                    ".venv",
                    ".env",
                    "node_modules",
                    "dist",
                    "data",
                    "*.pdf",
                    "__pycache__",
                    ".pytest_cache",
                    ".mypy_cache",
                    ".ruff_cache",
                ),
            )
            target = target_root / mutation.path
            source = target.read_text(encoding="utf-8")
            occurrences = source.count(mutation.original)
            if occurrences != 1:
                failures.append(
                    f"{mutation.name}: expected one mutation target, found {occurrences}",
                )
                continue
            target.write_text(
                source.replace(mutation.original, mutation.mutated, 1),
                encoding="utf-8",
            )
            environment = {
                **os.environ,
                "OPENAI_API_KEY": "mutation-test-key",
                "APP_API_KEY": "",
                "META_ACCESS_TOKEN": "",
            }
            completed = subprocess.run(
                [str(pytest), "-q", *mutation.tests],
                cwd=target_root,
                env=environment,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            if completed.returncode == 0:
                failures.append(f"{mutation.name}: mutation survived its regression tests")
            else:
                print(f"CAUGHT {mutation.name}")
    if failures:
        raise SystemExit("\n".join(failures))
    print(f"Caught {len(MUTATIONS)} of {len(MUTATIONS)} safety mutations")


if __name__ == "__main__":
    main()
