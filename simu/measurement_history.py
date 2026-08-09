"""Compact backend history for ordered realtime measurement frames."""

from __future__ import annotations

import math
import threading
import time
from array import array
from datetime import datetime
from typing import Any, Dict, Mapping, Optional, Sequence

from .measurement_delta import (
    measurement_definition_signature,
    measurement_rows_by_definition_index,
)


MEASUREMENT_HISTORY_ENCODING = "measurement-history-arrays-v1"
_MISSING_NUMBER = float("nan")
_MISSING_VALID = 255


def _number_or_nan(value: Any) -> float:
    if value is None or value == "":
        return _MISSING_NUMBER
    try:
        number = float(value)
    except (TypeError, ValueError):
        return _MISSING_NUMBER
    return number if math.isfinite(number) else _MISSING_NUMBER


def _number_or_none(value: float) -> Optional[float]:
    return None if math.isnan(value) else value


def _int_value(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _float_value(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


class MeasurementHistoryStore:
    """Store one model's current-run history in compact flat numeric arrays.

    Measurement identity is never repeated in a frame. Values are aligned to the
    current definition order and queried by positional index. The flat arrays
    avoid retaining one Python object per value, which is important for models
    with hundreds of points and long-running simulations.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._definition_signature = ""
        self._definition_count = 0
        self._definition_revision = 0
        self._run_id: Optional[int] = None
        self._next_seq = 0
        self._frames: list[Dict[str, Any]] = []
        self._real_values = array("d")
        self._scada_values = array("d")
        self._valid_values = bytearray()

    def _clear_unlocked(self, *, preserve_definition: bool) -> None:
        signature = self._definition_signature if preserve_definition else ""
        count = self._definition_count if preserve_definition else 0
        revision = self._definition_revision if preserve_definition else 0
        self._definition_signature = signature
        self._definition_count = count
        self._definition_revision = revision
        self._run_id = None
        self._next_seq = 0
        self._frames = []
        self._real_values = array("d")
        self._scada_values = array("d")
        self._valid_values = bytearray()

    def clear(self, *, preserve_definition: bool = True) -> None:
        with self._lock:
            self._clear_unlocked(preserve_definition=preserve_definition)

    def ensure_definition(
        self,
        definitions: Sequence[Mapping[str, Any]],
        *,
        definition_revision: int = 0,
    ) -> str:
        normalized = [row for row in definitions if isinstance(row, Mapping)]
        signature = measurement_definition_signature(normalized)
        with self._lock:
            if self._definition_signature and self._definition_signature != signature:
                self._clear_unlocked(preserve_definition=False)
            self._definition_signature = signature
            self._definition_count = len(normalized)
            self._definition_revision = int(definition_revision or 0)
        return signature

    def append(
        self,
        clock: Mapping[str, Any],
        measurements: Mapping[str, Any],
        *,
        definition_revision: int = 0,
        limit: int = 45000,
        wall_time: Optional[str] = None,
    ) -> bool:
        definitions = [
            row
            for row in measurements.get("definitions", []) or []
            if isinstance(row, Mapping)
        ]
        signature = measurement_definition_signature(definitions)
        count = len(definitions)
        if count <= 0:
            return False

        real_rows = measurement_rows_by_definition_index(
            definitions,
            measurements.get("real", []) or [],
        )
        scada_rows = measurement_rows_by_definition_index(
            definitions,
            measurements.get("scada", []) or [],
        )
        real_values = array(
            "d",
            (
                _number_or_nan(row.get("value") if row is not None else None)
                for row in real_rows
            ),
        )
        scada_values = array(
            "d",
            (
                _number_or_nan(row.get("value") if row is not None else None)
                for row in scada_rows
            ),
        )
        valid_values = bytearray()
        for position, definition in enumerate(definitions):
            row = scada_rows[position] or real_rows[position] or definition
            valid = row.get("valid", definition.get("valid"))
            if valid is None or valid == "":
                valid_values.append(_MISSING_VALID)
            else:
                valid_values.append(1 if _int_value(valid, 0) == 1 else 0)

        run_id = _int_value(clock.get("run_id"), 0)
        step_count = _int_value(clock.get("step_count"), 0)
        absolute_minute = _float_value(
            clock.get("absolute_minute", clock.get("minute")),
            0.0,
        )
        frame_wall_time = str(
            wall_time
            or clock.get("wall_time")
            or datetime.fromtimestamp(time.time()).isoformat(timespec="seconds")
        )

        with self._lock:
            definition_changed = bool(
                self._definition_signature
                and self._definition_signature != signature
            )
            previous = self._frames[-1] if self._frames else None
            lifecycle_changed = bool(
                self._run_id is not None
                and (
                    run_id != self._run_id
                    or (
                        previous is not None
                        and (
                            step_count < int(previous["step_count"])
                            or absolute_minute < float(previous["absolute_minute"]) - 1e-9
                        )
                    )
                )
            )
            if definition_changed or lifecycle_changed:
                self._clear_unlocked(preserve_definition=False)

            self._definition_signature = signature
            self._definition_count = count
            self._definition_revision = int(definition_revision or 0)
            self._run_id = run_id

            # A stopped/reset snapshot is a lifecycle boundary, not a sample.
            if step_count <= 0:
                return False

            duplicate = bool(
                self._frames
                and int(self._frames[-1]["run_id"]) == run_id
                and int(self._frames[-1]["step_count"]) == step_count
                and abs(float(self._frames[-1]["absolute_minute"]) - absolute_minute) <= 1e-9
            )
            if duplicate:
                offset = (len(self._frames) - 1) * count
                self._real_values[offset : offset + count] = real_values
                self._scada_values[offset : offset + count] = scada_values
                self._valid_values[offset : offset + count] = valid_values
                self._frames[-1].update(
                    {
                        "simu_time": str(clock.get("time") or "--"),
                        "wall_time": frame_wall_time,
                    }
                )
                return False

            self._next_seq += 1
            self._frames.append(
                {
                    "seq": self._next_seq,
                    "run_id": run_id,
                    "step_count": step_count,
                    "absolute_minute": absolute_minute,
                    "simu_time": str(clock.get("time") or "--"),
                    "wall_time": frame_wall_time,
                }
            )
            self._real_values.extend(real_values)
            self._scada_values.extend(scada_values)
            self._valid_values.extend(valid_values)
            self._trim_unlocked(max(1, int(limit)))
            return True

    def _trim_unlocked(self, limit: int) -> None:
        overflow = len(self._frames) - limit
        if overflow <= 0:
            return
        value_count = overflow * self._definition_count
        del self._frames[:overflow]
        del self._real_values[:value_count]
        del self._scada_values[:value_count]
        del self._valid_values[:value_count]

    def trim(self, limit: int) -> None:
        with self._lock:
            self._trim_unlocked(max(1, int(limit)))

    def payload(
        self,
        *,
        indices: Optional[Sequence[int]] = None,
        after_seq: int | float = 0,
        model_id: str = "",
        model_name: str = "",
    ) -> Dict[str, Any]:
        try:
            after = max(0, int(after_seq))
        except (TypeError, ValueError):
            after = 0
        with self._lock:
            count = self._definition_count
            if indices is None:
                selected = list(range(count))
            else:
                selected = []
                seen: set[int] = set()
                for raw_index in indices:
                    index = _int_value(raw_index, -1)
                    if 0 <= index < count and index not in seen:
                        selected.append(index)
                        seen.add(index)

            latest_seq = int(self._frames[-1]["seq"]) if self._frames else 0
            oldest_seq = int(self._frames[0]["seq"]) if self._frames else 0
            reset = bool(
                after <= 0
                or after > latest_seq
                or (oldest_seq and after < oldest_seq - 1)
            )
            source_frames = (
                self._frames
                if reset
                else [frame for frame in self._frames if int(frame["seq"]) > after]
            )
            frame_positions = (
                range(len(self._frames))
                if reset
                else (
                    position
                    for position, frame in enumerate(self._frames)
                    if int(frame["seq"]) > after
                )
            )
            frames: list[Dict[str, Any]] = []
            for position, frame in zip(frame_positions, source_frames):
                base = position * count
                frames.append(
                    {
                        **frame,
                        "real_values": [
                            _number_or_none(self._real_values[base + index])
                            for index in selected
                        ],
                        "scada_values": [
                            _number_or_none(self._scada_values[base + index])
                            for index in selected
                        ],
                        "valid_values": [
                            None
                            if self._valid_values[base + index] == _MISSING_VALID
                            else int(self._valid_values[base + index])
                            for index in selected
                        ],
                    }
                )
            return {
                "encoding": MEASUREMENT_HISTORY_ENCODING,
                "model_id": str(model_id),
                "model_name": str(model_name),
                "run_id": int(self._run_id or 0),
                "definition_signature": self._definition_signature,
                "definition_revision": self._definition_revision,
                "count": count,
                "selected_count": len(selected),
                "indices": selected,
                "latest_seq": latest_seq,
                "oldest_seq": oldest_seq,
                "reset": reset,
                "frames": frames,
            }
