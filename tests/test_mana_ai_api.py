from datetime import datetime
from pathlib import Path
from typing import Any, cast

import pytest
from httpx import ASGITransport, AsyncClient
from pytest import MonkeyPatch

from app.api.routes.mana_ai import public_capability_path
from app.core.config import get_settings
from app.mana_ai.application.policy import ALLOWED_ACTIONS
from app.mana_ai.application.service import ManaAIAnalysisService
from app.mana_ai.domain.enums import AnalysisVerdict, CheckStatus, ManaAICapability
from app.mana_ai.domain.requests import ManaAIRequest
from app.mana_ai.domain.responses import CheckResult, FindingDraft, ModelAnalysis
from app.product_ai_main import create_app
from tests.mana_ai_fixtures import NOW, details_for, request_for


class FixedClock:
    def now(self) -> datetime:
        return NOW


class NoRiskGateway:
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
        del deterministic_findings
        return ModelAnalysis(
            verdict=AnalysisVerdict.NO_RISK_DETECTED,
            summary="No risk was detected in the available signals.",
            details=details_for(request.input.capability),
            checks=[
                check.model_copy(
                    update={
                        "status": CheckStatus.NO_RISK_DETECTED,
                        "explanation": "No risk detected in the supplied signal.",
                    }
                )
                for check in required_checks
            ],
        )


def configure_test_env(monkeypatch: MonkeyPatch, database_path: Path) -> None:
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("APP_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("MARKETING_DATABASE_PATH", str(database_path))
    get_settings.cache_clear()


@pytest.mark.parametrize("capability", list(ManaAICapability))
async def test_each_capability_has_a_working_independent_endpoint(
    capability: ManaAICapability,
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "must-not-exist.db"
    configure_test_env(monkeypatch, database_path)
    app = create_app()

    async with app.router.lifespan_context(app):
        app.state.mana_ai_analysis_service = ManaAIAnalysisService(
            gateway=NoRiskGateway(),
            clock=FixedClock(),
        )
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            request = request_for(capability)
            response = await client.post(
                public_capability_path(capability),
                json=request.model_dump(mode="json"),
            )

    assert response.status_code == 200
    body = response.json()
    assert body["capability"] == capability.value
    assert body["read_only"] is True
    assert body["privacy"]["application_data_mutated"] is False
    assert body["privacy"]["provider_store_disabled"] is True
    assert "subject_id" not in body
    assert "capability" not in request.model_dump(mode="json")["input"]
    assert not database_path.exists()
    get_settings.cache_clear()


async def test_generic_analysis_endpoint_does_not_exist(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_test_env(monkeypatch, tmp_path / "must-not-exist.db")
    app = create_app()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/api/v1/mana-ai/analyze",
            json=request_for(ManaAICapability.PARENT_COPILOT).model_dump(mode="json"),
        )

    assert response.status_code == 404
    get_settings.cache_clear()


async def test_capability_catalog_returns_exact_integration_paths(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_test_env(monkeypatch, tmp_path / "must-not-exist.db")
    app = create_app()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/api/v1/mana-ai/capabilities")

    assert response.status_code == 200
    capabilities = response.json()["capabilities"]
    assert {(item["capability"], item["method"], item["path"]) for item in capabilities} == {
        (capability.value, "POST", public_capability_path(capability))
        for capability in ManaAICapability
    }
    assert all(item["status"] == "implemented" for item in capabilities)
    assert all(item["mutates_application_data"] is False for item in capabilities)
    get_settings.cache_clear()


def _schema_component(schema: dict[str, Any], reference: dict[str, str]) -> dict[str, Any]:
    name = reference["$ref"].rsplit("/", maxsplit=1)[-1]
    return cast(dict[str, Any], schema["components"]["schemas"][name])


def test_openapi_exposes_only_endpoint_specific_request_and_response_schemas(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_test_env(monkeypatch, tmp_path / "must-not-exist.db")
    schema = create_app().openapi()

    operation_ids: set[str] = set()
    for capability in ManaAICapability:
        path = public_capability_path(capability)
        operation = schema["paths"][path]["post"]
        operation_ids.add(operation["operationId"])
        assert "does not read or mutate" in operation["description"]
        assert operation["requestBody"]["content"]["application/json"]["examples"]

        request_ref = operation["requestBody"]["content"]["application/json"]["schema"]
        request_schema = _schema_component(schema, request_ref)
        assert "schema_version" not in request_schema["properties"]
        input_schema = _schema_component(schema, request_schema["properties"]["input"])
        assert "oneOf" not in input_schema
        assert "discriminator" not in input_schema
        assert "capability" not in input_schema["properties"]
        assert "evaluated_at" not in input_schema["properties"]

        response_ref = operation["responses"]["200"]["content"]["application/json"]["schema"]
        response_schema = _schema_component(schema, response_ref)
        assert "schema_version" not in response_schema["properties"]
        assert "subject_id" not in response_schema["properties"]
        details_schema = _schema_component(schema, response_schema["properties"]["details"])
        assert "oneOf" not in details_schema
        assert "capability" not in details_schema["properties"]
        assert response_schema["properties"]["read_only"]["const"] is True

        proposal_ref = response_schema["properties"]["proposed_actions"]["items"]
        proposal_schema = _schema_component(schema, proposal_ref)
        action_schema = proposal_schema["properties"]["action"]
        action_kinds = {
            _schema_component(schema, variant)["properties"]["kind"]["const"]
            for variant in action_schema["oneOf"]
        }
        assert action_kinds == {kind.value for kind in ALLOWED_ACTIONS[capability]}

    assert len(operation_ids) == len(ManaAICapability)
    assert "/api/v1/mana-ai/analyze" not in schema["paths"]
    assert "ManaAIAnalysisRequest" not in schema["components"]["schemas"]
    assert "ManaAIAnalysisResponse" not in schema["components"]["schemas"]
    get_settings.cache_clear()
