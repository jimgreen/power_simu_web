"""Compact ordered-array encoding for realtime measurement frames."""

from __future__ import annotations

import copy
from typing import Any, Dict, Mapping, MutableMapping, Optional, Sequence


COMPACT_MEASUREMENT_ENCODING = "measurement-arrays-v1"
LEGACY_COMPACT_MEASUREMENT_ENCODING = "measurement-rows-v1"
LEGACY_COMPACT_MEASUREMENT_COLUMNS = (
    "name",
    "real_value",
    "scada_value",
    "valid",
    "weight",
    "flags",
)
FLAG_DELETED = 1
FLAG_REAL_PRESENT = 2
FLAG_SCADA_PRESENT = 4
_DEFINITION_SIGNATURE_FIELDS = ("name", "dev_type", "dev_name", "meas_type")


class MeasurementArrayMismatchError(RuntimeError):
    """Raised when a value frame cannot be aligned with local definitions."""


def measurement_definition_signature(definitions: Sequence[Mapping[str, Any]]) -> str:
    """Return a short stable checksum for measurement identity and order."""

    rows = list(definitions)
    checksum = 0x811C9DC5
    for row in rows:
        token = "\x1e".join(
            "" if row.get(field_name) is None else str(row.get(field_name, ""))
            for field_name in _DEFINITION_SIGNATURE_FIELDS
        ) + "\x1f"
        for value in token.encode("utf-8"):
            checksum ^= value
            checksum = (checksum * 0x01000193) & 0xFFFFFFFF
    return f"{len(rows)}:{checksum:08x}"


def measurement_row_index(row: Mapping[str, Any]) -> int:
    """Return the stable measurement sequence number stored in ``idx``."""

    try:
        return int(float(row.get("idx", -1)))
    except (TypeError, ValueError):
        return -1


def measurement_rows_by_definition_index(
    definitions: Sequence[Mapping[str, Any]],
    rows: Sequence[Mapping[str, Any]],
) -> list[Optional[Mapping[str, Any]]]:
    """Align runtime rows with definitions by measurement index, never by name."""

    definition_rows = list(definitions)
    aligned: list[Optional[Mapping[str, Any]]] = [None] * len(definition_rows)
    first_index = measurement_row_index(definition_rows[0]) if definition_rows else 0
    contiguous = first_index >= 0 and all(
        measurement_row_index(definition) == first_index + position
        for position, definition in enumerate(definition_rows)
    )
    positions = (
        None
        if contiguous
        else {
            measurement_row_index(definition): position
            for position, definition in enumerate(definition_rows)
            if measurement_row_index(definition) >= 0
        }
    )
    row_list = list(rows)
    positional_fallback = len(row_list) == len(definition_rows)
    for row_position, row in enumerate(row_list):
        if not isinstance(row, Mapping):
            continue
        index = measurement_row_index(row)
        if contiguous:
            position = index - first_index if first_index <= index < first_index + len(aligned) else None
        else:
            position = positions.get(index) if positions is not None and index >= 0 else None
        if position is None and positional_fallback:
            position = row_position
        if position is not None and 0 <= position < len(aligned):
            aligned[position] = row
    return aligned


def compact_measurement_delta(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Encode a complete ordered measurement frame without measurement names."""

    items = [
        item
        for item in payload.get("items", []) or []
        if isinstance(item, Mapping)
    ]
    frame = bool(payload.get("frame", bool(items) or payload.get("reset")))
    compact = {
        key: value
        for key, value in payload.items()
        if key
        not in {
            "items",
            "rows",
            "columns",
            "encoding",
            "time",
            "frame",
            "count",
            "real_values",
            "scada_values",
            "valid_values",
            "status_values",
            "fixed_values",
        }
    }
    compact.update(
        {
            "encoding": COMPACT_MEASUREMENT_ENCODING,
            "frame": frame,
            "count": int(payload.get("count", len(items)) or 0),
            "simu_time": payload.get("simu_time", payload.get("time", "--")),
            "wall_time": payload.get("wall_time", "--"),
            "real_values": [item.get("real_value") for item in items] if frame else [],
            "scada_values": [item.get("scada_value") for item in items] if frame else [],
            "valid_values": [item.get("valid") for item in items] if frame else [],
            "status_values": [item.get("status") for item in items] if frame else [],
            "fixed_values": [item.get("fixed_value") for item in items] if frame else [],
        }
    )
    return compact


def measurement_delta_items(payload: Mapping[str, Any]) -> list[Dict[str, Any]]:
    """Decode legacy name-bearing frames for backward-compatible callers."""

    encoding = str(payload.get("encoding", ""))
    if encoding == COMPACT_MEASUREMENT_ENCODING:
        return []
    if encoding != LEGACY_COMPACT_MEASUREMENT_ENCODING:
        return [
            copy.deepcopy(dict(item))
            for item in payload.get("items", []) or []
            if isinstance(item, Mapping)
        ]
    simu_time = payload.get("simu_time", payload.get("time", "--"))
    wall_time = payload.get("wall_time", "--")
    absolute_minute = payload.get("absolute_minute")
    items: list[Dict[str, Any]] = []
    for row in payload.get("rows", []) or []:
        if not isinstance(row, Sequence) or isinstance(row, (str, bytes)) or not row:
            continue
        values = list(row) + [None] * max(0, len(LEGACY_COMPACT_MEASUREMENT_COLUMNS) - len(row))
        name = str(values[0] or "")
        if not name:
            continue
        flags = int(values[5] or 0)
        item: Dict[str, Any] = {
            "name": name,
            "real_value": values[1] if flags & FLAG_REAL_PRESENT else None,
            "scada_value": values[2] if flags & FLAG_SCADA_PRESENT else None,
            "valid": values[3],
            "weight": values[4],
            "updated_simu_time": simu_time,
            "updated_wall_time": wall_time,
            "updated_absolute_minute": absolute_minute,
        }
        item["value"] = item["scada_value"] if item["scada_value"] is not None else item["real_value"]
        if flags & FLAG_DELETED:
            item["deleted"] = True
        items.append(item)
    return items


def _measurement_value_array(payload: Mapping[str, Any], key: str) -> list[Any]:
    values = payload.get(key)
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise MeasurementArrayMismatchError(
            f"实时量测数组长度不一致：{key} 不是数组"
        )
    return list(values)


def _apply_measurement_array_frame(
    measurements: Mapping[str, Any] | None,
    definitions: Sequence[Mapping[str, Any]],
    payload: Mapping[str, Any],
) -> Dict[str, Any]:
    definition_rows = list(definitions)
    if any(not isinstance(row, Mapping) for row in definition_rows):
        raise MeasurementArrayMismatchError("实时量测定义不完整，整帧数据已拒绝")
    try:
        count = int(payload.get("count"))
    except (TypeError, ValueError):
        raise MeasurementArrayMismatchError("实时量测数组长度不一致：count 无效") from None

    expected_signature = measurement_definition_signature(definition_rows)
    received_signature = str(payload.get("definition_signature", "") or "")
    if not received_signature:
        raise MeasurementArrayMismatchError("实时量测定义顺序签名缺失，整帧数据已拒绝")
    if received_signature != expected_signature:
        raise MeasurementArrayMismatchError(
            "实时量测定义顺序不一致，整帧数据已拒绝："
            f"接收={received_signature}，本地={expected_signature}"
        )

    real_values = _measurement_value_array(payload, "real_values")
    scada_values = _measurement_value_array(payload, "scada_values")
    valid_values = _measurement_value_array(payload, "valid_values")
    status_values = payload.get("status_values")
    fixed_values = payload.get("fixed_values")
    if status_values is None:
        status_values = [definition.get("status") for definition in definition_rows]
    else:
        status_values = _measurement_value_array(payload, "status_values")
    if fixed_values is None:
        fixed_values = [definition.get("fixed_value") for definition in definition_rows]
    else:
        fixed_values = _measurement_value_array(payload, "fixed_values")
    frame = payload.get("frame") is not False
    expected_value_count = count if frame else 0
    lengths = {
        "definitions": len(definition_rows),
        "real_values": len(real_values),
        "scada_values": len(scada_values),
        "valid_values": len(valid_values),
        "status_values": len(status_values),
        "fixed_values": len(fixed_values),
    }
    values_match = all(
        lengths[key] == expected_value_count
        for key in ("real_values", "scada_values", "valid_values", "status_values", "fixed_values")
    )
    if lengths["definitions"] != count or not values_match:
        detail = "，".join(f"{key}={value}" for key, value in lengths.items())
        raise MeasurementArrayMismatchError(
            f"实时量测数组长度不一致：count={count}，{detail}，整帧数据已拒绝"
        )
    if not frame:
        return dict(measurements or {})

    normalized_definitions = [dict(row) for row in definition_rows]
    merged: Dict[str, Any] = dict(measurements or {})
    simu_time = payload.get("simu_time", payload.get("time", "--"))
    wall_time = payload.get("wall_time", "--")
    absolute_minute = payload.get("absolute_minute")
    real_rows: list[Dict[str, Any]] = []
    scada_rows: list[Dict[str, Any]] = []
    for index, definition in enumerate(normalized_definitions):
        valid = valid_values[index]
        if valid is None:
            valid = definition.get("valid")
        status = status_values[index]
        if status is None:
            status = definition.get("status")
        fixed_value = fixed_values[index]
        if fixed_value is None:
            fixed_value = definition.get("fixed_value")
        for target, value in ((real_rows, real_values[index]), (scada_rows, scada_values[index])):
            row = dict(definition)
            row["value"] = value
            row["valid"] = valid
            row["status"] = status
            row["fixed_value"] = fixed_value
            row["updated_simu_time"] = simu_time
            row["updated_wall_time"] = wall_time
            row["updated_absolute_minute"] = absolute_minute
            target.append(row)

    merged["definitions"] = normalized_definitions
    merged["real"] = real_rows
    merged["scada"] = scada_rows
    merged["definition_signature"] = expected_signature
    if payload.get("definition_revision") is not None:
        merged["definition_revision"] = payload.get("definition_revision")
    return merged


def apply_measurement_delta(
    measurements: Mapping[str, Any] | None,
    definitions: Sequence[Mapping[str, Any]],
    payload: Mapping[str, Any],
) -> Dict[str, Any]:
    """Apply one measurement response without ever partially mutating the input."""

    if str(payload.get("encoding", "")) == COMPACT_MEASUREMENT_ENCODING:
        return _apply_measurement_array_frame(measurements, definitions, payload)

    merged: Dict[str, Any] = copy.deepcopy(dict(measurements or {}))
    definition_rows = [copy.deepcopy(dict(row)) for row in definitions if isinstance(row, Mapping)]
    if not merged.get("definitions"):
        merged["definitions"] = definition_rows
    definitions_by_name = {
        str(row.get("name", "")): row
        for row in (merged.get("definitions") or definition_rows)
        if isinstance(row, Mapping) and str(row.get("name", ""))
    }
    if payload.get("reset"):
        real_by_name: MutableMapping[str, Dict[str, Any]] = {}
        scada_by_name: MutableMapping[str, Dict[str, Any]] = {}
    else:
        real_by_name = {
            str(row.get("name", "")): copy.deepcopy(dict(row))
            for row in merged.get("real", []) or []
            if isinstance(row, Mapping) and str(row.get("name", ""))
        }
        scada_by_name = {
            str(row.get("name", "")): copy.deepcopy(dict(row))
            for row in merged.get("scada", []) or []
            if isinstance(row, Mapping) and str(row.get("name", ""))
        }

    for item in measurement_delta_items(payload):
        name = str(item.get("name", ""))
        if not name:
            continue
        if item.get("deleted"):
            real_by_name.pop(name, None)
            scada_by_name.pop(name, None)
            continue
        definition = definitions_by_name.get(name)
        for value_key, target in (
            ("real_value", real_by_name),
            ("scada_value", scada_by_name),
        ):
            value = item.get(value_key)
            if value is None:
                continue
            row = target.get(name)
            if row is None:
                if definition is None:
                    continue
                row = copy.deepcopy(definition)
                target[name] = row
            row["value"] = value
            if item.get("valid") is not None:
                row["valid"] = item.get("valid")
            if item.get("weight") is not None:
                row["weight"] = item.get("weight")
            if item.get("status") is not None:
                row["status"] = item.get("status")
            if "fixed_value" in item:
                row["fixed_value"] = item.get("fixed_value")
            row["updated_simu_time"] = item.get("updated_simu_time")
            row["updated_wall_time"] = item.get("updated_wall_time")
            row["updated_absolute_minute"] = item.get("updated_absolute_minute")

    merged["real"] = list(real_by_name.values())
    merged["scada"] = list(scada_by_name.values())
    return merged
