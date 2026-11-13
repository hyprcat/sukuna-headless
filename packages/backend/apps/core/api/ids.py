from __future__ import annotations

from strawberry import relay

from apps.core.exceptions import InvalidInput


def parse_int_id(
    value: object,
    *,
    expected_type: str | None = None,
    field: str = "id",
) -> int:
    raw = str(value)
    if raw.isdecimal():
        return int(raw)
    global_id = _global_id_or_raise(raw, field)
    if expected_type is not None and global_id.type_name != expected_type:
        raise InvalidInput("Invalid ID.", field=field)
    node_id = str(global_id.node_id)
    if not node_id.isdecimal():
        raise InvalidInput("Invalid ID.", field=field)
    return int(node_id)


def parse_int_ids(
    values: list[object] | None,
    *,
    expected_type: str,
    field: str,
) -> list[int]:
    return [parse_int_id(value, expected_type=expected_type, field=field) for value in values or []]


def _global_id_or_raise(raw: str, field: str) -> relay.GlobalID:
    try:
        return relay.GlobalID.from_id(raw)
    except ValueError:
        raise InvalidInput("Invalid ID.", field=field) from None
