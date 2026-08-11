"""Trainee-facing measurement projection.

The trainee boundary carries SCADA measurements only. Simulation truth remains
inside the simulator process and is removed from snapshots, deltas, and history
before a trainee connection can consume or expose it.
"""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping, Sequence
from typing import Any


FLAG_REAL_PRESENT = 2


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
