"""Nested strict wire branches, preserving old captures and typed owning intent."""

import hashlib
import itertools
import json
from typing import Any

import pytest
from pydantic import ValidationError

from app.mana_ai.application.compact_manager_decision import (
    compact_manager_decision_instructions,
    compact_manager_decision_schema,
    compact_manager_decision_tools,
    parse_compact_manager_decision,
)
from app.mana_ai.application.input_presentation import without_schema_titles
from app.mana_ai.domain.client_upsell import UpsellEnquiry
from app.mana_ai.domain.parent_touch_manager import (
    ParentTouchClarificationReply,
    ParentTouchManagerScope,
)
from tests.test_compact_manager_decision import assert_strict_schema, enquiry, handoff, reply


def scope(**changes: Any) -> ParentTouchManagerScope:
    return ParentTouchManagerScope.model_validate(
        {
            "language": "ru",
            "upsell_enabled": True,
            "reminders_enabled": True,
            "clarifications_enabled": True,
            "tariff_handoff_enabled": True,
            "compact_decision_protocol": 2,
            **changes,
        }
    )


def wire(kind: str, **fields: Any) -> dict[str, Any]:
    return {"decision": {"kind": kind, **fields}}


@pytest.mark.parametrize(
    ("upsell", "reminders", "clarifications", "tariff"),
    list(itertools.product((False, True), repeat=4)),
)
def test_nested_schema_is_strict_and_scope_bound_without_root_anyof(
    upsell: bool, reminders: bool, clarifications: bool, tariff: bool
) -> None:
    captured = scope(
        upsell_enabled=upsell,
        reminders_enabled=reminders,
        clarifications_enabled=clarifications,
        tariff_handoff_enabled=tariff,
    )
    schema = compact_manager_decision_schema(captured)
    assert_strict_schema(schema)
    assert schema["type"] == "object" and "anyOf" not in schema
    assert set(schema["properties"]) == {"decision"}
    assert schema["required"] == ["decision"]
    definitions = schema["$defs"]
    branches = schema["properties"]["decision"]["anyOf"]
    assert branches == [
        {"$ref": "#/$defs/_ReplyWire"},
        {"$ref": "#/$defs/_HandoffWire"},
        *([{"$ref": "#/$defs/_UpsellWire"}] if upsell else []),
    ]
    native_reply = definitions["_ReplyWire"]["properties"]
    original_reply = without_schema_titles(ParentTouchClarificationReply.model_json_schema())
    assert native_reply["body"]["type"] == "string"
    assert "anyOf" not in native_reply["body"]
    assert set(native_reply) == {"kind", "body", "question"}
    assert native_reply["body"]["maxLength"] == original_reply["properties"]["body"]["maxLength"]
    assert native_reply["body"]["pattern"] == original_reply["properties"]["body"]["pattern"]
    assert native_reply["question"] == (
        original_reply["properties"]["question"] if clarifications else {"type": "null"}
    )
    native_handoff = definitions["_HandoffWire"]["properties"]
    assert set(native_handoff) == {"kind"}
    assert native_handoff["kind"]["enum"] == (
        ["child_safety", "reminder"] if reminders else ["child_safety"]
    )
    if upsell:
        assert set(definitions["_UpsellWire"]["properties"]) == {"kind", "enquiry"}
    if upsell and tariff:
        assert definitions["UpsellEnquiry"] == without_schema_titles(
            UpsellEnquiry.model_json_schema()
        )
    else:
        assert "UpsellEnquiry" not in definitions
        if upsell:
            assert definitions["_UpsellWire"]["properties"]["enquiry"] == {"type": "null"}


@pytest.mark.parametrize(
    ("native", "canonical"),
    [
        (wire("reply", body="Здравствуйте.", question=None), reply()),
        (
            wire("reply", body="", question="Android или iPhone?"),
            reply(body="", question="Android или iPhone?"),
        ),
        (wire("child_safety"), handoff("child_safety")),
        (wire("reminder"), handoff("reminder")),
        (wire("upsell", enquiry=None), handoff("upsell")),
        (wire("upsell", enquiry=enquiry()), handoff("upsell", enquiry=enquiry())),
        (
            wire("upsell", enquiry=enquiry(currency=None)),
            handoff("upsell", enquiry=enquiry(currency=None)),
        ),
    ],
)
def test_nested_wire_normalizes_to_the_same_existing_internal_decision(
    native: dict[str, Any], canonical: dict[str, Any]
) -> None:
    v2 = parse_compact_manager_decision(native, scope())
    v1 = parse_compact_manager_decision(canonical, scope(compact_decision_protocol=1))
    assert v2 == v1 and v2.model_dump(mode="json") == canonical


@pytest.mark.parametrize(
    "native",
    [
        wire("reply", body=None, question=None),
        wire("reply", body="Hello.", question=None, enquiry=None),
        wire("reply", body="Hello."),
        wire("reply", body="", question=None),
        wire("reply", body="Question?", question=None),
        wire("reply", body="parent_id is private", question=None),
        wire("reply", body="Hello.", question="First? Second?"),
        wire("child_safety", body=None),
        wire("child_safety", body="I already assessed this."),
        wire("child_safety", enquiry=None),
        wire("reminder", body=""),
        wire("reminder", question=None),
        wire("upsell"),
        wire("upsell", enquiry=None, body=None),
        wire("upsell", enquiry=enquiry(minimum_days=366, maximum_days=1)),
        wire("upsell", enquiry=enquiry(maximum_price_minor=True)),
        wire("upsell", enquiry=enquiry(currency="RUB")),
        wire("arbitrary_sql"),
        {"decision": {"kind": "child_safety"}, "execution_receipt": {"verified": True}},
        {"decision": None},
        [],
        None,
    ],
)
def test_branch_invalid_or_mixed_fields_are_rejected_before_normalization(native: object) -> None:
    with pytest.raises(ValidationError):
        parse_compact_manager_decision(native, scope())


def test_previous_flat_schema_gaps_are_not_advertised_by_v2_branches() -> None:
    old = compact_manager_decision_schema(scope(compact_decision_protocol=1))
    assert "reminder" in old["properties"]["kind"]["enum"]
    assert {"type": "null"} in old["properties"]["body"]["anyOf"]
    assert old["properties"]["body"]["anyOf"][0]["type"] == "string"
    new = compact_manager_decision_schema(scope())
    handoff_schema = new["$defs"]["_HandoffWire"]
    assert "body" not in handoff_schema["properties"]
    assert handoff_schema["additionalProperties"] is False
    assert new["$defs"]["_ReplyWire"]["properties"]["body"]["type"] == "string"
    for invalid in (wire("reminder", body=""), wire("reply", body=None, question=None)):
        with pytest.raises(ValidationError):
            parse_compact_manager_decision(invalid, scope())


@pytest.mark.parametrize("protocol", [None, 1])
def test_wire_versions_cannot_be_interchanged(protocol: int | None) -> None:
    with pytest.raises(ValidationError):
        parse_compact_manager_decision(handoff("child_safety"), scope())
    with pytest.raises(ValidationError):
        parse_compact_manager_decision(
            wire("child_safety"), scope(compact_decision_protocol=protocol)
        )


@pytest.mark.parametrize(
    ("native", "changes"),
    [
        (wire("reminder"), {"reminders_enabled": False}),
        (wire("upsell", enquiry=None), {"upsell_enabled": False}),
        (wire("upsell", enquiry=enquiry()), {"tariff_handoff_enabled": False}),
        (wire("reply", body="", question="Android?"), {"clarifications_enabled": False}),
    ],
)
def test_nested_wire_cannot_acquire_an_uncaptured_owner_or_slot(
    native: object, changes: dict[str, Any]
) -> None:
    with pytest.raises(ValueError):
        parse_compact_manager_decision(native, scope(**changes))


@pytest.mark.parametrize("optional", [False, True])
def test_v1_schema_tools_and_instructions_keep_original_exact_fingerprints(optional: bool) -> None:
    captured = scope(
        compact_decision_protocol=1,
        upsell_enabled=optional,
        reminders_enabled=optional,
        clarifications_enabled=optional,
        tariff_handoff_enabled=optional,
    )
    expected = (
        (
            "23a988e9c28ad2e3bd7234916968f6ddc4bd53eac64fa97e93a5dc9339caff8a",
            "dbec6c158959c69797da65d7a92764ae139fb53fcc335976d2f3eeff73692ecb",
            "5725d05d21b7d8f34349d87029d6188cb87a52f6b5f2f3a9c89298dcb0c858fb",
        )
        if optional
        else (
            "24e69af420b4103e8479471696d8f17802509e9a9e875d2a97f0ab91ede23b8b",
            "d3b9cd3b283925182f87d18dd460900c4e987c1a1aace0c737ff48590f9dbd4b",
            "bb6f5533fc4536000f281c9cb2b9f044d22a1f71f7d66a285b07458999f118b6",
        )
    )
    instructions = compact_manager_decision_instructions(captured)
    assert instructions is not None
    values = [
        instructions,
        compact_manager_decision_schema(captured),
        compact_manager_decision_tools(captured),
    ]
    for value, fingerprint in zip(values, expected, strict=True):
        serialized = (
            value
            if isinstance(value, str)
            else json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        )
        assert hashlib.sha256(serialized.encode()).hexdigest() == fingerprint


@pytest.mark.parametrize("language", ["ru", "uz-Latn", "uz-Cyrl", "en"])
def test_new_instructions_change_only_wire_clauses_and_preserve_every_policy_rule(
    language: str,
) -> None:
    captured = scope(language=language, language_reference="Android")
    old = compact_manager_decision_instructions(
        captured.model_copy(update={"compact_decision_protocol": 1})
    )
    new = compact_manager_decision_instructions(captured)
    assert old and new
    assert 'with {"decision":{...}}' in new and "decision.kind: child_safety" in new
    assert "reply fields: kind,body,question" in new
    assert "child_safety/reminder fields: kind" in new
    assert "upsell fields: kind,enquiry" in new
    assert "unused fields null" not in new and "handoff body=question=null" not in new
    assert "reply enquiry=null" not in new
    assert new.split("upsell enquiry=null", 1)[1] == old.split("upsell enquiry=null", 1)[1].replace(
        "reply enquiry=null; body statements. ", "reply body statements. "
    )
    for preserved in (
        "Match response_language_reference's language/script; neutral labels use prior "
        "clear parent dialogue",
        "Invent no facts/diagnoses/prices/discounts/benefits/billing/actions/screens",
        "ask no secrets/payment data/other-family details",
        "No telemetry/controls/source-check claims",
        "child safety/health/parenting assessments or behaviour/activity/location/data analysis",
        "reminder for explicit creation/change",
        "reply for greetings/app help",
        "latest request only, parent_quote exact substring",
        "currency explicit UZS/USD else null",
        "never inferred from language/location/history/catalogue",
        "month30,year365,unspecified1..366",
        "explicit cheapest total=lowest_total or daily-price comparison=lowest_daily",
        "maximum_price_minor=explicit total amount*100, even unlabelled, else null",
        "No invented eligibility/renewal/checkout",
        "one essential intent/device clarification",
        "Clarify device before steps",
        "no repeating known answers/questions/steps or routine closing questions",
        "Questions grant no action/source permission or verified device/completion state",
    ):
        assert preserved in old and preserved in new


@pytest.mark.parametrize("stage", ["child_safety", "reminder", "upsell"])
def test_v2_does_not_create_a_route_on_specialist_or_publication_stage(stage: str) -> None:
    captured = scope(stage=stage)
    assert compact_manager_decision_instructions(captured) is None
    with pytest.raises(ValueError):
        compact_manager_decision_schema(captured)
    with pytest.raises(ValueError):
        parse_compact_manager_decision(wire("child_safety"), captured)
