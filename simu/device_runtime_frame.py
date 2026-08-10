"""Compact ordered-array encoding for device runtime state."""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Dict, Mapping, Sequence, Tuple


COMPACT_DEVICE_RUNTIME_ENCODING = "device-runtime-arrays-v1"
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
    canonical = json.dumps(
        {field: payload.get(field) for field in _RUNTIME_SIGNATURE_FIELDS},
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


def apply_device_runtime_frame(
    devices: Sequence[Mapping[str, Any]],
    device_states: Sequence[Mapping[str, Any]],
    payload: Mapping[str, Any],
) -> tuple[list[Dict[str, Any]], list[Dict[str, Any]]]:
    """Validate and atomically apply one compact runtime frame."""

    if str(payload.get("encoding", "")) != COMPACT_DEVICE_RUNTIME_ENCODING:
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

    device_run_stats = _validated_array(payload, "device_run_stats", len(ordered_devices))
    device_statuses = _validated_array(payload, "device_statuses", len(ordered_devices))
    device_modes = _validated_array(payload, "device_modes", len(ordered_devices))
    device_set_values = _validated_array(payload, "device_set_values", len(ordered_devices))
    device_soc_present = _validated_array(payload, "device_soc_present", len(ordered_devices))
    device_soc_values = _validated_array(payload, "device_soc_values", len(ordered_devices))
    state_run_stats = _validated_array(payload, "state_run_stats", len(ordered_states))
    state_dead_islands = _validated_array(payload, "state_dead_islands", len(ordered_states))
    expected_runtime_signature = device_runtime_payload_signature(payload)
    if str(payload.get("runtime_signature", "")) != expected_runtime_signature:
        raise DeviceRuntimeFrameMismatchError(
            "runtime signature mismatch: "
            f"expected {expected_runtime_signature}, received {payload.get('runtime_signature', '')}"
        )

    for index, row in enumerate(ordered_devices):
        row["run_stat"] = device_run_stats[index]
        row["status"] = device_statuses[index]
        row["mode"] = device_modes[index]
        row["set_values"] = copy.deepcopy(device_set_values[index])
        if bool(device_soc_present[index]):
            row["soc_curr"] = device_soc_values[index]

    for index, row in enumerate(ordered_states):
        row["run_stat"] = state_run_stats[index]
        row["dead_island"] = bool(state_dead_islands[index])

    return decoded_devices, decoded_states
