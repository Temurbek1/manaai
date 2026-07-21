from pydantic import JsonValue


def json_str(value: JsonValue | None) -> str | None:
    return str(value) if value is not None else None


def nested_id(value: JsonValue | None) -> str | None:
    if isinstance(value, dict):
        nested = value.get("id")
        return str(nested) if nested is not None else None
    return None


def nested_name(value: JsonValue | None) -> str | None:
    if isinstance(value, dict):
        name = value.get("name")
        return str(name) if name is not None else None
    return None
