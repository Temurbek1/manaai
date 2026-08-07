import pytest
from pydantic import ValidationError

from app.api.mana_ai_examples import request_examples
from app.mana_ai.domain.enums import ManaAICapability
from tests.mana_ai_fixtures import REQUEST_TYPE_BY_CAPABILITY, request_for


@pytest.mark.parametrize("capability", list(ManaAICapability))
def test_every_capability_has_an_independent_strict_request_contract(
    capability: ManaAICapability,
) -> None:
    request = request_for(capability)

    assert request.input.capability is capability
    assert request.data_minimized is True
    assert "capability" not in request.input.model_dump()
    assert "capability" not in type(request.input).model_json_schema()["properties"]


def test_unknown_fields_are_rejected_at_the_endpoint_request_boundary() -> None:
    request = request_for(ManaAICapability.PARENT_COPILOT)
    raw = request.model_dump(mode="json")
    raw["unexpected"] = "not allowed"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        type(request).model_validate(raw)


def test_application_must_confirm_data_minimization() -> None:
    request = request_for(ManaAICapability.PARENT_COPILOT)
    raw = request.model_dump(mode="json")
    raw["data_minimized"] = False

    with pytest.raises(ValidationError):
        type(request).model_validate(raw)


def test_client_cannot_override_capability_in_body() -> None:
    request = request_for(ManaAICapability.PARENT_COPILOT)
    raw = request.model_dump(mode="json")
    raw["input"]["capability"] = ManaAICapability.SAFETY_MONITOR.value

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        type(request).model_validate(raw)


def test_payload_for_another_endpoint_is_rejected() -> None:
    location = request_for(ManaAICapability.LOCATION_INTELLIGENCE)
    parent = request_for(ManaAICapability.PARENT_COPILOT)
    raw = parent.model_dump(mode="json")
    raw["input"] = location.input.model_dump(mode="json")

    with pytest.raises(ValidationError):
        type(parent).model_validate(raw)


def test_parent_copilot_rejects_action_kinds_it_cannot_return() -> None:
    request = request_for(ManaAICapability.PARENT_COPILOT)
    raw = request.model_dump(mode="json")
    raw["input"]["allowed_action_kinds"] = ["notify_parent"]

    with pytest.raises(ValidationError):
        type(request).model_validate(raw)


def test_duplicate_evidence_ids_are_rejected_as_ambiguous() -> None:
    request = request_for(ManaAICapability.SAFETY_MONITOR)
    raw = request.model_dump(mode="json")
    duplicate = dict(raw["input"]["notifications"][0])
    raw["input"]["notifications"].append(duplicate)

    with pytest.raises(ValidationError, match="evidence_id values must be unique"):
        type(request).model_validate(raw)


def test_every_capability_uses_a_different_public_request_model() -> None:
    assert len(set(REQUEST_TYPE_BY_CAPABILITY.values())) == len(ManaAICapability)


@pytest.mark.parametrize("capability", list(ManaAICapability))
def test_every_swagger_example_validates_against_its_endpoint_model(
    capability: ManaAICapability,
) -> None:
    request_type = REQUEST_TYPE_BY_CAPABILITY[capability]
    example = request_examples(capability)["default"]["value"]

    request = request_type.model_validate(example)

    assert request.input.capability is capability
    assert "capability" not in example["input"]
    assert "schema_version" not in example
    assert "evaluated_at" not in example["input"]
