"""Trainee-facing realtime-data projection.

The trainee boundary carries SCADA measurements and current runtime state only.
Simulation truth, remote logs, alarm details, and remote history remain inside
the simulator process and are removed before a trainee connection can consume
or expose them.
"""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping, Sequence
from typing import Any


FLAG_REAL_PRESENT = 2

INTERSTATION_SNAPSHOT_FIELDS = (
    "clock",
    "measurement_clock",
    "compute",
    "commands",
    "command_signature",
    "measurement_delta",
    "device_runtime_signature",
    "device_runtime",
)

INTERSTATION_COMPUTE_FIELDS = (
    "status",
    "simu_time",
    "absolute_minute",
    "measurement_frame_stale",
    "last_successful_simu_time",
    "result_discarded",
)

NON_REALTIME_SNAPSHOT_FIELDS = (
    "runtime_logs",
    "runtime_logs_delta",
    "measurement_history",
    "command_history",
    "alarm_history",
    "warning_history",
    "alarms",
    "alarm_details",
    "warnings",
    "warning_details",
)

DIAGNOSTIC_DETAIL_FIELDS = (
    "error",
    "errors",
    "detail",
    "details",
    "exception",
    "stack",
    "stacktrace",
    "traceback",
)


def strip_trainee_truth_from_measurements(measurements: Any) -> Any:
    if not isinstance(measurements, Mapping):
        return measurements
    projected = dict(measurements)
    projected.pop("real", None)
    projected["value_channels"] = ["scada"]
    return projected


def strip_trainee_truth_from_measurement_delta(payload: Any) -> Any:
    if not isinstance(payload, Mapping):
        return payload
    projected = dict(payload)
    projected.pop("real_values", None)
    projected["value_channels"] = ["scada"]

    items = projected.get("items")
    if isinstance(items, Sequence) and not isinstance(items, (str, bytes, bytearray)):
        projected_items = []
        for raw_item in items:
            if not isinstance(raw_item, Mapping):
                projected_items.append(raw_item)
                continue
            item = dict(raw_item)
            item.pop("real_value", None)
            item["value"] = item.get("scada_value")
            projected_items.append(item)
        projected["items"] = projected_items

    rows = projected.get("rows")
    if isinstance(rows, Sequence) and not isinstance(rows, (str, bytes, bytearray)):
        projected_rows = []
        for raw_row in rows:
            if not isinstance(raw_row, Sequence) or isinstance(raw_row, (str, bytes, bytearray)):
                projected_rows.append(raw_row)
                continue
            row = list(raw_row)
            if len(row) > 1:
                row[1] = None
            if len(row) > 5:
                try:
                    row[5] = int(row[5] or 0) & ~FLAG_REAL_PRESENT
                except (TypeError, ValueError):
                    row[5] = 0
            projected_rows.append(row)
        projected["rows"] = projected_rows
    return projected


def strip_trainee_truth_from_measurement_history(payload: Any) -> Any:
    if not isinstance(payload, Mapping):
        return payload
    projected = dict(payload)
    projected.pop("real_values", None)
    projected["value_channels"] = ["scada"]
    frames = projected.get("frames")
    if isinstance(frames, Sequence) and not isinstance(frames, (str, bytes, bytearray)):
        projected_frames = []
        for raw_frame in frames:
            if not isinstance(raw_frame, Mapping):
                projected_frames.append(raw_frame)
                continue
            frame = dict(raw_frame)
            frame.pop("real_values", None)
            projected_frames.append(frame)
        projected["frames"] = projected_frames
    return projected


def strip_trainee_truth_from_snapshot(snapshot: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    if "measurements" in snapshot:
        snapshot["measurements"] = strip_trainee_truth_from_measurements(
            snapshot.get("measurements")
        )
    if "measurement_delta" in snapshot:
        snapshot["measurement_delta"] = strip_trainee_truth_from_measurement_delta(
            snapshot.get("measurement_delta")
        )
    if "measurement_history" in snapshot:
        snapshot["measurement_history"] = strip_trainee_truth_from_measurement_history(
            snapshot.get("measurement_history")
        )
    return snapshot


def strip_trainee_remote_details_from_snapshot(
    snapshot: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    """Keep local diagnostics local while projecting a simulator-to-trainee frame."""

    strip_trainee_truth_from_snapshot(snapshot)
    for field_name in NON_REALTIME_SNAPSHOT_FIELDS:
        snapshot.pop(field_name, None)

    commands = snapshot.get("commands")
    if isinstance(commands, Mapping):
        current_commands = dict(commands)
        current_commands.pop("history", None)
        snapshot["commands"] = current_commands

    for field_name in ("compute", "result"):
        payload = snapshot.get(field_name)
        if not isinstance(payload, Mapping):
            continue
        current = dict(payload)
        for detail_field in DIAGNOSTIC_DETAIL_FIELDS:
            current.pop(detail_field, None)
        snapshot[field_name] = current
    return snapshot


def project_trainee_interstation_snapshot(
    snapshot: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    """Reduce one simulator-to-trainee poll to transport-essential runtime fields."""

    strip_trainee_remote_details_from_snapshot(snapshot)
    compute = snapshot.get("compute")
    if isinstance(compute, Mapping):
        snapshot["compute"] = {
            field_name: compute.get(field_name)
            for field_name in INTERSTATION_COMPUTE_FIELDS
            if field_name in compute
        }
    delta = snapshot.get("measurement_delta")
    if isinstance(delta, Mapping):
        compact_delta = dict(delta)
        for redundant_field in ("model_id", "model_name", "measurement_clock"):
            compact_delta.pop(redundant_field, None)
        snapshot["measurement_delta"] = compact_delta
    allowed = set(INTERSTATION_SNAPSHOT_FIELDS)
    for field_name in tuple(snapshot):
        if field_name not in allowed:
            snapshot.pop(field_name, None)
    return snapshot
