"""Compact ordered-array encoding for device runtime state."""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Dict, Mapping, MutableMapping, Sequence, Tuple


COMPACT_DEVICE_RUNTIME_ENCODING = "device-runtime-arrays-v1"
COMPACT_DEVICE_RUNTIME_SUPPLEMENT_ENCODING = "device-runtime-supplement-arrays-v1"
_RUNTIME_SIGNATURE_FIELDS = (
    "encoding",
    "definition_revision",
    "device_count",
    "device_signature",
    "device_run_stats",
    "device_statuses",
    "device_modes",
    "device_set_values",
    "device_soc_present",
    "device_soc_values",
    "state_count",
    "state_signature",
    "state_run_stats",
    "state_dead_islands",
)
_SUPPLEMENT_SIGNATURE_FIELDS = (
    "encoding",
    "definition_revision",
    "device_count",
    "device_signature",
    "device_modes",
    "device_set_values",
    "device_run_stat_indices",
    "device_run_stat_values",
    "device_status_indices",
    "device_status_values",
    "device_soc_indices",
    "device_soc_values",
    "state_count",
    "state_signature",
    "state_run_stat_indices",
    "state_run_stat_values",
    "state_dead_islands",
)


class DeviceRuntimeFrameMismatchError(RuntimeError):
    """Raised when a runtime frame cannot align with local device definitions."""


def _device_key(row: Mapping[str, Any]) -> Tuple[str, str]:
    return (
        str(row.get("dev_type", "")).strip(),
        str(row.get("dev_name", row.get("name", ""))).strip(),
    )


def _ordered_rows(rows: Sequence[Mapping[str, Any]], label: str) -> list[Mapping[str, Any]]:
    normalized = [row for row in rows if isinstance(row, Mapping)]
    ordered = sorted(normalized, key=_device_key)
    keys = [_device_key(row) for row in ordered]
    if any(not dev_type or not dev_name for dev_type, dev_name in keys):
        raise DeviceRuntimeFrameMismatchError(f"{label} contains an empty device identity")
    if len(set(keys)) != len(keys):
        raise DeviceRuntimeFrameMismatchError(f"{label} contains duplicate device identities")
    return ordered


def _ordered_signature(ordered: Sequence[Mapping[str, Any]]) -> str:
    checksum = 0x811C9DC5
    for row in ordered:
        token = "\x1e".join(_device_key(row)) + "\x1f"
        for value in token.encode("utf-8"):
            checksum ^= value
            checksum = (checksum * 0x01000193) & 0xFFFFFFFF
    return f"{len(ordered)}:{checksum:08x}"


def device_order_signature(rows: Sequence[Mapping[str, Any]], label: str = "devices") -> str:
    """Return a stable checksum for canonical device identity and order."""

    return _ordered_signature(_ordered_rows(rows, label))


def device_runtime_payload_signature(payload: Mapping[str, Any]) -> str:
    signature_fields = (
        _SUPPLEMENT_SIGNATURE_FIELDS
        if str(payload.get("encoding", "")) == COMPACT_DEVICE_RUNTIME_SUPPLEMENT_ENCODING
        else _RUNTIME_SIGNATURE_FIELDS
    )
    canonical = json.dumps(
        {field: payload.get(field) for field in signature_fields},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compact_device_runtime_frame(
    devices: Sequence[Mapping[str, Any]],
    device_states: Sequence[Mapping[str, Any]],
    *,
    definition_revision: int = 0,
) -> Dict[str, Any]:
    ordered_devices = _ordered_rows(devices, "devices")
    ordered_states = _ordered_rows(device_states, "device_states")
    frame = {
        "encoding": COMPACT_DEVICE_RUNTIME_ENCODING,
        "definition_revision": int(definition_revision),
        "device_count": len(ordered_devices),
        "device_signature": _ordered_signature(ordered_devices),
        "device_run_stats": [row.get("run_stat") for row in ordered_devices],
        "device_statuses": [row.get("status") for row in ordered_devices],
        "device_modes": [row.get("mode") for row in ordered_devices],
        "device_set_values": [copy.deepcopy(row.get("set_values", {})) for row in ordered_devices],
        "device_soc_present": ["soc_curr" in row for row in ordered_devices],
        "device_soc_values": [row.get("soc_curr") for row in ordered_devices],
        "state_count": len(ordered_states),
        "state_signature": _ordered_signature(ordered_states),
        "state_run_stats": [row.get("run_stat") for row in ordered_states],
        "state_dead_islands": [bool(row.get("dead_island", False)) for row in ordered_states],
    }
    frame["runtime_signature"] = device_runtime_payload_signature(frame)
    return frame


def _measurement_identity(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("runtime_dev_type", row.get("dev_type", ""))).strip(),
        str(
            row.get(
                "runtime_dev_name",
                row.get("dev_name", row.get("name", "")),
            )
        ).strip(),
        str(row.get("meas_type", "")).strip().upper(),
    )


def _residual_runtime_values(
    ordered: Sequence[Mapping[str, Any]],
    measurement_keys: set[tuple[str, str, str]],
    measurement_type: str,
    field_name: str,
    *,
    require_field: bool = False,
) -> tuple[list[int], list[Any]]:
    indices: list[int] = []
    values: list[Any] = []
    for index, row in enumerate(ordered):
        if (*_device_key(row), measurement_type) in measurement_keys:
            continue
        if require_field and field_name not in row:
            continue
        indices.append(index)
        values.append(copy.deepcopy(row.get(field_name)))
    return indices, values


def compact_device_runtime_supplement_frame(
    devices: Sequence[Mapping[str, Any]],
    device_states: Sequence[Mapping[str, Any]],
    measurement_definitions: Sequence[Mapping[str, Any]],
    *,
    definition_revision: int = 0,
) -> Dict[str, Any]:
    """Encode only runtime fields that are not already carried by SCADA points."""

    ordered_devices = _ordered_rows(devices, "devices")
    ordered_states = _ordered_rows(device_states, "device_states")
    measurement_keys = {
        _measurement_identity(row)
        for row in measurement_definitions
        if isinstance(row, Mapping)
    }
    device_run_indices, device_run_values = _residual_runtime_values(
        ordered_devices,
        measurement_keys,
        "RUN_STAT",
        "run_stat",
    )
    device_status_indices, device_status_values = _residual_runtime_values(
        ordered_devices,
        measurement_keys,
        "STATUS",
        "status",
    )
    device_soc_indices, device_soc_values = _residual_runtime_values(
        ordered_devices,
        measurement_keys,
        "SOC",
        "soc_curr",
        require_field=True,
    )
    state_run_indices, state_run_values = _residual_runtime_values(
        ordered_states,
        measurement_keys,
        "RUN_STAT",
        "run_stat",
    )
    frame = {
        "encoding": COMPACT_DEVICE_RUNTIME_SUPPLEMENT_ENCODING,
        "definition_revision": int(definition_revision),
        "device_count": len(ordered_devices),
        "device_signature": _ordered_signature(ordered_devices),
        "device_modes": [row.get("mode") for row in ordered_devices],
        "device_set_values": [copy.deepcopy(row.get("set_values", {})) for row in ordered_devices],
        "device_run_stat_indices": device_run_indices,
        "device_run_stat_values": device_run_values,
        "device_status_indices": device_status_indices,
        "device_status_values": device_status_values,
        "device_soc_indices": device_soc_indices,
        "device_soc_values": device_soc_values,
        "state_count": len(ordered_states),
        "state_signature": _ordered_signature(ordered_states),
        "state_run_stat_indices": state_run_indices,
        "state_run_stat_values": state_run_values,
        "state_dead_islands": [bool(row.get("dead_island", False)) for row in ordered_states],
    }
    frame["runtime_signature"] = device_runtime_payload_signature(frame)
    return frame


def _validated_array(payload: Mapping[str, Any], name: str, count: int) -> list[Any]:
    values = payload.get(name)
    if not isinstance(values, list) or len(values) != count:
        actual = len(values) if isinstance(values, list) else -1
        raise DeviceRuntimeFrameMismatchError(
            f"{name} length mismatch: expected {count}, received {actual}"
        )
    return values


def _validated_count(payload: Mapping[str, Any], name: str, expected: int) -> None:
    try:
        actual = int(payload.get(name, -1))
    except (TypeError, ValueError):
        actual = -1
    if actual != expected:
        raise DeviceRuntimeFrameMismatchError(
            f"{name} mismatch: expected {expected}, received {actual}"
        )


def _validated_sparse_values(
    payload: Mapping[str, Any],
    prefix: str,
    count: int,
) -> list[tuple[int, Any]]:
    raw_indices = payload.get(f"{prefix}_indices")
    raw_values = payload.get(f"{prefix}_values")
    if not isinstance(raw_indices, list) or not isinstance(raw_values, list):
        raise DeviceRuntimeFrameMismatchError(f"{prefix} sparse payload is not an array")
    if len(raw_indices) != len(raw_values):
        raise DeviceRuntimeFrameMismatchError(
            f"{prefix} sparse length mismatch: indices={len(raw_indices)}, values={len(raw_values)}"
        )
    result: list[tuple[int, Any]] = []
    previous = -1
    for raw_index, value in zip(raw_indices, raw_values):
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            raise DeviceRuntimeFrameMismatchError(f"{prefix} contains an invalid index") from None
        if index < 0 or index >= count or index <= previous:
            raise DeviceRuntimeFrameMismatchError(
                f"{prefix} indices must be unique, ordered, and inside [0, {count})"
            )
        previous = index
        result.append((index, value))
    return result


def _clear_measurement_backed_runtime_fields(
    ordered_devices: Sequence[MutableMapping[str, Any]],
    ordered_states: Sequence[MutableMapping[str, Any]],
    measurement_definitions: Sequence[Mapping[str, Any]],
) -> None:
    measurement_keys = {
        _measurement_identity(row)
        for row in measurement_definitions
        if isinstance(row, Mapping)
    }
    for row in ordered_devices:
        identity = _device_key(row)
        for measurement_type, field_name in (
            ("RUN_STAT", "run_stat"),
            ("STATUS", "status"),
            ("SOC", "soc_curr"),
        ):
            if (*identity, measurement_type) in measurement_keys:
                row.pop(field_name, None)
    for row in ordered_states:
        if (*_device_key(row), "RUN_STAT") in measurement_keys:
            row.pop("run_stat", None)


def apply_device_runtime_frame(
    devices: Sequence[Mapping[str, Any]],
    device_states: Sequence[Mapping[str, Any]],
    payload: Mapping[str, Any],
    *,
    measurement_definitions: Sequence[Mapping[str, Any]] = (),
) -> tuple[list[Dict[str, Any]], list[Dict[str, Any]]]:
    """Validate and atomically apply one compact runtime frame."""

    encoding = str(payload.get("encoding", ""))
    if encoding not in {
        COMPACT_DEVICE_RUNTIME_ENCODING,
        COMPACT_DEVICE_RUNTIME_SUPPLEMENT_ENCODING,
    }:
        raise DeviceRuntimeFrameMismatchError("unsupported device runtime frame encoding")

    decoded_devices = [copy.deepcopy(dict(row)) for row in devices if isinstance(row, Mapping)]
    decoded_states = [copy.deepcopy(dict(row)) for row in device_states if isinstance(row, Mapping)]
    ordered_devices = _ordered_rows(decoded_devices, "devices")
    ordered_states = _ordered_rows(decoded_states, "device_states")

    _validated_count(payload, "device_count", len(ordered_devices))
    _validated_count(payload, "state_count", len(ordered_states))
    expected_device_signature = _ordered_signature(ordered_devices)
    expected_state_signature = _ordered_signature(ordered_states)
    if str(payload.get("device_signature", "")) != expected_device_signature:
        raise DeviceRuntimeFrameMismatchError(
            "device signature mismatch: "
            f"expected {expected_device_signature}, received {payload.get('device_signature', '')}"
        )
    if str(payload.get("state_signature", "")) != expected_state_signature:
        raise DeviceRuntimeFrameMismatchError(
            "device state signature mismatch: "
            f"expected {expected_state_signature}, received {payload.get('state_signature', '')}"
        )

    device_modes = _validated_array(payload, "device_modes", len(ordered_devices))
    device_set_values = _validated_array(payload, "device_set_values", len(ordered_devices))
    state_dead_islands = _validated_array(payload, "state_dead_islands", len(ordered_states))
    if encoding == COMPACT_DEVICE_RUNTIME_ENCODING:
        device_run_stats = _validated_array(payload, "device_run_stats", len(ordered_devices))
        device_statuses = _validated_array(payload, "device_statuses", len(ordered_devices))
        device_soc_present = _validated_array(payload, "device_soc_present", len(ordered_devices))
        device_soc_values = _validated_array(payload, "device_soc_values", len(ordered_devices))
        state_run_stats = _validated_array(payload, "state_run_stats", len(ordered_states))
        device_run_sparse: list[tuple[int, Any]] = []
        device_status_sparse: list[tuple[int, Any]] = []
        device_soc_sparse: list[tuple[int, Any]] = []
        state_run_sparse: list[tuple[int, Any]] = []
    else:
        device_run_stats = []
        device_statuses = []
        device_soc_present = []
        device_soc_values = []
        state_run_stats = []
        device_run_sparse = _validated_sparse_values(
            payload, "device_run_stat", len(ordered_devices)
        )
        device_status_sparse = _validated_sparse_values(
            payload, "device_status", len(ordered_devices)
        )
        device_soc_sparse = _validated_sparse_values(
            payload, "device_soc", len(ordered_devices)
        )
        state_run_sparse = _validated_sparse_values(
            payload, "state_run_stat", len(ordered_states)
        )
    expected_runtime_signature = device_runtime_payload_signature(payload)
    if str(payload.get("runtime_signature", "")) != expected_runtime_signature:
        raise DeviceRuntimeFrameMismatchError(
            "runtime signature mismatch: "
            f"expected {expected_runtime_signature}, received {payload.get('runtime_signature', '')}"
        )

    if encoding == COMPACT_DEVICE_RUNTIME_SUPPLEMENT_ENCODING:
        _clear_measurement_backed_runtime_fields(
            ordered_devices,
            ordered_states,
            measurement_definitions,
        )

    for index, row in enumerate(ordered_devices):
        if encoding == COMPACT_DEVICE_RUNTIME_ENCODING:
            row["run_stat"] = device_run_stats[index]
            row["status"] = device_statuses[index]
        row["mode"] = device_modes[index]
        row["set_values"] = copy.deepcopy(device_set_values[index])
        if encoding == COMPACT_DEVICE_RUNTIME_ENCODING and bool(device_soc_present[index]):
            row["soc_curr"] = device_soc_values[index]

    for index, value in device_run_sparse:
        ordered_devices[index]["run_stat"] = value
    for index, value in device_status_sparse:
        ordered_devices[index]["status"] = value
    for index, value in device_soc_sparse:
        ordered_devices[index]["soc_curr"] = value

    for index, row in enumerate(ordered_states):
        if encoding == COMPACT_DEVICE_RUNTIME_ENCODING:
            row["run_stat"] = state_run_stats[index]
        row["dead_island"] = bool(state_dead_islands[index])

    for index, value in state_run_sparse:
        ordered_states[index]["run_stat"] = value

    return decoded_devices, decoded_states
