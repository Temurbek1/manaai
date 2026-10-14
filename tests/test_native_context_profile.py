"""An explicit sample profile never upgrades stored native tasks or changes live settings."""

from pathlib import Path

import pytest
from dotenv import dotenv_values
from pydantic import ValidationError

from app.core.config import Settings


def test_code_fallback_retains_the_legacy_compaction_trigger() -> None:
    assert Settings.model_fields["operation_workspace_compact_threshold"].default == 8000
    assert Settings.model_fields["operation_agent_workspace_enabled"].default is False
    assert Settings.model_fields["operation_workspace_model_continuation_enabled"].default is False


def test_recommended_example_is_explicit_disabled_and_preserves_hard_bounds() -> None:
    example = dotenv_values(Path(__file__).resolve().parents[1] / ".env.example")
    assert example["OPERATION_WORKSPACE_COMPACT_THRESHOLD"] == "24000"
    assert example["OPERATION_WORKSPACE_MODEL_WINDOW_BYTES"] == "192000"
    assert example["OPERATION_WORKSPACE_MODEL_MAX_OUTPUT_TOKENS"] == "8192"
    for flag in (
        "OPERATION_AGENT_WORKSPACE_ENABLED",
        "OPERATION_WORKSPACE_MODEL_CONTINUATION_ENABLED",
        "OPERATION_WORKSPACE_REPORT_DISCOVERY_ENABLED",
        "OPERATION_WORKSPACE_SNAPSHOT_REPLACEMENT_ENABLED",
        "OPERATION_WORKSPACE_PAGE_PROJECTION_ENABLED",
        "OPERATION_WORKSPACE_REVIEW_VERDICTS_ENABLED",
        "OPERATION_PARENT_ANALYTICS_ENABLED",
        "OPERATION_CHILD_TELEMETRY_ENABLED",
    ):
        assert example[flag] == "false"


@pytest.mark.parametrize("threshold", [1023, 24001])
def test_example_recommendation_does_not_relax_the_configured_trigger_bounds(
    threshold: int,
) -> None:
    with pytest.raises(ValidationError, match="operation_workspace_compact_threshold"):
        Settings(
            _env_file=None,
            openai_api_key="fixture",
            operation_workspace_compact_threshold=threshold,
        )
