from dataclasses import dataclass
from typing import Literal

from pydantic import JsonValue

from app.services.marketing_payload import nested_id, nested_name

TargetingAudienceRole = Literal["included", "excluded"]


@dataclass(frozen=True)
class TargetingAudience:
    id: str
    name: str | None
    role: TargetingAudienceRole


def targeting_custom_audiences(
    targeting: dict[str, JsonValue],
    *,
    roles: set[TargetingAudienceRole] | None = None,
) -> list[TargetingAudience]:
    selected_roles = roles or {"included", "excluded"}
    audiences: list[TargetingAudience] = []

    role_fields: list[tuple[TargetingAudienceRole, str]] = [
        ("included", "custom_audiences"),
        ("excluded", "excluded_custom_audiences"),
    ]
    for role, field_name in role_fields:
        if role not in selected_roles:
            continue
        value = targeting.get(field_name)
        if not isinstance(value, list):
            continue
        audiences.extend(
            TargetingAudience(id=audience_id, name=nested_name(item), role=role)
            for item in value
            if isinstance(item, dict)
            if (audience_id := nested_id(item)) is not None
        )

    return audiences
