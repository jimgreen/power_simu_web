"""Shared trainee-side renewable-priority control engine.

The browser is only a client of this module.  One controller state is kept per
trainee model so every browser page sees and operates the same algorithm.
"""

from __future__ import annotations

import copy
import json
import math
import re
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, ContextManager, Deque, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

from simu.device_roles import (
    AC_TO_DC,
    converter_balance_coefficients,
    converter_control_mode,
    converter_power_in_ac_terminal_convention,
    converter_power_in_dc_to_ac_convention,
    converter_power_setpoint_fields,
    converter_setpoint_from_p_ac_convention,
)
from simu.control_config import (
    default_boolean,
    default_derating_curve,
    default_integer,
    default_number,
)
from simu.fuel_cell_control import (
    FuelCellControlDecision,
    FuelCellControlInputs,
    FuelCellControlParameters,
    calculate_fuel_cell_power_decision,
)
from simu.model_semantics import (
    energy_coupling_control_bindings,
    grid_converter_keys as structured_grid_converter_keys,
)
from simu.renewable_capability import (
    renewable_weather_available_kw as _renewable_weather_available_kw,
)
from simu.renewable_optimization import (
    RenewableDispatchOptimizationResult,
    optimize_topology_islands,
)
from simu.resource_topology import (
    DcTransferGroup,
    ResourceConnection,
    ResourceRef,
    ResourceTopology,
    resolve_resource_topology,
)
from simu.trainee_exchange import TraineeControlSnapshot


EPSILON = 1e-9
RENEWABLE_CONTROL_STRATEGY_ID = "renewable_priority"
DEFAULT_TRAINEE_BACKEND_REFRESH_SECONDS = 1.0
MINIMUM_CONTROL_INTERVAL_SECONDS = default_number(
    "minimum_simulation_control_interval_seconds"
)
MINIMUM_COMMAND_VALID_MINUTES = default_number(
    "minimum_command_valid_minutes"
)
MAXIMUM_POWER_PROTECTION_RATIO = default_number(
    "maximum_power_protection_ratio"
)
SIMULATION_DEFAULT_STEP_MINUTES = default_number(
    "simulation_default_step_minutes"
)
SIMULATION_MINIMUM_STEP_MINUTES = default_number(
    "simulation_minimum_step_minutes"
)


def _simulation_control_interval_seconds(value: Any) -> float:
    try:
        interval = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("自动控制周期必须为有效的仿真秒数。") from exc
    if (
        not math.isfinite(interval)
        or interval < MINIMUM_CONTROL_INTERVAL_SECONDS
    ):
        raise ValueError(
            "自动控制周期必须不少于 "
            f"{MINIMUM_CONTROL_INTERVAL_SECONDS:g} 仿真秒。"
        )
    return interval


SIMULATION_DEFAULT_SPEED = default_number("simulation_default_speed")
SIMULATION_MINIMUM_SPEED = default_number("simulation_minimum_speed")
STORAGE_MINIMUM_CONTROL_HORIZON_HOURS = default_number(
    "storage_minimum_control_horizon_hours"
)
POWER_CONTROL_MODES = {"P", "PQ", "PV", "PH", "ACP"}
AC_DC_CONVERTER_TYPES = frozenset({"ACDCConverter", "DCACConverter"})
RENEWABLE_PARAMETER_SPECS = (
    ("wind", "ACWindGen", "ACGenerator", "idx_acgenerator"),
    ("wind", "DCWindGen", "DCGenerator", "idx_dcgenerator"),
    ("pv", "ACPVGen", "ACGenerator", "idx_acgenerator"),
    ("pv", "DCPVGen", "DCGenerator", "idx_dcgenerator"),
)
STORAGE_PARAMETER_SPECS = (
    ("ACStorageGen", "ACGenerator", "idx_acgenerator"),
    ("DCStorageGen", "DCGenerator", "idx_dcgenerator"),
)
GRID_FOLLOWING_STORAGE_MODES = {"P", "PQ"}
BALANCE_STORAGE_MODES = {"SLACK", "V", "VF", "V/F", "PH"}
RENEWABLE_CONTROL_STATE_FILE = "renewable_control.json"
RENEWABLE_CONTROL_TREND_FILE = "renewable_control_trend.jsonl"
DEFAULT_STORAGE_CHARGE_DERATING_CURVE = default_derating_curve(
    "storage_charge_derating_curve"
)
DEFAULT_STORAGE_DISCHARGE_DERATING_CURVE = default_derating_curve(
    "storage_discharge_derating_curve"
)
DEFAULT_GRID_FOLLOWING_STORAGE_STEP_RATIO = default_number(
    "grid_following_storage_step_ratio"
)
CYCLE_PERFORMANCE_HISTORY_LIMIT = 120


def _performance_percentile(values: Sequence[float], percentile: float) -> float:
    ordered = sorted(float(value) for value in values if math.isfinite(float(value)))
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * min(1.0, max(0.0, float(percentile)))
    lower_index = int(math.floor(position))
    upper_index = int(math.ceil(position))
    if lower_index == upper_index:
        return ordered[lower_index]
    fraction = position - lower_index
    return ordered[lower_index] + (
        ordered[upper_index] - ordered[lower_index]
    ) * fraction


class _CyclePerformanceWindow:
    """Bounded completed-cycle timings used by the trainee diagnostics UI."""

    def __init__(self, limit: int = CYCLE_PERFORMANCE_HISTORY_LIMIT) -> None:
        self.limit = max(1, int(limit))
        self.samples: Deque[Dict[str, Any]] = deque(maxlen=self.limit)
        self.revision = 0

    def record(self, sample: Mapping[str, Any]) -> None:
        self.samples.append(_json_safe_copy(dict(sample)))
        self.revision += 1

    def payload(self) -> Dict[str, Any]:
        samples = list(self.samples)
        latest = copy.deepcopy(samples[-1]) if samples else None
        phase_names = sorted(
            {
                str(name)
                for sample in samples
                for name in (
                    sample.get("phasesMs", {}).keys()
                    if isinstance(sample.get("phasesMs"), Mapping)
                    else ()
                )
            }
        )
        phase_stats: Dict[str, Dict[str, Any]] = {}
        for name in phase_names:
            values = [
                float(value)
                for sample in samples
                for value in [
                    sample.get("phasesMs", {}).get(name)
                    if isinstance(sample.get("phasesMs"), Mapping)
                    else None
                ]
                if isinstance(value, (int, float)) and math.isfinite(float(value))
            ]
            if not values:
                continue
            phase_stats[name] = {
                "sampleCount": len(values),
                "latestMs": values[-1],
                "p50Ms": _performance_percentile(values, 0.50),
                "p95Ms": _performance_percentile(values, 0.95),
                "maxMs": max(values),
            }
        return {
            "historyLimit": self.limit,
            "sampleCount": len(samples),
            "latest": latest,
            "phaseStats": phase_stats,
        }


def _now_text() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _number(value: Any, default: Optional[float] = None) -> Optional[float]:
    if value is None or str(value).strip() == "":
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        match = re.search(r"[-+]?\d*\.?\d+(?:e[-+]?\d+)?", str(value).replace(",", ""), re.I)
        if not match:
            return default
        try:
            number = float(match.group(0))
        except ValueError:
            return default
    return number if math.isfinite(number) else default


def _finite_number(value: Any, default: float = 0.0) -> float:
    number = _number(value)
    return number if number is not None else default


def _boolean(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    number = _number(value)
    if number is not None:
        return number != 0.0
    normalized = str(value or "").strip().lower()
    if normalized in {"true", "yes", "on", "enabled"}:
        return True
    if normalized in {"false", "no", "off", "disabled", ""}:
        return False
    return default


def _sum_known(values: Iterable[Any]) -> Optional[float]:
    numbers = [_number(value) for value in values]
    if any(number is None for number in numbers):
        return None
    return sum(number for number in numbers if number is not None)


def _converter_direction(row: Mapping[str, Any]) -> str:
    del row
    return AC_TO_DC


def _is_grid_converter_row(row: Mapping[str, Any]) -> bool:
    return (
        str(row.get("converterRole", "")).strip().lower() == "grid"
        and str(row.get("converterDirection", "")).strip().upper() == AC_TO_DC
    )


def _converter_ac_balance_coefficient(row: Mapping[str, Any]) -> float:
    ac_coefficient, _dc_coefficient = converter_balance_coefficients(
        _converter_direction(row)
    )
    return ac_coefficient


def _converter_ac_injection_kw(row: Mapping[str, Any], power_kw: Any) -> float:
    """Convert declared converter power into AC-side signed injection."""
    return _converter_ac_balance_coefficient(row) * _finite_number(power_kw)


def _converter_system_power_kw(
    row: Mapping[str, Any],
    power_kw: Any,
) -> Optional[float]:
    """Convert the planner's internal P_AC value to the system P_DC convention."""
    number = _number(power_kw)
    if number is None:
        return None
    return converter_power_in_dc_to_ac_convention(
        number,
        _converter_direction(row),
        "P_AC",
    )


def _converter_power_from_ac_injection_kw(
    row: Mapping[str, Any],
    ac_injection_kw: Any,
) -> float:
    coefficient = _converter_ac_balance_coefficient(row)
    return _finite_number(ac_injection_kw) / coefficient


def _converter_ac_injection_delta_kw(
    row: Mapping[str, Any],
    current_kw: Any,
    target_kw: Any,
) -> float:
    """Return the AC-side injection change using the row's declared direction."""
    return _converter_ac_balance_coefficient(row) * (
        _finite_number(target_kw) - _finite_number(current_kw)
    )


def _positive(values: Iterable[Any], default: float = 0.0) -> float:
    for value in values:
        number = _number(value)
        if number is not None and number > 0:
            return number
    return default


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return min(maximum, max(minimum, value))


def _ratio(value: Any, default: Optional[float]) -> Optional[float]:
    number = _number(value)
    if number is None:
        return default
    if number > 1:
        number /= 100.0
    return _clamp(number, 0.0, 1.0)


def _storage_efficiency(parameter: Mapping[str, Any]) -> float:
    efficiency = _number(parameter.get("charge_discharge_efficiency"))
    return efficiency if efficiency is not None and efficiency > EPSILON else 1.0


def _live_soc_ratio(value: Any, default: Optional[float] = None) -> Optional[float]:
    number = _number(value)
    if number is None:
        return default
    if isinstance(value, str) and "%" in value:
        return number / 100.0
    return number


def _derating_curve_point(value: Any) -> Optional[Tuple[float, float]]:
    if isinstance(value, Mapping):
        soc_value = value.get("soc", value.get("socRatio", value.get("soc_ratio")))
        power_value = value.get(
            "powerRatio",
            value.get("power_ratio", value.get("ratio", value.get("power"))),
        )
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)) and len(value) >= 2:
        soc_value, power_value = value[0], value[1]
    else:
        return None
    soc = _ratio(soc_value, None)
    power_ratio = _ratio(power_value, None)
    if soc is None or power_ratio is None:
        return None
    return soc, power_ratio


def _normalized_derating_curve(
    value: Any,
    fallback: Tuple[Tuple[float, float], ...],
    *,
    increasing: bool,
) -> Tuple[Tuple[float, float], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return fallback
    parsed = [point for item in value if (point := _derating_curve_point(item)) is not None]
    if len(parsed) < 2:
        return fallback
    deduplicated: Dict[float, float] = {}
    for soc, power_ratio in parsed:
        deduplicated[soc] = power_ratio
    ordered = sorted(deduplicated.items())
    if len(ordered) < 2:
        return fallback
    normalized: List[Tuple[float, float]] = []
    previous = 0.0 if increasing else 1.0
    for soc, power_ratio in ordered:
        monotonic_ratio = max(previous, power_ratio) if increasing else min(previous, power_ratio)
        normalized.append((soc, monotonic_ratio))
        previous = monotonic_ratio
    return tuple(normalized)


def _derating_factor(soc: float, curve: Sequence[Tuple[float, float]]) -> float:
    if not curve:
        return 1.0
    if soc <= curve[0][0] + EPSILON:
        return _clamp(float(curve[0][1]), 0.0, 1.0)
    if soc >= curve[-1][0] - EPSILON:
        return _clamp(float(curve[-1][1]), 0.0, 1.0)
    for (lower_soc, lower_ratio), (upper_soc, upper_ratio) in zip(curve, curve[1:]):
        if soc > upper_soc + EPSILON:
            continue
        width = upper_soc - lower_soc
        if width <= EPSILON:
            return _clamp(float(upper_ratio), 0.0, 1.0)
        fraction = _clamp((soc - lower_soc) / width, 0.0, 1.0)
        return _clamp(lower_ratio + (upper_ratio - lower_ratio) * fraction, 0.0, 1.0)
    return _clamp(float(curve[-1][1]), 0.0, 1.0)


def _derating_curve_payload(curve: Sequence[Tuple[float, float]]) -> List[Dict[str, float]]:
    return [{"soc": soc, "powerRatio": power_ratio} for soc, power_ratio in curve]


def _derating_curve_text(curve: Sequence[Tuple[float, float]]) -> str:
    return "、".join(f"{soc * 100:.1f}%:{power_ratio * 100:.1f}%" for soc, power_ratio in curve)


def _command_number(value: float) -> float:
    normalized = 0.0 if abs(value) < 0.0005 else value
    return round(normalized, 3)


def _dispatch_setpoint_value(row: Mapping[str, Any]) -> float:
    """Return a field-specific command from the planner's P_AC target."""
    value = float(row["commandKw"])
    direction = str(row.get("converterDirection", "")).strip().upper()
    if not direction:
        return value
    return converter_setpoint_from_p_ac_convention(
        value,
        direction,
        row.get("set_type", "p_ac_set"),
    )


def _deduplicate_dispatch_commands(
    commands: Sequence[Mapping[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    ordered_keys: List[Tuple[str, str, str]] = []
    selected: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    values_by_key: Dict[Tuple[str, str, str], List[float]] = {}
    for row in commands:
        key = (
            str(row.get("dev_type", "")),
            str(row.get("dev_name", "")),
            str(row.get("set_type", "")),
        )
        value = _number(row.get("set_value"))
        if not all(key) or value is None or not math.isfinite(value):
            continue
        if key not in selected:
            ordered_keys.append(key)
        selected[key] = {
            "dev_type": key[0],
            "dev_name": key[1],
            "set_type": key[2],
            "set_value": _command_number(value),
        }
        values_by_key.setdefault(key, []).append(value)

    duplicates = [
        {
            "dev_type": key[0],
            "dev_name": key[1],
            "set_type": key[2],
            "duplicateCount": len(values),
            "candidateValues": [_command_number(value) for value in values],
            "selectedValue": selected[key]["set_value"],
            "conflict": any(
                abs(value - values[-1]) > EPSILON for value in values[:-1]
            ),
        }
        for key, values in values_by_key.items()
        if len(values) > 1
    ]
    return [selected[key] for key in ordered_keys], duplicates


def _device_type(device: Mapping[str, Any]) -> str:
    return str(device.get("dev_type", device.get("type", "")))


def _device_model_block(device: Mapping[str, Any]) -> str:
    return str(device.get("model_block", "")).strip()


def _device_name(device: Mapping[str, Any]) -> str:
    return str(device.get("dev_name", device.get("name", "")))


def _device_index(device: Mapping[str, Any]) -> str:
    raw = device.get("raw") if isinstance(device.get("raw"), Mapping) else {}
    return str(device.get("idx", raw.get("idx", ""))).strip()


def _device_key(device: Mapping[str, Any]) -> Tuple[str, str]:
    return _device_type(device), _device_name(device)


def _device_model_key(device: Mapping[str, Any]) -> Tuple[str, str]:
    return _device_model_block(device), _device_name(device)


def _parameter_rows(snapshot: Mapping[str, Any], block_name: str) -> List[Mapping[str, Any]]:
    parameters = snapshot.get("device_parameters")
    wanted = block_name.lower()
    if isinstance(parameters, Mapping):
        for name, rows in parameters.items():
            if str(name).lower() == wanted and isinstance(rows, Sequence) and not isinstance(rows, (str, bytes)):
                return [row for row in rows if isinstance(row, Mapping)]

    definitions = snapshot.get("definitions")
    if not isinstance(definitions, Mapping):
        return []
    for section_name in ("device", "model"):
        section = definitions.get(section_name)
        if not isinstance(section, Mapping):
            continue
        for name, block in section.items():
            if str(name).lower() != wanted:
                continue
            rows = block.get("rows") if isinstance(block, Mapping) else block
            if isinstance(rows, Sequence) and not isinstance(rows, (str, bytes)):
                return [row for row in rows if isinstance(row, Mapping)]
    return []


def _parameter_name(row: Mapping[str, Any]) -> str:
    return str(row.get("name", row.get("dev_name", "")))


def _indexed_device_matches(
    snapshot: Mapping[str, Any],
    dev_type: str,
    index: Any,
) -> Tuple[List[Mapping[str, Any]], List[Mapping[str, Any]]]:
    target = str(index if index is not None else "").strip()
    if not target:
        return [], []
    runtime_matches = [
        device
        for device in snapshot.get("devices", []) or []
        if isinstance(device, Mapping)
        and _device_model_block(device) == dev_type
        and _device_index(device) == target
    ]
    definitions = snapshot.get("definitions")
    model = definitions.get("model") if isinstance(definitions, Mapping) else None
    block = model.get(dev_type) if isinstance(model, Mapping) else None
    rows = block.get("rows") if isinstance(block, Mapping) else block
    model_matches = [
        row
        for row in rows
        if isinstance(row, Mapping) and str(row.get("idx", "")).strip() == target
    ] if isinstance(rows, Sequence) and not isinstance(rows, (str, bytes)) else []
    return runtime_matches, model_matches


def _device_map(snapshot: Mapping[str, Any]) -> Dict[Tuple[str, str], Mapping[str, Any]]:
    return {
        _device_key(device): device
        for device in snapshot.get("devices", []) or []
        if isinstance(device, Mapping)
    }


def _duplicate_typed_identities(
    snapshot: Mapping[str, Any],
) -> Dict[Tuple[str, str], str]:
    runtime_counts: Dict[Tuple[str, str], int] = {}
    for device in snapshot.get("devices", []) or []:
        if not isinstance(device, Mapping):
            continue
        key = _device_key(device)
        if all(key):
            runtime_counts[key] = runtime_counts.get(key, 0) + 1

    model_counts: Dict[Tuple[str, str], int] = {}
    definitions = snapshot.get("definitions")
    model = definitions.get("model") if isinstance(definitions, Mapping) else None
    if isinstance(model, Mapping):
        for dev_type, block in model.items():
            rows = block.get("rows") if isinstance(block, Mapping) else block
            if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
                continue
            for row in rows:
                if not isinstance(row, Mapping):
                    continue
                dev_name = str(row.get("name", row.get("dev_name", ""))).strip()
                key = (str(dev_type), dev_name)
                if all(key):
                    model_counts[key] = model_counts.get(key, 0) + 1

    diagnostics: Dict[Tuple[str, str], str] = {}
    for key in runtime_counts.keys() | model_counts.keys():
        reasons = []
        if runtime_counts.get(key, 0) > 1:
            reasons.append(f"运行设备列表存在{runtime_counts[key]}个同身份设备")
        if model_counts.get(key, 0) > 1:
            reasons.append(f"definitions.model存在{model_counts[key]}个同身份模型行")
        if reasons:
            diagnostics[key] = (
                f"资源{key[0]}.{key[1]}设备身份重复（{'；'.join(reasons)}），"
                "自动命令地址不唯一，本轮仅保留诊断"
            )
    return diagnostics


def _device_state_rows(snapshot: Mapping[str, Any], dev_type: str) -> List[Mapping[str, Any]]:
    return [
        row
        for row in snapshot.get("device_states", []) or []
        if isinstance(row, Mapping) and _device_model_block(row) == dev_type
    ]


@dataclass(frozen=True)
class _LinkedResourceSpec:
    technology: str
    parameter_block: str
    parameter: Mapping[str, Any]
    device: Mapping[str, Any]
    identity_diagnostic: str = ""

    @property
    def dev_type(self) -> str:
        return _device_type(self.device)

    @property
    def model_block(self) -> str:
        return _device_model_block(self.device)

    @property
    def dev_name(self) -> str:
        return _device_name(self.device)

    @property
    def topology_key(self) -> Tuple[str, str]:
        return self.model_block, self.dev_name


def _linked_resource_specs(
    snapshot: Mapping[str, Any],
    quality: "_Quality",
    identity_diagnostics: Optional[Mapping[Tuple[str, str], str]] = None,
) -> Tuple[List[_LinkedResourceSpec], List[_LinkedResourceSpec], List[ResourceRef]]:
    renewable_specs: List[_LinkedResourceSpec] = []
    storage_specs: List[_LinkedResourceSpec] = []
    linked_keys: set[Tuple[str, str]] = set()
    if identity_diagnostics is None:
        identity_diagnostics = _duplicate_typed_identities(snapshot)

    def indexed_device(
        block_name: str,
        position: int,
        dev_type: str,
        index_name: str,
        index_value: Any,
    ) -> Optional[Mapping[str, Any]]:
        runtime_matches, model_matches = _indexed_device_matches(
            snapshot,
            dev_type,
            index_value,
        )
        index_text = str(
            index_value if index_value is not None else ""
        ).strip() or "--"
        if not runtime_matches:
            quality.add(
                f"{block_name}参数行{position}引用的{dev_type}.{index_name}="
                f"{index_text}不存在，已忽略"
            )
            return None
        if len(runtime_matches) > 1 or len(model_matches) > 1:
            candidate_names = sorted(
                {
                    *(_device_name(device) for device in runtime_matches),
                    *(
                        str(row.get("name", row.get("dev_name", ""))).strip()
                        for row in model_matches
                    ),
                }
                - {""},
                key=lambda name: _natural_topology_identity(name),
            )
            source_counts = []
            if len(runtime_matches) > 1:
                source_counts.append(f"运行设备{len(runtime_matches)}行")
            if len(model_matches) > 1:
                source_counts.append(f"模型{len(model_matches)}行")
            candidates_text = "、".join(
                f"{dev_type}.{name}" for name in candidate_names
            ) or "--"
            quality.add(
                f"{block_name}参数行{position}引用的{dev_type}.{index_name}="
                f"{index_text}匹配到多个候选（{'、'.join(source_counts)}："
                f"{candidates_text}），引用歧义，已忽略"
            )
            return None
        return runtime_matches[0]

    def add_spec(
        technology: str,
        parameter_block: str,
        parameter: Mapping[str, Any],
        device: Mapping[str, Any],
    ) -> None:
        key = _device_key(device)
        if key in linked_keys:
            quality.add(
                f"资源{key[0]}.{key[1]}被多个技术参数行重复引用，保留首个有效引用"
            )
            return
        linked_keys.add(key)
        spec = _LinkedResourceSpec(
            technology=technology,
            parameter_block=parameter_block,
            parameter=parameter,
            device=device,
            identity_diagnostic=identity_diagnostics.get(key, ""),
        )
        if spec.identity_diagnostic:
            quality.add(spec.identity_diagnostic)
        (storage_specs if technology == "storage" else renewable_specs).append(spec)

    for technology, block_name, dev_type, index_name in RENEWABLE_PARAMETER_SPECS:
        for position, parameter in enumerate(_parameter_rows(snapshot, block_name), start=1):
            index_value = parameter.get(index_name)
            device = indexed_device(
                block_name,
                position,
                dev_type,
                index_name,
                index_value,
            )
            if device is None:
                continue
            add_spec(technology, block_name, parameter, device)

    for block_name, dev_type, index_name in STORAGE_PARAMETER_SPECS:
        for position, parameter in enumerate(_parameter_rows(snapshot, block_name), start=1):
            index_value = parameter.get(index_name)
            device = indexed_device(
                block_name,
                position,
                dev_type,
                index_name,
                index_value,
            )
            if device is None:
                continue
            add_spec("storage", block_name, parameter, device)

    refs = [
        ResourceRef(spec.technology, spec.model_block, spec.dev_name)
        for spec in (*renewable_specs, *storage_specs)
    ]
    return renewable_specs, storage_specs, refs


@dataclass(frozen=True)
class MeasurementValue:
    value: float
    source: str
    row: Mapping[str, Any]


def _measurement_index(snapshot: Mapping[str, Any]) -> Dict[Tuple[str, str, str], MeasurementValue]:
    measurements = snapshot.get("measurements")
    if not isinstance(measurements, Mapping):
        return {}
    index: Dict[Tuple[str, str, str], MeasurementValue] = {}
    for source in ("scada", "real"):
        rows = measurements.get(source)
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
            continue
        for row in rows:
            if not isinstance(row, Mapping) or int(_number(row.get("valid"), 1.0) or 0) != 1:
                continue
            value = _number(row.get("value"))
            if value is None:
                continue
            key = (
                str(row.get("dev_type", "")),
                str(row.get("dev_name", "")),
                str(row.get("meas_type", "")).upper(),
            )
            index.setdefault(key, MeasurementValue(value=value, source=source, row=row))
    return index


def _measured(
    measurements: Mapping[Tuple[str, str, str], MeasurementValue],
    dev_type: str,
    dev_name: str,
    meas_types: Sequence[str],
) -> Optional[MeasurementValue]:
    for meas_type in meas_types:
        found = measurements.get((dev_type, dev_name, meas_type.upper()))
        if found is not None:
            return found
    return None


def _is_online(
    device: Optional[Mapping[str, Any]],
    measurements: Mapping[Tuple[str, str, str], MeasurementValue],
) -> bool:
    if not device:
        return False
    run_measurement = _measured(measurements, _device_type(device), _device_name(device), ("RUN_STAT",))
    run_stat = run_measurement.value if run_measurement else _number(device.get("run_stat"), 1.0)
    status = _number(device.get("status"), 1.0)
    return int(run_stat or 0) == 1 and int(status or 0) != 0


def _control_rows(snapshot: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    definitions = snapshot.get("definitions")
    control = definitions.get("control") if isinstance(definitions, Mapping) else None
    set_value = control.get("SetValue") if isinstance(control, Mapping) else None
    rows = set_value.get("rows") if isinstance(set_value, Mapping) else None
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        return []
    return [row for row in rows if isinstance(row, Mapping)]


def _preferred_set_type(
    snapshot: Mapping[str, Any],
    device: Optional[Mapping[str, Any]],
    candidates: Sequence[str],
) -> str:
    if not device:
        return ""
    rows = _control_rows(snapshot)
    defined = {
        str(row.get("set_type", ""))
        for row in rows
        if str(row.get("dev_type", "")) == _device_type(device)
        and str(row.get("dev_name", "")) == _device_name(device)
    }
    for candidate in candidates:
        if candidate in defined:
            return candidate
    if rows:
        return ""
    set_types = {str(value) for value in device.get("set_types", []) or []}
    return next((candidate for candidate in candidates if candidate in set_types), "")


def _definition_device_rows(
    snapshot: Mapping[str, Any],
    block_names: Sequence[str],
) -> Dict[Tuple[str, str], Mapping[str, Any]]:
    rows: Dict[Tuple[str, str], Mapping[str, Any]] = {}
    for block_name in block_names:
        for row in _parameter_rows(snapshot, block_name):
            name = _parameter_name(row).strip()
            if name:
                rows[(block_name, name)] = row
    return rows


def _device_by_model_key(
    snapshot: Mapping[str, Any],
) -> Dict[Tuple[str, str], Mapping[str, Any]]:
    return {
        _device_model_key(device): device
        for device in snapshot.get("devices", []) or []
        if isinstance(device, Mapping) and all(_device_model_key(device))
    }


def _hydrogen_pressure_states(
    snapshot: Mapping[str, Any],
    measurements: Mapping[Tuple[str, str, str], MeasurementValue],
    settings: RenewableControlSettings,
) -> List[Dict[str, Any]]:
    devices = _device_by_model_key(snapshot)
    states: List[Dict[str, Any]] = []
    for row in _parameter_rows(snapshot, "HydroStorage"):
        name = _parameter_name(row).strip()
        device = devices.get(("HydroStorage", name))
        pressure_measurement = (
            _measured(measurements, _device_type(device), name, ("PRESSURE", "PRESS"))
            if device
            else _measured(measurements, "HydroStorage", name, ("PRESSURE", "PRESS"))
        )
        pressure = pressure_measurement.value if pressure_measurement else None
        soc_measurement = (
            _measured(measurements, _device_type(device), name, ("SOC",))
            if device
            else _measured(measurements, "HydroStorage", name, ("SOC",))
        )
        soc = _live_soc_ratio(soc_measurement.value) if soc_measurement else None
        pressure_min = _number(row.get("pressure_min"))
        pressure_max = _number(row.get("pressure_max"))
        limits_valid = bool(
            pressure_min is not None
            and pressure_max is not None
            and pressure_max > pressure_min + EPSILON
        )
        deadband = (
            settings.hydrogen_pressure_deadband_ratio
            * (float(pressure_max) - float(pressure_min))
            if limits_valid
            else None
        )
        online = bool(device and _is_online(device, measurements))
        states.append(
            {
                "devType": _device_type(device) if device else "HydroStorage",
                "devName": name,
                "online": online,
                "pressure": pressure,
                "pressureKnown": pressure is not None,
                "pressureSource": pressure_measurement.source if pressure_measurement else "missing",
                "soc": soc,
                "socKnown": soc is not None and math.isfinite(float(soc)),
                "socSource": soc_measurement.source if soc_measurement else "missing",
                "pressureMin": pressure_min,
                "pressureMax": pressure_max,
                "pressureDeadband": deadband,
                "lowGuard": float(pressure_min) + float(deadband) if limits_valid else None,
                "highGuard": float(pressure_max) - float(deadband) if limits_valid else None,
                "limitsValid": limits_valid,
                "hydrogenIslandId": "",
            }
        )
    return states


def _hydrogen_pressure_states_by_island(
    pressure_states: Sequence[MutableMapping[str, Any]],
    resource_topology: ResourceTopology,
) -> Dict[str, List[MutableMapping[str, Any]]]:
    result: Dict[str, List[MutableMapping[str, Any]]] = {}
    for row in pressure_states:
        key = (str(row.get("devType", "")), str(row.get("devName", "")))
        island_id = str(
            resource_topology.hydrogen_device_island_ids.get(key, "")
        )
        row["hydrogenIslandId"] = island_id
        if island_id:
            result.setdefault(island_id, []).append(row)
    return result


def _hydrogen_operating_metrics(
    snapshot: Mapping[str, Any],
    measurements: Mapping[Tuple[str, str, str], MeasurementValue],
    pressure_states: Sequence[Mapping[str, Any]],
    hydrogen_commands: Sequence[Mapping[str, Any]] = (),
) -> Dict[str, Any]:
    devices = _device_by_model_key(snapshot)
    bindings_by_coupling = energy_coupling_control_bindings(snapshot)
    command_by_coupling = {
        (
            str(row.get("couplingType", "")),
            str(row.get("couplingName", "")),
        ): row
        for row in hydrogen_commands
        if isinstance(row, Mapping)
    }
    category_values: Dict[str, Dict[str, List[float]]] = {
        "electrolyzer": {"currentPower": [], "targetPower": [], "currentFlow": [], "targetFlow": []},
        "fuelCell": {"currentPower": [], "targetPower": [], "currentFlow": [], "targetFlow": []},
    }
    online_counts = {"electrolyzer": 0, "fuelCell": 0}
    for coupling_type in ("AcE2Hydro", "DcE2Hydro", "Hydro2AcE", "Hydro2DcE"):
        category = "electrolyzer" if coupling_type in {"AcE2Hydro", "DcE2Hydro"} else "fuelCell"
        coefficient_field = "e2h_coeff" if category == "electrolyzer" else "h2e_coeff"
        for coupling in _parameter_rows(snapshot, coupling_type):
            coupling_name = _parameter_name(coupling).strip()
            coupling_device = devices.get((coupling_type, coupling_name))
            bindings = bindings_by_coupling.get((coupling_type, coupling_name), ())
            if (
                not coupling_device
                or not _is_online(coupling_device, measurements)
                or len(bindings) != 2
            ):
                continue
            power_binding = next((row for row in bindings if row.get("set_type") == "p_set"), None)
            flow_binding = next((row for row in bindings if row.get("set_type") == "flow_set"), None)
            if not power_binding or not flow_binding:
                continue
            power_key = (
                str(power_binding.get("target_dev_type", "")),
                str(power_binding.get("target_dev_name", "")),
            )
            flow_key = (
                str(flow_binding.get("target_dev_type", "")),
                str(flow_binding.get("target_dev_name", "")),
            )
            power_device = devices.get(power_key)
            flow_device = devices.get(flow_key)
            if (
                not power_device
                or not flow_device
                or not _is_online(power_device, measurements)
                or not _is_online(flow_device, measurements)
            ):
                continue
            online_counts[category] += 1
            power_measurement = _measured(
                measurements,
                _device_type(power_device),
                power_key[1],
                ("P_LOAD", "P_GEN", "P", "P_AC", "P_DC"),
            )
            flow_measurement = _measured(
                measurements,
                _device_type(flow_device),
                flow_key[1],
                ("FLOW",),
            )
            coefficient = _number(coupling.get(coefficient_field))
            current_power = abs(power_measurement.value) if power_measurement else None
            current_flow = abs(flow_measurement.value) if flow_measurement else None
            if coefficient is not None and coefficient > EPSILON:
                if current_power is None and current_flow is not None:
                    current_power = (
                        current_flow / coefficient
                        if category == "electrolyzer"
                        else current_flow * coefficient
                    )
                if current_flow is None and current_power is not None:
                    current_flow = (
                        current_power * coefficient
                        if category == "electrolyzer"
                        else current_power / coefficient
                    )
            command = command_by_coupling.get((coupling_type, coupling_name), {})
            target_power = _number(command.get("electricPowerKw"))
            target_flow = _number(command.get("equivalentFlow"))
            if target_power is None:
                target_power = current_power
            if target_flow is None:
                target_flow = current_flow
            values = category_values[category]
            if current_power is not None and math.isfinite(current_power):
                values["currentPower"].append(float(current_power))
            if target_power is not None and math.isfinite(target_power):
                values["targetPower"].append(float(target_power))
            if current_flow is not None and math.isfinite(current_flow):
                values["currentFlow"].append(float(current_flow))
            if target_flow is not None and math.isfinite(target_flow):
                values["targetFlow"].append(float(target_flow))

    def total(values: Sequence[float]) -> Optional[float]:
        return sum(values) if values else None

    storage_pressures: List[float] = []
    storage_low_guards: List[float] = []
    storage_high_guards: List[float] = []
    storage_gas_quantities: List[float] = []
    storage_soc_values: List[float] = []
    storage_flows: List[float] = []
    online_storage_count = 0
    pressure_by_key = {
        (str(row.get("devType", "")), str(row.get("devName", ""))): row
        for row in pressure_states
        if isinstance(row, Mapping)
    }
    for storage in _parameter_rows(snapshot, "HydroStorage"):
        storage_name = _parameter_name(storage).strip()
        storage_device = devices.get(("HydroStorage", storage_name))
        if not storage_device or not _is_online(storage_device, measurements):
            continue
        online_storage_count += 1
        device_type = _device_type(storage_device)
        state = pressure_by_key.get((device_type, storage_name), {})
        for key, target in (
            ("pressure", storage_pressures),
            ("lowGuard", storage_low_guards),
            ("highGuard", storage_high_guards),
        ):
            value = _number(state.get(key))
            if value is not None and math.isfinite(value):
                target.append(float(value))
        gas_quantity = _measured(measurements, device_type, storage_name, ("GAS_QUANTITY", "GAS_VOLUME"))
        soc = _measured(measurements, device_type, storage_name, ("SOC",))
        flow = _measured(measurements, device_type, storage_name, ("FLOW",))
        if gas_quantity is not None and math.isfinite(gas_quantity.value):
            storage_gas_quantities.append(float(gas_quantity.value))
        if soc is not None:
            soc_ratio = _live_soc_ratio(soc.value)
            if soc_ratio is not None and math.isfinite(soc_ratio):
                storage_soc_values.append(float(soc_ratio))
        if flow is not None and math.isfinite(flow.value):
            storage_flows.append(float(flow.value))

    def average(values: Sequence[float]) -> Optional[float]:
        return sum(values) / len(values) if values else None

    electrolyzer = category_values["electrolyzer"]
    fuel_cell = category_values["fuelCell"]
    return {
        "onlineElectrolyzerCount": online_counts["electrolyzer"],
        "onlineFuelCellCount": online_counts["fuelCell"],
        "onlineHydrogenStorageCount": online_storage_count,
        "electrolyzerCurrentKw": total(electrolyzer["currentPower"]),
        "electrolyzerTargetKw": total(electrolyzer["targetPower"]),
        "electrolyzerFlowCurrentNm3h": total(electrolyzer["currentFlow"]),
        "electrolyzerFlowTargetNm3h": total(electrolyzer["targetFlow"]),
        "fuelCellCurrentKw": total(fuel_cell["currentPower"]),
        "fuelCellTargetKw": total(fuel_cell["targetPower"]),
        "fuelCellFlowCurrentNm3h": total(fuel_cell["currentFlow"]),
        "fuelCellFlowTargetNm3h": total(fuel_cell["targetFlow"]),
        "hydrogenStoragePressureMpa": average(storage_pressures),
        "hydrogenStoragePressureLowGuardMpa": average(storage_low_guards),
        "hydrogenStoragePressureHighGuardMpa": average(storage_high_guards),
        "hydrogenStorageGasQuantityNm3": total(storage_gas_quantities),
        "hydrogenStorageSoc": average(storage_soc_values),
        "hydrogenStorageFlowNm3h": total(storage_flows),
    }


def _hydrogen_island_pressure_state(
    resource_topology: ResourceTopology,
    pressure_by_island: Mapping[str, Sequence[Mapping[str, Any]]],
    flow_key: Tuple[str, str],
) -> Tuple[str, Sequence[Mapping[str, Any]], str]:
    island_id = str(
        resource_topology.hydrogen_device_island_ids.get(flow_key, "")
    )
    if flow_key in set(resource_topology.hydrogen_invalid_devices):
        return "", (), "氢端设备节点或稳定身份无效"
    if not island_id:
        return "", (), "氢端设备未接入唯一有效氢网分岛"
    tanks = tuple(pressure_by_island.get(island_id, ()))
    if not tanks:
        return island_id, (), "所属氢网分岛没有在线储氢罐"
    if not all(row.get("pressureKnown") and row.get("limitsValid") for row in tanks):
        return island_id, tanks, "所属氢网分岛储氢罐压力或上下限无效"
    return island_id, tanks, ""


def _node_in_dc_transfer_group(
    resource_topology: ResourceTopology,
    node: Any,
) -> str:
    node_id = str(node if node is not None else "").strip()
    matches = [
        group_id
        for group_id, group in resource_topology.dc_transfer_groups.items()
        if node_id and node_id in group.dc_nodes
    ]
    return matches[0] if len(matches) == 1 else ""


def _allocate_converter_ac_injection_delta(
    converter_rows: Sequence[MutableMapping[str, Any]],
    delta_kw: float,
    *,
    step_ratio: Optional[float] = None,
) -> float:
    remaining = float(delta_kw)
    if abs(remaining) <= EPSILON:
        return 0.0
    ordered = sorted(converter_rows, key=_converter_row_sort_key)
    while abs(remaining) > EPSILON:
        margins = []
        for row in ordered:
            target_kw = _finite_number(row.get("commandKw"), row.get("currentKw"))
            target_injection = _converter_ac_injection_kw(row, target_kw)
            minimum, maximum = _converter_ac_injection_bounds_kw(row)
            physical_margin = (
                max(0.0, maximum - target_injection)
                if remaining > 0.0
                else max(0.0, target_injection - minimum)
            )
            step_kw = _number(row.get("stepKw"))
            if (
                step_kw is None
                and step_ratio is not None
                and step_ratio > EPSILON
            ):
                capacity_kw = _number(row.get("transferCapacityKw"))
                if capacity_kw is not None and capacity_kw > EPSILON:
                    step_kw = max(0.0, float(step_ratio) * capacity_kw)
            remaining_step_kw = (
                max(
                    0.0,
                    float(step_kw)
                    - abs(
                        _finite_number(row.get("commandKw"), row.get("currentKw"))
                        - _finite_number(row.get("currentKw"))
                    ),
                )
                if step_kw is not None
                else math.inf
            )
            margin = min(physical_margin, remaining_step_kw)
            margins.append(margin)
        total_margin = sum(margins)
        if total_margin <= EPSILON:
            break
        requested = min(abs(remaining), total_margin)
        allocations = [requested * margin / total_margin for margin in margins]
        delivered = 0.0
        for row, allocation in zip(ordered, allocations):
            if allocation <= EPSILON:
                continue
            old_target = _finite_number(row.get("commandKw"), row.get("currentKw"))
            old_injection = _converter_ac_injection_kw(row, old_target)
            new_injection = old_injection + (allocation if remaining > 0.0 else -allocation)
            new_target = _converter_target_from_ac_injection_kw(row, new_injection)
            row["commandKw"] = new_target
            row["strategyCommand"] = True
            delivered += abs(
                _converter_ac_injection_kw(row, new_target) - old_injection
            )
        if delivered <= EPSILON:
            break
        remaining -= delivered if remaining > 0.0 else -delivered
    return float(delta_kw) - remaining


def _row_command_delta_margin(
    rows: Sequence[Mapping[str, Any]],
    *,
    increase: bool,
) -> float:
    margin = 0.0
    for row in rows:
        current = _number(row.get("commandKw"))
        lower = _number(row.get("minKw"))
        upper = _number(row.get("capacityKw"))
        if current is None or lower is None or upper is None or lower > upper:
            continue
        margin += max(0.0, upper - current) if increase else max(0.0, current - lower)
    return margin


def _allocate_row_command_delta(
    rows: Sequence[MutableMapping[str, Any]],
    delta_kw: float,
) -> float:
    increase = delta_kw > 0.0
    remaining = abs(float(delta_kw))
    eligible = []
    for row in rows:
        current = _number(row.get("commandKw"))
        lower = _number(row.get("minKw"))
        upper = _number(row.get("capacityKw"))
        if current is None or lower is None or upper is None or lower > upper:
            continue
        margin = max(0.0, upper - current) if increase else max(0.0, current - lower)
        if margin > EPSILON:
            eligible.append((row, current, margin))
    total_margin = sum(item[2] for item in eligible)
    delivered = min(remaining, total_margin)
    if delivered <= EPSILON:
        return 0.0
    for row, current, margin in eligible:
        allocation = delivered * margin / total_margin
        row["commandKw"] = current + allocation if increase else current - allocation
        row["strategyCommand"] = True
        row["statusLabel"] = f"{row.get('statusLabel', '')}·综合能源原子平衡校核"
    return delivered if increase else -delivered


def _hydrogen_post_dispatch_plan(
    snapshot: Mapping[str, Any],
    measurements: Mapping[Tuple[str, str, str], MeasurementValue],
    settings: RenewableControlSettings,
    resource_topology: ResourceTopology,
    command_rows: List[Dict[str, Any]],
    storage_rows: Sequence[Mapping[str, Any]],
    *,
    diesel_current_kw: float,
    diesel_capacity_kw: Optional[float] = None,
    diesel_unit_count: int = 1,
    diesel_input_valid: bool = True,
    apply_electrical_corrections: bool = True,
) -> Dict[str, Any]:
    diesel_unit_count = max(1, int(diesel_unit_count))
    diesel_capacity_kw = (
        max(0.0, float(diesel_capacity_kw))
        if diesel_capacity_kw is not None
        else 100.0 * diesel_unit_count
    )
    electrolyzer_diesel_limit_ratio = (
        float(settings.electrolyzer_diesel_power_limit_kw)
        * diesel_unit_count
        / diesel_capacity_kw
        if settings.electrolyzer_diesel_power_limit_kw is not None
        and diesel_capacity_kw > EPSILON
        else settings.electrolyzer_diesel_power_limit_ratio
    )
    electrolyzer_diesel_deadband_ratio = (
        float(settings.electrolyzer_diesel_power_deadband_kw)
        * diesel_unit_count
        / diesel_capacity_kw
        if settings.electrolyzer_diesel_power_deadband_kw is not None
        and diesel_capacity_kw > EPSILON
        else settings.electrolyzer_diesel_power_deadband_ratio
    )
    fuel_cell_diesel_limit_ratio = (
        float(settings.fuel_cell_diesel_power_limit_kw)
        * diesel_unit_count
        / diesel_capacity_kw
        if settings.fuel_cell_diesel_power_limit_kw is not None
        and diesel_capacity_kw > EPSILON
        else settings.fuel_cell_diesel_power_limit_ratio
    )
    pressure_states = _hydrogen_pressure_states(snapshot, measurements, settings)
    pressure_by_island = _hydrogen_pressure_states_by_island(
        pressure_states,
        resource_topology,
    )
    diagnostics: Dict[str, Any] = {
        "closedLoopEnabled": bool(apply_electrical_corrections),
        "dispatchMode": (
            "closed-loop-atomic"
            if apply_electrical_corrections
            else "open-loop-preview"
        ),
        "pressureDeadbandRatio": settings.hydrogen_pressure_deadband_ratio,
        "pressureStates": pressure_states,
        "action": "hold",
        "electricPowerAdjustmentKw": 0.0,
        "targetElectricPowerKw": 0.0,
        "targetEquivalentFlow": 0.0,
        "commands": [],
        "converterCorrectionKw": 0.0,
        "balanceCorrectionKw": 0.0,
        "predictedDieselBeforeKw": diesel_current_kw,
        "predictedDieselAfterKw": diesel_current_kw,
        "dieselCapacityKw": diesel_capacity_kw,
        "dieselUnitCount": diesel_unit_count,
        "predictedDieselAverageBeforeKw": diesel_current_kw / diesel_unit_count,
        "predictedDieselAverageAfterKw": diesel_current_kw / diesel_unit_count,
        "predictedDieselLoadRatioBefore": (
            diesel_current_kw / diesel_capacity_kw
            if diesel_capacity_kw > EPSILON
            else None
        ),
        "predictedDieselLoadRatioAfter": (
            diesel_current_kw / diesel_capacity_kw
            if diesel_capacity_kw > EPSILON
            else None
        ),
        "electricStorageSocAverage": None,
        "atomic": True,
        "warnings": [],
    }
    diagnostics.update(
        _hydrogen_operating_metrics(
            snapshot,
            measurements,
            pressure_states,
        )
    )
    if not diesel_input_valid or diesel_capacity_kw <= EPSILON:
        diagnostics["action"] = "blocked"
        diagnostics["warnings"].append(
            "氢能策略缺少全部在线柴发的有效实时有功或额定容量，已按 fail closed 禁止计算"
        )
        return diagnostics

    model_rows = _definition_device_rows(
        snapshot,
        (
            "ACGenerator",
            "DCGenerator",
            "ACLoad",
            "DCLoad",
            "HydroSource",
            "HydroLoad",
            "AcE2Hydro",
            "DcE2Hydro",
            "Hydro2AcE",
            "Hydro2DcE",
        ),
    )
    devices = _device_by_model_key(snapshot)
    bindings_by_coupling = energy_coupling_control_bindings(snapshot)
    current_command_by_key = {
        (
            str(row.get("dev_type", "")),
            str(row.get("dev_name", "")),
            str(row.get("set_type", "")),
        ): row
        for row in command_rows
        if row.get("set_type")
    }

    # The two hydrogen conversion directions are physically exclusive.  Build
    # the interlock from explicit coupling bindings and live endpoint values
    # before planning either direction, so iteration order cannot start an
    # electrolyzer while a fuel cell is already running (or vice versa).
    active_hydrogen_modes: set[str] = set()
    for coupling_type in ("AcE2Hydro", "DcE2Hydro", "Hydro2AcE", "Hydro2DcE"):
        mode = (
            "electrolyzer"
            if coupling_type in {"AcE2Hydro", "DcE2Hydro"}
            else "fuel_cell"
        )
        for coupling in _parameter_rows(snapshot, coupling_type):
            coupling_name = _parameter_name(coupling).strip()
            coupling_device = devices.get((coupling_type, coupling_name))
            bindings = bindings_by_coupling.get((coupling_type, coupling_name), ())
            power_binding = next(
                (row for row in bindings if row.get("set_type") == "p_set"),
                None,
            )
            flow_binding = next(
                (row for row in bindings if row.get("set_type") == "flow_set"),
                None,
            )
            if not power_binding or not flow_binding:
                continue
            power_type = str(power_binding.get("target_dev_type", ""))
            power_name = str(power_binding.get("target_dev_name", ""))
            flow_type = str(flow_binding.get("target_dev_type", ""))
            flow_name = str(flow_binding.get("target_dev_name", ""))
            power_device = devices.get((power_type, power_name))
            flow_device = devices.get((flow_type, flow_name))
            if (
                not coupling_device
                or not _is_online(coupling_device, measurements)
                or not power_device
                or not flow_device
                or not _is_online(power_device, measurements)
                or not _is_online(flow_device, measurements)
            ):
                continue
            live_power = _measured(
                measurements,
                _device_type(power_device),
                power_name,
                ("P_LOAD", "P_GEN", "P", "P_AC", "P_DC"),
            )
            live_flow = _measured(
                measurements,
                _device_type(flow_device),
                flow_name,
                ("FLOW",),
            )
            if live_power is not None:
                running = abs(live_power.value) > EPSILON
            else:
                running = live_flow is not None and abs(live_flow.value) > EPSILON
            if running:
                active_hydrogen_modes.add(mode)

    hydrogen_mode_lock = (
        next(iter(active_hydrogen_modes))
        if len(active_hydrogen_modes) == 1
        else "conflict"
        if len(active_hydrogen_modes) > 1
        else ""
    )
    diagnostics["interlockMode"] = hydrogen_mode_lock or "idle"
    diagnostics["interlockActive"] = bool(hydrogen_mode_lock)
    conflict_stop_mode = ""
    conflict_keep_mode = ""
    if hydrogen_mode_lock == "conflict":
        initial_diesel_load_ratio = diesel_current_kw / diesel_capacity_kw
        conflict_stop_mode = (
            "electrolyzer"
            if initial_diesel_load_ratio
            > fuel_cell_diesel_limit_ratio + EPSILON
            else "fuel_cell"
        )
        conflict_keep_mode = (
            "fuel_cell" if conflict_stop_mode == "electrolyzer" else "electrolyzer"
        )
        diagnostics["interlockStopMode"] = conflict_stop_mode
        diagnostics["interlockKeepMode"] = conflict_keep_mode
        diagnostics["warnings"].append(
            "实时量测显示电制氢和燃料电池同时运行，"
            f"柴发负载率{initial_diesel_load_ratio * 100:.3f}%"
            f"{'高于' if conflict_stop_mode == 'electrolyzer' else '未高于'}"
            f"燃料电池柴发负载率限值{fuel_cell_diesel_limit_ratio * 100:.3f}%，"
            f"本轮停止{'电制氢' if conflict_stop_mode == 'electrolyzer' else '燃料电池'}，"
            f"保留{'燃料电池' if conflict_keep_mode == 'fuel_cell' else '电制氢'}运行"
        )

    online_storage = [row for row in storage_rows if row.get("online")]
    known_storage_soc = [
        float(row["soc"])
        for row in online_storage
        if row.get("socKnown")
        and _number(row.get("soc")) is not None
        and math.isfinite(float(row["soc"]))
    ]
    electric_storage_soc = (
        sum(known_storage_soc) / len(known_storage_soc)
        if online_storage and len(known_storage_soc) == len(online_storage)
        else None
    )
    diagnostics["electricStorageSocAverage"] = electric_storage_soc
    coupling_types = ("AcE2Hydro", "DcE2Hydro", "Hydro2AcE", "Hydro2DcE")
    planned: List[Dict[str, Any]] = []
    converter_correction = 0.0
    balance_correction = 0.0
    predicted_diesel_kw = float(diesel_current_kw)
    diesel_command_rows = [
        row
        for row in command_rows
        if row.get("category") == "柴油发电"
        and row.get("online")
        and row.get("commandable") is not False
    ]
    for coupling_type in coupling_types:
        is_electrolyzer = coupling_type in {"AcE2Hydro", "DcE2Hydro"}
        for coupling in _parameter_rows(snapshot, coupling_type):
            coupling_name = _parameter_name(coupling).strip()
            coupling_device = devices.get((coupling_type, coupling_name))
            bindings = bindings_by_coupling.get((coupling_type, coupling_name), ())
            if (
                not coupling_device
                or not _is_online(coupling_device, measurements)
                or len(bindings) != 2
            ):
                continue
            power_binding = next((row for row in bindings if row.get("set_type") == "p_set"), None)
            flow_binding = next((row for row in bindings if row.get("set_type") == "flow_set"), None)
            active_binding = next((row for row in bindings if row.get("active")), None)
            if not power_binding or not flow_binding or not active_binding:
                continue
            power_type = str(power_binding.get("target_dev_type", ""))
            power_name = str(power_binding.get("target_dev_name", ""))
            flow_type = str(flow_binding.get("target_dev_type", ""))
            flow_name = str(flow_binding.get("target_dev_name", ""))
            flow_key = (flow_type, flow_name)
            hydrogen_island_id, island_tanks, topology_error = (
                _hydrogen_island_pressure_state(
                    resource_topology,
                    pressure_by_island,
                    flow_key,
                )
            )
            if topology_error:
                diagnostics["warnings"].append(
                    f"氢能设备{coupling_name}{topology_error}，本设备已按 fail closed 禁止自动调节"
                )
                continue
            pressure_blocked = bool(
                any(
                    float(row["pressure"]) >= float(row["highGuard"])
                    for row in island_tanks
                )
                if is_electrolyzer
                else any(
                    float(row["pressure"]) < float(row["lowGuard"])
                    for row in island_tanks
                )
            )
            island_soc_values = [
                float(row["soc"])
                for row in island_tanks
                if row.get("online")
                and row.get("socKnown")
                and _number(row.get("soc")) is not None
                and math.isfinite(float(row["soc"]))
            ]
            online_island_tanks = [row for row in island_tanks if row.get("online")]
            hydrogen_storage_soc = (
                sum(island_soc_values) / len(island_soc_values)
                if online_island_tanks
                and len(island_soc_values) == len(online_island_tanks)
                else None
            )
            power_row = model_rows.get((power_type, power_name), {})
            flow_row = model_rows.get((flow_type, flow_name), {})
            power_device = devices.get((power_type, power_name))
            flow_device = devices.get((flow_type, flow_name))
            if (
                not power_device
                or not flow_device
                or not _is_online(power_device, measurements)
                or not _is_online(flow_device, measurements)
            ):
                continue
            coefficient_field = "e2h_coeff" if is_electrolyzer else "h2e_coeff"
            coefficient = _number(coupling.get(coefficient_field))
            if coefficient is None or coefficient <= EPSILON:
                continue
            power_min = _number(power_row.get("p_min"))
            power_max = _number(power_row.get("p_max"))
            rated_power_kw = _rated_capacity(power_row, power_device, "hydrogen")
            flow_min = _number(flow_row.get("flow_min"))
            flow_max = _number(flow_row.get("flow_max"))
            if (
                power_min is None
                or power_max is None
                or power_min > power_max
                or rated_power_kw <= EPSILON
                or flow_min is None
                or flow_max is None
                or flow_min > flow_max
            ):
                continue
            power_measurement = _measured(
                measurements,
                _device_type(power_device),
                power_name,
                ("P_LOAD", "P_GEN", "P", "P_AC", "P_DC"),
            )
            flow_measurement = _measured(
                measurements,
                _device_type(flow_device),
                flow_name,
                ("FLOW",),
            )
            if power_measurement is not None:
                current_power = abs(power_measurement.value)
            elif flow_measurement is not None:
                current_power = (
                    abs(flow_measurement.value) / float(coefficient)
                    if is_electrolyzer
                    else abs(flow_measurement.value) * float(coefficient)
                )
            else:
                diagnostics["warnings"].append(
                    f"氢能设备{coupling_name}缺少实时电功率和氢流量量测，已按 fail closed 保持当前状态"
                )
                continue
            if is_electrolyzer:
                flow_power_max = max(0.0, float(flow_max)) / float(coefficient)
                flow_power_min = max(0.0, float(flow_min)) / float(coefficient)
                configured_minimum = (
                    float(settings.electrolyzer_power_min_kw)
                    if settings.electrolyzer_power_min_kw is not None
                    else settings.electrolyzer_power_min_ratio * rated_power_kw
                )
                configured_maximum = (
                    float(settings.electrolyzer_power_max_kw)
                    if settings.electrolyzer_power_max_kw is not None
                    else settings.electrolyzer_power_max_ratio * rated_power_kw
                )
                power_deadband_kw = (
                    float(settings.electrolyzer_power_deadband_kw)
                    if settings.electrolyzer_power_deadband_kw is not None
                    else settings.electrolyzer_power_deadband_ratio * rated_power_kw
                )
                step_kw = (
                    float(settings.electrolyzer_power_step_kw)
                    if settings.electrolyzer_power_step_kw is not None
                    else settings.electrolyzer_power_step_ratio * rated_power_kw
                )
            else:
                flow_power_max = max(0.0, float(flow_max)) * float(coefficient)
                flow_power_min = max(0.0, float(flow_min)) * float(coefficient)
                configured_minimum = (
                    float(settings.fuel_cell_power_min_kw)
                    if settings.fuel_cell_power_min_kw is not None
                    else settings.fuel_cell_power_min_ratio * rated_power_kw
                )
                configured_maximum = (
                    float(settings.fuel_cell_power_max_kw)
                    if settings.fuel_cell_power_max_kw is not None
                    else settings.fuel_cell_power_max_ratio * rated_power_kw
                )
                power_deadband_kw = (
                    float(settings.fuel_cell_power_deadband_kw)
                    if settings.fuel_cell_power_deadband_kw is not None
                    else settings.fuel_cell_power_deadband_ratio * rated_power_kw
                )
                step_kw = (
                    float(settings.fuel_cell_power_step_kw)
                    if settings.fuel_cell_power_step_kw is not None
                    else settings.fuel_cell_power_step_ratio * rated_power_kw
                )
            allowed_power = min(
                max(0.0, float(power_max)),
                flow_power_max,
                configured_maximum,
            )
            physical_minimum_power = max(
                0.0,
                float(power_min),
                flow_power_min,
            )
            minimum_running_power = max(
                physical_minimum_power,
                configured_minimum,
            )
            start_threshold_kw = minimum_running_power + power_deadband_kw
            stop_threshold_kw = max(
                physical_minimum_power,
                minimum_running_power - power_deadband_kw,
            )
            if (
                minimum_running_power > allowed_power + EPSILON
                or start_threshold_kw > allowed_power + EPSILON
            ):
                diagnostics["warnings"].append(
                    f"氢能设备{coupling_name}配置上下限与模型功率/流量边界无有效运行区间，"
                    "本设备已按 fail closed 禁止自动调节"
                )
                continue

            power_hysteresis_stop = False
            safety_stop = pressure_blocked and current_power > EPSILON
            device_action = "electrolyzer" if is_electrolyzer else "fuel_cell"
            device_action_reason = ""
            requested_delta_kw = 0.0
            required_start_delta_kw: Optional[float] = None
            predicted_diesel_load_ratio = predicted_diesel_kw / diesel_capacity_kw
            fuel_cell_decision = None
            if is_electrolyzer:
                diesel_raise_margin_kw = max(
                    0.0,
                    electrolyzer_diesel_limit_ratio * diesel_capacity_kw
                    - predicted_diesel_kw,
                )
                diesel_reduce_margin_kw = max(
                    0.0,
                    predicted_diesel_kw
                    - (
                        electrolyzer_diesel_limit_ratio
                        + electrolyzer_diesel_deadband_ratio
                    )
                    * diesel_capacity_kw,
                )
                electrolyzer_raise_allowed = bool(
                    diesel_raise_margin_kw > EPSILON
                    and electric_storage_soc is not None
                    and electric_storage_soc
                    > settings.electrolyzer_storage_soc_start_minimum + EPSILON
                    and hydrogen_storage_soc is not None
                    and hydrogen_storage_soc
                    < settings.electrolyzer_hydrogen_storage_soc_stop_minimum
                    - EPSILON
                    and hydrogen_mode_lock != "fuel_cell"
                    and conflict_stop_mode != "electrolyzer"
                )
                electrolyzer_reduce_required = bool(
                    diesel_reduce_margin_kw > EPSILON
                    or (
                        electric_storage_soc is not None
                        and electric_storage_soc
                        < settings.electrolyzer_storage_soc_stop_maximum - EPSILON
                    )
                    or (
                        hydrogen_storage_soc is not None
                        and hydrogen_storage_soc
                        > settings.electrolyzer_hydrogen_storage_soc_stop_minimum
                        + EPSILON
                    )
                )
            else:
                fuel_cell_decision = calculate_fuel_cell_power_decision(
                    FuelCellControlParameters(
                        power_step_kw=step_kw,
                        diesel_power_limit_ratio=fuel_cell_diesel_limit_ratio,
                        electric_storage_soc_limit=settings.fuel_cell_storage_soc_limit,
                        hydrogen_storage_soc_start_limit=(
                            settings.fuel_cell_hydrogen_storage_soc_upper_limit
                        ),
                        hydrogen_storage_soc_stop_limit=(
                            settings.fuel_cell_hydrogen_storage_soc_lower_limit
                        ),
                    ),
                    FuelCellControlInputs(
                        current_power_kw=current_power,
                        maximum_power_kw=allowed_power,
                        start_threshold_kw=start_threshold_kw,
                        stop_threshold_kw=stop_threshold_kw,
                        diesel_power_kw=predicted_diesel_kw,
                        diesel_capacity_kw=diesel_capacity_kw,
                        electric_storage_soc_average=electric_storage_soc,
                        hydrogen_storage_soc_average=hydrogen_storage_soc,
                    ),
                )
                if (
                    (
                        hydrogen_mode_lock == "electrolyzer"
                        or conflict_stop_mode == "fuel_cell"
                    )
                    and fuel_cell_decision.action in {"start", "increase"}
                ):
                    diagnostics["warnings"].append(
                        f"氢能设备{coupling_name}受电制氢运行互锁，已禁止燃料电池启动或升功率"
                    )
                    fuel_cell_decision = FuelCellControlDecision(
                        action="hold",
                        reason="hydrogen_mode_interlock",
                        diesel_raise_margin_kw=(
                            fuel_cell_decision.diesel_raise_margin_kw
                        ),
                        diesel_reduce_margin_kw=(
                            fuel_cell_decision.diesel_reduce_margin_kw
                        ),
                    )
            conflict_stops_device = bool(
                hydrogen_mode_lock == "conflict"
                and (
                    (is_electrolyzer and conflict_stop_mode == "electrolyzer")
                    or (not is_electrolyzer and conflict_stop_mode == "fuel_cell")
                )
            )
            if conflict_stops_device and current_power > EPSILON:
                requested_delta_kw = -current_power
                device_action = "hydrogen_interlock_stop"
                device_action_reason = (
                    f"simultaneous_operation_stop_{conflict_stop_mode}"
                )
            elif pressure_blocked:
                requested_delta_kw = -current_power
            elif current_power > EPSILON and current_power < stop_threshold_kw - EPSILON:
                requested_delta_kw = -current_power
                power_hysteresis_stop = True
                device_action = "power_hysteresis_stop"
            elif electric_storage_soc is None or hydrogen_storage_soc is None:
                diagnostics["warnings"].append(
                    f"氢能设备{coupling_name}缺少完整的在线电储平均SOC或本氢岛氢储平均SOC，已按 fail closed 保持当前功率"
                )
                continue
            elif is_electrolyzer and current_power > EPSILON:
                if electrolyzer_raise_allowed:
                    requested_delta_kw = min(
                        diesel_raise_margin_kw,
                        step_kw,
                        max(0.0, allowed_power - current_power),
                    )
                elif electrolyzer_reduce_required:
                    device_action = "electrolyzer_reduce"
                    requested_delta_kw = -min(
                        (
                            diesel_reduce_margin_kw
                            if diesel_reduce_margin_kw > EPSILON
                            else step_kw
                        ),
                        step_kw,
                        current_power,
                    )
            elif is_electrolyzer:
                if not electrolyzer_raise_allowed:
                    if (
                        hydrogen_mode_lock == "fuel_cell"
                        or conflict_stop_mode == "electrolyzer"
                    ):
                        diagnostics["warnings"].append(
                            f"氢能设备{coupling_name}受燃料电池运行互锁，已禁止制氢启动"
                        )
                    else:
                        start_blockers: List[str] = []
                        if diesel_raise_margin_kw <= EPSILON:
                            start_blockers.append(
                                f"柴发负载率{predicted_diesel_load_ratio * 100:.3f}%未低于启机限值"
                                f"{electrolyzer_diesel_limit_ratio * 100:.3f}%"
                            )
                        if (
                            electric_storage_soc
                            <= settings.electrolyzer_storage_soc_start_minimum + EPSILON
                        ):
                            start_blockers.append(
                                f"电储SOC{electric_storage_soc * 100:.3f}%未严格高于启机阈值"
                                f"{settings.electrolyzer_storage_soc_start_minimum * 100:.3f}%"
                            )
                        if (
                            hydrogen_storage_soc
                            >= settings.electrolyzer_hydrogen_storage_soc_stop_minimum
                            - EPSILON
                        ):
                            start_blockers.append(
                                f"本氢岛氢储SOC{hydrogen_storage_soc * 100:.3f}%未严格低于停机阈值"
                                f"{settings.electrolyzer_hydrogen_storage_soc_stop_minimum * 100:.3f}%"
                            )
                        diagnostics["warnings"].append(
                            f"氢能设备{coupling_name}制氢启动条件未满足："
                            f"{'；'.join(start_blockers) or '存在未识别的启机阻断条件'}；已保持停机"
                        )
                    continue
                required_start_delta_kw = start_threshold_kw
                if required_start_delta_kw > diesel_raise_margin_kw + EPSILON:
                    diagnostics["warnings"].append(
                        f"氢能设备{coupling_name}需要一次达到启动功率"
                        f"{start_threshold_kw:.3f} kW，当前柴发调节裕度仅"
                        f"{diesel_raise_margin_kw:.3f} kW，已保持停机"
                    )
                    continue
                requested_delta_kw = required_start_delta_kw
            else:
                if fuel_cell_decision is None:
                    continue
                requested_delta_kw = fuel_cell_decision.requested_delta_kw
                required_start_delta_kw = fuel_cell_decision.required_start_delta_kw
                device_action_reason = fuel_cell_decision.reason
                if fuel_cell_decision.action in {"decrease", "stop"}:
                    device_action = "fuel_cell_reduce"
                if fuel_cell_decision.reason == "start_margin_insufficient":
                    diagnostics["warnings"].append(
                        f"氢能设备{coupling_name}需要一次达到启动功率"
                        f"{start_threshold_kw:.3f} kW，当前柴发调节裕度或设备功率上限不足，已保持停机"
                    )
                    continue
                if fuel_cell_decision.action == "hold":
                    continue

            proposed_power = max(0.0, current_power + requested_delta_kw)
            if (
                not pressure_blocked
                and current_power > EPSILON
                and requested_delta_kw < -EPSILON
                and proposed_power < stop_threshold_kw - EPSILON
            ):
                requested_delta_kw = -current_power
                proposed_power = 0.0
                power_hysteresis_stop = True
                device_action = "power_hysteresis_stop"
            if abs(requested_delta_kw) <= EPSILON and not pressure_blocked:
                continue
            active_set_type = str(
                active_binding.get("target_set_type", active_binding.get("set_type", ""))
            )
            current_active_value = (
                current_power
                if active_set_type == "p_set"
                else current_power * float(coefficient)
                if is_electrolyzer
                else current_power / float(coefficient)
            )
            active_type = str(active_binding.get("target_dev_type", ""))
            active_name = str(active_binding.get("target_dev_name", ""))
            active_device = devices.get((active_type, active_name))
            if (
                not active_device
                or _preferred_set_type(
                    snapshot,
                    active_device,
                    (active_set_type,),
                )
                != active_set_type
            ):
                continue
            electric_side = "AC" if power_type.startswith("AC") else "DC"
            dc_group_id = (
                _node_in_dc_transfer_group(resource_topology, power_row.get("node"))
                if electric_side == "DC"
                else ""
            )
            accepted_delta_kw = requested_delta_kw
            converter_rows: List[MutableMapping[str, Any]] = []
            converter_request_kw = 0.0
            if electric_side == "DC" and abs(accepted_delta_kw) > EPSILON:
                converter_rows = [
                    row
                    for row in command_rows
                    if _is_grid_converter_row(row)
                    and row.get("online")
                    and row.get("commandable") is not False
                    and str(row.get("dcTransferGroupId", "")) == dc_group_id
                ]
                if not dc_group_id or not converter_rows:
                    diagnostics["warnings"].append(
                        f"氢能设备{coupling_name}直流拓扑组无可调ACDC，已取消本设备氢能增量"
                    )
                    continue
                converter_request_kw = (
                    -accepted_delta_kw if is_electrolyzer else accepted_delta_kw
                )
                converter_probe = [copy.deepcopy(row) for row in converter_rows]
                converter_delivered_kw = _allocate_converter_ac_injection_delta(
                    converter_probe,
                    converter_request_kw,
                    step_ratio=settings.converter_step_ratio,
                )
                accepted_magnitude = min(
                    abs(accepted_delta_kw),
                    abs(converter_delivered_kw),
                )
                accepted_delta_kw = math.copysign(
                    accepted_magnitude,
                    accepted_delta_kw,
                )
                converter_request_kw = math.copysign(
                    accepted_magnitude,
                    converter_request_kw,
                )

            diesel_delta_kw = (
                accepted_delta_kw if is_electrolyzer else -accepted_delta_kw
            )
            if diesel_command_rows and abs(diesel_delta_kw) > EPSILON:
                diesel_margin_kw = _row_command_delta_margin(
                    diesel_command_rows,
                    increase=diesel_delta_kw > 0.0,
                )
                accepted_magnitude = min(abs(accepted_delta_kw), diesel_margin_kw)
                accepted_delta_kw = math.copysign(
                    accepted_magnitude,
                    accepted_delta_kw,
                )
                diesel_delta_kw = math.copysign(
                    accepted_magnitude,
                    diesel_delta_kw,
                )
                if electric_side == "DC":
                    converter_request_kw = math.copysign(
                        accepted_magnitude,
                        converter_request_kw,
                    )
            if abs(accepted_delta_kw) <= EPSILON and not (
                pressure_blocked and current_power <= EPSILON
            ):
                diagnostics["warnings"].append(
                    f"氢能设备{coupling_name}的氢端、ACDC步长或平衡设备无共同调节裕度，已原子保持"
                )
                continue

            if (
                required_start_delta_kw is not None
                and accepted_delta_kw < required_start_delta_kw - EPSILON
            ):
                diagnostics["warnings"].append(
                    f"氢能设备{coupling_name}当前氢端、ACDC或平衡设备共同裕度不足以一次达到"
                    f"启动功率{start_threshold_kw:.3f} kW，已保持停机"
                )
                continue
            target_power = max(0.0, current_power + accepted_delta_kw)
            target_flow = (
                target_power * float(coefficient)
                if is_electrolyzer
                else target_power / float(coefficient)
            )
            if target_power > EPSILON and (
                target_power < physical_minimum_power - EPSILON
                or target_power > allowed_power + EPSILON
                or target_flow < max(0.0, float(flow_min)) - EPSILON
                or target_flow > max(0.0, float(flow_max)) + EPSILON
            ):
                diagnostics["warnings"].append(
                    f"氢能设备{coupling_name}原子限幅后目标落入设备禁运区，已保持当前值"
                )
                continue
            set_value = target_power if active_set_type == "p_set" else target_flow
            active_key = (active_type, active_name, active_set_type)
            active_row = current_command_by_key.get(active_key)
            if active_row is None:
                active_row = {
                    "category": "氢能",
                    "dev_type": active_type,
                    "model_block": active_type,
                    "dev_name": active_name,
                    "online": True,
                    "commandable": True,
                    "strategyCommand": True,
                    "dispatchEnabled": bool(apply_electrical_corrections),
                    "set_type": active_set_type,
                    "currentKw": current_active_value,
                    "commandKw": set_value,
                    "statusLabel": "综合新能源策略",
                }
                command_rows.append(active_row)
                current_command_by_key[active_key] = active_row
            else:
                active_row["commandKw"] = set_value
                active_row["strategyCommand"] = True
                active_row["dispatchEnabled"] = bool(
                    apply_electrical_corrections
                )
            if (
                apply_electrical_corrections
                and electric_side == "DC"
                and abs(converter_request_kw) > EPSILON
            ):
                converter_correction += _allocate_converter_ac_injection_delta(
                    converter_rows,
                    converter_request_kw,
                    step_ratio=settings.converter_step_ratio,
                )
            if (
                apply_electrical_corrections
                and diesel_command_rows
                and abs(diesel_delta_kw) > EPSILON
            ):
                balance_correction += _allocate_row_command_delta(
                    diesel_command_rows,
                    diesel_delta_kw,
                )
            planned.append(
                {
                    "action": (
                        f"{device_action}_pressure_safety_stop"
                        if safety_stop
                        else f"{device_action}_pressure_safe_zero"
                        if pressure_blocked
                        else device_action
                    ),
                    "couplingType": coupling_type,
                    "couplingName": coupling_name,
                    "activeDevType": active_type,
                    "activeDevName": active_name,
                    "activeSetType": active_set_type,
                    "setValue": set_value,
                    "electricSide": electric_side,
                    "electricPowerKw": target_power,
                    "electricDeltaKw": accepted_delta_kw,
                    "equivalentFlow": target_flow,
                    "dcTransferGroupId": dc_group_id,
                    "hydrogenIslandId": hydrogen_island_id,
                    "dieselLoadRatioBefore": predicted_diesel_load_ratio,
                    "electricStorageSocAverage": electric_storage_soc,
                    "hydrogenStorageSocAverage": hydrogen_storage_soc,
                    "controlReason": device_action_reason,
                    "stepLimitKw": step_kw,
                    "minimumRunningPowerKw": minimum_running_power,
                    "physicalMinimumPowerKw": physical_minimum_power,
                    "configuredMinimumPowerKw": configured_minimum,
                    "configuredMaximumPowerKw": configured_maximum,
                    "ratedPowerKw": rated_power_kw,
                    "powerDeadbandKw": power_deadband_kw,
                    "startThresholdKw": start_threshold_kw,
                    "stopThresholdKw": stop_threshold_kw,
                    "pressureSafetyStop": pressure_blocked,
                    "powerHysteresisStop": power_hysteresis_stop,
                }
            )
            if accepted_delta_kw > EPSILON and not hydrogen_mode_lock:
                hydrogen_mode_lock = (
                    "electrolyzer" if is_electrolyzer else "fuel_cell"
                )
                diagnostics["interlockMode"] = hydrogen_mode_lock
                diagnostics["interlockActive"] = True
            predicted_diesel_kw += diesel_delta_kw
    diagnostics.update(
        {
            "action": (
                "pressure_safety_stop"
                if planned and any(row.get("pressureSafetyStop") for row in planned)
                else "power_hysteresis_stop"
                if planned and any(row.get("powerHysteresisStop") for row in planned)
                else str(planned[0].get("action", "hold"))
                if planned
                else "blocked"
                if diagnostics["warnings"]
                else "hold"
            ),
            "electricPowerAdjustmentKw": sum(
                float(row["electricDeltaKw"]) for row in planned
            ),
            "targetElectricPowerKw": sum(
                float(row["electricPowerKw"]) for row in planned
            ),
            "targetEquivalentFlow": sum(
                float(row["equivalentFlow"]) for row in planned
            ),
            "commands": planned,
            "converterCorrectionKw": converter_correction,
            "balanceCorrectionKw": balance_correction,
            "predictedDieselAfterKw": predicted_diesel_kw,
            "predictedDieselLoadRatioAfter": predicted_diesel_kw
            / diesel_capacity_kw,
            "predictedDieselAverageAfterKw": predicted_diesel_kw
            / diesel_unit_count,
        }
    )
    diagnostics.update(
        _hydrogen_operating_metrics(
            snapshot,
            measurements,
            pressure_states,
            planned,
        )
    )
    if not planned:
        diagnostics["warnings"].append(
            "氢能触发条件已满足，但耦合设备、遥调点、实时量测或设备边界不完整，未生成氢能策略"
        )
    return diagnostics


def _runtime_mode(snapshot: Mapping[str, Any], device: Mapping[str, Any]) -> str:
    settings = snapshot.get("settings")
    modes = settings.get("modes", []) if isinstance(settings, Mapping) else []
    override: Mapping[str, Any] = {}
    for row in modes if isinstance(modes, Sequence) else []:
        if not isinstance(row, Mapping):
            continue
        if str(row.get("dev_type", "")) == _device_type(device) and str(row.get("dev_name", "")) == _device_name(device):
            override = row
            break
    raw_domains = device.get("terminal_domains", ())
    terminal_domains = {
        str(value).strip().upper()
        for value in raw_domains
        if str(value).strip()
    } if isinstance(raw_domains, (list, tuple, set)) else set()
    raw = device.get("raw") if isinstance(device.get("raw"), Mapping) else {}
    if terminal_domains == {"AC", "DC"} or (
        "ac_node" in raw and "dc_node" in raw
    ):
        override_mode = str(
            override.get("mode") or override.get("control_type") or ""
        ).strip().upper()
        if override_mode and override_mode != "NONE":
            return override_mode
        return converter_control_mode(
            {
                **dict(raw),
                "mode": device.get("mode", raw.get("mode", "")),
            }
        )
    return str(
        override.get("mode")
        or override.get("control_type")
        or device.get("mode")
        or raw.get("ac_control_type")
        or raw.get("control_type")
        or raw.get("dc_control_type")
        or ""
    ).strip().upper()


@dataclass(frozen=True)
class RenewableControlSettings:
    # Simulation-clock seconds between automatic control decisions.
    interval_seconds: float = default_number("simulation_control_interval_seconds")
    soc_min: float = default_number("soc_min")
    soc_max: float = default_number("soc_max")
    large_step_threshold_kw: float = default_number("large_step_threshold_kw")
    step_coefficient: float = default_number("renewable_step_ratio")
    storage_step_ratio: float = default_number(
        "grid_following_storage_step_ratio"
    )
    storage_soc_correction_step_scale: float = default_number(
        "storage_soc_correction_step_scale"
    )
    grid_forming_storage_protection_ratio: float = default_number(
        "grid_forming_storage_protection_ratio"
    )
    diesel_power_protection_ratio: float = default_number(
        "diesel_power_protection_ratio"
    )
    soc_deadband: float = default_number("soc_deadband")
    hydrogen_closed_loop_enabled: bool = default_boolean(
        "hydrogen_closed_loop_enabled"
    )
    hydrogen_pressure_deadband_ratio: float = default_number(
        "hydrogen_pressure_deadband_ratio"
    )
    electrolyzer_power_min_ratio: float = default_number("electrolyzer_power_min_ratio")
    electrolyzer_power_max_ratio: float = default_number("electrolyzer_power_max_ratio")
    electrolyzer_power_deadband_ratio: float = default_number(
        "electrolyzer_power_deadband_ratio"
    )
    electrolyzer_power_step_ratio: float = default_number("electrolyzer_power_step_ratio")
    electrolyzer_diesel_power_limit_ratio: float = default_number(
        "electrolyzer_diesel_power_limit_ratio"
    )
    electrolyzer_diesel_power_deadband_ratio: float = default_number(
        "electrolyzer_diesel_power_deadband_ratio"
    )
    electrolyzer_storage_soc_start_minimum: float = default_number(
        "electrolyzer_storage_soc_start_minimum"
    )
    electrolyzer_storage_soc_stop_maximum: float = default_number(
        "electrolyzer_storage_soc_stop_maximum"
    )
    electrolyzer_hydrogen_storage_soc_stop_minimum: float = default_number(
        "electrolyzer_hydrogen_storage_soc_stop_minimum"
    )
    fuel_cell_power_min_ratio: float = default_number("fuel_cell_power_min_ratio")
    fuel_cell_power_max_ratio: float = default_number("fuel_cell_power_max_ratio")
    fuel_cell_power_deadband_ratio: float = default_number(
        "fuel_cell_power_deadband_ratio"
    )
    fuel_cell_power_step_ratio: float = default_number("fuel_cell_power_step_ratio")
    fuel_cell_diesel_power_limit_ratio: float = default_number(
        "fuel_cell_diesel_power_limit_ratio"
    )
    fuel_cell_storage_soc_limit: float = default_number(
        "fuel_cell_storage_soc_limit"
    )
    fuel_cell_hydrogen_storage_soc_upper_limit: float = default_number(
        "fuel_cell_hydrogen_storage_soc_upper_limit"
    )
    fuel_cell_hydrogen_storage_soc_lower_limit: float = default_number(
        "fuel_cell_hydrogen_storage_soc_lower_limit"
    )
    converter_step_ratio: float = default_number("legacy_converter_step_ratio")
    storage_charge_derating_curve: Tuple[Tuple[float, float], ...] = DEFAULT_STORAGE_CHARGE_DERATING_CURVE
    storage_discharge_derating_curve: Tuple[Tuple[float, float], ...] = DEFAULT_STORAGE_DISCHARGE_DERATING_CURVE
    command_valid_minutes: float = default_number("command_valid_minutes")
    optimization_renewable_curtailment_weight: float = default_number(
        "optimization_renewable_curtailment_weight"
    )
    optimization_diesel_output_weight: float = default_number(
        "optimization_diesel_output_weight"
    )
    optimization_curtailment_square_weight: float = default_number(
        "optimization_curtailment_square_weight"
    )
    optimization_source_storage_adjustment_square_weight: float = default_number(
        "optimization_source_storage_adjustment_square_weight"
    )
    optimization_balance_delta_square_weight: float = default_number(
        "optimization_balance_delta_square_weight"
    )
    optimization_balance_delta_warning_kw: float = default_number(
        "optimization_balance_delta_warning_kw"
    )
    optimization_balance_tolerance_kw: float = default_number(
        "optimization_balance_tolerance_kw"
    )
    optimization_bound_tolerance_kw: float = default_number(
        "optimization_bound_tolerance_kw"
    )
    optimization_ftol: float = default_number("optimization_ftol")
    optimization_max_iterations: int = default_integer(
        "optimization_max_iterations"
    )
    # Constructor-only compatibility for older callers. Persisted settings and
    # WEB payloads are migrated to ratios and never emit these absolute fields.
    electrolyzer_power_min_kw: Optional[float] = None
    electrolyzer_power_max_kw: Optional[float] = None
    electrolyzer_power_deadband_kw: Optional[float] = None
    electrolyzer_power_step_kw: Optional[float] = None
    electrolyzer_diesel_power_limit_kw: Optional[float] = None
    electrolyzer_diesel_power_deadband_kw: Optional[float] = None
    fuel_cell_power_min_kw: Optional[float] = None
    fuel_cell_power_max_kw: Optional[float] = None
    fuel_cell_power_deadband_kw: Optional[float] = None
    fuel_cell_power_step_kw: Optional[float] = None
    fuel_cell_diesel_power_limit_kw: Optional[float] = None
    # Constructor-only compatibility. The legacy names described physical bounds,
    # but their actual planner semantics were upper -> start and lower -> stop.
    electrolyzer_storage_soc_lower_limit: Optional[float] = None
    electrolyzer_storage_soc_upper_limit: Optional[float] = None
    electrolyzer_hydrogen_storage_soc_upper_limit: Optional[float] = None

    def __post_init__(self) -> None:
        if self.electrolyzer_storage_soc_upper_limit is not None:
            object.__setattr__(
                self,
                "electrolyzer_storage_soc_start_minimum",
                float(self.electrolyzer_storage_soc_upper_limit),
            )
        if self.electrolyzer_storage_soc_lower_limit is not None:
            object.__setattr__(
                self,
                "electrolyzer_storage_soc_stop_maximum",
                float(self.electrolyzer_storage_soc_lower_limit),
            )
        if self.electrolyzer_hydrogen_storage_soc_upper_limit is not None:
            object.__setattr__(
                self,
                "electrolyzer_hydrogen_storage_soc_stop_minimum",
                float(self.electrolyzer_hydrogen_storage_soc_upper_limit),
            )

    def normalized(self) -> "RenewableControlSettings":
        minimum = _clamp(float(self.soc_min), 0.0, 1.0)
        maximum = _clamp(float(self.soc_max), minimum, 1.0)
        storage_step_ratio = max(0.0, float(self.storage_step_ratio))
        legacy_converter_step_ratio = max(0.0, float(self.converter_step_ratio))
        if (
            legacy_converter_step_ratio > EPSILON
            and abs(
                storage_step_ratio
                - DEFAULT_GRID_FOLLOWING_STORAGE_STEP_RATIO
            )
            <= EPSILON
        ):
            storage_step_ratio = legacy_converter_step_ratio
        electrolyzer_power_min_ratio = _clamp(
            float(self.electrolyzer_power_min_ratio), 0.0, 1.0
        )
        electrolyzer_power_max_ratio = _clamp(
            float(self.electrolyzer_power_max_ratio),
            electrolyzer_power_min_ratio,
            1.0,
        )
        fuel_cell_power_min_ratio = _clamp(
            float(self.fuel_cell_power_min_ratio), 0.0, 1.0
        )
        fuel_cell_power_max_ratio = _clamp(
            float(self.fuel_cell_power_max_ratio),
            fuel_cell_power_min_ratio,
            1.0,
        )
        electrolyzer_storage_soc_start_minimum = _clamp(
            float(self.electrolyzer_storage_soc_start_minimum), 0.0, 1.0
        )
        electrolyzer_storage_soc_stop_maximum = _clamp(
            float(self.electrolyzer_storage_soc_stop_maximum), 0.0, 1.0
        )
        fuel_cell_hydrogen_storage_soc_lower_limit = _clamp(
            float(self.fuel_cell_hydrogen_storage_soc_lower_limit), 0.0, 1.0
        )
        fuel_cell_hydrogen_storage_soc_upper_limit = _clamp(
            float(self.fuel_cell_hydrogen_storage_soc_upper_limit),
            fuel_cell_hydrogen_storage_soc_lower_limit,
            1.0,
        )
        return replace(
            self,
            interval_seconds=max(
                MINIMUM_CONTROL_INTERVAL_SECONDS,
                float(self.interval_seconds),
            ),
            soc_min=minimum,
            soc_max=maximum,
            large_step_threshold_kw=max(0.0, float(self.large_step_threshold_kw)),
            step_coefficient=max(0.0, float(self.step_coefficient)),
            storage_step_ratio=storage_step_ratio,
            storage_soc_correction_step_scale=_clamp(
                float(self.storage_soc_correction_step_scale),
                0.10,
                1.0,
            ),
            grid_forming_storage_protection_ratio=_clamp(
                float(self.grid_forming_storage_protection_ratio),
                0.0,
                MAXIMUM_POWER_PROTECTION_RATIO,
            ),
            diesel_power_protection_ratio=_clamp(
                float(self.diesel_power_protection_ratio),
                0.0,
                MAXIMUM_POWER_PROTECTION_RATIO,
            ),
            soc_deadband=_clamp(float(self.soc_deadband), 0.0, 1.0),
            hydrogen_closed_loop_enabled=bool(
                self.hydrogen_closed_loop_enabled
            ),
            hydrogen_pressure_deadband_ratio=_clamp(
                float(self.hydrogen_pressure_deadband_ratio),
                0.0,
                0.5,
            ),
            electrolyzer_power_min_ratio=electrolyzer_power_min_ratio,
            electrolyzer_power_max_ratio=electrolyzer_power_max_ratio,
            electrolyzer_power_deadband_ratio=_clamp(
                float(self.electrolyzer_power_deadband_ratio),
                0.0,
                electrolyzer_power_max_ratio - electrolyzer_power_min_ratio,
            ),
            electrolyzer_power_step_ratio=_clamp(
                float(self.electrolyzer_power_step_ratio),
                EPSILON,
                1.0,
            ),
            electrolyzer_diesel_power_limit_ratio=_clamp(
                float(self.electrolyzer_diesel_power_limit_ratio), 0.0, 1.0
            ),
            electrolyzer_diesel_power_deadband_ratio=_clamp(
                float(self.electrolyzer_diesel_power_deadband_ratio), 0.0, 1.0
            ),
            electrolyzer_storage_soc_start_minimum=electrolyzer_storage_soc_start_minimum,
            electrolyzer_storage_soc_stop_maximum=electrolyzer_storage_soc_stop_maximum,
            electrolyzer_hydrogen_storage_soc_stop_minimum=_clamp(
                float(self.electrolyzer_hydrogen_storage_soc_stop_minimum),
                0.0,
                1.0,
            ),
            fuel_cell_power_min_ratio=fuel_cell_power_min_ratio,
            fuel_cell_power_max_ratio=fuel_cell_power_max_ratio,
            fuel_cell_power_deadband_ratio=_clamp(
                float(self.fuel_cell_power_deadband_ratio),
                0.0,
                fuel_cell_power_max_ratio - fuel_cell_power_min_ratio,
            ),
            fuel_cell_power_step_ratio=_clamp(
                float(self.fuel_cell_power_step_ratio),
                EPSILON,
                1.0,
            ),
            fuel_cell_diesel_power_limit_ratio=_clamp(
                float(self.fuel_cell_diesel_power_limit_ratio), 0.0, 1.0
            ),
            fuel_cell_storage_soc_limit=_clamp(
                float(self.fuel_cell_storage_soc_limit), 0.0, 1.0
            ),
            fuel_cell_hydrogen_storage_soc_upper_limit=fuel_cell_hydrogen_storage_soc_upper_limit,
            fuel_cell_hydrogen_storage_soc_lower_limit=fuel_cell_hydrogen_storage_soc_lower_limit,
            converter_step_ratio=0.0,
            storage_charge_derating_curve=_normalized_derating_curve(
                self.storage_charge_derating_curve,
                DEFAULT_STORAGE_CHARGE_DERATING_CURVE,
                increasing=False,
            ),
            storage_discharge_derating_curve=_normalized_derating_curve(
                self.storage_discharge_derating_curve,
                DEFAULT_STORAGE_DISCHARGE_DERATING_CURVE,
                increasing=True,
            ),
            command_valid_minutes=max(
                MINIMUM_COMMAND_VALID_MINUTES,
                float(self.command_valid_minutes),
            ),
            optimization_renewable_curtailment_weight=max(
                0.0, float(self.optimization_renewable_curtailment_weight)
            ),
            optimization_diesel_output_weight=max(
                0.0, float(self.optimization_diesel_output_weight)
            ),
            optimization_curtailment_square_weight=max(
                0.0, float(self.optimization_curtailment_square_weight)
            ),
            optimization_source_storage_adjustment_square_weight=max(
                0.0,
                float(self.optimization_source_storage_adjustment_square_weight),
            ),
            optimization_balance_delta_square_weight=max(
                EPSILON, float(self.optimization_balance_delta_square_weight)
            ),
            optimization_balance_delta_warning_kw=max(
                0.0, float(self.optimization_balance_delta_warning_kw)
            ),
            optimization_balance_tolerance_kw=max(
                EPSILON, float(self.optimization_balance_tolerance_kw)
            ),
            optimization_bound_tolerance_kw=max(
                EPSILON, float(self.optimization_bound_tolerance_kw)
            ),
            optimization_ftol=max(EPSILON, float(self.optimization_ftol)),
            optimization_max_iterations=max(
                1, int(self.optimization_max_iterations)
            ),
            electrolyzer_storage_soc_lower_limit=None,
            electrolyzer_storage_soc_upper_limit=None,
            electrolyzer_hydrogen_storage_soc_upper_limit=None,
        )

    def updated(self, payload: Mapping[str, Any]) -> "RenewableControlSettings":
        aliases = {
            "interval_seconds": (
                "simulation_interval_seconds",
                "simulationIntervalSeconds",
                "interval_seconds",
                "intervalSeconds",
            ),
            "soc_min": ("soc_min", "socMin"),
            "soc_max": ("soc_max", "socMax"),
            "large_step_threshold_kw": ("large_step_threshold_kw", "largeStepThresholdKw"),
            "step_coefficient": (
                "step_coefficient",
                "stepCoefficient",
                "renewableStepRatePerMinute",
                "renewableStepRatio",
            ),
            "storage_step_ratio": (
                "storage_step_ratio",
                "storageStepRatePerMinute",
                "storageStepRatio",
                "gridFollowingStorageStepRatio",
            ),
            "storage_soc_correction_step_scale": (
                "storage_soc_correction_step_scale",
                "storageSocCorrectionStepScale",
            ),
            "grid_forming_storage_protection_ratio": (
                "grid_forming_storage_protection_ratio",
                "gridFormingStorageProtectionRatio",
            ),
            "diesel_power_protection_ratio": (
                "diesel_power_protection_ratio",
                "dieselPowerProtectionRatio",
                "diesel_deadband_ratio",
                "dieselDeadbandRatio",
            ),
            "soc_deadband": ("soc_deadband", "socDeadband"),
            "hydrogen_pressure_deadband_ratio": (
                "hydrogen_pressure_deadband_ratio",
                "hydrogenPressureDeadbandRatio",
            ),
            "electrolyzer_power_min_ratio": (
                "electrolyzer_power_min_ratio",
                "electrolyzerPowerMinRatio",
            ),
            "electrolyzer_power_max_ratio": (
                "electrolyzer_power_max_ratio",
                "electrolyzerPowerMaxRatio",
            ),
            "electrolyzer_power_deadband_ratio": (
                "electrolyzer_power_deadband_ratio",
                "electrolyzerPowerDeadbandRatio",
            ),
            "electrolyzer_power_step_ratio": (
                "electrolyzer_power_step_ratio",
                "electrolyzerPowerStepRatio",
            ),
            "electrolyzer_diesel_power_limit_ratio": (
                "electrolyzer_diesel_power_limit_ratio",
                "electrolyzerDieselPowerLimitRatio",
            ),
            "electrolyzer_diesel_power_deadband_ratio": (
                "electrolyzer_diesel_power_deadband_ratio",
                "electrolyzerDieselPowerDeadbandRatio",
            ),
            "electrolyzer_storage_soc_start_minimum": (
                "electrolyzer_storage_soc_start_minimum",
                "electrolyzerStorageSocStartMinimum",
                "electrolyzer_storage_soc_upper_limit",
                "electrolyzerStorageSocUpperLimit",
            ),
            "electrolyzer_storage_soc_stop_maximum": (
                "electrolyzer_storage_soc_stop_maximum",
                "electrolyzerStorageSocStopMaximum",
                "electrolyzer_storage_soc_lower_limit",
                "electrolyzerStorageSocLowerLimit",
            ),
            "electrolyzer_hydrogen_storage_soc_stop_minimum": (
                "electrolyzer_hydrogen_storage_soc_stop_minimum",
                "electrolyzerHydrogenStorageSocStopMinimum",
                "electrolyzer_hydrogen_storage_soc_upper_limit",
                "electrolyzerHydrogenStorageSocUpperLimit",
            ),
            "fuel_cell_power_min_ratio": (
                "fuel_cell_power_min_ratio",
                "fuelCellPowerMinRatio",
            ),
            "fuel_cell_power_max_ratio": (
                "fuel_cell_power_max_ratio",
                "fuelCellPowerMaxRatio",
            ),
            "fuel_cell_power_deadband_ratio": (
                "fuel_cell_power_deadband_ratio",
                "fuelCellPowerDeadbandRatio",
            ),
            "fuel_cell_power_step_ratio": (
                "fuel_cell_power_step_ratio",
                "fuelCellPowerStepRatio",
            ),
            "fuel_cell_diesel_power_limit_ratio": (
                "fuel_cell_diesel_power_limit_ratio",
                "fuelCellDieselPowerLimitRatio",
            ),
            "fuel_cell_storage_soc_limit": (
                "fuel_cell_storage_soc_limit",
                "fuelCellStorageSocLimit",
            ),
            "fuel_cell_hydrogen_storage_soc_upper_limit": (
                "fuel_cell_hydrogen_storage_soc_upper_limit",
                "fuelCellHydrogenStorageSocUpperLimit",
            ),
            "fuel_cell_hydrogen_storage_soc_lower_limit": (
                "fuel_cell_hydrogen_storage_soc_lower_limit",
                "fuelCellHydrogenStorageSocLowerLimit",
            ),
            "command_valid_minutes": ("command_valid_minutes", "commandValidMinutes"),
            "optimization_renewable_curtailment_weight": (
                "optimization_renewable_curtailment_weight",
                "optimizationRenewableCurtailmentWeight",
            ),
            "optimization_diesel_output_weight": (
                "optimization_diesel_output_weight",
                "optimizationDieselOutputWeight",
            ),
            "optimization_curtailment_square_weight": (
                "optimization_curtailment_square_weight",
                "optimizationCurtailmentSquareWeight",
            ),
            "optimization_source_storage_adjustment_square_weight": (
                "optimization_source_storage_adjustment_square_weight",
                "optimizationSourceStorageAdjustmentSquareWeight",
            ),
            "optimization_balance_delta_square_weight": (
                "optimization_balance_delta_square_weight",
                "optimizationBalanceDeltaSquareWeight",
            ),
            "optimization_balance_delta_warning_kw": (
                "optimization_balance_delta_warning_kw",
                "optimizationBalanceDeltaWarningKw",
            ),
            "optimization_balance_tolerance_kw": (
                "optimization_balance_tolerance_kw",
                "optimizationBalanceToleranceKw",
            ),
            "optimization_bound_tolerance_kw": (
                "optimization_bound_tolerance_kw",
                "optimizationBoundToleranceKw",
            ),
            "optimization_ftol": (
                "optimization_ftol",
                "optimizationFtol",
            ),
            "optimization_max_iterations": (
                "optimization_max_iterations",
                "optimizationMaxIterations",
            ),
        }
        values: Dict[str, Any] = {}
        for field_name, names in aliases.items():
            for name in names:
                if name in payload:
                    parsed = _number(payload.get(name))
                    if parsed is not None:
                        values[field_name] = parsed
                    break
        for name in (
            "hydrogen_closed_loop_enabled",
            "hydrogenClosedLoopEnabled",
        ):
            if name in payload:
                values["hydrogen_closed_loop_enabled"] = _boolean(
                    payload.get(name),
                    self.hydrogen_closed_loop_enabled,
                )
                break
        legacy_percent_aliases = {
            "electrolyzer_power_min_ratio": ("electrolyzer_power_min_kw", "electrolyzerPowerMinKw"),
            "electrolyzer_power_max_ratio": ("electrolyzer_power_max_kw", "electrolyzerPowerMaxKw"),
            "electrolyzer_power_deadband_ratio": ("electrolyzer_power_deadband_kw", "electrolyzerPowerDeadbandKw"),
            "electrolyzer_power_step_ratio": ("electrolyzer_power_step_kw", "electrolyzerPowerStepKw"),
            "electrolyzer_diesel_power_limit_ratio": ("electrolyzer_diesel_power_limit_kw", "electrolyzerDieselPowerLimitKw"),
            "electrolyzer_diesel_power_deadband_ratio": ("electrolyzer_diesel_power_deadband_kw", "electrolyzerDieselPowerDeadbandKw"),
            "fuel_cell_power_min_ratio": ("fuel_cell_power_min_kw", "fuelCellPowerMinKw"),
            "fuel_cell_power_max_ratio": ("fuel_cell_power_max_kw", "fuelCellPowerMaxKw"),
            "fuel_cell_power_deadband_ratio": ("fuel_cell_power_deadband_kw", "fuelCellPowerDeadbandKw"),
            "fuel_cell_power_step_ratio": ("fuel_cell_power_step_kw", "fuelCellPowerStepKw"),
            "fuel_cell_diesel_power_limit_ratio": ("fuel_cell_diesel_power_limit_kw", "fuelCellDieselPowerLimitKw"),
        }
        for field_name, names in legacy_percent_aliases.items():
            if field_name in values:
                continue
            for name in names:
                if name not in payload:
                    continue
                parsed = _number(payload.get(name))
                if parsed is not None:
                    values[field_name] = parsed / 100.0
                break
        if not any(
            name in payload
            for name in (
                "storage_step_ratio",
                "storageStepRatePerMinute",
                "storageStepRatio",
                "gridFollowingStorageStepRatio",
            )
        ):
            legacy_storage_step = _number(
                payload.get(
                    "converter_step_ratio",
                    payload.get("converterStepRatio"),
                )
            )
            if legacy_storage_step is not None:
                values["storage_step_ratio"] = legacy_storage_step
        if not any(
            name in payload
            for name in (
                "grid_forming_storage_protection_ratio",
                "gridFormingStorageProtectionRatio",
            )
        ):
            legacy_storage_protection = _number(
                payload.get(
                    "storage_switch_deadband_kw",
                    payload.get("storageSwitchDeadbandKw"),
                )
            )
            if legacy_storage_protection is not None:
                values["grid_forming_storage_protection_ratio"] = (
                    legacy_storage_protection / 100.0
                )
        charge_curve = payload.get(
            "storage_charge_derating_curve",
            payload.get("storageChargeDeratingCurve"),
        )
        discharge_curve = payload.get(
            "storage_discharge_derating_curve",
            payload.get("storageDischargeDeratingCurve"),
        )
        if charge_curve is not None:
            values["storage_charge_derating_curve"] = _normalized_derating_curve(
                charge_curve,
                self.storage_charge_derating_curve,
                increasing=False,
            )
        if discharge_curve is not None:
            values["storage_discharge_derating_curve"] = _normalized_derating_curve(
                discharge_curve,
                self.storage_discharge_derating_curve,
                increasing=True,
            )
        return replace(self, **values).normalized()

    def payload(self) -> Dict[str, Any]:
        return {
            "simulationIntervalSeconds": self.interval_seconds,
            "intervalSeconds": self.interval_seconds,
            "socMin": self.soc_min,
            "socMax": self.soc_max,
            "largeStepThresholdKw": self.large_step_threshold_kw,
            "stepCoefficient": self.step_coefficient,
            "renewableStepRatio": self.step_coefficient,
            "storageStepRatio": self.storage_step_ratio,
            "storageSocCorrectionStepScale": self.storage_soc_correction_step_scale,
            "gridFormingStorageProtectionRatio": self.grid_forming_storage_protection_ratio,
            "dieselPowerProtectionRatio": self.diesel_power_protection_ratio,
            "socDeadband": self.soc_deadband,
            "hydrogenClosedLoopEnabled": self.hydrogen_closed_loop_enabled,
            "hydrogenPressureDeadbandRatio": self.hydrogen_pressure_deadband_ratio,
            "electrolyzerPowerMinRatio": self.electrolyzer_power_min_ratio,
            "electrolyzerPowerMaxRatio": self.electrolyzer_power_max_ratio,
            "electrolyzerPowerDeadbandRatio": self.electrolyzer_power_deadband_ratio,
            "electrolyzerPowerStepRatio": self.electrolyzer_power_step_ratio,
            "electrolyzerDieselPowerLimitRatio": self.electrolyzer_diesel_power_limit_ratio,
            "electrolyzerDieselPowerDeadbandRatio": self.electrolyzer_diesel_power_deadband_ratio,
            "electrolyzerStorageSocStartMinimum": self.electrolyzer_storage_soc_start_minimum,
            "electrolyzerStorageSocStopMaximum": self.electrolyzer_storage_soc_stop_maximum,
            "electrolyzerHydrogenStorageSocStopMinimum": self.electrolyzer_hydrogen_storage_soc_stop_minimum,
            "fuelCellPowerMinRatio": self.fuel_cell_power_min_ratio,
            "fuelCellPowerMaxRatio": self.fuel_cell_power_max_ratio,
            "fuelCellPowerDeadbandRatio": self.fuel_cell_power_deadband_ratio,
            "fuelCellPowerStepRatio": self.fuel_cell_power_step_ratio,
            "fuelCellDieselPowerLimitRatio": self.fuel_cell_diesel_power_limit_ratio,
            "fuelCellStorageSocLimit": self.fuel_cell_storage_soc_limit,
            "fuelCellHydrogenStorageSocUpperLimit": self.fuel_cell_hydrogen_storage_soc_upper_limit,
            "fuelCellHydrogenStorageSocLowerLimit": self.fuel_cell_hydrogen_storage_soc_lower_limit,
            "storageChargeDeratingCurve": _derating_curve_payload(self.storage_charge_derating_curve),
            "storageDischargeDeratingCurve": _derating_curve_payload(self.storage_discharge_derating_curve),
            "commandValidMinutes": self.command_valid_minutes,
            "optimizationRenewableCurtailmentWeight": self.optimization_renewable_curtailment_weight,
            "optimizationDieselOutputWeight": self.optimization_diesel_output_weight,
            "optimizationCurtailmentSquareWeight": self.optimization_curtailment_square_weight,
            "optimizationSourceStorageAdjustmentSquareWeight": self.optimization_source_storage_adjustment_square_weight,
            "optimizationBalanceDeltaSquareWeight": self.optimization_balance_delta_square_weight,
            "optimizationBalanceDeltaWarningKw": self.optimization_balance_delta_warning_kw,
            "optimizationBalanceToleranceKw": self.optimization_balance_tolerance_kw,
            "optimizationBoundToleranceKw": self.optimization_bound_tolerance_kw,
            "optimizationFtol": self.optimization_ftol,
            "optimizationMaxIterations": self.optimization_max_iterations,
        }


class _Quality:
    def __init__(self, source: str, snapshot_age_seconds: float) -> None:
        self.source = source
        self.snapshot_age_seconds = max(0.0, float(snapshot_age_seconds))
        self.issues: List[str] = []
        self.inputs: Dict[str, Dict[str, Any]] = {}
        self.blocked = False
        self.dispatch_forbidden = source not in {"remote", "trainee-live"}
        if source in {"cached", "trainee-cache"}:
            self.add("学员台实时交换更新失败，当前使用最近一次有效快照", dispatch_forbidden=True)
        elif source == "local":
            self.add("当前使用学员台本地模型数据，不允许闭环下发", dispatch_forbidden=True)

    def input(self, name: str, value: Any, source: str, valid: bool = True) -> None:
        self.inputs[name] = {"value": value, "source": source, "valid": bool(valid)}

    def add(self, message: str, *, blocked: bool = False, dispatch_forbidden: bool = False) -> None:
        if message and message not in self.issues:
            self.issues.append(message)
        self.blocked = self.blocked or blocked
        self.dispatch_forbidden = self.dispatch_forbidden or dispatch_forbidden or blocked

    def payload(self) -> Dict[str, Any]:
        status = "blocked" if self.blocked else "degraded" if self.issues else "ok"
        return {
            "status": status,
            "dispatchAllowed": not self.dispatch_forbidden,
            "source": self.source,
            "snapshotAgeSeconds": round(self.snapshot_age_seconds, 3),
            "issues": list(self.issues),
            "inputs": copy.deepcopy(self.inputs),
        }


def _rated_capacity(row: Mapping[str, Any], device: Optional[Mapping[str, Any]], category: str) -> float:
    del category
    raw = device.get("raw") if device and isinstance(device.get("raw"), Mapping) else {}
    return _positive(
        (
            row.get("rated_power"),
            row.get("rated_capacity"),
            row.get("p_max"),
            raw.get("rated_capacity"),
            raw.get("rated_power"),
            raw.get("p_max"),
        )
    )


def _curve_boundary_value(snapshot: Mapping[str, Any], key: str) -> Optional[float]:
    boundary = snapshot.get("curve_boundary")
    point = boundary.get("point") if isinstance(boundary, Mapping) else None
    return _number(point.get(key)) if isinstance(point, Mapping) else None


def _observed_environment_value(
    snapshot: Mapping[str, Any],
    measurement: Optional[MeasurementValue],
    boundary_key: str,
) -> Optional[float]:
    if measurement is not None and math.isfinite(measurement.value):
        return measurement.value
    return _curve_boundary_value(snapshot, boundary_key)


def _load_boundary(
    snapshot: Mapping[str, Any],
    measurements: Mapping[Tuple[str, str, str], MeasurementValue],
    quality: _Quality,
) -> float:
    total = 0.0
    sources: set[str] = set()
    measured_count = 0
    for device in snapshot.get("devices", []) or []:
        if not isinstance(device, Mapping) or _device_model_block(device) not in {"ACLoad", "DCLoad"}:
            continue
        if not _is_online(device, measurements):
            continue
        measured = _measured(
            measurements,
            _device_type(device),
            _device_name(device),
            ("P_LOAD", "P", "P_AC", "P_DC"),
        )
        if measured is None:
            continue
        total += measured.value
        measured_count += 1
        sources.add(measured.source)
    if measured_count:
        source = next(iter(sources)) if len(sources) == 1 else "mixed"
        quality.input("load", total, source, True)
        return total

    boundary = snapshot.get("curve_boundary")
    boundary_load = _number(boundary.get("load_total")) if isinstance(boundary, Mapping) else None
    if boundary_load is not None and boundary_load >= 0:
        quality.input("load", boundary_load, "curve_boundary", True)
        return boundary_load

    estimated = 0.0
    estimated_count = 0
    for device in snapshot.get("devices", []) or []:
        if not isinstance(device, Mapping) or _device_model_block(device) not in {"ACLoad", "DCLoad"}:
            continue
        if not _is_online(device, measurements):
            continue
        raw = device.get("raw") if isinstance(device.get("raw"), Mapping) else {}
        values = device.get("set_values") if isinstance(device.get("set_values"), Mapping) else {}
        value = _number(values.get("p_set", raw.get("pv0", raw.get("p_set"))))
        if value is not None and value >= 0:
            estimated += value
            estimated_count += 1
    if estimated_count:
        quality.input("load", estimated, "model_setpoint", True)
        return estimated

    quality.input("load", None, "missing", False)
    return 0.0


def _normalized_generation_current(
    measured: Optional[MeasurementValue],
    capacity_kw: float,
    quality: _Quality,
    label: str,
) -> Tuple[Optional[float], Optional[float]]:
    if measured is None:
        return None, None
    current = measured.value
    if capacity_kw > 0 and current > capacity_kw:
        quality.add(
            f"{label}实时有功 {current:g} kW 超过额定容量 {capacity_kw:g} kW"
        )
    return current, current


def _topology_payload(
    spec: _LinkedResourceSpec,
    connection: Optional[ResourceConnection],
) -> Dict[str, Any]:
    if connection is None:
        return {
            "technology": spec.technology,
            "resourceDevType": spec.dev_type,
            "resourceDevName": spec.dev_name,
            "connectionSide": "INVALID",
            "activelyConnected": False,
            "busbarType": "",
            "busbarName": "",
            "busbarNode": "",
            "structuralPath": [],
            "activePath": [],
            "converterPath": [],
            "gridComponentId": "",
            "dcTransferGroupId": "",
            "topologyStatusLabel": "资源模型引用或端子无效",
        }
    return {
        "technology": spec.technology,
        "resourceDevType": spec.dev_type,
        "resourceDevName": spec.dev_name,
        "connectionSide": connection.connection_side,
        "activelyConnected": bool(connection.actively_connected),
        "busbarType": connection.busbar_type,
        "busbarName": connection.busbar_name,
        "busbarNode": connection.busbar_node,
        "structuralPath": list(connection.structural_path),
        "activePath": list(connection.active_path),
        "converterPath": list(connection.converter_path),
        "gridComponentId": connection.grid_component_id,
        "dcTransferGroupId": connection.dc_transfer_group_id,
        "topologyStatusLabel": connection.topology_status_label,
    }


def _renewable_rows(
    snapshot: Mapping[str, Any],
    measurements: Mapping[Tuple[str, str, str], MeasurementValue],
    resource_specs: Sequence[_LinkedResourceSpec],
    connections: Mapping[Tuple[str, str], ResourceConnection],
    quality: _Quality,
    *,
    observed_wind_speed: Optional[float] = None,
    observed_solar_irradiance: Optional[float] = None,
    observed_air_temperature: Optional[float] = None,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    categories = {
        ("wind", "AC"): "交流风电",
        ("wind", "DC"): "直流风电",
        ("pv", "AC"): "交流光伏",
        ("pv", "DC"): "直流光伏",
    }
    for spec in resource_specs:
        device = spec.device
        dev_type = spec.dev_type
        name = spec.dev_name
        topology = _topology_payload(spec, connections.get(spec.topology_key))
        connection_side = topology["connectionSide"]
        device_online = _is_online(device, measurements)
        online = device_online and topology["activelyConnected"]
        capacity = _rated_capacity(
            spec.parameter,
            device,
            "风电" if spec.technology == "wind" else "光伏",
        )
        weather_available_kw = _renewable_weather_available_kw(
            spec.technology,
            spec.parameter,
            capacity,
            wind_speed=observed_wind_speed,
            solar_irradiance=observed_solar_irradiance,
            air_temperature=observed_air_temperature,
        )
        measured = (
            _measured(measurements, dev_type, name, ("P_GEN", "P", "P_AC", "P_DC"))
            if device_online
            else None
        )
        category = categories.get(
            (spec.technology, connection_side),
            "拓扑未解析新能源",
        )
        current, planning_current = _normalized_generation_current(
            measured,
            capacity,
            quality,
            f"{category}{name}",
        )
        set_type = _preferred_set_type(snapshot, device, ("p_set",))
        capability_known = capacity > EPSILON
        recovery_ready = planning_current is not None and capability_known
        signed_baseline_valid = planning_current is None or planning_current >= 0.0
        capacity_baseline_valid = (
            planning_current is None
            or not capability_known
            or planning_current <= capacity
        )
        identity_valid = not spec.identity_diagnostic
        topology_valid = connection_side in {"AC", "DC"}
        commandable = bool(
            online
            and topology_valid
            and identity_valid
            and set_type
            and recovery_ready
            and signed_baseline_valid
        )

        if not topology_valid:
            quality.add(
                f"新能源{name}拓扑状态{connection_side}：{topology['topologyStatusLabel']}，本轮仅保留诊断"
            )
        elif device_online and not topology["activelyConnected"]:
            quality.add(f"新能源{name}当前拓扑断开，本轮不参与自动策略")
        if device_online and not set_type:
            quality.add(f"新能源{name}缺少有效p_set有功遥调点，本轮仅保留诊断")
        if online and planning_current is not None and planning_current < 0.0:
            quality.add(
                f"新能源{name}实时有功 {planning_current:g} kW 为负，本轮保持原值且不下发自动设点"
            )

        status_label = (
            topology["topologyStatusLabel"]
            if not topology_valid
            else "停用"
            if not device_online
            else "当前断开"
            if not topology["activelyConnected"]
            else "设备身份重复·仅保留诊断"
            if not identity_valid
            else "无遥调点"
            if not set_type
            else "额定容量无效"
            if not capability_known
            else "实时有功未知"
            if planning_current is None
            else "实时有功为负·保持原值"
            if not signed_baseline_valid
            else "实时有功超过容量·校正至额定上限"
            if not capacity_baseline_valid
            else "可控"
        )
        rows.append(
            {
                **topology,
                "category": category,
                "dev_type": dev_type,
                "dev_name": name,
                "source_name": name,
                "deviceOnline": device_online,
                "online": online,
                "environmentKnown": False,
                "weatherAvailableKnown": weather_available_kw is not None,
                "weatherAvailableKw": weather_available_kw,
                "capabilityKnown": capability_known,
                "resourceIdentityValid": identity_valid,
                "resourceIdentityDiagnostic": spec.identity_diagnostic,
                "capacityKw": capacity,
                "currentKw": current if device_online else 0.0,
                "planningCurrentKw": planning_current if device_online else 0.0,
                "headroomKw": (
                    max(0.0, capacity - (planning_current or 0.0))
                    if recovery_ready
                    and signed_baseline_valid
                    else 0.0
                ),
                "commandable": commandable,
                "availableKw": capacity if capability_known else None,
                "set_type": set_type if topology_valid else "",
                "statusLabel": status_label,
            }
        )
    return rows


def _diesel_rows(
    snapshot: Mapping[str, Any],
    measurements: Mapping[Tuple[str, str, str], MeasurementValue],
    resource_keys: Optional[set[Tuple[str, str]]] = None,
    quality: Optional[_Quality] = None,
) -> List[Dict[str, Any]]:
    wind_indexes = {
        str(row.get("idx_acgenerator", "")).strip()
        for row in _parameter_rows(snapshot, "ACWindGen")
        if str(row.get("idx_acgenerator", "")).strip()
    }
    relation_parameters = {
        str(row.get("idx_acgenerator", "")).strip(): row
        for row in _parameter_rows(snapshot, "ACDieselGen")
        if str(row.get("idx_acgenerator", "")).strip()
    }
    rows: List[Dict[str, Any]] = []
    for device in snapshot.get("devices", []) or []:
        if not isinstance(device, Mapping) or _device_model_block(device) != "ACGenerator":
            continue
        if resource_keys and _device_key(device) in resource_keys:
            continue
        if _device_index(device) in wind_indexes:
            continue
        name = _device_name(device)
        dev_type = _device_type(device)
        raw = device.get("raw") if isinstance(device.get("raw"), Mapping) else {}
        parameter = relation_parameters.get(_device_index(device), {})
        if not parameter:
            continue
        online = _is_online(device, measurements)
        capacity = _positive(
            (
                parameter.get("p_max"),
                parameter.get("rated_capacity"),
                parameter.get("rated_power"),
                raw.get("p_max"),
                raw.get("rated_capacity"),
                raw.get("rated_power"),
            )
        )
        rated_capacity = _positive(
            (
                parameter.get("rated_capacity"),
                parameter.get("rated_power"),
                raw.get("rated_capacity"),
                raw.get("rated_power"),
                parameter.get("p_max"),
                raw.get("p_max"),
            )
        )
        defined_min = max(
            0.0,
            _number(
                parameter.get(
                    "p_min",
                    parameter.get("min_power", parameter.get("minimum_power", raw.get("p_min", raw.get("min_power", raw.get("minimum_power"))))),
                ),
                0.0,
            )
            or 0.0,
        )
        minimum = min(defined_min, capacity) if online and capacity > 0 else defined_min if online else 0.0
        measured = _measured(measurements, dev_type, name, ("P_GEN", "P")) if online else None
        current = measured.value if measured else None
        set_type = _preferred_set_type(snapshot, device, ("p_set", "p_ac_set"))
        limits_valid = bool(capacity > EPSILON and minimum <= capacity + EPSILON)
        commandable = bool(
            online
            and current is not None
            and math.isfinite(current)
            and limits_valid
            and set_type
        )
        state_eligible = bool(
            online
            and current is not None
            and math.isfinite(current)
            and limits_valid
        )
        if online and current is None and quality is not None:
            quality.add(f"柴油发电机{name}缺少有效实时有功，本轮禁止直接下发有功策略")
        if online and not limits_valid and quality is not None:
            quality.add(f"柴油发电机{name}有功上下限无效，本轮禁止直接下发有功策略")
        rows.append(
            {
                "category": "柴油发电",
                "dev_type": dev_type,
                "model_block": "ACGenerator",
                "dev_name": name,
                "online": online,
                "commandable": commandable,
                "stateEligible": state_eligible,
                "currentKw": current if online else 0.0,
                "minKw": minimum,
                "capacityKw": capacity,
                "ratedCapacityKw": rated_capacity,
                "set_type": set_type,
                "directDispatchBlockedReason": (
                    "缺少有效p_set有功遥调点"
                    if online and not set_type
                    else "实时有功未知"
                    if online and current is None
                    else "有功上下限无效"
                    if online and not limits_valid
                    else ""
                ),
                "statusLabel": (
                    "停用"
                    if not online
                    else "实时有功未知"
                    if current is None
                    else "有功边界无效"
                    if not limits_valid
                    else "平衡运行·可直控"
                    if set_type
                    else "平衡运行·无有功遥调点"
                ),
            }
        )
    return rows


def _annotate_diesel_topology(
    rows: Sequence[MutableMapping[str, Any]],
    connections: Mapping[Tuple[str, str], ResourceConnection],
    device_component_ids: Mapping[Tuple[str, str], str],
) -> None:
    for row in rows:
        key = (str(row.get("model_block", "")), str(row.get("dev_name", "")))
        connection = connections.get(key)
        component_id = str(device_component_ids.get(key, ""))
        topology_valid = bool(
            connection is not None
            and connection.connection_side == "AC"
            and connection.actively_connected
            and connection.grid_component_id
        )
        row.update(
            {
                "connectionSide": (
                    connection.connection_side if connection is not None else "INVALID"
                ),
                "activelyConnected": bool(
                    connection is not None and connection.actively_connected
                ),
                "busbarType": connection.busbar_type if connection is not None else "",
                "busbarName": connection.busbar_name if connection is not None else "",
                "busbarNode": connection.busbar_node if connection is not None else "",
                "gridComponentId": (
                    connection.grid_component_id
                    if connection is not None
                    else component_id
                ),
                "topologyStatusLabel": (
                    connection.topology_status_label
                    if connection is not None
                    else "资源模型引用或端子无效"
                ),
                "stateEligible": bool(
                    row.get("stateEligible") and topology_valid
                ),
            }
        )
        if not topology_valid:
            row["commandable"] = False
            row["stateEligible"] = False
            row["set_type"] = ""
            row["directDispatchBlockedReason"] = (
                "设备拓扑无效或未活动接入交流分量"
            )
            row["statusLabel"] = "拓扑无效·禁止自动控制"


def _measurement_sample_clock(snapshot: Mapping[str, Any]) -> Mapping[str, Any]:
    measurement_clock = snapshot.get("measurement_clock")
    if (
        isinstance(measurement_clock, Mapping)
        and (_number(measurement_clock.get("step_count"), 0.0) or 0.0) > 0.0
    ):
        return measurement_clock
    clock = snapshot.get("clock")
    return clock if isinstance(clock, Mapping) else {}


def _effective_step_minutes(snapshot: Mapping[str, Any]) -> float:
    parameters = snapshot.get("system_parameters")
    if isinstance(parameters, Mapping):
        effective = _number(parameters.get("effective_step_minutes"))
        if effective is not None and effective > 0:
            return effective
    clock = _measurement_sample_clock(snapshot)
    step = max(
        SIMULATION_MINIMUM_STEP_MINUTES,
        _number(
            clock.get("step_minutes"),
            SIMULATION_DEFAULT_STEP_MINUTES,
        )
        or SIMULATION_DEFAULT_STEP_MINUTES,
    )
    speed = max(
        SIMULATION_MINIMUM_SPEED,
        _number(clock.get("speed"), SIMULATION_DEFAULT_SPEED)
        or SIMULATION_DEFAULT_SPEED,
    )
    return step * speed


def _storage_control_horizon_minutes(
    snapshot: Mapping[str, Any],
    settings: RenewableControlSettings,
) -> float:
    effective_step = _effective_step_minutes(snapshot)
    effective_step_seconds = effective_step * 60.0
    interval_seconds = _simulation_control_interval_seconds(
        settings.interval_seconds
    )
    simulator_steps = max(
        1,
        int(math.ceil(interval_seconds / effective_step_seconds)),
    )
    return effective_step * simulator_steps


def _storage_rows(
    snapshot: Mapping[str, Any],
    measurements: Mapping[Tuple[str, str, str], MeasurementValue],
    settings: RenewableControlSettings,
    quality: _Quality,
    resource_specs: Sequence[_LinkedResourceSpec],
    connections: Mapping[Tuple[str, str], ResourceConnection],
    dc_transfer_groups: Mapping[str, DcTransferGroup],
) -> List[Dict[str, Any]]:
    control_horizon_minutes = _storage_control_horizon_minutes(snapshot, settings)
    step_hours = max(
        STORAGE_MINIMUM_CONTROL_HORIZON_HOURS,
        control_horizon_minutes / 60.0,
    )
    rows: List[Dict[str, Any]] = []
    categories = {
        ("AC", "grid_following"): "交流跟网储能",
        ("DC", "grid_following"): "直流跟网储能",
        ("AC", "balance"): "交流平衡储能",
        ("DC", "balance"): "直流平衡储能",
    }
    for spec in resource_specs:
        parameter = spec.parameter
        device = spec.device
        dev_type = spec.dev_type
        name = spec.dev_name
        topology = _topology_payload(spec, connections.get(spec.topology_key))
        connection_side = topology["connectionSide"]
        topology_valid = connection_side in {"AC", "DC"}
        identity_valid = not spec.identity_diagnostic
        device_online = _is_online(device, measurements)
        online = device_online and topology["activelyConnected"]
        mode = _runtime_mode(snapshot, device).strip().upper()
        preferred_set_type = _preferred_set_type(snapshot, device, ("p_set",))
        role = (
            "grid_following"
            if mode in GRID_FOLLOWING_STORAGE_MODES and preferred_set_type == "p_set"
            else "balance"
            if mode in BALANCE_STORAGE_MODES
            else "uncontrolled"
        )
        set_type = (
            preferred_set_type
            if role in {"grid_following", "balance"}
            else ""
        )
        category = categories.get(
            (connection_side, role),
            "拓扑未解析储能",
        )
        soc_measurement = (
            _measured(measurements, dev_type, name, ("SOC",))
            if device_online
            else None
        )
        live_soc = _live_soc_ratio(soc_measurement.value) if soc_measurement else None
        soc_weight = _number(soc_measurement.row.get("weight"), 0.0) if soc_measurement else 0.0
        soc_noise_sigma = 1.0 / math.sqrt(soc_weight) if soc_weight and soc_weight > 0 else 0.0
        soc = live_soc
        soc_known = live_soc is not None
        if online and not soc_known:
            quality.add(f"储能{name}缺少有效实时SOC，本轮禁止该储能参与充放电调节")
        power = (
            _measured(measurements, dev_type, name, ("P_GEN", "P", "P_AC", "P_DC"))
            if device_online
            else None
        )
        raw = device.get("raw") if isinstance(device.get("raw"), Mapping) else {}
        capacity_value = _positive(
            (
                parameter.get("energy_capacity"),
                parameter.get("capacity_kwh"),
                parameter.get("emva"),
                raw.get("energy_capacity"),
                raw.get("capacity_kwh"),
                raw.get("rated_capacity"),
            )
        )
        calculation_capacity = max(EPSILON, capacity_value)
        lower_value = parameter.get("soc_lower_limit", parameter.get("soc_min"))
        upper_value = parameter.get("soc_upper_limit", parameter.get("soc_max"))
        defined_min = _ratio(lower_value, None)
        defined_max = _ratio(upper_value, None)
        soc_min = _clamp(defined_min if defined_min is not None else settings.soc_min, 0.0, 1.0)
        soc_max = _clamp(defined_max if defined_max is not None else settings.soc_max, soc_min, 1.0)
        efficiency = _storage_efficiency(parameter)
        charge_limit_value = parameter.get(
            "max_charge_power",
            parameter.get("charge_p_max"),
        )
        discharge_limit_value = parameter.get(
            "max_discharge_power",
            parameter.get("dis_charge_p_max", parameter.get("discharge_p_max")),
        )
        parsed_charge_max = _number(charge_limit_value)
        parsed_discharge_max = _number(discharge_limit_value)
        charge_max = max(0.0, parsed_charge_max or 0.0)
        discharge_max = max(0.0, parsed_discharge_max or 0.0)
        lower_present = lower_value is not None and str(lower_value).strip() != ""
        upper_present = upper_value is not None and str(upper_value).strip() != ""
        limits_valid = bool(
            capacity_value > EPSILON
            and parsed_charge_max is not None
            and parsed_charge_max >= 0.0
            and parsed_discharge_max is not None
            and parsed_discharge_max >= 0.0
            and (parsed_charge_max > EPSILON or parsed_discharge_max > EPSILON)
            and (not lower_present or defined_min is not None)
            and (not upper_present or defined_max is not None)
            and soc_min < soc_max - EPSILON
        )
        charge_by_energy = (
            max(
                0.0,
                ((soc_max - (soc or 0.0)) * calculation_capacity)
                / (efficiency * step_hours),
            )
            if soc_known
            else 0.0
        )
        discharge_by_energy = (
            max(
                0.0,
                (((soc or 0.0) - soc_min) * calculation_capacity * efficiency)
                / step_hours,
            )
            if soc_known
            else 0.0
        )
        charge_before_derating = min(charge_max, charge_by_energy)
        discharge_before_derating = min(discharge_max, discharge_by_energy)
        charge_derating_factor = (
            0.0
            if not soc_known or (soc or 0.0) >= soc_max - EPSILON
            else _derating_factor(float(soc), settings.storage_charge_derating_curve)
        )
        discharge_derating_factor = (
            0.0
            if not soc_known or (soc or 0.0) <= soc_min + EPSILON
            else _derating_factor(float(soc), settings.storage_discharge_derating_curve)
        )
        charge_curve_limit = charge_max * charge_derating_factor
        discharge_curve_limit = discharge_max * discharge_derating_factor
        charge_power = min(charge_before_derating, charge_curve_limit)
        discharge_power = min(discharge_before_derating, discharge_curve_limit)
        soc_constraint = (
            "offline"
            if not device_online
            else "disconnected"
            if not topology["activelyConnected"]
            else "unknown"
            if not soc_known
            else "above_upper"
            if (soc or 0.0) >= soc_max
            else "below_lower"
            if (soc or 0.0) <= soc_min
            else "normal"
        )
        if not topology_valid:
            quality.add(
                f"储能{name}拓扑状态{connection_side}：{topology['topologyStatusLabel']}，本轮仅保留诊断"
            )
        elif device_online and not topology["activelyConnected"]:
            quality.add(f"储能{name}当前拓扑断开，本轮不参与自动策略")
        if online and power is None:
            quality.add(
                f"储能{name}缺少有效实时有功，本轮禁止该储能参与自动调节",
                blocked=role == "balance" and topology_valid,
            )
        if device_online and not limits_valid:
            quality.add(f"储能{name}功率边界、能量容量或SOC上下限无效，本轮仅禁用该储能")
        if device_online and role == "uncontrolled":
            quality.add(f"储能{name}控制模式{mode or '--'}或p_set遥调点无效，本轮仅保留诊断")

        group = dc_transfer_groups.get(topology["dcTransferGroupId"])
        indirect_control_devices = [
            {"dev_type": dev_type_value, "dev_name": dev_name_value}
            for dev_type_value, dev_name_value in getattr(group, "converter_keys", ())
        ]
        if not indirect_control_devices:
            indirect_control_devices = [
                {"dev_type": dev_type_value, "dev_name": dev_name_value}
                for dev_type_value, dev_name_value in topology["converterPath"]
                if (dev_type_value, dev_name_value)
                in {
                    key
                    for item in dc_transfer_groups.values()
                    for key in getattr(item, "converter_keys", ())
                }
            ]

        commandable = bool(
            role in {"grid_following", "balance"}
            and topology_valid
            and identity_valid
            and online
            and soc_known
            and power is not None
            and limits_valid
            and set_type == "p_set"
        )
        state_eligible = bool(
            role == "balance"
            and topology_valid
            and identity_valid
            and online
            and soc_known
            and power is not None
            and limits_valid
        )
        status_label = (
            topology["topologyStatusLabel"]
            if not topology_valid
            else "停用"
            if not device_online
            else "当前断开"
            if not topology["activelyConnected"]
            else "设备身份重复·仅保留诊断"
            if not identity_valid
            else "控制模式或遥调点无效"
            if role == "uncontrolled"
            else "SOC未知"
            if not soc_known
            else "实时有功未知"
            if power is None
            else "储能边界无效"
            if not limits_valid
            else "SOC达到上限·禁止充电"
            if soc_constraint == "above_upper"
            else "SOC达到下限·禁止放电"
            if soc_constraint == "below_lower"
            else "构网储能·可直控"
            if role == "balance" and commandable
            else "构网储能·间接校核"
            if role == "balance"
            else f"充电降额 {charge_derating_factor * 100:.0f}%"
            if charge_derating_factor < 1.0 - EPSILON
            else f"放电降额 {discharge_derating_factor * 100:.0f}%"
            if discharge_derating_factor < 1.0 - EPSILON
            else "可控"
        )
        rows.append(
            {
                **topology,
                "category": category,
                "dev_type": dev_type,
                "dev_name": name,
                "source_name": name,
                "deviceOnline": device_online,
                "online": online,
                "resourceIdentityValid": identity_valid,
                "resourceIdentityDiagnostic": spec.identity_diagnostic,
                "commandable": commandable,
                "stateEligible": state_eligible,
                "role": role,
                "mode": mode,
                "currentKw": power.value if power else 0.0 if not device_online else None,
                "soc": soc,
                "socKnown": soc_known,
                "socNoiseSigma": soc_noise_sigma,
                "socMin": soc_min,
                "socMax": soc_max,
                "socConstraint": soc_constraint,
                "capacityKwh": capacity_value,
                "maxChargePowerKw": charge_max,
                "maxDischargePowerKw": discharge_max,
                "limitsValid": limits_valid,
                "chargePowerBeforeDerating": charge_before_derating,
                "dischargePowerBeforeDerating": discharge_before_derating,
                "chargeDeratingFactor": charge_derating_factor,
                "dischargeDeratingFactor": discharge_derating_factor,
                "chargeDeratingCurveLimitKw": charge_curve_limit,
                "dischargeDeratingCurveLimitKw": discharge_curve_limit,
                "chargeDeratingActive": charge_max > EPSILON and charge_derating_factor < 1.0 - EPSILON,
                "dischargeDeratingActive": discharge_max > EPSILON and discharge_derating_factor < 1.0 - EPSILON,
                "chargePower": charge_power,
                "dischargePower": discharge_power,
                "efficiency": efficiency,
                "controlHorizonMinutes": control_horizon_minutes,
                "set_type": set_type,
                "directDispatchBlockedReason": (
                    "缺少有效p_set有功遥调点"
                    if role == "balance" and not set_type
                    else ""
                ),
                "indirectControlDevices": indirect_control_devices,
                "statusLabel": status_label,
            }
        )
    return rows


def _converter_rows(
    snapshot: Mapping[str, Any],
    measurements: Mapping[Tuple[str, str, str], MeasurementValue],
    converter_group_ids: Optional[Mapping[Tuple[str, str], str]] = None,
    internal_converter_keys: Optional[set[Tuple[str, str]]] = None,
    grid_converter_keys: Optional[set[Tuple[str, str]]] = None,
    identity_diagnostics: Optional[Mapping[Tuple[str, str], str]] = None,
    quality: Optional[_Quality] = None,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    devices_by_key: Dict[Tuple[str, str], List[Mapping[str, Any]]] = {}
    dispatchable_keys = set(grid_converter_keys or ())
    for device in snapshot.get("devices", []) or []:
        if not isinstance(device, Mapping):
            continue
        key = _device_model_key(device)
        if key in dispatchable_keys:
            devices_by_key.setdefault(key, []).append(device)

    for key, candidates in devices_by_key.items():
        if key in (internal_converter_keys or set()):
            continue
        if grid_converter_keys is not None and key not in grid_converter_keys:
            continue
        device = min(
            candidates,
            key=lambda item: (
                _natural_topology_identity(_device_index(item)),
                json.dumps(dict(item), ensure_ascii=False, sort_keys=True, default=str),
            ),
        )
        identity_diagnostic = (identity_diagnostics or {}).get(key, "")
        if identity_diagnostic and quality is not None:
            quality.add(identity_diagnostic)
        raw = device.get("raw") if isinstance(device.get("raw"), Mapping) else {}
        converter_role = "grid"
        converter_direction = AC_TO_DC
        ac_balance_coefficient, dc_balance_coefficient = (
            converter_balance_coefficients(converter_direction)
        )
        mode = _runtime_mode(snapshot, device)
        set_type = _preferred_set_type(
            snapshot,
            device,
            converter_power_setpoint_fields(raw),
        )
        online = _is_online(device, measurements)
        measured = _measured(
            measurements,
            _device_type(device),
            _device_name(device),
            ("P_AC", "P_DC", "P"),
        )
        measured_p_ac_kw = None
        if measured is not None and converter_direction:
            measured_type = str(measured.row.get("meas_type", "P_AC") or "P_AC")
            measured_p_ac_kw = converter_power_in_ac_terminal_convention(
                measured.value,
                converter_direction,
                measured_type,
            )
        group_id = (converter_group_ids or {}).get(key, "")
        p_ac_min = _number(
            raw.get(
                "p_ac_min",
                raw.get("ac_p_min", device.get("p_ac_min", device.get("ac_p_min"))),
            )
        )
        p_ac_max = _number(
            raw.get(
                "p_ac_max",
                raw.get("ac_p_max", device.get("p_ac_max", device.get("ac_p_max"))),
            )
        )
        p_ac_limits_valid = bool(
            p_ac_min is not None
            and p_ac_max is not None
            and math.isfinite(p_ac_min)
            and math.isfinite(p_ac_max)
            and p_ac_min <= p_ac_max
        )
        if not p_ac_limits_valid:
            p_dc_min = _number(
                raw.get(
                    "p_dc_min",
                    raw.get("dc_p_min", device.get("p_dc_min", device.get("dc_p_min"))),
                )
            )
            p_dc_max = _number(
                raw.get(
                    "p_dc_max",
                    raw.get("dc_p_max", device.get("p_dc_max", device.get("dc_p_max"))),
                )
            )
            if (
                p_dc_min is not None
                and p_dc_max is not None
                and math.isfinite(p_dc_min)
                and math.isfinite(p_dc_max)
                and p_dc_min <= p_dc_max
            ):
                p_ac_min = -float(p_dc_max)
                p_ac_max = -float(p_dc_min)
        if p_ac_min is None or p_ac_max is None:
            rated_capacity = _positive(
                (
                    raw.get("rated_capacity"),
                    raw.get("rated_power"),
                    device.get("rated_capacity"),
                    device.get("rated_power"),
                )
            )
            if rated_capacity > EPSILON:
                p_ac_min = -rated_capacity
                p_ac_max = rated_capacity
        limits_valid = bool(
            p_ac_min is not None
            and p_ac_max is not None
            and math.isfinite(p_ac_min)
            and math.isfinite(p_ac_max)
            and p_ac_min <= p_ac_max
        )
        signed_min = float(p_ac_min) if limits_valid else 0.0
        signed_max = float(p_ac_max) if limits_valid else 0.0
        transfer_capacity = (
            max(abs(signed_min), abs(signed_max)) if limits_valid else 0.0
        )
        commandable = bool(
            not identity_diagnostic
            and online
            and mode in POWER_CONTROL_MODES
            and set_type
            and measured is not None
            and limits_valid
            and group_id
        )
        diagnostic = ""
        if identity_diagnostic:
            diagnostic = "设备身份重复"
        elif not online:
            diagnostic = "设备离线"
        elif mode not in POWER_CONTROL_MODES:
            diagnostic = f"控制模式{mode or '--'}不支持有功调节"
        elif not set_type:
            diagnostic = "缺少有效有功遥调点"
        elif measured is None:
            diagnostic = "缺少有效实时有功"
        elif not limits_valid:
            diagnostic = "设备有功上下限无效"
        elif not group_id:
            diagnostic = "拓扑无效或未活动接入直流传输组"
        if diagnostic and quality is not None:
            quality.add(
                f"交直流变流器{_device_name(device)}{diagnostic}，本轮禁止自动控制",
                blocked=bool(
                    online
                    and measured is None
                    and group_id
                ),
            )
        rows.append(
            {
                "category": "交直流变流器",
                "dev_type": _device_type(device),
                "model_block": _device_model_block(device),
                "dev_name": _device_name(device),
                "online": online,
                "commandable": commandable,
                "resourceIdentityValid": not identity_diagnostic,
                "resourceIdentityDiagnostic": identity_diagnostic,
                "explicitType": "",
                "converterRole": converter_role,
                "converterRoleSource": "topology",
                "converterDirection": converter_direction,
                "acBalanceCoefficient": ac_balance_coefficient,
                "dcBalanceCoefficient": dc_balance_coefficient,
                "mode": mode,
                "set_type": set_type if commandable else "",
                "currentKw": measured_p_ac_kw,
                "transferCapacityKw": transfer_capacity,
                "signedMinTargetKw": signed_min,
                "signedMaxTargetKw": signed_max,
                "limitsValid": limits_valid,
                "capacitySource": "device_limits" if limits_valid else "missing",
                "dcTransferGroupId": group_id,
                "statusLabel": (
                    f"{diagnostic}·仅保留诊断"
                    if diagnostic
                    else (
                        f"双向并联 {mode}·系统汇总P_DC正向DC→AC"
                    )
                ),
            }
        )
    return rows


def _apply_grid_forming_fail_closed_scopes(
    renewable_rows: Sequence[MutableMapping[str, Any]],
    storage_rows: Sequence[MutableMapping[str, Any]],
    converter_rows: Sequence[MutableMapping[str, Any]],
    diesel_rows: Sequence[MutableMapping[str, Any]],
    quality: _Quality,
) -> Dict[str, set[str]]:
    blocked_ac_components: set[str] = set()
    blocked_dc_groups: set[str] = set()
    for row in storage_rows:
        if (
            row.get("role") != "balance"
            or not row.get("deviceOnline")
            or not row.get("activelyConnected")
            or row.get("stateEligible")
        ):
            continue
        side = str(row.get("connectionSide", ""))
        scope_id = str(
            row.get("gridComponentId", "")
            if side == "AC"
            else row.get("dcTransferGroupId", "")
        )
        if not scope_id:
            continue
        missing = []
        if not row.get("socKnown"):
            missing.append("SOC")
        if _number(row.get("currentKw")) is None:
            missing.append("实时有功")
        if not row.get("limitsValid"):
            missing.append("功率/能量/SOC边界")
        if not missing:
            missing.append("设备身份或拓扑状态")
        if side == "AC":
            blocked_ac_components.add(scope_id)
            scope_label = f"交流分量闭锁（{scope_id}）"
        else:
            blocked_dc_groups.add(scope_id)
            scope_label = f"直流传输组闭锁（{scope_id}）"
        reason = (
            f"构网储能{row.get('dev_name', '')}缺少有效{'、'.join(missing)}，"
            f"{scope_label}，禁止该范围自动策略"
        )
        row["automaticControlBlocked"] = True
        row["automaticControlBlockedReason"] = reason
        quality.add(reason)

    def block_row(row: MutableMapping[str, Any], reason: str) -> None:
        row["commandable"] = False
        row["stateEligible"] = False
        row["automaticControlBlocked"] = True
        row["automaticControlBlockedReason"] = reason
        status = str(row.get("statusLabel", "")).strip()
        row["statusLabel"] = f"{status}·自动闭锁" if status else "自动闭锁"

    for row in (*renewable_rows, *storage_rows):
        side = str(row.get("connectionSide", ""))
        blocked = (
            side == "AC"
            and str(row.get("gridComponentId", "")) in blocked_ac_components
            or side == "DC"
            and str(row.get("dcTransferGroupId", "")) in blocked_dc_groups
        )
        if blocked:
            block_row(row, "所在构网储能控制范围的数据不完整")

    for row in converter_rows:
        group_id = str(row.get("dcTransferGroupId", ""))
        if group_id in blocked_dc_groups:
            block_row(row, "所在直流传输组的构网储能数据不完整")

    if blocked_ac_components:
        for row in diesel_rows:
            block_row(row, "交流构网储能控制范围的数据不完整")

    return {
        "acComponents": blocked_ac_components,
        "dcTransferGroups": blocked_dc_groups,
    }


def _optimization_component_ids_for_row(
    row: Mapping[str, Any],
    topology: ResourceTopology,
) -> Tuple[str, ...]:
    key = (
        str(row.get("model_block") or row.get("dev_type") or ""),
        str(row.get("dev_name") or ""),
    )
    endpoints = topology.converter_component_ids.get(key)
    if endpoints:
        return tuple(component_id for component_id in endpoints if component_id)
    side = str(row.get("connectionSide", "")).strip().upper()
    if side == "AC":
        component_id = str(row.get("gridComponentId", "")).strip()
    elif side == "DC":
        component_id = str(
            row.get("dcTransferGroupId") or row.get("gridComponentId") or ""
        ).strip()
    else:
        component_id = str(topology.device_component_ids.get(key, "")).strip()
    return (component_id,) if component_id else ()


def _blocked_optimization_component_ids(
    topology: ResourceTopology,
    fail_closed_scopes: Mapping[str, Iterable[str]],
    renewable_rows: Sequence[Mapping[str, Any]],
    storage_rows: Sequence[Mapping[str, Any]],
    diesel_rows: Sequence[Mapping[str, Any]],
    converter_rows: Sequence[Mapping[str, Any]],
    quality: _Quality,
) -> Tuple[str, ...]:
    blocked = {
        str(component_id).strip()
        for scope_name in ("acComponents", "dcTransferGroups")
        for component_id in fail_closed_scopes.get(scope_name, ())
        if str(component_id).strip()
    }
    for row in (*renewable_rows, *storage_rows, *diesel_rows, *converter_rows):
        if not row.get("online"):
            continue
        if (
            _number(row.get("currentKw")) is not None
            and not row.get("automaticControlBlocked")
        ):
            continue
        blocked.update(_optimization_component_ids_for_row(row, topology))
    if quality.blocked:
        blocked.update(
            str(component_id).strip()
            for component_id in topology.device_component_ids.values()
            if str(component_id).strip()
        )
        blocked.update(
            str(component_id).strip()
            for endpoints in topology.converter_component_ids.values()
            for component_id in endpoints
            if str(component_id).strip()
        )
    return tuple(sorted(blocked))


@dataclass(frozen=True)
class _RenewableStorageIslandComponent:
    grid_component_id: str
    dc_transfer_group_id: str
    renewable_rows: Tuple[Mapping[str, Any], ...]
    storage_rows: Tuple[Mapping[str, Any], ...]
    converter_rows: Tuple[Mapping[str, Any], ...]


def _natural_topology_identity(value: Any) -> Tuple[Tuple[int, Any], ...]:
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part.casefold())
        for part in re.split(r"(\d+)", str(value))
        if part
    )


def _converter_row_sort_key(row: Mapping[str, Any]) -> Tuple[Any, ...]:
    return (
        _natural_topology_identity(row.get("dcTransferGroupId", "")),
        _natural_topology_identity(row.get("dev_type", "")),
        _natural_topology_identity(row.get("dev_name", "")),
    )


def _dc_transfer_group_sort_key(
    topology: ResourceTopology,
    group_id: str,
) -> Tuple[Any, ...]:
    group = topology.dc_transfer_groups.get(group_id)
    nodes = tuple(
        _natural_topology_identity(node)
        for node in getattr(group, "dc_nodes", ())
    )
    return nodes, group_id


def _active_dc_transfer_group_ids(
    topology: ResourceTopology,
    rows: Sequence[Mapping[str, Any]],
) -> set[str]:
    rows_by_group: Dict[str, List[Mapping[str, Any]]] = {}
    for row in rows:
        group_id = str(row.get("dcTransferGroupId", ""))
        if group_id:
            rows_by_group.setdefault(group_id, []).append(row)

    active_group_ids: set[str] = set()
    for group_id in topology.dc_transfer_groups:
        group_rows = [row for row in rows_by_group.get(group_id, []) if row.get("online")]
        converters = [
            row
            for row in group_rows
            if _is_grid_converter_row(row)
            and row.get("commandable") is not False
        ]
        dc_rows = [row for row in group_rows if row.get("connectionSide") == "DC"]
        if group_rows and converters and dc_rows:
            active_group_ids.add(group_id)
    return active_group_ids


def _renewable_storage_island_components(
    renewable_rows: Sequence[Mapping[str, Any]],
    storage_rows: Sequence[Mapping[str, Any]],
    converter_rows: Sequence[Mapping[str, Any]],
) -> List[_RenewableStorageIslandComponent]:
    storage_by_component: Dict[Tuple[str, str], List[Mapping[str, Any]]] = {}
    for row in storage_rows:
        key = (
            str(row.get("gridComponentId", "")),
            str(row.get("dcTransferGroupId", "")),
        )
        if all(key):
            storage_by_component.setdefault(key, []).append(row)

    renewable_by_component: Dict[Tuple[str, str], List[Mapping[str, Any]]] = {}
    component_order: List[Tuple[str, str]] = []
    for row in renewable_rows:
        key = (
            str(row.get("gridComponentId", "")),
            str(row.get("dcTransferGroupId", "")),
        )
        if not all(key):
            continue
        if key not in renewable_by_component:
            component_order.append(key)
            renewable_by_component[key] = []
        renewable_by_component[key].append(row)

    converters_by_group: Dict[str, List[Mapping[str, Any]]] = {}
    for row in converter_rows:
        group_id = str(row.get("dcTransferGroupId", ""))
        if group_id:
            converters_by_group.setdefault(group_id, []).append(row)

    return [
        _RenewableStorageIslandComponent(
            grid_component_id=component_id,
            dc_transfer_group_id=group_id,
            renewable_rows=tuple(renewable_by_component[(component_id, group_id)]),
            storage_rows=tuple(storage_by_component[(component_id, group_id)]),
            converter_rows=tuple(converters_by_group.get(group_id, ())),
        )
        for component_id, group_id in component_order
        if (component_id, group_id) in storage_by_component
    ]


def _plan_renewable_storage_island_component(
    component: _RenewableStorageIslandComponent,
    settings: RenewableControlSettings,
) -> Dict[str, Any]:
    known_soc_rows = [
        row
        for row in component.storage_rows
        if row.get("socKnown") and row.get("soc") is not None
    ]
    storage_soc = _capacity_weighted_soc(known_soc_rows)
    total_soc_weight = sum(
        (
            _finite_number(row.get("capacityKwh"))
            if _finite_number(row.get("capacityKwh")) > EPSILON
            else 1.0
        )
        for row in known_soc_rows
    )
    storage_soc_upper_limit = (
        sum(
            _finite_number(row.get("socMax"))
            * (
                _finite_number(row.get("capacityKwh"))
                if _finite_number(row.get("capacityKwh")) > EPSILON
                else 1.0
            )
            for row in known_soc_rows
        )
        / total_soc_weight
        if total_soc_weight > EPSILON
        else None
    )
    raw_charge = sum(
        max(0.0, _finite_number(row.get("chargePower")))
        for row in component.storage_rows
    )
    storage_current = sum(
        _finite_number(row.get("currentKw"))
        for row in component.storage_rows
        if row.get("currentKw") is not None
    )
    converter_current = sum(
        min(0.0, _finite_number(row.get("currentKw")))
        for row in component.converter_rows
        if row.get("currentKw") is not None
    )
    projected_storage_charge = max(0.0, -(storage_current + converter_current))
    charge_residual = max(0.0, projected_storage_charge - raw_charge)

    if storage_soc is None or storage_soc_upper_limit is None:
        action = "hold_unknown_soc"
    elif storage_soc >= storage_soc_upper_limit - EPSILON:
        action = "curtail_one_step_storage_island_full_soc"
    elif raw_charge <= EPSILON:
        action = "curtail_one_step_storage_island_no_charge_capacity"
    elif charge_residual > EPSILON:
        action = "curtail_charge_safety"
    else:
        action = "recover_one_step_storage_island"

    targets: Dict[Tuple[str, str], Optional[float]] = {}
    renewable_states: List[MutableMapping[str, Any]] = []
    for row in component.renewable_rows:
        key = (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
        planning_current = _number(row.get("planningCurrentKw"))
        if planning_current is None:
            targets[key] = None
            continue
        if not row.get("commandable"):
            targets[key] = planning_current
            continue
        capacity = max(0.0, _finite_number(row.get("capacityKw")))
        step = settings.step_coefficient * capacity
        if action == "recover_one_step_storage_island":
            renewable_states.append(
                {
                    "key": key,
                    "currentKw": planning_current,
                    "marginKw": min(step, max(0.0, capacity - planning_current)),
                }
            )
            target = planning_current
        elif action in {
            "curtail_one_step_storage_island_full_soc",
            "curtail_one_step_storage_island_no_charge_capacity",
            "curtail_charge_safety",
        }:
            target = max(0.0, planning_current - step)
        else:
            target = planning_current
        targets[key] = target

    if action == "recover_one_step_storage_island" and renewable_states:
        charge_headroom_kw = sum(
            max(
                0.0,
                _finite_number(row.get("chargePower"))
                - max(0.0, -_finite_number(row.get("currentKw"))),
            )
            for row in component.storage_rows
        )
        allocations = _allocate_by_margin(
            renewable_states,
            min(
                charge_headroom_kw,
                sum(_finite_number(state.get("marginKw")) for state in renewable_states),
            ),
            "marginKw",
        )
        for state, allocation_kw in zip(renewable_states, allocations):
            targets[state["key"]] = _finite_number(state.get("currentKw")) + allocation_kw

    return {
        "gridComponentId": component.grid_component_id,
        "dcTransferGroupId": component.dc_transfer_group_id,
        "action": action,
        "storageSoc": storage_soc,
        "storageSocUpperLimit": storage_soc_upper_limit,
        "renewableCurrentKw": sum(
            _finite_number(row.get("currentKw")) for row in component.renewable_rows
        ),
        "renewableTargetKw": sum(
            _finite_number(target) for target in targets.values()
        ),
        "renewableTargets": targets,
        "converterTargetKw": 0.0,
        "converterKeys": [
            (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
            for row in component.converter_rows
        ],
    }


def _resolve_converter_capacities(
    rows: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    # Converter capability must come from the converter itself.  Storage power
    # boundaries are not a valid substitute for a missing ACDC nameplate limit.
    return [dict(source) for source in rows]


def _allocate(items: Sequence[Mapping[str, Any]], total: float, capacity_key: str) -> List[float]:
    target = max(0.0, total)
    capacities = [max(0.0, _number(item.get(capacity_key), 0.0) or 0.0) for item in items]
    total_capacity = sum(capacities)
    if target <= 0 or total_capacity <= 0:
        return [0.0 for _ in items]
    return [min(capacity, target * capacity / total_capacity) for capacity in capacities]


def _capacity_weighted_soc(rows: Sequence[Mapping[str, Any]]) -> Optional[float]:
    weighted_sum = 0.0
    total_weight = 0.0
    for row in rows:
        soc = _number(row.get("soc"))
        if not row.get("socKnown") or soc is None or not math.isfinite(soc):
            continue
        capacity = _number(row.get("capacityKwh"))
        weight = (
            capacity
            if capacity is not None and math.isfinite(capacity) and capacity > EPSILON
            else 1.0
        )
        weighted_sum += soc * weight
        total_weight += weight
    return weighted_sum / total_weight if total_weight > EPSILON else None


def _json_safe_copy(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe_copy(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe_copy(item) for item in value]
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        number = float(value)
        if not math.isfinite(number):
            return None
        return value
    return str(value)


def _equal_margin_increments(rows: Sequence[Mapping[str, Any]], target: float) -> List[float]:
    increments = [0.0 for _ in rows]
    remaining = max(0.0, target)
    active = [index for index, row in enumerate(rows) if (_number(row.get("headroomKw"), 0.0) or 0.0) > EPSILON]
    while remaining > EPSILON and active:
        share = remaining / len(active)
        saturated = [
            index
            for index in active
            if (_number(rows[index].get("headroomKw"), 0.0) or 0.0) - increments[index] <= share + EPSILON
        ]
        if not saturated:
            for index in active:
                increments[index] += share
            break
        for index in saturated:
            addition = max(0.0, (_number(rows[index].get("headroomKw"), 0.0) or 0.0) - increments[index])
            increments[index] += addition
            remaining = max(0.0, remaining - addition)
        saturated_set = set(saturated)
        active = [index for index in active if index not in saturated_set]
    return increments


def _plan_recovery(
    rows: Sequence[Mapping[str, Any]],
    room_kw: float,
    settings: RenewableControlSettings,
) -> Dict[str, Any]:
    normalized: List[Dict[str, Any]] = []
    for row in rows:
        capacity = max(0.0, _number(row.get("capacityKw"), 0.0) or 0.0)
        current = min(capacity, max(0.0, _number(row.get("planningCurrentKw", row.get("currentKw")), 0.0) or 0.0))
        normalized.append({**row, "capacityKw": capacity, "planningCurrentKw": current, "headroomKw": max(0.0, capacity - current)})
    total_headroom = sum(row["headroomKw"] for row in normalized)
    requested = min(max(0.0, room_kw), total_headroom)
    mode = "equal-margin" if requested > settings.large_step_threshold_kw else "capacity-step"
    if mode == "equal-margin":
        increments = _equal_margin_increments(normalized, requested)
    else:
        proposed = [min(row["headroomKw"], settings.step_coefficient * row["capacityKw"]) for row in normalized]
        proposed_total = sum(proposed)
        target = min(requested, proposed_total)
        scale = min(1.0, target / proposed_total) if target > EPSILON and proposed_total > EPSILON else 0.0
        increments = [value * scale for value in proposed]
    result_rows = []
    for row, increment in zip(normalized, increments):
        recovery = min(row["headroomKw"], max(0.0, increment))
        result_rows.append({**row, "recoveryKw": recovery, "setpointKw": row["planningCurrentKw"] + recovery})
    return {
        "mode": mode,
        "requestedKw": requested,
        "recoverableKw": sum(row["recoveryKw"] for row in result_rows),
        "totalHeadroomKw": total_headroom,
        "rows": result_rows,
    }


def _apply_storage_switch_deadband(
    current_kw: float,
    desired_kw: float,
    deadband_kw: float,
) -> Tuple[float, str]:
    deadband = max(0.0, deadband_kw)
    if deadband <= EPSILON:
        return desired_kw, "disabled"
    if abs(current_kw) <= EPSILON:
        return (0.0, "idle_deadband") if abs(desired_kw) < deadband else (desired_kw, "direction_start_allowed")
    if current_kw > 0.0 and desired_kw < 0.0:
        return (0.0, "discharge_to_charge_blocked") if abs(desired_kw) < deadband else (desired_kw, "direction_switch_allowed")
    if current_kw < 0.0 and desired_kw > 0.0:
        return (0.0, "charge_to_discharge_blocked") if desired_kw < deadband else (desired_kw, "direction_switch_allowed")
    return desired_kw, "same_direction"


def _move_toward(current: float, target: float, step: float) -> float:
    limit = max(0.0, step)
    if limit <= EPSILON:
        return current
    if target > current:
        return min(target, current + limit)
    if target < current:
        return max(target, current - limit)
    return current


def _diesel_boundary_violation(value_kw: float, minimum_kw: float, capacity_kw: float) -> float:
    if value_kw < minimum_kw:
        return minimum_kw - value_kw
    if capacity_kw > EPSILON and value_kw > capacity_kw:
        return value_kw - capacity_kw
    return 0.0


def _parallel_converter_limit(rows: Sequence[Mapping[str, Any]]) -> float:
    if not rows:
        return 0.0
    capacities = [max(0.0, _number(row.get("transferCapacityKw"), 0.0) or 0.0) for row in rows]
    return sum(capacities) if all(capacity > 0 for capacity in capacities) else math.inf


def _converter_signed_bounds_kw(row: Mapping[str, Any]) -> Tuple[float, float]:
    minimum = _number(row.get("signedMinTargetKw"))
    maximum = _number(row.get("signedMaxTargetKw"))
    if minimum is None or maximum is None or minimum > maximum:
        return 0.0, 0.0
    return minimum, maximum


def _clamp_converter_target_kw(row: Mapping[str, Any], target_kw: Any) -> float:
    minimum, maximum = _converter_signed_bounds_kw(row)
    return _clamp(_finite_number(target_kw), minimum, maximum)


def _converter_ac_injection_bounds_kw(
    row: Mapping[str, Any],
) -> Tuple[float, float]:
    minimum_kw, maximum_kw = _converter_signed_bounds_kw(row)
    converted = sorted(
        (
            _converter_ac_injection_kw(row, minimum_kw),
            _converter_ac_injection_kw(row, maximum_kw),
        )
    )
    return converted[0], converted[1]


def _converter_export_margins_kw(
    row: Mapping[str, Any],
    current_kw: Any,
    target_kw: Any,
    step_kw: Optional[float],
) -> Tuple[float, float]:
    current_ac_injection_kw = _converter_ac_injection_kw(row, current_kw)
    target_ac_injection_kw = _converter_ac_injection_kw(row, target_kw)
    _minimum_ac_injection_kw, maximum_ac_injection_kw = (
        _converter_ac_injection_bounds_kw(row)
    )
    remaining_step_kw = math.inf
    if step_kw is not None:
        remaining_step_kw = max(
            0.0,
            float(step_kw)
            - abs(_finite_number(target_kw) - _finite_number(current_kw)),
        )
    increase_margin_kw = (
        min(
            max(0.0, maximum_ac_injection_kw - target_ac_injection_kw),
            remaining_step_kw,
        )
        if current_ac_injection_kw >= -EPSILON
        and target_ac_injection_kw >= -EPSILON
        else 0.0
    )
    reduction_margin_kw = min(
        max(0.0, target_ac_injection_kw),
        remaining_step_kw,
    )
    return increase_margin_kw, reduction_margin_kw


def _converter_target_from_ac_injection_kw(
    row: Mapping[str, Any],
    ac_injection_kw: Any,
) -> float:
    return _clamp_converter_target_kw(
        row,
        _converter_power_from_ac_injection_kw(row, ac_injection_kw),
    )


def _allocate_converters(rows: Sequence[Mapping[str, Any]], total: float) -> List[float]:
    target = max(0.0, total)
    if not rows or target <= 0:
        return [0.0 for _ in rows]
    if all((_number(row.get("transferCapacityKw"), 0.0) or 0.0) > 0 for row in rows):
        return _allocate(rows, target, "transferCapacityKw")
    return [target / len(rows) for _ in rows]


def _allocate_signed_converter_target(
    rows: Sequence[Mapping[str, Any]],
    total_kw: float,
) -> List[float]:
    if not rows:
        return []
    if total_kw >= 0.0:
        states = [
            {"marginKw": max(0.0, _converter_signed_bounds_kw(row)[1])}
            for row in rows
        ]
        return _allocate_by_margin(states, total_kw, "marginKw")
    states = [
        {"marginKw": max(0.0, -_converter_signed_bounds_kw(row)[0])}
        for row in rows
    ]
    return [
        -value
        for value in _allocate_by_margin(states, -total_kw, "marginKw")
    ]


def _grid_storage_step_kw(row, settings):
    rated = max(_finite_number(row.get('maxChargePowerKw')), _finite_number(row.get('maxDischargePowerKw')))
    return max(0.0, settings.storage_step_ratio * rated)


def _grid_storage_sort_key(row: Mapping[str, Any]) -> Tuple[Any, ...]:
    return (
        _natural_topology_identity(row.get("connectionSide", "")),
        _natural_topology_identity(row.get("dcTransferGroupId", "")),
        _natural_topology_identity(row.get("dev_type", "")),
        _natural_topology_identity(row.get("dev_name", "")),
    )


def _grid_storage_signed_power_bounds_kw(
    row: Mapping[str, Any],
) -> Tuple[float, float]:
    if not row.get("limitsValid") or not row.get("socKnown"):
        return 0.0, 0.0

    soc = _number(row.get("soc"))
    soc_min = _number(row.get("socMin"))
    soc_max = _number(row.get("socMax"))
    capacity_kwh = _number(row.get("capacityKwh"))
    efficiency = _number(row.get("efficiency"))
    horizon_minutes = _number(row.get("controlHorizonMinutes"))
    if (
        soc is None
        or soc_min is None
        or soc_max is None
        or capacity_kwh is None
        or capacity_kwh <= EPSILON
        or efficiency is None
        or efficiency <= EPSILON
        or horizon_minutes is None
        or horizon_minutes <= EPSILON
    ):
        return 0.0, 0.0

    # Apply direct-storage limits in the required order: model power limits,
    # configured SOC derating, then one-period energy margin.
    charge_limit_kw = max(0.0, _finite_number(row.get("maxChargePowerKw")))
    discharge_limit_kw = max(0.0, _finite_number(row.get("maxDischargePowerKw")))

    charge_derating_factor = _clamp(
        _finite_number(row.get("chargeDeratingFactor")),
        0.0,
        1.0,
    )
    discharge_derating_factor = _clamp(
        _finite_number(row.get("dischargeDeratingFactor")),
        0.0,
        1.0,
    )
    charge_limit_kw = min(
        charge_limit_kw,
        max(0.0, _finite_number(row.get("maxChargePowerKw")))
        * charge_derating_factor,
    )
    discharge_limit_kw = min(
        discharge_limit_kw,
        max(0.0, _finite_number(row.get("maxDischargePowerKw")))
        * discharge_derating_factor,
    )

    horizon_hours = max(EPSILON, horizon_minutes / 60.0)
    charge_energy_limit_kw = max(
        0.0,
        ((soc_max - soc) * capacity_kwh) / (efficiency * horizon_hours),
    )
    discharge_energy_limit_kw = max(
        0.0,
        ((soc - soc_min) * capacity_kwh * efficiency) / horizon_hours,
    )
    charge_limit_kw = min(charge_limit_kw, charge_energy_limit_kw)
    discharge_limit_kw = min(discharge_limit_kw, discharge_energy_limit_kw)
    return -charge_limit_kw, discharge_limit_kw


def _grid_storage_target_margins(
    row: Mapping[str, Any],
    settings: RenewableControlSettings,
    diesel_boundary_distance_kw: float,
) -> Dict[str, Any]:
    current_kw = _number(row.get("currentKw"))
    step_kw = _grid_storage_step_kw(row, settings)
    eligible = bool(
        row.get("role") == "grid_following"
        and row.get("commandable")
        and current_kw is not None
        and math.isfinite(current_kw)
        and step_kw > EPSILON
    )
    if not eligible:
        return {
            "eligible": False,
            "currentKw": current_kw,
            "targetKw": current_kw,
            "signedMinTargetKw": current_kw,
            "signedMaxTargetKw": current_kw,
            "stepKw": step_kw,
            "stepScale": 1.0,
            "chargeMarginKw": 0.0,
            "dischargeMarginKw": 0.0,
            "positiveReductionMarginKw": 0.0,
            "protectiveDeltaKw": 0.0,
        }

    signed_min_kw, signed_max_kw = _grid_storage_signed_power_bounds_kw(row)
    bounded_current_kw = _clamp(current_kw, signed_min_kw, signed_max_kw)
    protective_target_kw = _move_toward(
        current_kw,
        bounded_current_kw,
        step_kw,
    )
    protective_delta_kw = protective_target_kw - current_kw
    protection_active = abs(protective_delta_kw) > EPSILON

    # Deadbands protect diesel/grid-forming power limits. They do not shrink
    # the ordinary storage adjustment step. The step is a continuous maximum
    # delta, so the optimizer may still choose any smaller movement.
    increase_step_scale = 1.0
    discharge_step_kw = step_kw * increase_step_scale

    if protection_active:
        charge_margin_kw = 0.0
        discharge_margin_kw = 0.0
        positive_reduction_margin_kw = 0.0
    else:
        charge_margin_kw = min(
            step_kw,
            max(0.0, current_kw - signed_min_kw),
        )
        discharge_margin_kw = min(
            discharge_step_kw,
            max(0.0, signed_max_kw - current_kw),
        )
        positive_reduction_margin_kw = min(
            step_kw,
            max(0.0, current_kw),
        )

    return {
        "eligible": True,
        "currentKw": current_kw,
        "targetKw": protective_target_kw,
        "signedMinTargetKw": signed_min_kw,
        "signedMaxTargetKw": signed_max_kw,
        "stepKw": step_kw,
        "stepScale": increase_step_scale,
        "chargeMarginKw": charge_margin_kw,
        "dischargeMarginKw": discharge_margin_kw,
        "positiveReductionMarginKw": positive_reduction_margin_kw,
        "protectiveDeltaKw": protective_delta_kw,
    }


def _allocate_by_margin(
    rows: Sequence[MutableMapping[str, Any]],
    total_kw: float,
    margin_key: str,
) -> List[float]:
    requested_kw = max(0.0, total_kw)
    margins = [max(0.0, _finite_number(row.get(margin_key))) for row in rows]
    total_margin_kw = sum(margins)
    accepted_kw = min(requested_kw, total_margin_kw)
    if accepted_kw <= EPSILON or total_margin_kw <= EPSILON:
        return [0.0 for _ in rows]

    allocations = [
        min(margin_kw, accepted_kw * margin_kw / total_margin_kw)
        for margin_kw in margins
    ]
    remainder_kw = max(0.0, accepted_kw - sum(allocations))
    if remainder_kw <= EPSILON:
        return allocations

    remaining_margins = [
        max(0.0, margin_kw - allocation_kw)
        for margin_kw, allocation_kw in zip(margins, allocations)
    ]
    remaining_total_kw = sum(remaining_margins)
    if remaining_total_kw <= EPSILON:
        return allocations
    for index, remaining_margin_kw in enumerate(remaining_margins):
        if remainder_kw <= EPSILON:
            break
        if remaining_margin_kw <= EPSILON:
            continue
        addition_kw = min(
            remaining_margin_kw,
            remainder_kw * remaining_margin_kw / remaining_total_kw,
        )
        allocations[index] += addition_kw
        remainder_kw = max(0.0, remainder_kw - addition_kw)
        remaining_total_kw = max(0.0, remaining_total_kw - remaining_margin_kw)
    return allocations


def _apply_ac_to_dc_renewable_absorption(
    resource_topology: ResourceTopology,
    renewable_rows: Sequence[Mapping[str, Any]],
    storage_rows: Sequence[Mapping[str, Any]],
    converter_rows: Sequence[Mapping[str, Any]],
    renewable_targets: Mapping[Tuple[str, str], Any],
    storage_targets: Mapping[Tuple[str, str], Any],
    converter_targets: Mapping[Tuple[str, str], Any],
    settings: RenewableControlSettings,
) -> Dict[str, Any]:
    """Pair AC renewable recovery with AC-to-DC transfer and DC storage charge.

    The three equal increments are power-neutral on both sides of the
    converter: AC renewable ``+x`` is consumed by ``p_ac_set +x`` because
    positive AC-terminal power means AC-to-DC transfer; the resulting DC-side
    injection is absorbed by storage ``-x``. No branch transfer rating is
    consulted; only each participating device's own one-step and operating
    limits are used.
    """
    final_renewable_targets = dict(renewable_targets)
    final_storage_targets = dict(storage_targets)
    final_converter_targets = dict(converter_targets)
    group_details: List[Dict[str, Any]] = []

    for group_id, group in sorted(
        resource_topology.dc_transfer_groups.items(),
        key=lambda item: _natural_topology_identity(item[0]),
    ):
        # A DC group coupled to several independent AC components needs a
        # converter-to-AC-component relation before a per-component neutral
        # dispatch can be proven.  Until that relation is explicit, fail closed.
        if len(group.ac_component_ids) != 1:
            continue
        ac_component_id = group.ac_component_ids[0]

        renewable_states: List[MutableMapping[str, Any]] = []
        for row in sorted(renewable_rows, key=_grid_storage_sort_key):
            if not (
                row.get("online")
                and row.get("commandable")
                and row.get("activelyConnected")
                and row.get("connectionSide") == "AC"
                and row.get("gridComponentId") == ac_component_id
            ):
                continue
            key = _device_key(row)
            current_kw = _number(row.get("planningCurrentKw", row.get("currentKw")))
            target_kw = _number(final_renewable_targets.get(key), current_kw)
            capacity_kw = _number(row.get("capacityKw"))
            if current_kw is None or target_kw is None or capacity_kw is None:
                continue
            # Never undo a curtailment selected by an earlier protection pass.
            if target_kw < current_kw - EPSILON:
                continue
            one_step_max_kw = min(
                max(0.0, capacity_kw),
                current_kw + settings.step_coefficient * max(0.0, capacity_kw),
            )
            margin_kw = max(0.0, one_step_max_kw - target_kw)
            if margin_kw > EPSILON:
                renewable_states.append(
                    {"row": row, "key": key, "targetKw": target_kw, "marginKw": margin_kw}
                )

        storage_states: List[MutableMapping[str, Any]] = []
        for row in sorted(storage_rows, key=_grid_storage_sort_key):
            if not (
                row.get("online")
                and row.get("commandable")
                and row.get("activelyConnected")
                and row.get("connectionSide") == "DC"
                and row.get("dcTransferGroupId") == group_id
                and row.get("role") == "grid_following"
            ):
                continue
            key = _device_key(row)
            current_kw = _number(row.get("currentKw"))
            target_kw = _number(final_storage_targets.get(key), current_kw)
            if current_kw is None or target_kw is None:
                continue
            signed_min_kw, _signed_max_kw = _grid_storage_signed_power_bounds_kw(row)
            one_step_min_kw = max(
                signed_min_kw,
                current_kw - _grid_storage_step_kw(row, settings),
            )
            margin_kw = max(0.0, target_kw - one_step_min_kw)
            if margin_kw > EPSILON:
                storage_states.append(
                    {"row": row, "key": key, "targetKw": target_kw, "marginKw": margin_kw}
                )

        converter_states: List[MutableMapping[str, Any]] = []
        for row in sorted(converter_rows, key=_converter_row_sort_key):
            if not (
                row.get("online")
                and row.get("commandable")
                and row.get("limitsValid")
                and row.get("dcTransferGroupId") == group_id
                and row.get("converterRole") == "grid"
            ):
                continue
            key = _device_key(row)
            current_kw = _number(row.get("currentKw"))
            target_kw = _number(final_converter_targets.get(key), current_kw)
            if current_kw is None or target_kw is None:
                continue
            minimum_ac_injection_kw, _maximum_ac_injection_kw = (
                _converter_ac_injection_bounds_kw(row)
            )
            current_transfer_kw = -_converter_ac_injection_kw(row, current_kw)
            target_transfer_kw = -_converter_ac_injection_kw(row, target_kw)
            one_step_max_kw = min(
                -minimum_ac_injection_kw,
                current_transfer_kw
                + settings.converter_step_ratio
                * max(0.0, _finite_number(row.get("transferCapacityKw"))),
            )
            margin_kw = max(0.0, one_step_max_kw - target_transfer_kw)
            if margin_kw > EPSILON:
                converter_states.append(
                    {
                        "row": row,
                        "key": key,
                        "targetKw": target_kw,
                        "targetTransferKw": target_transfer_kw,
                        "marginKw": margin_kw,
                    }
                )

        paired_kw = min(
            sum(_finite_number(state.get("marginKw")) for state in renewable_states),
            sum(_finite_number(state.get("marginKw")) for state in storage_states),
            sum(_finite_number(state.get("marginKw")) for state in converter_states),
        )
        if paired_kw <= EPSILON:
            continue

        renewable_allocations = _allocate_by_margin(
            renewable_states,
            paired_kw,
            "marginKw",
        )
        storage_allocations = _allocate_by_margin(
            storage_states,
            paired_kw,
            "marginKw",
        )
        converter_allocations = _allocate_by_margin(
            converter_states,
            paired_kw,
            "marginKw",
        )
        for state, allocation_kw in zip(renewable_states, renewable_allocations):
            final_renewable_targets[state["key"]] = _finite_number(state.get("targetKw")) + allocation_kw
        for state, allocation_kw in zip(storage_states, storage_allocations):
            final_storage_targets[state["key"]] = _finite_number(state.get("targetKw")) - allocation_kw
        for state, allocation_kw in zip(converter_states, converter_allocations):
            final_converter_targets[state["key"]] = _converter_target_from_ac_injection_kw(
                state["row"],
                -(
                    _finite_number(state.get("targetTransferKw"))
                    + allocation_kw
                ),
            )
        group_details.append(
            {
                "dcTransferGroupId": group_id,
                "acComponentId": ac_component_id,
                "pairedKw": paired_kw,
            }
        )

    return {
        "renewableTargets": final_renewable_targets,
        "storageTargets": final_storage_targets,
        "converterTargets": final_converter_targets,
        "groups": group_details,
        "pairedKw": sum(_finite_number(item.get("pairedKw")) for item in group_details),
    }


@dataclass(frozen=True)
class _DcGroupBudget:
    group_id: str
    renewable_current_kw: float
    renewable_recovery_kw: float
    local_net_demand_kw: float
    grid_storage_charge_margin_kw: float
    grid_storage_discharge_margin_kw: float
    balance_storage_charge_margin_kw: float
    balance_storage_discharge_margin_kw: float
    balance_storage_current_kw: float
    acdc_current_export_kw: float
    acdc_export_headroom_kw: float
    acdc_step_headroom_kw: float


@dataclass(frozen=True)
class _AcSideBudget:
    renewable_current_kw: float
    renewable_recovery_kw: float
    local_net_demand_kw: float
    diesel_down_margin_kw: float
    grid_storage_charge_margin_kw: float
    grid_storage_discharge_margin_kw: float
    balance_storage_charge_margin_kw: float
    balance_storage_discharge_margin_kw: float
    balance_storage_current_kw: float
    accepted_acdc_export_kw: float


def _active_load_budgets(
    snapshot: Mapping[str, Any],
    measurements: Mapping[Tuple[str, str, str], MeasurementValue],
    dc_transfer_groups: Mapping[str, DcTransferGroup],
) -> Tuple[float, Dict[str, float]]:
    ac_total_kw = 0.0
    dc_totals_kw = {group_id: 0.0 for group_id in dc_transfer_groups}
    dc_group_by_node = {
        str(node): group_id
        for group_id, group in dc_transfer_groups.items()
        for node in group.dc_nodes
    }
    model = (
        snapshot.get("definitions", {}).get("model", {})
        if isinstance(snapshot.get("definitions"), Mapping)
        else {}
    )
    model_nodes: Dict[Tuple[str, str], str] = {}
    if isinstance(model, Mapping):
        for dev_type in ("ACLoad", "DCLoad"):
            block = model.get(dev_type)
            rows = block.get("rows") if isinstance(block, Mapping) else []
            for row in rows or []:
                if isinstance(row, Mapping) and str(row.get("name", "")):
                    model_nodes[(dev_type, str(row.get("name")))] = str(
                        row.get("node", "")
                    )

    for device in snapshot.get("devices", []) or []:
        if not isinstance(device, Mapping):
            continue
        model_block = _device_model_block(device)
        if model_block not in {"ACLoad", "DCLoad"} or not _is_online(
            device, measurements
        ):
            continue
        dev_type = _device_type(device)
        dead_island = _number(device.get("dead_island"), 0.0)
        if dead_island is not None and dead_island != 0.0:
            continue
        dev_name = _device_name(device)
        measured = _measured(
            measurements,
            dev_type,
            dev_name,
            ("P_LOAD", "P", "P_AC", "P_DC"),
        )
        if measured is None:
            continue
        if model_block == "ACLoad":
            ac_total_kw += measured.value
            continue
        raw = device.get("raw") if isinstance(device.get("raw"), Mapping) else {}
        node = model_nodes.get((model_block, dev_name), str(raw.get("node", "")))
        group_id = dc_group_by_node.get(str(node), "")
        if group_id:
            dc_totals_kw[group_id] += measured.value
    return ac_total_kw, dc_totals_kw


def _active_load_side_metrics(
    snapshot: Mapping[str, Any],
    measurements: Mapping[Tuple[str, str, str], MeasurementValue],
) -> Dict[str, Any]:
    totals = {"AC": 0.0, "DC": 0.0}
    active_counts = {"AC": 0, "DC": 0}
    measured_counts = {"AC": 0, "DC": 0}
    for device in snapshot.get("devices", []) or []:
        if not isinstance(device, Mapping):
            continue
        dev_type = _device_type(device)
        model_block = _device_model_block(device)
        side = "AC" if model_block == "ACLoad" else "DC" if model_block == "DCLoad" else ""
        if not side or not _is_online(device, measurements):
            continue
        dead_island = _number(device.get("dead_island"), 0.0)
        if dead_island is not None and dead_island != 0.0:
            continue
        active_counts[side] += 1
        measured = _measured(
            measurements,
            dev_type,
            _device_name(device),
            ("P_LOAD", "P", "P_AC", "P_DC"),
        )
        if measured is None:
            continue
        totals[side] += measured.value
        measured_counts[side] += 1

    def side_value(side: str) -> Optional[float]:
        if active_counts[side] == 0:
            return 0.0
        return totals[side] if measured_counts[side] > 0 else None

    return {
        "acLoadKw": side_value("AC"),
        "dcLoadKw": side_value("DC"),
        "onlineAcLoadCount": active_counts["AC"],
        "onlineDcLoadCount": active_counts["DC"],
    }


def _side_aware_storage_state(
    row: Mapping[str, Any],
    settings: RenewableControlSettings,
    initial_target_kw: Any,
    *,
    preserve_initial: bool = True,
) -> MutableMapping[str, Any]:
    current_kw = _number(row.get("currentKw"))
    state = _grid_storage_target_margins(row, settings, 0.0)
    state.update(
        {
            "row": row,
            "key": (str(row.get("dev_type", "")), str(row.get("dev_name", ""))),
            "side": str(row.get("connectionSide", "")),
            "groupId": str(row.get("dcTransferGroupId", "")),
        }
    )
    if current_kw is None or not state.get("eligible"):
        state["targetKw"] = current_kw
        return state
    candidate_kw = _number(initial_target_kw, current_kw)
    state["targetKw"] = (
        candidate_kw
        if preserve_initial
        and candidate_kw is not None
        and candidate_kw >= min(current_kw, 0.0) - EPSILON
        else current_kw
    )
    return state


def _project_balance_storage_targets(
    balance_rows: Sequence[Mapping[str, Any]],
    renewable_states: Sequence[Mapping[str, Any]],
    storage_states: Sequence[Mapping[str, Any]],
    converter_states: Sequence[Mapping[str, Any]],
    *,
    ac_balance_delta_kw: Optional[float] = None,
    dc_balance_delta_by_group: Optional[Mapping[str, float]] = None,
) -> Tuple[
    Dict[Tuple[str, str], float],
    Dict[Tuple[str, str], List[Dict[str, str]]],
]:
    projected_targets: Dict[Tuple[str, str], float] = {}
    indirect_devices: Dict[Tuple[str, str], List[Dict[str, str]]] = {}

    def changed_device_keys(states: Sequence[Mapping[str, Any]]) -> List[Tuple[str, str]]:
        keys = set()
        for state in states:
            row = state.get("row") if isinstance(state.get("row"), Mapping) else state
            current_kw = _number(state.get("currentKw", row.get("currentKw")))
            target_kw = _number(state.get("targetKw", state.get("commandKw")))
            if (
                current_kw is None
                or target_kw is None
                or abs(target_kw - current_kw) <= EPSILON
            ):
                continue
            keys.add(
                (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
            )
        return sorted(keys)

    def allocate_rows(
        rows: Sequence[Mapping[str, Any]],
        delta_kw: float,
        changed_states: Sequence[Mapping[str, Any]],
    ) -> None:
        candidates: List[MutableMapping[str, Any]] = []
        margin_key = "upMarginKw" if delta_kw >= 0.0 else "downMarginKw"
        for row in sorted(rows, key=_grid_storage_sort_key):
            current_kw = _finite_number(row.get("currentKw"))
            signed_min_kw, signed_max_kw = _grid_storage_signed_power_bounds_kw(row)
            candidates.append(
                {
                    "row": row,
                    "upMarginKw": max(0.0, signed_max_kw - current_kw),
                    "downMarginKw": max(0.0, current_kw - signed_min_kw),
                }
            )
        allocations = _allocate_by_margin(candidates, abs(delta_kw), margin_key)
        direction = 1.0 if delta_kw >= 0.0 else -1.0
        devices = changed_device_keys(changed_states)
        for candidate, allocation_kw in zip(candidates, allocations):
            row = candidate["row"]
            key = (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
            current_kw = _finite_number(row.get("currentKw"))
            signed_min_kw, signed_max_kw = _grid_storage_signed_power_bounds_kw(row)
            candidate_kw = current_kw + direction * allocation_kw
            if current_kw < signed_min_kw - EPSILON:
                projected_targets[key] = _clamp(
                    candidate_kw,
                    current_kw,
                    signed_max_kw,
                )
            elif current_kw > signed_max_kw + EPSILON:
                projected_targets[key] = _clamp(
                    candidate_kw,
                    signed_min_kw,
                    current_kw,
                )
            else:
                projected_targets[key] = _clamp(
                    candidate_kw,
                    signed_min_kw,
                    signed_max_kw,
                )
            indirect_devices[key] = [
                {"dev_type": dev_type, "dev_name": dev_name}
                for dev_type, dev_name in devices
                if (dev_type, dev_name) != key
            ]

    ac_rows = [
        row for row in balance_rows if row.get("connectionSide") == "AC"
    ]
    if ac_rows:
        ac_renewable_delta_kw = sum(
            _finite_number(state.get("targetKw"))
            - _finite_number(state.get("currentKw"))
            for state in renewable_states
            if state.get("side") == "AC"
        )
        ac_storage_delta_kw = sum(
            _finite_number(state.get("targetKw"))
            - _finite_number(state.get("currentKw"))
            for state in storage_states
            if state.get("side") == "AC"
        )
        export_delta_kw = sum(
            _converter_ac_injection_delta_kw(
                state["row"],
                state.get("currentKw"),
                state.get("targetKw"),
            )
            for state in converter_states
            if state.get("currentKw") is not None
            and state.get("targetKw") is not None
        )
        projected_delta_kw = (
            ac_balance_delta_kw
            if ac_balance_delta_kw is not None
            else -(ac_renewable_delta_kw + ac_storage_delta_kw + export_delta_kw)
        )
        allocate_rows(
            ac_rows,
            projected_delta_kw,
            [*renewable_states, *storage_states, *converter_states],
        )

    group_ids = sorted(
        {
            str(row.get("dcTransferGroupId", ""))
            for row in balance_rows
            if row.get("connectionSide") == "DC"
            and str(row.get("dcTransferGroupId", ""))
        },
        key=_natural_topology_identity,
    )
    for group_id in group_ids:
        rows = [
            row
            for row in balance_rows
            if row.get("connectionSide") == "DC"
            and row.get("dcTransferGroupId") == group_id
        ]
        group_renewables = [
            state
            for state in renewable_states
            if state.get("side") == "DC" and state.get("groupId") == group_id
        ]
        group_storage = [
            state
            for state in storage_states
            if state.get("side") == "DC" and state.get("groupId") == group_id
        ]
        group_converters = [
            state
            for state in converter_states
            if state.get("groupId") == group_id
        ]
        renewable_delta_kw = sum(
            _finite_number(state.get("targetKw"))
            - _finite_number(state.get("currentKw"))
            for state in group_renewables
        )
        storage_delta_kw = sum(
            _finite_number(state.get("targetKw"))
            - _finite_number(state.get("currentKw"))
            for state in group_storage
        )
        export_delta_kw = sum(
            _converter_ac_injection_delta_kw(
                state["row"],
                state.get("currentKw"),
                state.get("targetKw"),
            )
            for state in group_converters
            if state.get("currentKw") is not None
            and state.get("targetKw") is not None
        )
        projected_delta_kw = (
            _finite_number(dc_balance_delta_by_group.get(group_id))
            if dc_balance_delta_by_group is not None
            and group_id in dc_balance_delta_by_group
            else -(renewable_delta_kw + storage_delta_kw) + export_delta_kw
        )
        allocate_rows(
            rows,
            projected_delta_kw,
            [*group_renewables, *group_storage, *group_converters],
        )
    return projected_targets, indirect_devices


def _side_aware_renewable_recovery_plan_without_balance(
    snapshot: Mapping[str, Any],
    measurements: Mapping[Tuple[str, str, str], MeasurementValue],
    settings: RenewableControlSettings,
    resource_topology: ResourceTopology,
    renewable_rows: Sequence[Mapping[str, Any]],
    storage_rows: Sequence[Mapping[str, Any]],
    converter_rows: Sequence[Mapping[str, Any]],
    initial_storage_targets: Mapping[Tuple[str, str], Any],
    initial_converter_targets: Mapping[Tuple[str, str], Any],
    initial_renewable_targets: Mapping[Tuple[str, str], Any],
    allow_topology_recovery_fallback: bool,
    *,
    diesel_current_kw: float,
    diesel_min_kw: float,
    diesel_deadband_upper_kw: Optional[float] = None,
) -> Dict[str, Any]:
    preserve_state_machine_recovery_budget = any(
        row.get("role") == "balance" and row.get("stateEligible")
        for row in storage_rows
    )
    high_soc_dc_group_ids = {
        str(row.get("dcTransferGroupId", ""))
        for row in storage_rows
        if row.get("role") == "balance"
        and row.get("connectionSide") == "DC"
        and str(row.get("dcTransferGroupId", ""))
        and _number(row.get("soc")) is not None
        and _number(row.get("socMax")) is not None
        and _finite_number(row.get("soc"))
        > _finite_number(row.get("socMax")) + EPSILON
    }
    high_soc_ac_component_ids = {
        str(row.get("gridComponentId", ""))
        for row in storage_rows
        if row.get("role") == "balance"
        and row.get("connectionSide") == "AC"
        and str(row.get("gridComponentId", ""))
        and _number(row.get("soc")) is not None
        and _number(row.get("socMax")) is not None
        and _finite_number(row.get("soc"))
        > _finite_number(row.get("socMax")) + EPSILON
    }
    initial_curtail_request_kw = sum(
        max(
            0.0,
            _finite_number(row.get("planningCurrentKw"))
            - _finite_number(
                initial_renewable_targets.get(
                    (str(row.get("dev_type", "")), str(row.get("dev_name", ""))),
                    row.get("planningCurrentKw"),
                )
            ),
        )
        for row in renewable_rows
        if _number(row.get("planningCurrentKw")) is not None
    )
    high_soc_curtail_rows = [
        row
        for row in renewable_rows
        if _number(row.get("planningCurrentKw")) is not None
        and (
            row.get("connectionSide") == "DC"
            and str(row.get("dcTransferGroupId", "")) in high_soc_dc_group_ids
            or row.get("connectionSide") == "AC"
            and str(row.get("gridComponentId", "")) in high_soc_ac_component_ids
        )
    ]
    high_soc_curtail_allocations = _allocate(
        high_soc_curtail_rows,
        min(
            initial_curtail_request_kw,
            sum(
                max(0.0, _finite_number(row.get("planningCurrentKw")))
                for row in high_soc_curtail_rows
            ),
        ),
        "planningCurrentKw",
    )
    high_soc_curtail_by_key = {
        (str(row.get("dev_type", "")), str(row.get("dev_name", ""))): allocation_kw
        for row, allocation_kw in zip(
            high_soc_curtail_rows,
            high_soc_curtail_allocations,
        )
    }
    renewable_states: List[MutableMapping[str, Any]] = []
    for row in sorted(
        renewable_rows,
        key=lambda item: (
            str(item.get("connectionSide", "")),
            str(item.get("dcTransferGroupId", "")),
            str(item.get("technology", "")),
            str(item.get("dev_type", "")),
            str(item.get("dev_name", "")),
        ),
    ):
        current_kw = _number(row.get("planningCurrentKw"))
        capacity_kw = _number(row.get("capacityKw"))
        key = (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
        initial_target_kw = _number(
            initial_renewable_targets.get(key),
            current_kw,
        )
        preserved_curtailment_kw = _finite_number(
            high_soc_curtail_by_key.get(key)
        )
        eligible = bool(
            row.get("commandable")
            and current_kw is not None
            and capacity_kw is not None
            and capacity_kw > EPSILON
            and current_kw >= -EPSILON
            and current_kw <= capacity_kw + EPSILON
        )
        initial_recovery_margin_kw = max(
            0.0,
            _finite_number(initial_target_kw, current_kw) - current_kw,
        ) if current_kw is not None else 0.0
        margin_kw = (
            min(
                max(0.0, capacity_kw - current_kw),
                initial_recovery_margin_kw
                if initial_recovery_margin_kw > EPSILON
                else settings.step_coefficient * capacity_kw
                if allow_topology_recovery_fallback
                or not preserve_state_machine_recovery_budget
                else 0.0,
            )
            if eligible
            else 0.0
        )
        renewable_states.append(
            {
                "row": row,
                "key": key,
                "side": str(row.get("connectionSide", "")),
                "groupId": str(row.get("dcTransferGroupId", "")),
                "technology": str(row.get("technology", "")),
                "currentKw": current_kw,
                "targetKw": (
                    max(0.0, current_kw - preserved_curtailment_kw)
                    if current_kw is not None
                    and preserved_curtailment_kw > EPSILON
                    else current_kw
                ),
                "marginKw": margin_kw,
                "acceptedKw": 0.0,
            }
        )

    storage_states = [
        _side_aware_storage_state(
            row,
            settings,
            initial_storage_targets.get(
                (str(row.get("dev_type", "")), str(row.get("dev_name", ""))),
                row.get("currentKw"),
            ),
        )
        for row in sorted(storage_rows, key=_grid_storage_sort_key)
        if row.get("role") == "grid_following"
    ]
    converter_states: List[MutableMapping[str, Any]] = []
    for row in sorted(converter_rows, key=_converter_row_sort_key):
        current_kw = _number(row.get("currentKw"))
        capacity_kw = _number(row.get("transferCapacityKw"))
        key = (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
        target_kw = _number(initial_converter_targets.get(key), current_kw)
        if current_kw is None or target_kw is None:
            target_kw = current_kw
        if target_kw is not None:
            target_kw = _clamp_converter_target_kw(row, target_kw)
        step_kw = (
            settings.converter_step_ratio * capacity_kw
            if capacity_kw is not None and capacity_kw > EPSILON
            else 0.0
        )
        export_margin_kw = 0.0
        export_reduction_margin_kw = 0.0
        if (
            row.get("commandable")
            and current_kw is not None
            and target_kw is not None
            and capacity_kw is not None
            and capacity_kw > EPSILON
        ):
            export_margin_kw, export_reduction_margin_kw = (
                _converter_export_margins_kw(
                    row,
                    current_kw,
                    target_kw,
                    step_kw,
                )
            )
        converter_states.append(
            {
                "row": row,
                "key": key,
                "groupId": str(row.get("dcTransferGroupId", "")),
                "currentKw": current_kw,
                "targetKw": target_kw,
                "capacityKw": capacity_kw,
                "exportMarginKw": export_margin_kw,
                "exportReductionMarginKw": export_reduction_margin_kw,
            }
        )

    # Near the diesel deadband boundary, the ACDC and AC-renewable candidates
    # would otherwise consume the same small diesel margin twice.  Prefer the
    # directly connected AC renewable recovery for this one-step correction and
    # keep ACDC at its measured export; clearly high diesel output still uses
    # the normal ACDC discharge path below.
    diesel_boundary_kw = max(
        diesel_min_kw,
        _finite_number(diesel_deadband_upper_kw, diesel_min_kw),
    )
    converter_base_step_kw = sum(
        max(0.0, _finite_number(state.get("capacityKw")))
        * settings.converter_step_ratio
        for state in converter_states
    )
    ac_renewable_has_headroom = any(
        state.get("side") == "AC"
        and _number(state.get("currentKw")) is not None
        and _finite_number(state.get("marginKw")) > EPSILON
        for state in renewable_states
    )
    if (
        ac_renewable_has_headroom
        and converter_base_step_kw > EPSILON
        and diesel_current_kw > diesel_boundary_kw + EPSILON
        and diesel_current_kw - diesel_boundary_kw
        <= converter_base_step_kw + EPSILON
    ):
        for state in converter_states:
            current_kw = _number(state.get("currentKw"))
            target_kw = _number(state.get("targetKw"))
            capacity_kw = _number(state.get("capacityKw"))
            if (
                current_kw is None
                or target_kw is None
                or capacity_kw is None
                or target_kw >= current_kw - EPSILON
            ):
                continue
            state["targetKw"] = current_kw
            (
                state["exportMarginKw"],
                state["exportReductionMarginKw"],
            ) = _converter_export_margins_kw(
                state["row"],
                current_kw,
                current_kw,
                settings.converter_step_ratio * capacity_kw,
            )

    def allocate_renewable(
        states: Sequence[MutableMapping[str, Any]],
        request_kw: float,
        accepted_key: str = "",
    ) -> float:
        allocations = _allocate_by_margin(states, request_kw, "marginKw")
        for state, allocation_kw in zip(states, allocations):
            if _number(state.get("targetKw")) is None:
                continue
            state["targetKw"] = _finite_number(state.get("targetKw")) + allocation_kw
            state["marginKw"] = max(0.0, _finite_number(state.get("marginKw")) - allocation_kw)
            state["acceptedKw"] = _finite_number(state.get("acceptedKw")) + allocation_kw
            if accepted_key:
                state[accepted_key] = _finite_number(state.get(accepted_key)) + allocation_kw
        return sum(allocations)

    def charge_storage(states: Sequence[MutableMapping[str, Any]], request_kw: float) -> float:
        allocations = _allocate_by_margin(states, request_kw, "chargeMarginKw")
        for state, allocation_kw in zip(states, allocations):
            if _number(state.get("targetKw")) is None:
                continue
            state["targetKw"] = _finite_number(state.get("targetKw")) - allocation_kw
            state["chargeMarginKw"] = max(
                0.0, _finite_number(state.get("chargeMarginKw")) - allocation_kw
            )
        return sum(allocations)

    def increase_group_export(group_id: str, request_kw: float) -> float:
        states = [state for state in converter_states if state.get("groupId") == group_id]
        allocations = _allocate_by_margin(states, request_kw, "exportMarginKw")
        for state, allocation_kw in zip(states, allocations):
            if _number(state.get("targetKw")) is None:
                continue
            target_ac_injection_kw = _converter_ac_injection_kw(
                state["row"],
                state.get("targetKw"),
            )
            state["targetKw"] = _converter_target_from_ac_injection_kw(
                state["row"],
                target_ac_injection_kw + allocation_kw,
            )
            state["exportMarginKw"] = max(
                0.0, _finite_number(state.get("exportMarginKw")) - allocation_kw
            )
        return sum(allocations)

    ac_load_kw, dc_load_kw = _active_load_budgets(
        snapshot,
        measurements,
        resource_topology.dc_transfer_groups,
    )
    initial_ac_storage_effect_kw = sum(
        _finite_number(state.get("targetKw")) - _finite_number(state.get("currentKw"))
        for state in storage_states
        if state.get("side") == "AC" and state.get("currentKw") is not None
    )
    initial_export_effect_kw = sum(
        _converter_ac_injection_delta_kw(
            state["row"],
            state.get("currentKw"),
            state.get("targetKw"),
        )
        for state in converter_states
        if state.get("currentKw") is not None and state.get("targetKw") is not None
    )
    diesel_margin_kw = max(
        0.0,
        diesel_current_kw
        - max(
            diesel_min_kw,
            _finite_number(diesel_deadband_upper_kw, diesel_min_kw),
        )
        - max(0.0, initial_ac_storage_effect_kw)
        - max(0.0, initial_export_effect_kw),
    )
    direct_balance_rows = [
        row
        for row in storage_rows
        if row.get("role") == "balance"
        and row.get("stateEligible")
    ]
    ac_balance_rows = [
        row for row in direct_balance_rows if row.get("connectionSide") == "AC"
    ]

    ac_renewables = [state for state in renewable_states if state.get("side") == "AC"]
    ac_recovery_margin_kw = sum(_finite_number(state.get("marginKw")) for state in ac_renewables)
    ac_diesel_recovery_kw = allocate_renewable(
        ac_renewables,
        min(ac_recovery_margin_kw, diesel_margin_kw),
        "dieselAcceptedKw",
    )
    diesel_margin_kw = max(0.0, diesel_margin_kw - ac_diesel_recovery_kw)
    ac_storage_states = [state for state in storage_states if state.get("side") == "AC"]
    ac_charge_request_kw = min(
        sum(_finite_number(state.get("marginKw")) for state in ac_renewables),
        sum(_finite_number(state.get("chargeMarginKw")) for state in ac_storage_states),
    )
    ac_charge_source_kw = allocate_renewable(
        ac_renewables,
        ac_charge_request_kw,
        "acGridStorageAcceptedKw",
    )
    ac_storage_charge_kw = charge_storage(ac_storage_states, ac_charge_source_kw)
    if ac_storage_charge_kw + EPSILON < ac_charge_source_kw:
        rollback_kw = ac_charge_source_kw - ac_storage_charge_kw
        for state in reversed(ac_renewables):
            amount_kw = min(rollback_kw, _finite_number(state.get("acceptedKw")))
            state["targetKw"] = _finite_number(state.get("targetKw")) - amount_kw
            state["acceptedKw"] = _finite_number(state.get("acceptedKw")) - amount_kw
            state["acGridStorageAcceptedKw"] = max(
                0.0,
                _finite_number(state.get("acGridStorageAcceptedKw")) - amount_kw,
            )
            state["marginKw"] = _finite_number(state.get("marginKw")) + amount_kw
            rollback_kw -= amount_kw
            if rollback_kw <= EPSILON:
                break
    ac_balance_charge_request_kw = min(
        sum(_finite_number(state.get("marginKw")) for state in ac_renewables),
        sum(
            max(
                0.0,
                _finite_number(row.get("currentKw"))
                - _grid_storage_signed_power_bounds_kw(row)[0],
            )
            for row in ac_balance_rows
        ),
    )
    ac_balance_charge_accepted_kw = allocate_renewable(
        ac_renewables,
        ac_balance_charge_request_kw,
        "acBalanceAcceptedKw",
    )

    dc_budgets: List[_DcGroupBudget] = []
    dc_balance_delta_by_group: Dict[str, float] = {}
    paired_export_kw = 0.0
    for group_id in sorted(
        resource_topology.dc_transfer_groups,
        key=_natural_topology_identity,
    ):
        group_renewables = [
            state
            for state in renewable_states
            if state.get("side") == "DC" and state.get("groupId") == group_id
        ]
        group_storage = [
            state
            for state in storage_states
            if state.get("side") == "DC" and state.get("groupId") == group_id
        ]
        group_balance = [
            row
            for row in storage_rows
            if row.get("role") == "balance"
            and row.get("connectionSide") == "DC"
            and row.get("dcTransferGroupId") == group_id
            and row.get("stateEligible")
        ]
        renewable_current_kw = sum(
            _finite_number(state.get("currentKw")) for state in group_renewables
        )
        balance_current_kw = sum(
            _finite_number(row.get("currentKw")) for row in group_balance
        )
        local_deficit_kw = max(
            0.0,
            _finite_number(dc_load_kw.get(group_id))
            - renewable_current_kw
            - sum(
                _finite_number(state.get("currentKw"))
                for state in group_storage
            ),
        )
        local_recovery_kw = allocate_renewable(
            group_renewables,
            local_deficit_kw,
            "dcLocalLoadAcceptedKw",
        )
        charge_request_kw = min(
            sum(_finite_number(state.get("marginKw")) for state in group_renewables),
            sum(_finite_number(state.get("chargeMarginKw")) for state in group_storage),
        )
        charge_source_kw = allocate_renewable(
            group_renewables,
            charge_request_kw,
            "dcGridStorageAcceptedKw",
        )
        local_storage_charge_kw = charge_storage(group_storage, charge_source_kw)
        balance_charge_request_kw = min(
            sum(_finite_number(state.get("marginKw")) for state in group_renewables),
            sum(
                max(
                    0.0,
                    _finite_number(row.get("currentKw"))
                    - _grid_storage_signed_power_bounds_kw(row)[0],
                )
                for row in group_balance
            ),
        )
        balance_charge_source_kw = allocate_renewable(
            group_renewables,
            balance_charge_request_kw,
            "dcBalanceAcceptedKw",
        )
        dc_balance_delta_by_group[group_id] = -balance_charge_source_kw
        export_request_kw = min(
            sum(_finite_number(state.get("marginKw")) for state in group_renewables),
            diesel_margin_kw,
            sum(
                _finite_number(state.get("exportMarginKw"))
                for state in converter_states
                if state.get("groupId") == group_id
            ),
        )
        export_source_kw = allocate_renewable(
            group_renewables,
            export_request_kw,
            "dcAcdcExportAcceptedKw",
        )
        accepted_export_kw = increase_group_export(group_id, export_source_kw)
        paired_export_kw += accepted_export_kw
        diesel_margin_kw = max(0.0, diesel_margin_kw - accepted_export_kw)
        dc_budgets.append(
            _DcGroupBudget(
                group_id=group_id,
                renewable_current_kw=renewable_current_kw,
                renewable_recovery_kw=sum(
                    _finite_number(state.get("acceptedKw")) for state in group_renewables
                ),
                local_net_demand_kw=_finite_number(dc_load_kw.get(group_id)),
                grid_storage_charge_margin_kw=sum(
                    _finite_number(state.get("chargeMarginKw")) for state in group_storage
                ),
                grid_storage_discharge_margin_kw=sum(
                    _finite_number(state.get("dischargeMarginKw")) for state in group_storage
                ),
                balance_storage_charge_margin_kw=sum(
                    max(0.0, _finite_number(row.get("currentKw")) - _grid_storage_signed_power_bounds_kw(row)[0])
                    for row in group_balance
                ),
                balance_storage_discharge_margin_kw=sum(
                    max(0.0, _grid_storage_signed_power_bounds_kw(row)[1] - _finite_number(row.get("currentKw")))
                    for row in group_balance
                ),
                balance_storage_current_kw=balance_current_kw,
                acdc_current_export_kw=sum(
                    max(0.0, -_finite_number(state.get("currentKw")))
                    for state in converter_states
                    if state.get("groupId") == group_id
                ),
                acdc_export_headroom_kw=sum(
                    _finite_number(state.get("exportMarginKw"))
                    for state in converter_states
                    if state.get("groupId") == group_id
                ),
                acdc_step_headroom_kw=sum(
                    _finite_number(state.get("exportMarginKw"))
                    for state in converter_states
                    if state.get("groupId") == group_id
                ),
            )
        )

    ac_renewable_delta_kw = sum(
        _finite_number(state.get("targetKw")) - _finite_number(state.get("currentKw"))
        for state in ac_renewables
    )
    ac_storage_delta_kw = sum(
        _finite_number(state.get("targetKw")) - _finite_number(state.get("currentKw"))
        for state in ac_storage_states
    )
    export_delta_kw = sum(
        _converter_ac_injection_delta_kw(
            state["row"],
            state.get("currentKw"),
            state.get("targetKw"),
        )
        for state in converter_states
        if state.get("currentKw") is not None and state.get("targetKw") is not None
    )
    diesel_effect_kw = (
        ac_renewable_delta_kw
        - ac_balance_charge_accepted_kw
        + ac_storage_delta_kw
        + export_delta_kw
    )
    projected_targets, indirect_devices = _project_balance_storage_targets(
        direct_balance_rows,
        renewable_states,
        storage_states,
        converter_states,
        ac_balance_delta_kw=-ac_balance_charge_accepted_kw,
        dc_balance_delta_by_group=dc_balance_delta_by_group,
    )
    ac_balance = [
        row for row in direct_balance_rows if row.get("connectionSide") == "AC"
    ]
    ac_budget = _AcSideBudget(
        renewable_current_kw=sum(
            _finite_number(state.get("currentKw")) for state in ac_renewables
        ),
        renewable_recovery_kw=ac_renewable_delta_kw,
        local_net_demand_kw=ac_load_kw,
        diesel_down_margin_kw=max(0.0, diesel_current_kw - diesel_min_kw),
        grid_storage_charge_margin_kw=sum(
            _finite_number(state.get("chargeMarginKw")) for state in ac_storage_states
        ),
        grid_storage_discharge_margin_kw=sum(
            _finite_number(state.get("dischargeMarginKw")) for state in ac_storage_states
        ),
        balance_storage_charge_margin_kw=sum(
            max(
                0.0,
                _finite_number(row.get("currentKw"))
                - _grid_storage_signed_power_bounds_kw(row)[0],
            )
            for row in direct_balance_rows
            if row.get("connectionSide") == "AC"
        ),
        balance_storage_discharge_margin_kw=sum(
            max(
                0.0,
                _grid_storage_signed_power_bounds_kw(row)[1]
                - _finite_number(row.get("currentKw")),
            )
            for row in direct_balance_rows
            if row.get("connectionSide") == "AC"
        ),
        balance_storage_current_kw=sum(
            _finite_number(row.get("currentKw"))
            for row in storage_rows
            if row.get("role") == "balance" and row.get("connectionSide") == "AC"
        ),
        accepted_acdc_export_kw=paired_export_kw,
    )
    return {
        "renewableTargets": {
            state["key"]: state.get("targetKw") for state in renewable_states
        },
        "storageTargets": {
            state["key"]: state.get("targetKw") for state in storage_states
        },
        "storageStates": {state["key"]: state for state in storage_states},
        "converterTargets": {
            state["key"]: _clamp_converter_target_kw(
                state["row"],
                state.get("targetKw"),
            )
            for state in converter_states
            if state.get("targetKw") is not None
        },
        "dieselEffectKw": diesel_effect_kw,
        "dieselTargetKw": diesel_current_kw - diesel_effect_kw,
        "acBudget": ac_budget,
        "dcBudgets": tuple(dc_budgets),
        "projectedBalanceTargets": projected_targets,
        "indirectControlDevices": indirect_devices,
    }


def _side_aware_renewable_recovery_plan(
    snapshot: Mapping[str, Any],
    measurements: Mapping[Tuple[str, str, str], MeasurementValue],
    settings: RenewableControlSettings,
    resource_topology: ResourceTopology,
    renewable_rows: Sequence[Mapping[str, Any]],
    storage_rows: Sequence[Mapping[str, Any]],
    converter_rows: Sequence[Mapping[str, Any]],
    initial_storage_targets: Mapping[Tuple[str, str], Any],
    initial_converter_targets: Mapping[Tuple[str, str], Any],
    initial_renewable_targets: Mapping[Tuple[str, str], Any],
    allow_topology_recovery_fallback: bool,
    *,
    diesel_current_kw: float,
    diesel_min_kw: float,
    diesel_deadband_upper_kw: Optional[float] = None,
) -> Dict[str, Any]:
    balance_rows = [
        row
        for row in storage_rows
        if row.get("role") == "balance"
        and row.get("stateEligible")
    ]
    protective_rows: List[Mapping[str, Any]] = []
    for row in balance_rows:
        current_kw = _number(row.get("currentKw"))
        if current_kw is None:
            continue
        signed_min_kw, signed_max_kw = _grid_storage_signed_power_bounds_kw(row)
        if current_kw < signed_min_kw - EPSILON or current_kw > signed_max_kw + EPSILON:
            protective_rows.append(row)
    if not protective_rows:
        return _side_aware_renewable_recovery_plan_without_balance(
            snapshot,
            measurements,
            settings,
            resource_topology,
            renewable_rows,
            storage_rows,
            converter_rows,
            initial_storage_targets,
            initial_converter_targets,
            initial_renewable_targets,
            allow_topology_recovery_fallback,
            diesel_current_kw=diesel_current_kw,
            diesel_min_kw=diesel_min_kw,
            diesel_deadband_upper_kw=diesel_deadband_upper_kw,
        )

    protected_ac_present = any(
        row.get("connectionSide") == "AC" for row in protective_rows
    )
    protected_dc_group_ids = {
        str(row.get("dcTransferGroupId", ""))
        for row in protective_rows
        if row.get("connectionSide") == "DC"
        and str(row.get("dcTransferGroupId", ""))
    }

    def preserve_initial_storage_candidate(row: Mapping[str, Any]) -> bool:
        current_kw = _number(row.get("currentKw"))
        if current_kw is not None:
            signed_min_kw, signed_max_kw = _grid_storage_signed_power_bounds_kw(row)
            if (
                current_kw < signed_min_kw - EPSILON
                or current_kw > signed_max_kw + EPSILON
            ):
                return True
        if row.get("connectionSide") == "AC" and protected_ac_present:
            return False
        if (
            row.get("connectionSide") == "DC"
            and str(row.get("dcTransferGroupId", "")) in protected_dc_group_ids
        ):
            return False
        return True

    renewable_states: List[MutableMapping[str, Any]] = []
    for row in sorted(
        renewable_rows,
        key=lambda item: (
            str(item.get("connectionSide", "")),
            str(item.get("dcTransferGroupId", "")),
            str(item.get("technology", "")),
            str(item.get("dev_type", "")),
            str(item.get("dev_name", "")),
        ),
    ):
        current_kw = _number(row.get("planningCurrentKw"))
        capacity_kw = _number(row.get("capacityKw"))
        key = (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
        initial_target_kw = _number(
            initial_renewable_targets.get(key),
            current_kw,
        )
        eligible = bool(
            row.get("commandable")
            and current_kw is not None
            and capacity_kw is not None
            and capacity_kw > EPSILON
            and -EPSILON <= current_kw <= capacity_kw + EPSILON
        )
        renewable_states.append(
            {
                "row": row,
                "key": key,
                "side": str(row.get("connectionSide", "")),
                "groupId": str(row.get("dcTransferGroupId", "")),
                "currentKw": current_kw,
                "targetKw": current_kw,
                "recoveryMarginKw": (
                    min(
                        max(0.0, capacity_kw - current_kw),
                        (
                            max(
                                0.0,
                                _finite_number(initial_target_kw, current_kw)
                                - current_kw,
                            )
                            or (
                                settings.step_coefficient * capacity_kw
                                if allow_topology_recovery_fallback
                                else 0.0
                            )
                        ),
                    )
                    if eligible
                    else 0.0
                ),
                "curtailMarginKw": (
                    max(0.0, current_kw)
                    if eligible
                    else 0.0
                ),
            }
        )
    storage_states = [
        _side_aware_storage_state(
            row,
            settings,
            initial_storage_targets.get(
                (str(row.get("dev_type", "")), str(row.get("dev_name", ""))),
                row.get("currentKw"),
            ),
            preserve_initial=preserve_initial_storage_candidate(row),
        )
        for row in sorted(storage_rows, key=_grid_storage_sort_key)
        if row.get("role") == "grid_following"
    ]
    reduce_export_protective_group_ids = {
        str(row.get("dcTransferGroupId", ""))
        for row in balance_rows
        if row.get("connectionSide") == "DC"
        and str(row.get("dcTransferGroupId", ""))
        and _number(row.get("currentKw")) is not None
        and _finite_number(row.get("currentKw"))
        > _grid_storage_signed_power_bounds_kw(row)[1] + EPSILON
    }
    emergency_stop_export_group_ids = {
        str(row.get("dcTransferGroupId", ""))
        for row in balance_rows
        if row.get("connectionSide") == "DC"
        and str(row.get("dcTransferGroupId", ""))
        and _number(row.get("soc")) is not None
        and _number(row.get("socMin")) is not None
        and _finite_number(row.get("soc"))
        <= _finite_number(row.get("socMin")) + EPSILON
    }
    increase_export_protective_group_ids = {
        str(row.get("dcTransferGroupId", ""))
        for row in balance_rows
        if row.get("connectionSide") == "DC"
        and str(row.get("dcTransferGroupId", ""))
        and _number(row.get("currentKw")) is not None
        and _finite_number(row.get("currentKw"))
        < _grid_storage_signed_power_bounds_kw(row)[0] - EPSILON
    }
    converter_states: List[MutableMapping[str, Any]] = []
    for row in sorted(converter_rows, key=_converter_row_sort_key):
        current_kw = _number(row.get("currentKw"))
        capacity_kw = _number(row.get("transferCapacityKw"))
        key = (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
        target_kw = _number(initial_converter_targets.get(key), current_kw)
        step_kw = (
            settings.converter_step_ratio * capacity_kw
            if capacity_kw is not None and capacity_kw > EPSILON
            else 0.0
        )
        if target_kw is not None:
            target_kw = _clamp_converter_target_kw(row, target_kw)
        group_id = str(row.get("dcTransferGroupId", ""))
        if (
            group_id in emergency_stop_export_group_ids
            and group_id not in increase_export_protective_group_ids
        ):
            target_kw = 0.0
        preserve_immediate_stop = bool(
            current_kw is not None
            and target_kw is not None
            and target_kw > current_kw + EPSILON
            and (
                group_id in emergency_stop_export_group_ids
                or current_kw > EPSILON
            )
        )
        if (
            current_kw is not None
            and target_kw is not None
            and not preserve_immediate_stop
        ):
            target_kw = _move_toward(current_kw, target_kw, step_kw)
        used_step_kw = (
            abs(target_kw - current_kw)
            if target_kw is not None and current_kw is not None
            else step_kw
        )
        remaining_step_kw = max(0.0, step_kw - used_step_kw)
        converter_states.append(
            {
                "row": row,
                "key": key,
                "groupId": group_id,
                "currentKw": current_kw,
                "targetKw": target_kw,
                "capacityKw": capacity_kw,
                "exportMarginKw": (
                    max(0.0, capacity_kw + target_kw)
                    if group_id in increase_export_protective_group_ids
                    and group_id not in reduce_export_protective_group_ids
                    else min(max(0.0, capacity_kw + target_kw), remaining_step_kw)
                    if row.get("commandable")
                    and current_kw is not None
                    and current_kw <= EPSILON
                    and target_kw is not None
                    and capacity_kw is not None
                    and capacity_kw > EPSILON
                    else 0.0
                ),
                "exportReductionMarginKw": (
                    max(0.0, -target_kw)
                    if row.get("commandable")
                    and target_kw is not None
                    and group_id in reduce_export_protective_group_ids
                    and group_id not in increase_export_protective_group_ids
                    else min(max(0.0, -target_kw), remaining_step_kw)
                    if row.get("commandable") and target_kw is not None
                    else 0.0
                ),
            }
        )

    def apply_margin(
        states: Sequence[MutableMapping[str, Any]],
        request_kw: float,
        margin_key: str,
        target_sign: float,
    ) -> float:
        allocations = _allocate_by_margin(states, request_kw, margin_key)
        for state, allocation_kw in zip(states, allocations):
            if _number(state.get("targetKw")) is None:
                continue
            state["targetKw"] = _finite_number(state.get("targetKw")) + target_sign * allocation_kw
            state[margin_key] = max(
                0.0, _finite_number(state.get(margin_key)) - allocation_kw
            )
        return sum(allocations)

    def group_converters(group_id: str) -> List[MutableMapping[str, Any]]:
        return [
            state
            for state in converter_states
            if state.get("groupId") == group_id
        ]

    initial_ac_storage_effect_kw = sum(
        _finite_number(state.get("targetKw"))
        - _finite_number(state.get("currentKw"))
        for state in storage_states
        if state.get("side") == "AC"
        and state.get("currentKw") is not None
        and state.get("targetKw") is not None
    )
    initial_export_effect_kw = sum(
        _converter_ac_injection_delta_kw(
            state["row"],
            state.get("currentKw"),
            state.get("targetKw"),
        )
        for state in converter_states
        if state.get("currentKw") is not None
        and state.get("targetKw") is not None
    )
    diesel_margin_kw = max(
        0.0,
        diesel_current_kw
        - max(
            diesel_min_kw,
            _finite_number(diesel_deadband_upper_kw, diesel_min_kw),
        )
        - max(0.0, initial_ac_storage_effect_kw)
        - max(0.0, initial_export_effect_kw),
    )
    protected_ac = [
        row for row in protective_rows if row.get("connectionSide") == "AC"
    ]
    protected_groups = sorted(
        protected_dc_group_ids,
        key=_natural_topology_identity,
    )
    initial_projected_targets, _initial_indirect_devices = (
        _project_balance_storage_targets(
            balance_rows,
            renewable_states,
            storage_states,
            converter_states,
        )
    )
    ac_load_kw, dc_load_kw = _active_load_budgets(
        snapshot,
        measurements,
        resource_topology.dc_transfer_groups,
    )
    healthy_ac_balance_charge_kw = 0.0
    healthy_dc_local_recovery_by_group: Dict[str, float] = {}

    if protected_ac:
        ac_renewables = [
            state for state in renewable_states if state.get("side") == "AC"
        ]
        ac_grid = [state for state in storage_states if state.get("side") == "AC"]
        low_request_kw = sum(
            max(
                0.0,
                _finite_number(
                    initial_projected_targets.get(
                        (
                            str(row.get("dev_type", "")),
                            str(row.get("dev_name", "")),
                        ),
                        row.get("currentKw"),
                    )
                )
                - _grid_storage_signed_power_bounds_kw(row)[1],
            )
            for row in protected_ac
        )
        high_request_kw = sum(
            max(
                0.0,
                _grid_storage_signed_power_bounds_kw(row)[0]
                - _finite_number(
                    initial_projected_targets.get(
                        (
                            str(row.get("dev_type", "")),
                            str(row.get("dev_name", "")),
                        ),
                        row.get("currentKw"),
                    )
                ),
            )
            for row in protected_ac
        )
        if low_request_kw > EPSILON:
            recovered_kw = apply_margin(
                ac_renewables,
                min(low_request_kw, diesel_margin_kw),
                "recoveryMarginKw",
                1.0,
            )
            diesel_margin_kw -= recovered_kw
            remaining_kw = max(0.0, low_request_kw - recovered_kw)
            discharged_kw = apply_margin(
                ac_grid,
                min(remaining_kw, diesel_margin_kw),
                "dischargeMarginKw",
                1.0,
            )
            diesel_margin_kw -= discharged_kw
            remaining_kw = max(0.0, remaining_kw - discharged_kw)
            for group_id in sorted(
                resource_topology.dc_transfer_groups,
                key=_natural_topology_identity,
            ):
                if remaining_kw <= EPSILON or diesel_margin_kw <= EPSILON:
                    break
                exported_kw = apply_margin(
                    group_converters(group_id),
                    min(remaining_kw, diesel_margin_kw),
                    "exportMarginKw",
                    -1.0,
                )
                diesel_margin_kw -= exported_kw
                remaining_kw -= exported_kw
        if any(
            _number(row.get("soc")) is not None
            and _number(row.get("socMin")) is not None
            and _finite_number(row.get("soc"))
            < _finite_number(row.get("socMin")) - EPSILON
            for row in protected_ac
        ):
            recovered_kw = apply_margin(
                ac_renewables,
                min(
                    diesel_margin_kw,
                    sum(
                        _finite_number(state.get("recoveryMarginKw"))
                        for state in ac_renewables
                    ),
                ),
                "recoveryMarginKw",
                1.0,
            )
            diesel_margin_kw = max(0.0, diesel_margin_kw - recovered_kw)
        if high_request_kw > EPSILON:
            verified_surplus_kw = min(
                high_request_kw,
                sum(
                    max(0.0, -_finite_number(row.get("currentKw")))
                    for row in protected_ac
                ),
                sum(
                    max(0.0, _finite_number(state.get("currentKw")))
                    for state in ac_renewables
                ),
            )
            charged_kw = apply_margin(
                ac_grid,
                verified_surplus_kw,
                "chargeMarginKw",
                -1.0,
            )
            remaining_kw = max(0.0, high_request_kw - charged_kw)
            curtailed_kw = apply_margin(
                ac_renewables,
                remaining_kw,
                "curtailMarginKw",
                -1.0,
            )
            remaining_kw -= curtailed_kw
            for group_id in sorted(
                resource_topology.dc_transfer_groups,
                key=_natural_topology_identity,
            ):
                if remaining_kw <= EPSILON:
                    break
                remaining_kw -= apply_margin(
                    group_converters(group_id),
                    remaining_kw,
                    "exportReductionMarginKw",
                    1.0,
                )

    for group_id in protected_groups:
        group_balance = [
            row
            for row in protective_rows
            if row.get("connectionSide") == "DC"
            and row.get("dcTransferGroupId") == group_id
        ]
        group_renewables = [
            state
            for state in renewable_states
            if state.get("side") == "DC" and state.get("groupId") == group_id
        ]
        group_grid = [
            state
            for state in storage_states
            if state.get("side") == "DC" and state.get("groupId") == group_id
        ]
        low_request_kw = sum(
            max(
                0.0,
                _finite_number(
                    initial_projected_targets.get(
                        (
                            str(row.get("dev_type", "")),
                            str(row.get("dev_name", "")),
                        ),
                        row.get("currentKw"),
                    )
                )
                - _grid_storage_signed_power_bounds_kw(row)[1],
            )
            for row in group_balance
        )
        high_request_kw = sum(
            max(
                0.0,
                _grid_storage_signed_power_bounds_kw(row)[0]
                - _finite_number(
                    initial_projected_targets.get(
                        (
                            str(row.get("dev_type", "")),
                            str(row.get("dev_name", "")),
                        ),
                        row.get("currentKw"),
                    )
                ),
            )
            for row in group_balance
        )
        if low_request_kw > EPSILON:
            reduced_export_kw = apply_margin(
                group_converters(group_id),
                low_request_kw,
                "exportReductionMarginKw",
                1.0,
            )
            remaining_kw = max(0.0, low_request_kw - reduced_export_kw)
            recovered_kw = apply_margin(
                group_renewables,
                remaining_kw,
                "recoveryMarginKw",
                1.0,
            )
            remaining_kw -= recovered_kw
            apply_margin(
                group_grid,
                remaining_kw,
                "dischargeMarginKw",
                1.0,
            )
        if any(
            _number(row.get("soc")) is not None
            and _number(row.get("socMin")) is not None
            and _finite_number(row.get("soc"))
            < _finite_number(row.get("socMin")) - EPSILON
            for row in group_balance
        ):
            apply_margin(
                group_renewables,
                sum(
                    _finite_number(state.get("recoveryMarginKw"))
                    for state in group_renewables
                ),
                "recoveryMarginKw",
                1.0,
            )
        if high_request_kw > EPSILON:
            exported_kw = apply_margin(
                group_converters(group_id),
                min(high_request_kw, diesel_margin_kw),
                "exportMarginKw",
                -1.0,
            )
            diesel_margin_kw -= exported_kw
            remaining_kw = max(0.0, high_request_kw - exported_kw)
            apply_margin(
                group_renewables,
                remaining_kw,
                "curtailMarginKw",
                -1.0,
            )

    # Protection is scoped to the affected side or DC transfer group.  A
    # protective action elsewhere must not suppress ordinary renewable
    # recovery where a healthy local storage or load can absorb the increase.
    if not protected_ac_present:
        healthy_ac_renewables = [
            state for state in renewable_states if state.get("side") == "AC"
        ]
        healthy_ac_grid_storage = [
            state for state in storage_states if state.get("side") == "AC"
        ]
        healthy_ac_balance_storage = [
            row
            for row in balance_rows
            if row.get("connectionSide") == "AC"
        ]
        recovered_kw = apply_margin(
            healthy_ac_renewables,
            min(
                diesel_margin_kw,
                sum(
                    _finite_number(state.get("recoveryMarginKw"))
                    for state in healthy_ac_renewables
                ),
            ),
            "recoveryMarginKw",
            1.0,
        )
        diesel_margin_kw = max(0.0, diesel_margin_kw - recovered_kw)
        grid_charge_request_kw = min(
            sum(
                _finite_number(state.get("recoveryMarginKw"))
                for state in healthy_ac_renewables
            ),
            sum(
                _finite_number(state.get("chargeMarginKw"))
                for state in healthy_ac_grid_storage
            ),
        )
        grid_charge_source_kw = apply_margin(
            healthy_ac_renewables,
            grid_charge_request_kw,
            "recoveryMarginKw",
            1.0,
        )
        apply_margin(
            healthy_ac_grid_storage,
            grid_charge_source_kw,
            "chargeMarginKw",
            -1.0,
        )
        balance_charge_request_kw = min(
            sum(
                _finite_number(state.get("recoveryMarginKw"))
                for state in healthy_ac_renewables
            ),
            sum(
                max(
                    0.0,
                    _finite_number(row.get("currentKw"))
                    - _grid_storage_signed_power_bounds_kw(row)[0],
                )
                for row in healthy_ac_balance_storage
            ),
        )
        healthy_ac_balance_charge_kw = apply_margin(
            healthy_ac_renewables,
            balance_charge_request_kw,
            "recoveryMarginKw",
            1.0,
        )

    for group_id in sorted(
        resource_topology.dc_transfer_groups,
        key=_natural_topology_identity,
    ):
        if group_id in protected_dc_group_ids:
            continue
        healthy_group_renewables = [
            state
            for state in renewable_states
            if state.get("side") == "DC" and state.get("groupId") == group_id
        ]
        healthy_group_grid_storage = [
            state
            for state in storage_states
            if state.get("side") == "DC" and state.get("groupId") == group_id
        ]
        healthy_group_balance_storage = [
            row
            for row in balance_rows
            if row.get("connectionSide") == "DC"
            and row.get("dcTransferGroupId") == group_id
        ]
        renewable_current_kw = sum(
            _finite_number(state.get("currentKw"))
            for state in healthy_group_renewables
        )
        local_deficit_kw = max(
            0.0,
            _finite_number(dc_load_kw.get(group_id))
            - renewable_current_kw
            - sum(
                _finite_number(state.get("currentKw"))
                for state in healthy_group_grid_storage
            ),
        )
        healthy_dc_local_recovery_by_group[group_id] = apply_margin(
            healthy_group_renewables,
            local_deficit_kw,
            "recoveryMarginKw",
            1.0,
        )
        grid_charge_request_kw = min(
            sum(
                _finite_number(state.get("recoveryMarginKw"))
                for state in healthy_group_renewables
            ),
            sum(
                _finite_number(state.get("chargeMarginKw"))
                for state in healthy_group_grid_storage
            ),
        )
        grid_charge_source_kw = apply_margin(
            healthy_group_renewables,
            grid_charge_request_kw,
            "recoveryMarginKw",
            1.0,
        )
        apply_margin(
            healthy_group_grid_storage,
            grid_charge_source_kw,
            "chargeMarginKw",
            -1.0,
        )
        balance_charge_request_kw = min(
            sum(
                _finite_number(state.get("recoveryMarginKw"))
                for state in healthy_group_renewables
            ),
            sum(
                max(
                    0.0,
                    _finite_number(row.get("currentKw"))
                    - _grid_storage_signed_power_bounds_kw(row)[0],
                )
                for row in healthy_group_balance_storage
            ),
        )
        apply_margin(
            healthy_group_renewables,
            balance_charge_request_kw,
            "recoveryMarginKw",
            1.0,
        )
        export_request_kw = min(
            sum(
                _finite_number(state.get("recoveryMarginKw"))
                for state in healthy_group_renewables
            ),
            diesel_margin_kw,
            sum(
                _finite_number(state.get("exportMarginKw"))
                for state in group_converters(group_id)
            ),
        )
        export_source_kw = apply_margin(
            healthy_group_renewables,
            export_request_kw,
            "recoveryMarginKw",
            1.0,
        )
        exported_kw = apply_margin(
            group_converters(group_id),
            export_source_kw,
            "exportMarginKw",
            -1.0,
        )
        diesel_margin_kw = max(0.0, diesel_margin_kw - exported_kw)

    ac_renewable_delta_kw = sum(
        _finite_number(state.get("targetKw")) - _finite_number(state.get("currentKw"))
        for state in renewable_states
        if state.get("side") == "AC"
    )
    ac_storage_delta_kw = sum(
        _finite_number(state.get("targetKw")) - _finite_number(state.get("currentKw"))
        for state in storage_states
        if state.get("side") == "AC"
    )
    export_delta_kw = sum(
        _converter_ac_injection_delta_kw(
            state["row"],
            state.get("currentKw"),
            state.get("targetKw"),
        )
        for state in converter_states
        if state.get("currentKw") is not None and state.get("targetKw") is not None
    )

    healthy_dc_balance_delta_by_group: Dict[str, float] = {}
    for group_id, local_recovery_kw in healthy_dc_local_recovery_by_group.items():
        group_renewables = [
            state
            for state in renewable_states
            if state.get("side") == "DC" and state.get("groupId") == group_id
        ]
        group_storage = [
            state
            for state in storage_states
            if state.get("side") == "DC" and state.get("groupId") == group_id
        ]
        group_converter_states = group_converters(group_id)
        renewable_delta_kw = sum(
            _finite_number(state.get("targetKw"))
            - _finite_number(state.get("currentKw"))
            for state in group_renewables
        )
        storage_delta_kw = sum(
            _finite_number(state.get("targetKw"))
            - _finite_number(state.get("currentKw"))
            for state in group_storage
        )
        export_delta_kw = sum(
            _converter_ac_injection_delta_kw(
                state["row"],
                state.get("currentKw"),
                state.get("targetKw"),
            )
            for state in group_converter_states
            if state.get("currentKw") is not None
            and state.get("targetKw") is not None
        )
        healthy_dc_balance_delta_by_group[group_id] = (
            -(renewable_delta_kw + storage_delta_kw)
            + export_delta_kw
            + local_recovery_kw
        )

    projected_targets, indirect_devices = _project_balance_storage_targets(
        balance_rows,
        renewable_states,
        storage_states,
        converter_states,
        ac_balance_delta_kw=(
            -healthy_ac_balance_charge_kw
            if not protected_ac_present
            else None
        ),
        dc_balance_delta_by_group=(
            healthy_dc_balance_delta_by_group
            if healthy_dc_balance_delta_by_group
            else None
        ),
    )

    dc_budgets = []
    for group_id in sorted(resource_topology.dc_transfer_groups):
        group_renewables = [
            state
            for state in renewable_states
            if state.get("side") == "DC" and state.get("groupId") == group_id
        ]
        group_grid = [
            state
            for state in storage_states
            if state.get("side") == "DC" and state.get("groupId") == group_id
        ]
        group_balance = [
            row
            for row in balance_rows
            if row.get("connectionSide") == "DC"
            and row.get("dcTransferGroupId") == group_id
        ]
        dc_budgets.append(
            _DcGroupBudget(
                group_id=group_id,
                renewable_current_kw=sum(
                    _finite_number(state.get("currentKw")) for state in group_renewables
                ),
                renewable_recovery_kw=sum(
                    max(
                        0.0,
                        _finite_number(state.get("targetKw"))
                        - _finite_number(state.get("currentKw")),
                    )
                    for state in group_renewables
                ),
                local_net_demand_kw=_finite_number(dc_load_kw.get(group_id)),
                grid_storage_charge_margin_kw=sum(
                    _finite_number(state.get("chargeMarginKw")) for state in group_grid
                ),
                grid_storage_discharge_margin_kw=sum(
                    _finite_number(state.get("dischargeMarginKw")) for state in group_grid
                ),
                balance_storage_charge_margin_kw=sum(
                    max(
                        0.0,
                        _finite_number(row.get("currentKw"))
                        - _grid_storage_signed_power_bounds_kw(row)[0],
                    )
                    for row in group_balance
                ),
                balance_storage_discharge_margin_kw=sum(
                    max(
                        0.0,
                        _grid_storage_signed_power_bounds_kw(row)[1]
                        - _finite_number(row.get("currentKw")),
                    )
                    for row in group_balance
                ),
                balance_storage_current_kw=sum(
                    _finite_number(row.get("currentKw")) for row in group_balance
                ),
                acdc_current_export_kw=sum(
                    max(0.0, -_finite_number(state.get("currentKw")))
                    for state in group_converters(group_id)
                ),
                acdc_export_headroom_kw=sum(
                    _finite_number(state.get("exportMarginKw"))
                    for state in group_converters(group_id)
                ),
                acdc_step_headroom_kw=sum(
                    _finite_number(state.get("exportMarginKw"))
                    for state in group_converters(group_id)
                ),
            )
        )
    ac_balance = [
        row for row in balance_rows if row.get("connectionSide") == "AC"
    ]
    ac_budget = _AcSideBudget(
        renewable_current_kw=sum(
            _finite_number(state.get("currentKw"))
            for state in renewable_states
            if state.get("side") == "AC"
        ),
        renewable_recovery_kw=ac_renewable_delta_kw,
        local_net_demand_kw=ac_load_kw,
        diesel_down_margin_kw=max(0.0, diesel_current_kw - diesel_min_kw),
        grid_storage_charge_margin_kw=sum(
            _finite_number(state.get("chargeMarginKw"))
            for state in storage_states
            if state.get("side") == "AC"
        ),
        grid_storage_discharge_margin_kw=sum(
            _finite_number(state.get("dischargeMarginKw"))
            for state in storage_states
            if state.get("side") == "AC"
        ),
        balance_storage_charge_margin_kw=sum(
            max(
                0.0,
                _finite_number(row.get("currentKw"))
                - _grid_storage_signed_power_bounds_kw(row)[0],
            )
            for row in ac_balance
        ),
        balance_storage_discharge_margin_kw=sum(
            max(
                0.0,
                _grid_storage_signed_power_bounds_kw(row)[1]
                - _finite_number(row.get("currentKw")),
            )
            for row in ac_balance
        ),
        balance_storage_current_kw=sum(
            _finite_number(row.get("currentKw")) for row in ac_balance
        ),
        accepted_acdc_export_kw=export_delta_kw,
    )
    diesel_effect_kw = (
        ac_renewable_delta_kw
        - (
            healthy_ac_balance_charge_kw
            if not protected_ac_present
            else 0.0
        )
        + ac_storage_delta_kw
        + export_delta_kw
    )
    return {
        "renewableTargets": {
            state["key"]: state.get("targetKw") for state in renewable_states
        },
        "storageTargets": {
            state["key"]: state.get("targetKw") for state in storage_states
        },
        "storageStates": {state["key"]: state for state in storage_states},
        "converterTargets": {
            state["key"]: _clamp_converter_target_kw(
                state["row"],
                state.get("targetKw"),
            )
            for state in converter_states
            if state.get("targetKw") is not None
        },
        "dieselEffectKw": diesel_effect_kw,
        "dieselTargetKw": diesel_current_kw - diesel_effect_kw,
        "acBudget": ac_budget,
        "dcBudgets": tuple(dc_budgets),
        "projectedBalanceTargets": projected_targets,
        "indirectControlDevices": indirect_devices,
    }


def _converter_direct_state(
    row: Mapping[str, Any],
    base_target_kw: Any,
    settings: RenewableControlSettings,
) -> Dict[str, Any]:
    current_kw = _number(row.get("currentKw"))
    capacity_kw = _number(row.get("transferCapacityKw"))
    parsed_base_target_kw = _number(base_target_kw)
    if (
        not row.get("commandable")
        or current_kw is None
        or capacity_kw is None
        or capacity_kw <= EPSILON
    ):
        return {
            "row": row,
            "groupId": str(row.get("dcTransferGroupId", "")),
            "currentKw": current_kw,
            "targetKw": (
                _clamp_converter_target_kw(row, parsed_base_target_kw)
                if parsed_base_target_kw is not None
                else _clamp_converter_target_kw(row, current_kw)
                if current_kw is not None
                else None
            ),
            "exportMarginKw": 0.0,
            "exportReductionMarginKw": 0.0,
            "eligible": False,
        }

    signed_min_kw, signed_max_kw = _converter_signed_bounds_kw(row)
    bounded_base_target_kw = _clamp(
        _finite_number(base_target_kw, current_kw),
        signed_min_kw,
        signed_max_kw,
    )
    step_kw = max(0.0, settings.converter_step_ratio * capacity_kw)
    export_margin_kw, export_reduction_margin_kw = (
        _converter_export_margins_kw(
            row,
            current_kw,
            bounded_base_target_kw,
            step_kw,
        )
    )
    return {
        "row": row,
        "groupId": str(row.get("dcTransferGroupId", "")),
        "currentKw": current_kw,
        "targetKw": bounded_base_target_kw,
        "capacityKw": capacity_kw,
        "stepKw": step_kw,
        "exportMarginKw": export_margin_kw,
        "exportReductionMarginKw": export_reduction_margin_kw,
        "eligible": bool(str(row.get("dcTransferGroupId", ""))),
    }


def _apply_converter_group_adjustment(
    converter_states: Sequence[MutableMapping[str, Any]],
    group_id: str,
    request_kw: float,
    *,
    increase_export: bool,
) -> float:
    margin_key = "exportMarginKw" if increase_export else "exportReductionMarginKw"
    group_states = [
        state
        for state in converter_states
        if state.get("eligible") and state.get("groupId") == group_id
    ]
    allocations = _allocate_by_margin(group_states, request_kw, margin_key)
    for state, allocation_kw in zip(group_states, allocations):
        row = state["row"]
        target_ac_injection_kw = _converter_ac_injection_kw(
            row,
            state.get("targetKw"),
        )
        if increase_export:
            target_ac_injection_kw += allocation_kw
        else:
            target_ac_injection_kw = max(
                0.0,
                target_ac_injection_kw - allocation_kw,
            )
        state["targetKw"] = _converter_target_from_ac_injection_kw(
            row,
            target_ac_injection_kw,
        )
        state[margin_key] = max(
            0.0,
            _finite_number(state.get(margin_key)) - allocation_kw,
        )
    return sum(allocations)


def _plan_direct_grid_storage_dispatch(
    storage_rows: Sequence[Mapping[str, Any]],
    converter_rows: Sequence[Mapping[str, Any]],
    base_converter_targets: Mapping[Tuple[str, str], float],
    settings: RenewableControlSettings,
    *,
    diesel_current_kw: float,
    diesel_min_kw: float,
    diesel_deadband_upper_kw: float,
    balance_effect_kw: float,
    enabled: bool,
) -> Dict[str, Any]:
    predicted_after_balance_kw = diesel_current_kw - balance_effect_kw
    diesel_boundary_distance_kw = max(
        0.0,
        predicted_after_balance_kw - diesel_deadband_upper_kw,
    )
    grid_rows = sorted(
        (
            row
            for row in storage_rows
            if row.get("role") == "grid_following"
        ),
        key=_grid_storage_sort_key,
    )
    storage_states: List[MutableMapping[str, Any]] = []
    for row in grid_rows:
        state = _grid_storage_target_margins(
            row,
            settings,
            diesel_boundary_distance_kw,
        )
        state.update(
            {
                "row": row,
                "key": (
                    str(row.get("dev_type", "")),
                    str(row.get("dev_name", "")),
                ),
                "side": str(row.get("connectionSide", "")),
                "groupId": str(row.get("dcTransferGroupId", "")),
            }
        )
        if not enabled and state.get("currentKw") is not None:
            state["targetKw"] = state["currentKw"]
            state["chargeMarginKw"] = 0.0
            state["dischargeMarginKw"] = 0.0
            state["positiveReductionMarginKw"] = 0.0
            state["protectiveDeltaKw"] = 0.0
        storage_states.append(state)

    converter_states = [
        _converter_direct_state(
            row,
            base_converter_targets.get(
                (str(row.get("dev_type", "")), str(row.get("dev_name", ""))),
                row.get("currentKw"),
            ),
            settings,
        )
        for row in sorted(converter_rows, key=_converter_row_sort_key)
    ]

    if enabled:
        # AC protective corrections are direct. DC protective corrections are
        # paired with an equal same-group ACDC target change.
        for state in storage_states:
            if state.get("side") != "AC" or not state.get("eligible"):
                continue
            state["targetKw"] = _finite_number(state.get("targetKw"))

        for group_id in sorted(
            {
                str(state.get("groupId", ""))
                for state in storage_states
                if state.get("side") == "DC" and state.get("groupId")
            },
            key=_natural_topology_identity,
        ):
            group_states = [
                state
                for state in storage_states
                if state.get("side") == "DC"
                and state.get("groupId") == group_id
                and state.get("eligible")
            ]
            for increase_export in (True, False):
                candidates: List[MutableMapping[str, Any]] = []
                for state in group_states:
                    protective_delta_kw = _finite_number(state.get("protectiveDeltaKw"))
                    requested_kw = (
                        max(0.0, protective_delta_kw)
                        if increase_export
                        else max(0.0, -protective_delta_kw)
                    )
                    if requested_kw <= EPSILON:
                        continue
                    candidates.append({"state": state, "marginKw": requested_kw})
                if not candidates:
                    continue
                converter_accepted_kw = _apply_converter_group_adjustment(
                    converter_states,
                    group_id,
                    sum(_finite_number(item.get("marginKw")) for item in candidates),
                    increase_export=increase_export,
                )
                storage_allocations = _allocate_by_margin(
                    candidates,
                    converter_accepted_kw,
                    "marginKw",
                )
                for item, allocation_kw in zip(candidates, storage_allocations):
                    state = item["state"]
                    current_kw = _finite_number(state.get("currentKw"))
                    state["targetKw"] = (
                        current_kw + allocation_kw
                        if increase_export
                        else current_kw - allocation_kw
                    )

    def ac_effect_kw() -> float:
        return sum(
            _finite_number(state.get("targetKw"))
            - _finite_number(state.get("currentKw"))
            for state in storage_states
            if state.get("side") == "AC"
            and state.get("currentKw") is not None
            and state.get("targetKw") is not None
        )

    def converter_effect_kw() -> float:
        return sum(
            _finite_number(
                base_converter_targets.get(
                    (
                        str(state["row"].get("dev_type", "")),
                        str(state["row"].get("dev_name", "")),
                    ),
                    state.get("currentKw"),
                )
            )
            - _finite_number(state.get("targetKw"))
            for state in converter_states
            if state.get("targetKw") is not None
        )

    predicted_kw = (
        predicted_after_balance_kw
        - ac_effect_kw()
        - converter_effect_kw()
    )
    action = "hold"
    requested_kw = 0.0
    if enabled and predicted_kw < diesel_min_kw - EPSILON:
        action = "reduce_discharge"
        requested_kw = diesel_min_kw - predicted_kw
        ac_states = [
            state
            for state in storage_states
            if state.get("side") == "AC"
            and state.get("eligible")
            and _finite_number(state.get("positiveReductionMarginKw")) > EPSILON
        ]
        ac_allocations = _allocate_by_margin(
            ac_states,
            requested_kw,
            "positiveReductionMarginKw",
        )
        for state, allocation_kw in zip(ac_states, ac_allocations):
            state["targetKw"] = _finite_number(state.get("targetKw")) - allocation_kw
        remaining_kw = max(0.0, requested_kw - sum(ac_allocations))

        group_budgets: List[MutableMapping[str, Any]] = []
        for group_id in sorted(
            {
                str(state.get("groupId", ""))
                for state in storage_states
                if state.get("side") == "DC" and state.get("groupId")
            },
            key=_natural_topology_identity,
        ):
            storage_margin_kw = sum(
                _finite_number(state.get("positiveReductionMarginKw"))
                for state in storage_states
                if state.get("side") == "DC"
                and state.get("groupId") == group_id
                and state.get("eligible")
            )
            converter_margin_kw = sum(
                _finite_number(state.get("exportReductionMarginKw"))
                for state in converter_states
                if state.get("groupId") == group_id and state.get("eligible")
            )
            group_budgets.append(
                {
                    "groupId": group_id,
                    "marginKw": min(storage_margin_kw, converter_margin_kw),
                }
            )
        group_allocations = _allocate_by_margin(
            group_budgets,
            remaining_kw,
            "marginKw",
        )
        for group_budget, group_request_kw in zip(group_budgets, group_allocations):
            group_id = str(group_budget.get("groupId", ""))
            converter_accepted_kw = _apply_converter_group_adjustment(
                converter_states,
                group_id,
                group_request_kw,
                increase_export=False,
            )
            group_storage_states = [
                state
                for state in storage_states
                if state.get("side") == "DC"
                and state.get("groupId") == group_id
                and state.get("eligible")
            ]
            storage_allocations = _allocate_by_margin(
                group_storage_states,
                converter_accepted_kw,
                "positiveReductionMarginKw",
            )
            for state, allocation_kw in zip(group_storage_states, storage_allocations):
                state["targetKw"] = _finite_number(state.get("targetKw")) - allocation_kw
    elif enabled and predicted_kw > diesel_deadband_upper_kw + EPSILON:
        action = "increase_discharge"
        requested_kw = predicted_kw - diesel_deadband_upper_kw
        ac_states = [
            state
            for state in storage_states
            if state.get("side") == "AC"
            and state.get("eligible")
            and _finite_number(state.get("dischargeMarginKw")) > EPSILON
        ]
        ac_allocations = _allocate_by_margin(
            ac_states,
            requested_kw,
            "dischargeMarginKw",
        )
        for state, allocation_kw in zip(ac_states, ac_allocations):
            state["targetKw"] = _finite_number(state.get("targetKw")) + allocation_kw
        remaining_kw = max(0.0, requested_kw - sum(ac_allocations))

        group_budgets = []
        for group_id in sorted(
            {
                str(state.get("groupId", ""))
                for state in storage_states
                if state.get("side") == "DC" and state.get("groupId")
            },
            key=_natural_topology_identity,
        ):
            storage_margin_kw = sum(
                _finite_number(state.get("dischargeMarginKw"))
                for state in storage_states
                if state.get("side") == "DC"
                and state.get("groupId") == group_id
                and state.get("eligible")
            )
            converter_margin_kw = sum(
                _finite_number(state.get("exportMarginKw"))
                for state in converter_states
                if state.get("groupId") == group_id and state.get("eligible")
            )
            group_budgets.append(
                {
                    "groupId": group_id,
                    "marginKw": min(storage_margin_kw, converter_margin_kw),
                }
            )
        group_allocations = _allocate_by_margin(
            group_budgets,
            remaining_kw,
            "marginKw",
        )
        for group_budget, group_request_kw in zip(group_budgets, group_allocations):
            group_id = str(group_budget.get("groupId", ""))
            converter_accepted_kw = _apply_converter_group_adjustment(
                converter_states,
                group_id,
                group_request_kw,
                increase_export=True,
            )
            group_storage_states = [
                state
                for state in storage_states
                if state.get("side") == "DC"
                and state.get("groupId") == group_id
                and state.get("eligible")
            ]
            storage_allocations = _allocate_by_margin(
                group_storage_states,
                converter_accepted_kw,
                "dischargeMarginKw",
            )
            for state, allocation_kw in zip(group_storage_states, storage_allocations):
                state["targetKw"] = _finite_number(state.get("targetKw")) + allocation_kw

    final_ac_effect_kw = ac_effect_kw()
    final_converter_effect_kw = converter_effect_kw()
    final_predicted_kw = (
        predicted_after_balance_kw
        - final_ac_effect_kw
        - final_converter_effect_kw
    )
    accepted_correction_kw = (
        max(0.0, predicted_kw - final_predicted_kw)
        if action == "increase_discharge"
        else max(0.0, final_predicted_kw - predicted_kw)
        if action == "reduce_discharge"
        else 0.0
    )

    storage_targets = {
        state["key"]: state.get("targetKw")
        for state in storage_states
    }
    converter_targets = {
        (
            str(state["row"].get("dev_type", "")),
            str(state["row"].get("dev_name", "")),
        ): _clamp_converter_target_kw(state["row"], state.get("targetKw"))
        for state in converter_states
        if state.get("targetKw") is not None
    }
    group_summaries = []
    for group_id in sorted(
        {
            str(state.get("groupId", ""))
            for state in storage_states
            if state.get("side") == "DC" and state.get("groupId")
        },
        key=_natural_topology_identity,
    ):
        group_summaries.append(
            {
                "dcTransferGroupId": group_id,
                "storageDeltaKw": sum(
                    _finite_number(state.get("targetKw"))
                    - _finite_number(state.get("currentKw"))
                    for state in storage_states
                    if state.get("side") == "DC"
                    and state.get("groupId") == group_id
                    and state.get("currentKw") is not None
                    and state.get("targetKw") is not None
                ),
                "acdcDeltaKw": sum(
                    _finite_number(
                        base_converter_targets.get(
                            (
                                str(state["row"].get("dev_type", "")),
                                str(state["row"].get("dev_name", "")),
                            ),
                            state.get("currentKw"),
                        )
                    )
                    - _finite_number(state.get("targetKw"))
                    for state in converter_states
                    if state.get("groupId") == group_id
                    and state.get("targetKw") is not None
                ),
                "exportHeadroomKw": sum(
                    _finite_number(state.get("exportMarginKw"))
                    for state in converter_states
                    if state.get("groupId") == group_id
                ),
            }
        )

    return {
        "action": action,
        "requestedKw": requested_kw,
        "acceptedKw": accepted_correction_kw,
        "residualKw": max(0.0, requested_kw - accepted_correction_kw),
        "storageStates": {
            state["key"]: state
            for state in storage_states
        },
        "storageTargets": storage_targets,
        "converterTargets": converter_targets,
        "acEffectKw": final_ac_effect_kw,
        "acdcEffectKw": final_converter_effect_kw,
        "predictedDieselKw": final_predicted_kw,
        "groups": group_summaries,
    }


def _plan_direct_grid_forming_dispatch(
    renewable_rows: Sequence[Mapping[str, Any]],
    storage_rows: Sequence[Mapping[str, Any]],
    converter_rows: Sequence[Mapping[str, Any]],
    renewable_targets: Mapping[Tuple[str, str], Any],
    grid_storage_targets: Mapping[Tuple[str, str], Any],
    converter_targets: Mapping[Tuple[str, str], Any],
    projected_balance_targets: Mapping[Tuple[str, str], Any],
    settings: RenewableControlSettings,
    *,
    diesel_current_kw: float,
    diesel_min_kw: float,
    diesel_deadband_upper_kw: float,
    enabled: bool,
    dc_load_kw: Optional[Mapping[str, float]] = None,
) -> Dict[str, Any]:
    renewable_target_map = {}
    for row in renewable_rows:
        key = (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
        if key not in renewable_targets:
            continue
        renewable_target_map[key] = _number(
            renewable_targets.get(key),
            row.get("planningCurrentKw", row.get("currentKw")),
        )
    grid_target_map = {
        (str(row.get("dev_type", "")), str(row.get("dev_name", ""))): _number(
            grid_storage_targets.get(
                (str(row.get("dev_type", "")), str(row.get("dev_name", ""))),
                row.get("currentKw"),
            )
        )
        for row in storage_rows
        if row.get("role") == "grid_following"
    }
    protective_grid_storage_keys = {
        (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
        for row in storage_rows
        if row.get("role") == "grid_following"
        and _number(row.get("currentKw")) is not None
        and (
            _finite_number(row.get("currentKw"))
            < _grid_storage_signed_power_bounds_kw(row)[0] - EPSILON
            or _finite_number(row.get("currentKw"))
            > _grid_storage_signed_power_bounds_kw(row)[1] + EPSILON
        )
    }
    converter_target_map = {
        (str(row.get("dev_type", "")), str(row.get("dev_name", ""))): (
            _clamp_converter_target_kw(
                row,
                converter_targets.get(
                    (str(row.get("dev_type", "")), str(row.get("dev_name", ""))),
                    row.get("currentKw"),
                ),
            )
        )
        for row in converter_rows
        if _number(row.get("currentKw")) is not None
    }
    balance_rows = sorted(
        (row for row in storage_rows if row.get("role") == "balance"),
        key=_grid_storage_sort_key,
    )
    direct_balance_rows = [
        row
        for row in balance_rows
        if row.get("commandable") and row.get("stateEligible")
    ]
    direct_balance_keys = {
        (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
        for row in direct_balance_rows
    }
    protective_balance_keys = {
        (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
        for row in balance_rows
        if _number(row.get("currentKw")) is not None
        and (
            _finite_number(row.get("currentKw"))
            < _grid_storage_signed_power_bounds_kw(row)[0] - EPSILON
            or _finite_number(row.get("currentKw"))
            > _grid_storage_signed_power_bounds_kw(row)[1] + EPSILON
        )
    }
    projected_balance_keys = {
        (str(key[0]), str(key[1]))
        for key in projected_balance_targets
        if isinstance(key, tuple) and len(key) == 2
    }
    balance_target_map: Dict[Tuple[str, str], Optional[float]] = {}
    for row in balance_rows:
        key = (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
        current_kw = _number(row.get("currentKw"))
        requested_kw = _number(projected_balance_targets.get(key), current_kw)
        if current_kw is None:
            balance_target_map[key] = None
            continue
        if row.get("stateEligible"):
            signed_min_kw, signed_max_kw = _grid_storage_signed_power_bounds_kw(row)
            requested_target_kw = _finite_number(requested_kw, current_kw)
            soc = _number(row.get("soc"))
            soc_min = _number(row.get("socMin"))
            soc_max = _number(row.get("socMax"))
            emergency_charge_stop = bool(
                current_kw < signed_min_kw - EPSILON
                and soc is not None
                and soc_max is not None
                and soc >= soc_max - EPSILON
            )
            emergency_discharge_stop = bool(
                current_kw > signed_max_kw + EPSILON
                and soc is not None
                and soc_min is not None
                and soc <= soc_min + EPSILON
            )
            if emergency_charge_stop or emergency_discharge_stop:
                balance_target_map[key] = _clamp(
                    requested_target_kw,
                    signed_min_kw,
                    signed_max_kw,
                )
            elif current_kw < signed_min_kw - EPSILON:
                balance_target_map[key] = _clamp(
                    requested_target_kw,
                    current_kw,
                    signed_max_kw,
                )
            elif current_kw > signed_max_kw + EPSILON:
                balance_target_map[key] = _clamp(
                    requested_target_kw,
                    signed_min_kw,
                    current_kw,
                )
            else:
                balance_target_map[key] = _clamp(
                    requested_target_kw,
                    signed_min_kw,
                    signed_max_kw,
                )
        else:
            balance_target_map[key] = current_kw

    renewable_states = [
        {
            "row": row,
            "side": str(row.get("connectionSide", "")),
            "groupId": str(row.get("dcTransferGroupId", "")),
            "currentKw": _number(row.get("planningCurrentKw", row.get("currentKw"))),
            "targetKw": renewable_target_map.get(
                (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
            ),
        }
        for row in renewable_rows
        if (
            str(row.get("dev_type", "")),
            str(row.get("dev_name", "")),
        )
        in renewable_target_map
    ]
    grid_states = [
        {
            "row": row,
            "side": str(row.get("connectionSide", "")),
            "groupId": str(row.get("dcTransferGroupId", "")),
            "currentKw": _number(row.get("currentKw")),
            "targetKw": grid_target_map.get(
                (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
            ),
        }
        for row in storage_rows
        if row.get("role") == "grid_following"
    ]
    converter_states: List[MutableMapping[str, Any]] = []
    for row in sorted(converter_rows, key=_converter_row_sort_key):
        key = (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
        state = _converter_direct_state(
            row,
            converter_target_map.get(key, row.get("currentKw")),
            settings,
        )
        if state.get("currentKw") is None or state.get("targetKw") is None:
            continue
        converter_states.append({**state, "key": key})

    def sync_candidate_states() -> None:
        for state in renewable_states:
            row = state["row"]
            key = (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
            state["targetKw"] = renewable_target_map.get(key, state.get("currentKw"))
        for state in grid_states:
            row = state["row"]
            key = (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
            state["targetKw"] = grid_target_map.get(key, state.get("currentKw"))

    # A side-aware state-machine projection is authoritative: it may represent
    # an SOC hard-protection action or local-load absorption that cannot be
    # reconstructed from deltas alone. Only synthesize targets for directly
    # dispatchable DC balancing storage that does not already have such a
    # projection.
    def recalculate_dc_balance_targets() -> None:
        sync_candidate_states()
        group_ids = sorted(
            {
                str(row.get("dcTransferGroupId", ""))
                for row in balance_rows
                if row.get("connectionSide") == "DC"
                and str(row.get("dcTransferGroupId", ""))
                and (
                    (key := (
                        str(row.get("dev_type", "")),
                        str(row.get("dev_name", "")),
                    ))
                    in protective_balance_keys
                    or key in direct_balance_keys
                    and key not in projected_balance_keys
                )
            },
            key=_natural_topology_identity,
        )
        for group_id in group_ids:
            group_rows = [
                row
                for row in balance_rows
                if row.get("connectionSide") == "DC"
                and row.get("dcTransferGroupId") == group_id
                and (
                    (
                        str(row.get("dev_type", "")),
                        str(row.get("dev_name", "")),
                    )
                    in direct_balance_keys
                    and (
                        str(row.get("dev_type", "")),
                        str(row.get("dev_name", "")),
                    )
                    not in projected_balance_keys
                    or (
                        str(row.get("dev_type", "")),
                        str(row.get("dev_name", "")),
                    )
                    in protective_balance_keys
                )
            ]
            if not group_rows:
                continue
            group_renewables = [
                state
                for state in renewable_states
                if state.get("side") == "DC" and state.get("groupId") == group_id
            ]
            group_storage = [
                state
                for state in grid_states
                if state.get("side") == "DC" and state.get("groupId") == group_id
            ]
            group_converters = [
                state for state in converter_states if state.get("groupId") == group_id
            ]
            renewable_delta_kw = sum(
                _finite_number(state.get("targetKw"))
                - _finite_number(state.get("currentKw"))
                for state in group_renewables
            )
            storage_delta_kw = sum(
                _finite_number(state.get("targetKw"))
                - _finite_number(state.get("currentKw"))
                for state in group_storage
            )
            nonbalance_delta_kw = renewable_delta_kw + storage_delta_kw
            current_renewable_kw = sum(
                _finite_number(state.get("currentKw"))
                for state in group_renewables
            )
            current_grid_storage_kw = sum(
                _finite_number(state.get("currentKw"))
                for state in group_storage
            )
            local_sink_headroom_kw = max(
                0.0,
                _finite_number((dc_load_kw or {}).get(group_id))
                - current_renewable_kw
                - current_grid_storage_kw,
            )
            locally_absorbed_kw = min(
                max(0.0, nonbalance_delta_kw),
                local_sink_headroom_kw,
            )
            effective_nonbalance_delta_kw = (
                nonbalance_delta_kw - locally_absorbed_kw
            )
            export_delta_kw = sum(
                _converter_ac_injection_delta_kw(
                    state["row"],
                    state.get("currentKw"),
                    state.get("targetKw"),
                )
                for state in group_converters
            )
            balance_delta_kw = export_delta_kw - effective_nonbalance_delta_kw
            recalculated_targets, _indirect = _project_balance_storage_targets(
                group_rows,
                group_renewables,
                group_storage,
                group_converters,
                dc_balance_delta_by_group={group_id: balance_delta_kw},
            )
            balance_target_map.update(recalculated_targets)

    recalculate_dc_balance_targets()

    def ac_effect_kw() -> float:
        renewable_effect = sum(
            _finite_number(renewable_target_map.get(key), current_kw) - current_kw
            for row in renewable_rows
            if row.get("connectionSide") == "AC"
            and (current_kw := _number(row.get("planningCurrentKw", row.get("currentKw"))))
            is not None
            and (
                key := (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
            )
        )
        grid_effect = sum(
            _finite_number(grid_target_map.get(key), current_kw) - current_kw
            for row in storage_rows
            if row.get("role") == "grid_following"
            and row.get("connectionSide") == "AC"
            and (current_kw := _number(row.get("currentKw"))) is not None
            and (
                key := (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
            )
        )
        balance_effect = sum(
            _finite_number(balance_target_map.get(key), current_kw) - current_kw
            for row in balance_rows
            if row.get("connectionSide") == "AC"
            and (current_kw := _number(row.get("currentKw"))) is not None
            and (key := (
                str(row.get("dev_type", "")),
                str(row.get("dev_name", "")),
            ))
            in (
                direct_balance_keys | projected_balance_keys
            )
        )
        converter_effect = sum(
            _converter_ac_injection_delta_kw(
                state["row"],
                state.get("currentKw"),
                state.get("targetKw"),
            )
            for state in converter_states
        )
        return renewable_effect + grid_effect + balance_effect + converter_effect

    predicted_diesel_kw = diesel_current_kw - ac_effect_kw()
    action = "hold"
    if (
        enabled
        and diesel_current_kw > diesel_deadband_upper_kw + EPSILON
        and predicted_diesel_kw > diesel_deadband_upper_kw + EPSILON
    ):
        action = "increase_grid_forming_discharge"
        remaining_kw = predicted_diesel_kw - diesel_deadband_upper_kw
        ac_candidates: List[MutableMapping[str, Any]] = []
        for row in balance_rows:
            if (
                row.get("connectionSide") != "AC"
                or not row.get("commandable")
                or not row.get("stateEligible")
            ):
                continue
            key = (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
            target_kw = _number(balance_target_map.get(key))
            if target_kw is None:
                continue
            _signed_min_kw, signed_max_kw = _grid_storage_signed_power_bounds_kw(row)
            ac_candidates.append(
                {
                    "row": row,
                    "key": key,
                    "marginKw": max(0.0, signed_max_kw - target_kw),
                }
            )
        allocations = _allocate_by_margin(ac_candidates, remaining_kw, "marginKw")
        for candidate, allocation_kw in zip(ac_candidates, allocations):
            key = candidate["key"]
            balance_target_map[key] = _finite_number(balance_target_map.get(key)) + allocation_kw
        remaining_kw = max(0.0, remaining_kw - sum(allocations))

        dc_group_ids = sorted(
            {
                str(row.get("dcTransferGroupId", ""))
                for row in balance_rows
                if row.get("connectionSide") == "DC"
                and row.get("commandable")
                and row.get("stateEligible")
                and str(row.get("dcTransferGroupId", ""))
            },
            key=_natural_topology_identity,
        )
        for group_id in dc_group_ids:
            if remaining_kw <= EPSILON:
                break
            balance_candidates = []
            for row in balance_rows:
                if (
                    row.get("connectionSide") != "DC"
                    or row.get("dcTransferGroupId") != group_id
                    or not row.get("commandable")
                    or not row.get("stateEligible")
                ):
                    continue
                key = (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
                target_kw = _number(balance_target_map.get(key))
                if target_kw is None:
                    continue
                _signed_min_kw, signed_max_kw = _grid_storage_signed_power_bounds_kw(row)
                balance_candidates.append(
                    {
                        "row": row,
                        "key": key,
                        "marginKw": max(0.0, signed_max_kw - target_kw),
                    }
                )
            converter_margin_kw = sum(
                _finite_number(state.get("exportMarginKw"))
                for state in converter_states
                if state.get("groupId") == group_id
            )
            group_request_kw = min(
                remaining_kw,
                converter_margin_kw,
                sum(_finite_number(item.get("marginKw")) for item in balance_candidates),
            )
            exported_kw = _apply_converter_group_adjustment(
                converter_states,
                group_id,
                group_request_kw,
                increase_export=True,
            )
            balance_allocations = _allocate_by_margin(
                balance_candidates,
                exported_kw,
                "marginKw",
            )
            for candidate, allocation_kw in zip(balance_candidates, balance_allocations):
                key = candidate["key"]
                balance_target_map[key] = _finite_number(balance_target_map.get(key)) + allocation_kw
            remaining_kw = max(0.0, remaining_kw - sum(balance_allocations))

    predicted_after_forming_kw = diesel_current_kw - ac_effect_kw()
    helpful_diesel_raise_kw = sum(
        max(
            0.0,
            current_kw
            - _finite_number(renewable_target_map.get(key), current_kw),
        )
        for row in renewable_rows
        if row.get("connectionSide") == "AC"
        and (current_kw := _number(row.get("planningCurrentKw", row.get("currentKw"))))
        is not None
        and (key := (str(row.get("dev_type", "")), str(row.get("dev_name", ""))))
    )
    helpful_diesel_raise_kw += sum(
        max(
            0.0,
            current_kw
            - _finite_number(
                (
                    grid_target_map
                    if row.get("role") == "grid_following"
                    else balance_target_map
                ).get(key),
                current_kw,
            ),
        )
        for row in storage_rows
        if row.get("connectionSide") == "AC"
        and (current_kw := _number(row.get("currentKw"))) is not None
        and (key := (str(row.get("dev_type", "")), str(row.get("dev_name", ""))))
        and (
            row.get("role") == "grid_following"
            or key in direct_balance_keys
        )
    )
    helpful_diesel_raise_kw += sum(
        max(
            0.0,
            _finite_number(state.get("targetKw"))
            - _finite_number(state.get("currentKw")),
        )
        for state in converter_states
    )
    validation_floor_kw = (
        diesel_min_kw
        if diesel_current_kw >= diesel_min_kw - EPSILON
        else min(diesel_min_kw, diesel_current_kw + helpful_diesel_raise_kw)
    )
    if enabled and predicted_after_forming_kw < validation_floor_kw - EPSILON:
        action = "restore_diesel_floor"
        remaining_kw = validation_floor_kw - predicted_after_forming_kw
        converter_candidates = []
        for state in converter_states:
            current_kw = _finite_number(state.get("currentKw"))
            target_kw = _finite_number(state.get("targetKw"))
            rollback_margin_kw = max(0.0, current_kw - target_kw)
            converter_candidates.append(
                {"state": state, "marginKw": rollback_margin_kw}
            )
        converter_allocations = _allocate_by_margin(
            converter_candidates,
            remaining_kw,
            "marginKw",
        )
        for candidate, allocation_kw in zip(
            converter_candidates,
            converter_allocations,
        ):
            state = candidate["state"]
            state["targetKw"] = _clamp_converter_target_kw(
                state["row"],
                _finite_number(state.get("targetKw")) + allocation_kw,
            )
        remaining_kw = max(0.0, remaining_kw - sum(converter_allocations))
        recalculate_dc_balance_targets()

        rollback_candidates: List[MutableMapping[str, Any]] = []
        for row in renewable_rows:
            if row.get("connectionSide") != "AC":
                continue
            key = (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
            current_kw = _number(row.get("planningCurrentKw", row.get("currentKw")))
            target_kw = _number(renewable_target_map.get(key))
            if current_kw is None or target_kw is None:
                continue
            rollback_candidates.append(
                {
                    "kind": "renewable",
                    "key": key,
                    "marginKw": max(0.0, target_kw - current_kw),
                }
            )
        for row in storage_rows:
            if row.get("connectionSide") != "AC":
                continue
            key = (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
            if key in protective_grid_storage_keys:
                continue
            current_kw = _number(row.get("currentKw"))
            targets = (
                grid_target_map
                if row.get("role") == "grid_following"
                else balance_target_map
            )
            if row.get("role") == "balance" and key not in direct_balance_keys:
                continue
            target_kw = _number(targets.get(key))
            if current_kw is None or target_kw is None:
                continue
            rollback_candidates.append(
                {
                    "kind": str(row.get("role", "")),
                    "key": key,
                    "marginKw": max(0.0, target_kw - current_kw),
                }
            )
        rollback_allocations = _allocate_by_margin(
            rollback_candidates,
            remaining_kw,
            "marginKw",
        )
        for candidate, allocation_kw in zip(
            rollback_candidates,
            rollback_allocations,
        ):
            key = candidate["key"]
            if candidate["kind"] == "renewable":
                renewable_target_map[key] = _finite_number(
                    renewable_target_map.get(key)
                ) - allocation_kw
            elif candidate["kind"] == "grid_following":
                grid_target_map[key] = _finite_number(
                    grid_target_map.get(key)
                ) - allocation_kw
            else:
                balance_target_map[key] = _finite_number(
                    balance_target_map.get(key)
                ) - allocation_kw

        recalculate_dc_balance_targets()

    converter_target_map.update(
        {
            state["key"]: _clamp_converter_target_kw(
                state["row"],
                state.get("targetKw"),
            )
            for state in converter_states
        }
    )
    final_effect_kw = ac_effect_kw()
    final_predicted_diesel_kw = diesel_current_kw - final_effect_kw
    balance_states = {}
    for row in balance_rows:
        key = (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
        current_kw = _number(row.get("currentKw"))
        target_kw = _number(balance_target_map.get(key), current_kw)
        signed_min_kw, signed_max_kw = (
            _grid_storage_signed_power_bounds_kw(row)
            if row.get("stateEligible")
            else (current_kw or 0.0, current_kw or 0.0)
        )
        balance_states[key] = {
            "row": row,
            "currentKw": current_kw,
            "targetKw": target_kw,
            "signedMinTargetKw": signed_min_kw,
            "signedMaxTargetKw": signed_max_kw,
            "directDispatchEligible": bool(
                enabled
                and row.get("commandable")
                and row.get("stateEligible")
                and row.get("set_type") == "p_set"
            ),
        }

    group_residuals = []
    group_ids = sorted(
        {
            str(row.get("dcTransferGroupId", ""))
            for row in (*renewable_rows, *storage_rows)
            if row.get("connectionSide") == "DC"
            and str(row.get("dcTransferGroupId", ""))
        },
        key=_natural_topology_identity,
    )
    for group_id in group_ids:
        renewable_delta_kw = sum(
            _finite_number(renewable_target_map.get(key), current_kw) - current_kw
            for row in renewable_rows
            if row.get("connectionSide") == "DC"
            and row.get("dcTransferGroupId") == group_id
            and (current_kw := _number(row.get("planningCurrentKw", row.get("currentKw"))))
            is not None
            and (
                key := (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
            )
        )
        storage_delta_kw = sum(
            _finite_number(
                (
                    grid_target_map
                    if row.get("role") == "grid_following"
                    else balance_target_map
                ).get(key),
                current_kw,
            )
            - current_kw
            for row in storage_rows
            if row.get("connectionSide") == "DC"
            and row.get("dcTransferGroupId") == group_id
            and row.get("role") in {"grid_following", "balance"}
            and (current_kw := _number(row.get("currentKw"))) is not None
            and (
                key := (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
            )
        )
        export_delta_kw = sum(
            _converter_ac_injection_delta_kw(
                state["row"],
                state.get("currentKw"),
                state.get("targetKw"),
            )
            for state in converter_states
            if state.get("groupId") == group_id
        )
        group_residuals.append(
            {
                "dcTransferGroupId": group_id,
                "renewableDeltaKw": renewable_delta_kw,
                "storageDeltaKw": storage_delta_kw,
                "acdcExportDeltaKw": export_delta_kw,
                "residualKw": renewable_delta_kw + storage_delta_kw - export_delta_kw,
            }
        )

    return {
        "action": action,
        "renewableTargets": renewable_target_map,
        "gridStorageTargets": grid_target_map,
        "balanceTargets": balance_target_map,
        "balanceStates": balance_states,
        "converterTargets": converter_target_map,
        "dieselEffectKw": final_effect_kw,
        "dieselTargetKw": final_predicted_diesel_kw,
        "dcGroups": group_residuals,
    }


def _storage_target_is_hard_protection(
    row: Mapping[str, Any],
    target_kw: Any,
) -> bool:
    current_kw = _number(row.get("currentKw"))
    parsed_target_kw = _number(target_kw)
    if (
        current_kw is None
        or parsed_target_kw is None
        or not row.get("limitsValid")
        or not row.get("socKnown")
    ):
        return False
    signed_min_kw, signed_max_kw = _grid_storage_signed_power_bounds_kw(row)
    return bool(
        current_kw < signed_min_kw - EPSILON
        and parsed_target_kw > current_kw + EPSILON
        or current_kw > signed_max_kw + EPSILON
        and parsed_target_kw < current_kw - EPSILON
    )


def _clamp_direct_balance_targets_to_soc_bounds(
    storage_rows: Sequence[Mapping[str, Any]],
    balance_targets: Mapping[Tuple[str, str], Any],
) -> Dict[Tuple[str, str], Any]:
    """Keep directly controllable balance storage commands inside SOC limits.

    Indirect grid-forming projections may remain outside the instantaneous
    bound while the surrounding DC group is being rebalanced. That is useful
    feedback, but it is not safe to send as a direct p_set command. Direct
    balance storage therefore gets a final local SOC/power projection before
    AC-component and DC-group validation continue.
    """
    final_targets = dict(balance_targets)
    for row in storage_rows:
        if (
            row.get("role") != "balance"
            or row.get("set_type") != "p_set"
            or not row.get("commandable")
            or not row.get("stateEligible")
            or not row.get("limitsValid")
            or not row.get("socKnown")
        ):
            continue
        key = (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
        current_kw = _number(row.get("currentKw"))
        target_kw = _number(final_targets.get(key), current_kw)
        if current_kw is None or target_kw is None:
            continue
        signed_min_kw, signed_max_kw = _grid_storage_signed_power_bounds_kw(row)
        final_targets[key] = _clamp(target_kw, signed_min_kw, signed_max_kw)
    return final_targets


def _validate_dispatch_by_ac_component(
    topology: ResourceTopology,
    diesel_rows: Sequence[Mapping[str, Any]],
    renewable_rows: Sequence[Mapping[str, Any]],
    storage_rows: Sequence[Mapping[str, Any]],
    converter_rows: Sequence[Mapping[str, Any]],
    renewable_targets: Mapping[Tuple[str, str], Any],
    grid_storage_targets: Mapping[Tuple[str, str], Any],
    balance_targets: Mapping[Tuple[str, str], Any],
    converter_targets: Mapping[Tuple[str, str], Any],
    settings: RenewableControlSettings,
    *,
    dc_load_kw: Optional[Mapping[str, float]] = None,
) -> Dict[str, Any]:
    final_renewable_targets = dict(renewable_targets)
    final_grid_storage_targets = dict(grid_storage_targets)
    final_balance_targets = dict(balance_targets)
    final_converter_targets = dict(converter_targets)

    diesels_by_component: Dict[str, List[Mapping[str, Any]]] = {}
    for row in diesel_rows:
        component_id = str(row.get("gridComponentId", ""))
        if (
            not component_id
            or not row.get("online")
            or _number(row.get("currentKw")) is None
        ):
            continue
        diesels_by_component.setdefault(component_id, []).append(row)

    group_component_ids = {
        group_id: str(group.ac_component_ids[0])
        for group_id, group in topology.dc_transfer_groups.items()
        if len(group.ac_component_ids) == 1
    }

    def row_key(row: Mapping[str, Any]) -> Tuple[str, str]:
        return str(row.get("dev_type", "")), str(row.get("dev_name", ""))

    def storage_target(row: Mapping[str, Any]) -> Optional[float]:
        key = row_key(row)
        targets = (
            final_grid_storage_targets
            if row.get("role") == "grid_following"
            else final_balance_targets
        )
        return _number(targets.get(key), row.get("currentKw"))

    # A diesel correction belongs only to its own AC electrical component.
    # When a DC transfer group reaches an AC component with no online diesel,
    # discard ordinary discharge/export candidates inherited from another
    # component. Keep SOC hard-protection moves and positive-ACDC correction.
    for group_id, component_id in sorted(
        group_component_ids.items(),
        key=lambda item: _natural_topology_identity(item[0]),
    ):
        if component_id in diesels_by_component:
            continue
        hard_storage_delta_kw = 0.0
        for row in storage_rows:
            if (
                row.get("connectionSide") != "DC"
                or str(row.get("dcTransferGroupId", "")) != group_id
                or row.get("role") not in {"grid_following", "balance"}
            ):
                continue
            key = row_key(row)
            current_kw = _number(row.get("currentKw"))
            target_kw = storage_target(row)
            if current_kw is None or target_kw is None:
                continue
            if _storage_target_is_hard_protection(row, target_kw):
                hard_storage_delta_kw += target_kw - current_kw
                continue
            if target_kw > current_kw + EPSILON:
                targets = (
                    final_grid_storage_targets
                    if row.get("role") == "grid_following"
                    else final_balance_targets
                )
                targets[key] = current_kw

        group_converters = [
            row
            for row in converter_rows
            if str(row.get("dcTransferGroupId", "")) == group_id
            and _number(row.get("currentKw")) is not None
        ]
        if not group_converters:
            continue
        current_total_kw = sum(
            _finite_number(row.get("currentKw")) for row in group_converters
        )
        signed_min_total_kw = sum(
            _converter_signed_bounds_kw(row)[0] for row in group_converters
        )
        signed_max_total_kw = sum(
            _converter_signed_bounds_kw(row)[1] for row in group_converters
        )
        target_total_kw = _clamp(
            current_total_kw - hard_storage_delta_kw,
            signed_min_total_kw,
            signed_max_total_kw,
        )
        allocations = _allocate_signed_converter_target(
            group_converters,
            target_total_kw,
        )
        for row, allocation_kw in zip(group_converters, allocations):
            final_converter_targets[row_key(row)] = allocation_kw

    def component_effect_kw(component_id: str) -> float:
        effect_kw = 0.0
        for row in renewable_rows:
            if (
                row.get("connectionSide") != "AC"
                or str(row.get("gridComponentId", "")) != component_id
            ):
                continue
            current_kw = _number(row.get("planningCurrentKw", row.get("currentKw")))
            target_kw = _number(final_renewable_targets.get(row_key(row)))
            if current_kw is not None and target_kw is not None:
                effect_kw += target_kw - current_kw
        for row in storage_rows:
            if (
                row.get("connectionSide") != "AC"
                or str(row.get("gridComponentId", "")) != component_id
                or row.get("role") not in {"grid_following", "balance"}
            ):
                continue
            current_kw = _number(row.get("currentKw"))
            target_kw = storage_target(row)
            if current_kw is not None and target_kw is not None:
                effect_kw += target_kw - current_kw
        for row in converter_rows:
            group_id = str(row.get("dcTransferGroupId", ""))
            if group_component_ids.get(group_id) != component_id:
                continue
            current_kw = _number(row.get("currentKw"))
            target_kw = _number(final_converter_targets.get(row_key(row)))
            if current_kw is not None and target_kw is not None:
                effect_kw += current_kw - target_kw
        return effect_kw

    def rollback_dc_group_source(group_id: str, request_kw: float) -> float:
        sink_candidates: List[MutableMapping[str, Any]] = []
        for row in storage_rows:
            if (
                row.get("connectionSide") != "DC"
                or str(row.get("dcTransferGroupId", "")) != group_id
                or row.get("role") not in {"grid_following", "balance"}
            ):
                continue
            current_kw = _number(row.get("currentKw"))
            target_kw = storage_target(row)
            if current_kw is None or target_kw is None:
                continue
            signed_min_kw, _signed_max_kw = _grid_storage_signed_power_bounds_kw(row)
            if (
                target_kw <= signed_min_kw + EPSILON
                or _storage_target_is_hard_protection(row, target_kw)
            ):
                continue
            sink_candidates.append(
                {
                    "kind": str(row.get("role", "")),
                    "key": row_key(row),
                    "marginKw": target_kw - signed_min_kw,
                }
            )
        sink_allocations = _allocate_by_margin(
            sink_candidates,
            request_kw,
            "marginKw",
        )
        for candidate, allocation_kw in zip(sink_candidates, sink_allocations):
            key = candidate["key"]
            targets = (
                final_grid_storage_targets
                if candidate["kind"] == "grid_following"
                else final_balance_targets
            )
            targets[key] = _finite_number(targets.get(key)) - allocation_kw
        absorbed_kw = sum(sink_allocations)
        remaining_request_kw = max(0.0, request_kw - absorbed_kw)

        candidates: List[MutableMapping[str, Any]] = []
        for row in storage_rows:
            if (
                row.get("connectionSide") != "DC"
                or str(row.get("dcTransferGroupId", "")) != group_id
                or row.get("role") not in {"grid_following", "balance"}
            ):
                continue
            current_kw = _number(row.get("currentKw"))
            target_kw = storage_target(row)
            if (
                current_kw is None
                or target_kw is None
                or target_kw <= current_kw + EPSILON
                or _storage_target_is_hard_protection(row, target_kw)
            ):
                continue
            candidates.append(
                {
                    "kind": str(row.get("role", "")),
                    "key": row_key(row),
                    "marginKw": target_kw - current_kw,
                }
            )
        for row in renewable_rows:
            if (
                row.get("connectionSide") != "DC"
                or str(row.get("dcTransferGroupId", "")) != group_id
            ):
                continue
            key = row_key(row)
            current_kw = _number(row.get("planningCurrentKw", row.get("currentKw")))
            target_kw = _number(final_renewable_targets.get(key))
            if current_kw is None or target_kw is None or target_kw <= current_kw + EPSILON:
                continue
            candidates.append(
                {
                    "kind": "renewable",
                    "key": key,
                    "marginKw": target_kw - current_kw,
                }
            )
        allocations = _allocate_by_margin(
            candidates,
            remaining_request_kw,
            "marginKw",
        )
        for candidate, allocation_kw in zip(candidates, allocations):
            key = candidate["key"]
            if candidate["kind"] == "renewable":
                final_renewable_targets[key] = _finite_number(
                    final_renewable_targets.get(key)
                ) - allocation_kw
            elif candidate["kind"] == "grid_following":
                final_grid_storage_targets[key] = _finite_number(
                    final_grid_storage_targets.get(key)
                ) - allocation_kw
            else:
                final_balance_targets[key] = _finite_number(
                    final_balance_targets.get(key)
                ) - allocation_kw
        return absorbed_kw + sum(allocations)

    component_rollbacks: Dict[str, float] = {}
    for component_id in sorted(diesels_by_component, key=_natural_topology_identity):
        component_diesels = diesels_by_component[component_id]
        diesel_current_kw = sum(
            _finite_number(row.get("currentKw")) for row in component_diesels
        )
        diesel_min_kw = sum(
            max(0.0, _finite_number(row.get("minKw"))) for row in component_diesels
        )
        diesel_capacity_kw = sum(
            max(0.0, _finite_number(row.get("capacityKw")))
            for row in component_diesels
        )
        deadband_upper_kw = (
            diesel_min_kw
            + settings.diesel_power_protection_ratio * diesel_capacity_kw
        )
        allowed_effect_kw = max(0.0, diesel_current_kw - deadband_upper_kw)
        rollback_request_kw = max(
            0.0,
            component_effect_kw(component_id) - allowed_effect_kw,
        )
        original_request_kw = rollback_request_kw

        for row in sorted(converter_rows, key=_converter_row_sort_key):
            if rollback_request_kw <= EPSILON:
                break
            group_id = str(row.get("dcTransferGroupId", ""))
            if group_component_ids.get(group_id) != component_id:
                continue
            key = row_key(row)
            current_kw = _number(row.get("currentKw"))
            target_kw = _number(final_converter_targets.get(key))
            if current_kw is None or target_kw is None:
                continue
            export_increase_kw = max(0.0, current_kw - target_kw)
            if export_increase_kw <= EPSILON:
                continue
            paired_rollback_kw = rollback_dc_group_source(
                group_id,
                min(rollback_request_kw, export_increase_kw),
            )
            if paired_rollback_kw <= EPSILON:
                continue
            final_converter_targets[key] = _clamp_converter_target_kw(
                row,
                target_kw + paired_rollback_kw,
            )
            rollback_request_kw = max(0.0, rollback_request_kw - paired_rollback_kw)

        ac_storage_candidates: List[MutableMapping[str, Any]] = []
        for row in storage_rows:
            if (
                row.get("connectionSide") != "AC"
                or str(row.get("gridComponentId", "")) != component_id
                or row.get("role") not in {"grid_following", "balance"}
            ):
                continue
            current_kw = _number(row.get("currentKw"))
            target_kw = storage_target(row)
            if (
                current_kw is None
                or target_kw is None
                or target_kw <= current_kw + EPSILON
                or _storage_target_is_hard_protection(row, target_kw)
            ):
                continue
            ac_storage_candidates.append(
                {
                    "row": row,
                    "key": row_key(row),
                    "marginKw": target_kw - current_kw,
                }
            )
        allocations = _allocate_by_margin(
            ac_storage_candidates,
            rollback_request_kw,
            "marginKw",
        )
        for candidate, allocation_kw in zip(ac_storage_candidates, allocations):
            row = candidate["row"]
            key = candidate["key"]
            targets = (
                final_grid_storage_targets
                if row.get("role") == "grid_following"
                else final_balance_targets
            )
            targets[key] = _finite_number(targets.get(key)) - allocation_kw
        rollback_request_kw = max(0.0, rollback_request_kw - sum(allocations))

        ac_renewable_candidates = []
        for row in renewable_rows:
            if (
                row.get("connectionSide") != "AC"
                or str(row.get("gridComponentId", "")) != component_id
            ):
                continue
            key = row_key(row)
            current_kw = _number(row.get("planningCurrentKw", row.get("currentKw")))
            target_kw = _number(final_renewable_targets.get(key))
            if current_kw is None or target_kw is None or target_kw <= current_kw + EPSILON:
                continue
            ac_renewable_candidates.append(
                {"key": key, "marginKw": target_kw - current_kw}
            )
        allocations = _allocate_by_margin(
            ac_renewable_candidates,
            rollback_request_kw,
            "marginKw",
        )
        for candidate, allocation_kw in zip(ac_renewable_candidates, allocations):
            key = candidate["key"]
            final_renewable_targets[key] = _finite_number(
                final_renewable_targets.get(key)
            ) - allocation_kw
        rollback_request_kw = max(0.0, rollback_request_kw - sum(allocations))
        component_rollbacks[component_id] = max(
            0.0,
            original_request_kw - rollback_request_kw,
        )

    for group_id in sorted(topology.dc_transfer_groups, key=_natural_topology_identity):
        group_renewables = [
            row
            for row in renewable_rows
            if row.get("connectionSide") == "DC"
            and str(row.get("dcTransferGroupId", "")) == group_id
        ]
        group_converters = [
            row
            for row in converter_rows
            if str(row.get("dcTransferGroupId", "")) == group_id
        ]
        group_renewable_delta_kw = sum(
            _finite_number(final_renewable_targets.get(row_key(row)))
            - _finite_number(row.get("planningCurrentKw", row.get("currentKw")))
            for row in renewable_rows
            if row.get("connectionSide") == "DC"
            and str(row.get("dcTransferGroupId", "")) == group_id
            and _number(row.get("planningCurrentKw", row.get("currentKw")))
            is not None
            and _number(final_renewable_targets.get(row_key(row))) is not None
        )
        group_grid_storage_delta_kw = sum(
            _finite_number(storage_target(row)) - _finite_number(row.get("currentKw"))
            for row in storage_rows
            if row.get("connectionSide") == "DC"
            and str(row.get("dcTransferGroupId", "")) == group_id
            and row.get("role") == "grid_following"
            and _number(row.get("currentKw")) is not None
            and storage_target(row) is not None
        )
        group_balance_delta_kw = sum(
            _finite_number(storage_target(row)) - _finite_number(row.get("currentKw"))
            for row in storage_rows
            if row.get("connectionSide") == "DC"
            and str(row.get("dcTransferGroupId", "")) == group_id
            and row.get("role") == "balance"
            and _number(row.get("currentKw")) is not None
            and storage_target(row) is not None
        )
        group_export_delta_kw = sum(
            _converter_ac_injection_delta_kw(
                row,
                row.get("currentKw"),
                final_converter_targets.get(row_key(row)),
            )
            for row in converter_rows
            if str(row.get("dcTransferGroupId", "")) == group_id
            and _number(row.get("currentKw")) is not None
            and _number(final_converter_targets.get(row_key(row))) is not None
        )
        local_sink_headroom_kw = max(
            0.0,
            _finite_number((dc_load_kw or {}).get(group_id))
            - sum(
                _finite_number(row.get("planningCurrentKw", row.get("currentKw")))
                for row in renewable_rows
                if row.get("connectionSide") == "DC"
                and str(row.get("dcTransferGroupId", "")) == group_id
            )
            - sum(
                _finite_number(row.get("currentKw"))
                for row in storage_rows
                if row.get("connectionSide") == "DC"
                and str(row.get("dcTransferGroupId", "")) == group_id
                and row.get("role") == "grid_following"
            ),
        )
        locally_absorbed_kw = min(
            max(0.0, group_renewable_delta_kw + group_grid_storage_delta_kw),
            local_sink_headroom_kw,
        )
        residual_kw = (
            group_renewable_delta_kw
            + group_grid_storage_delta_kw
            - locally_absorbed_kw
            + group_balance_delta_kw
            - group_export_delta_kw
        )
        if abs(residual_kw) <= EPSILON:
            continue
        candidates: List[MutableMapping[str, Any]] = []
        for row in storage_rows:
            if (
                row.get("connectionSide") != "DC"
                or str(row.get("dcTransferGroupId", "")) != group_id
                or row.get("role") not in {"balance", "grid_following"}
            ):
                continue
            current_kw = _number(row.get("currentKw"))
            target_kw = storage_target(row)
            if current_kw is None or target_kw is None:
                continue
            if _storage_target_is_hard_protection(row, target_kw):
                # A DC balance storage already outside its SOC power bound is
                # being moved back toward safety. Do not re-expand that
                # target just to close a temporary group residual; let the
                # same-group renewable or ACDC candidate absorb the residual.
                continue
            signed_min_kw, signed_max_kw = _grid_storage_signed_power_bounds_kw(row)
            lower_target_kw = current_kw if current_kw < signed_min_kw - EPSILON else signed_min_kw
            upper_target_kw = current_kw if current_kw > signed_max_kw + EPSILON else signed_max_kw
            margin_kw = (
                max(0.0, target_kw - lower_target_kw)
                if residual_kw > 0.0
                else max(0.0, upper_target_kw - target_kw)
            )
            if margin_kw <= EPSILON:
                continue
            candidates.append(
                {
                    "kind": str(row.get("role", "")),
                    "key": row_key(row),
                    "marginKw": margin_kw,
                }
            )
        allocations = _allocate_by_margin(
            candidates,
            abs(residual_kw),
            "marginKw",
        )
        for candidate, allocation_kw in zip(candidates, allocations):
            key = candidate["key"]
            targets = (
                final_grid_storage_targets
                if candidate["kind"] == "grid_following"
                else final_balance_targets
            )
            targets[key] = _finite_number(targets.get(key)) + (
                -allocation_kw if residual_kw > 0.0 else allocation_kw
            )

        remaining_residual_kw = max(0.0, abs(residual_kw) - sum(allocations))
        if remaining_residual_kw > EPSILON:
            renewable_candidates: List[MutableMapping[str, Any]] = []
            for row in renewable_rows:
                if (
                    row.get("connectionSide") != "DC"
                    or str(row.get("dcTransferGroupId", "")) != group_id
                ):
                    continue
                key = row_key(row)
                target_kw = _number(final_renewable_targets.get(key))
                capacity_kw = _number(row.get("capacityKw"))
                if target_kw is None or capacity_kw is None:
                    continue
                margin_kw = (
                    max(0.0, target_kw)
                    if residual_kw > 0.0
                    else max(0.0, capacity_kw - target_kw)
                )
                if margin_kw > EPSILON:
                    renewable_candidates.append(
                        {"key": key, "marginKw": margin_kw}
                    )
            renewable_allocations = _allocate_by_margin(
                renewable_candidates,
                remaining_residual_kw,
                "marginKw",
            )
            for candidate, allocation_kw in zip(
                renewable_candidates,
                renewable_allocations,
            ):
                key = candidate["key"]
                target_kw = _finite_number(final_renewable_targets.get(key))
                final_renewable_targets[key] = max(
                    0.0,
                    target_kw - allocation_kw
                    if residual_kw > 0.0
                    else target_kw + allocation_kw,
                )

            accepted_renewable_kw = sum(renewable_allocations)
            residual_kw = (
                residual_kw - accepted_renewable_kw
                if residual_kw > 0.0
                else residual_kw + accepted_renewable_kw
            )

    diesel_targets: Dict[str, float] = {}
    component_summaries: List[Dict[str, Any]] = []
    for component_id in sorted(diesels_by_component, key=_natural_topology_identity):
        component_diesels = diesels_by_component[component_id]
        diesel_current_kw = sum(
            _finite_number(row.get("currentKw")) for row in component_diesels
        )
        diesel_min_kw = sum(
            max(0.0, _finite_number(row.get("minKw"))) for row in component_diesels
        )
        diesel_capacity_kw = sum(
            max(0.0, _finite_number(row.get("capacityKw")))
            for row in component_diesels
        )
        effect_kw = component_effect_kw(component_id)
        predicted_kw = diesel_current_kw - effect_kw
        bounded_target_kw = _clamp(predicted_kw, diesel_min_kw, diesel_capacity_kw)
        per_device_targets = {
            str(row.get("dev_name", "")): _finite_number(row.get("currentKw"))
            for row in component_diesels
        }
        if bounded_target_kw < diesel_current_kw - EPSILON:
            candidates = [
                {
                    "name": str(row.get("dev_name", "")),
                    "marginKw": max(
                        0.0,
                        _finite_number(row.get("currentKw"))
                        - _finite_number(row.get("minKw")),
                    ),
                }
                for row in component_diesels
            ]
            allocations = _allocate_by_margin(
                candidates,
                diesel_current_kw - bounded_target_kw,
                "marginKw",
            )
            for candidate, allocation_kw in zip(candidates, allocations):
                per_device_targets[candidate["name"]] -= allocation_kw
        elif bounded_target_kw > diesel_current_kw + EPSILON:
            candidates = [
                {
                    "name": str(row.get("dev_name", "")),
                    "marginKw": max(
                        0.0,
                        _finite_number(row.get("capacityKw"))
                        - _finite_number(row.get("currentKw")),
                    ),
                }
                for row in component_diesels
            ]
            allocations = _allocate_by_margin(
                candidates,
                bounded_target_kw - diesel_current_kw,
                "marginKw",
            )
            for candidate, allocation_kw in zip(candidates, allocations):
                per_device_targets[candidate["name"]] += allocation_kw
        diesel_targets.update(per_device_targets)
        component_summaries.append(
            {
                "gridComponentId": component_id,
                "dieselCurrentKw": diesel_current_kw,
                "dieselMinKw": diesel_min_kw,
                "dieselCapacityKw": diesel_capacity_kw,
                "dieselDeadbandUpperKw": (
                    diesel_min_kw
                    + settings.diesel_power_protection_ratio
                    * diesel_capacity_kw
                ),
                "candidatePowerEffectKw": effect_kw,
                "predictedDieselKw": predicted_kw,
                "commandedDieselKw": bounded_target_kw,
                "rollbackKw": _finite_number(component_rollbacks.get(component_id)),
                "boundaryResidualKw": max(0.0, diesel_min_kw - predicted_kw),
            }
        )

    dc_group_summaries: List[Dict[str, Any]] = []
    for group_id in sorted(topology.dc_transfer_groups, key=_natural_topology_identity):
        group_renewables = [
            row
            for row in renewable_rows
            if row.get("connectionSide") == "DC"
            and str(row.get("dcTransferGroupId", "")) == group_id
        ]
        group_storage = [
            row
            for row in storage_rows
            if row.get("connectionSide") == "DC"
            and str(row.get("dcTransferGroupId", "")) == group_id
            and row.get("role") in {"grid_following", "balance"}
        ]
        group_converters = [
            row
            for row in converter_rows
            if str(row.get("dcTransferGroupId", "")) == group_id
        ]
        renewable_current_kw = _sum_known(
            row.get("planningCurrentKw", row.get("currentKw"))
            for row in group_renewables
        )
        renewable_target_kw = _sum_known(
            final_renewable_targets.get(
                row_key(row),
                row.get("planningCurrentKw", row.get("currentKw")),
            )
            for row in group_renewables
        )
        storage_current_kw = _sum_known(
            row.get("currentKw") for row in group_storage
        )
        storage_target_kw = _sum_known(
            storage_target(row) for row in group_storage
        )
        acdc_current_kw = _sum_known(
            _converter_system_power_kw(row, row.get("currentKw"))
            for row in group_converters
        )
        acdc_target_kw = _sum_known(
            _converter_system_power_kw(
                row,
                final_converter_targets.get(row_key(row), row.get("currentKw")),
            )
            for row in group_converters
        )
        if any(
            value is None
            for value in (
                renewable_current_kw,
                renewable_target_kw,
                storage_current_kw,
                storage_target_kw,
                acdc_current_kw,
                acdc_target_kw,
            )
        ):
            dc_group_summaries.append(
                {
                    "dcTransferGroupId": group_id,
                    "acComponentIds": list(
                        topology.dc_transfer_groups[group_id].ac_component_ids
                    ),
                    "renewableCurrentKw": renewable_current_kw,
                    "renewableTargetKw": renewable_target_kw,
                    "renewableDeltaKw": None,
                    "storageCurrentKw": storage_current_kw,
                    "storageTargetKw": storage_target_kw,
                    "storageDeltaKw": None,
                    "localLoadKw": _number((dc_load_kw or {}).get(group_id)),
                    "locallyAbsorbedKw": None,
                    "acdcCurrentKw": acdc_current_kw,
                    "acdcTargetKw": acdc_target_kw,
                    "acdcExportDeltaKw": None,
                    "residualKw": None,
                    "dataComplete": False,
                }
            )
            continue
        renewable_delta_kw = renewable_target_kw - renewable_current_kw
        storage_delta_kw = storage_target_kw - storage_current_kw
        grid_storage_delta_kw = sum(
            _finite_number(storage_target(row)) - _finite_number(row.get("currentKw"))
            for row in group_storage
            if row.get("role") == "grid_following"
        )
        balance_storage_delta_kw = sum(
            _finite_number(storage_target(row)) - _finite_number(row.get("currentKw"))
            for row in group_storage
            if row.get("role") == "balance"
        )
        acdc_export_delta_kw = sum(
            _converter_ac_injection_delta_kw(
                row,
                row.get("currentKw"),
                final_converter_targets.get(row_key(row), row.get("currentKw")),
            )
            for row in group_converters
        )
        local_load_value_kw = _finite_number((dc_load_kw or {}).get(group_id))
        local_sink_headroom_kw = max(
            0.0,
            local_load_value_kw
            - renewable_current_kw
            - sum(
                _finite_number(row.get("currentKw"))
                for row in group_storage
                if row.get("role") == "grid_following"
            ),
        )
        locally_absorbed_kw = min(
            max(0.0, renewable_delta_kw + grid_storage_delta_kw),
            local_sink_headroom_kw,
        )
        dc_group_summaries.append(
            {
                "dcTransferGroupId": group_id,
                "acComponentIds": list(
                    topology.dc_transfer_groups[group_id].ac_component_ids
                ),
                "renewableCurrentKw": renewable_current_kw,
                "renewableTargetKw": renewable_target_kw,
                "renewableDeltaKw": renewable_delta_kw,
                "storageCurrentKw": storage_current_kw,
                "storageTargetKw": storage_target_kw,
                "storageDeltaKw": storage_delta_kw,
                "localLoadKw": local_load_value_kw,
                "locallyAbsorbedKw": locally_absorbed_kw,
                "acdcCurrentKw": acdc_current_kw,
                "acdcTargetKw": acdc_target_kw,
                "acdcExportDeltaKw": acdc_export_delta_kw,
                "residualKw": (
                    renewable_delta_kw
                    + grid_storage_delta_kw
                    - locally_absorbed_kw
                    + balance_storage_delta_kw
                    - acdc_export_delta_kw
                ),
                "dataComplete": True,
            }
        )

    converter_rows_by_key = {
        row_key(row): row for row in converter_rows
    }
    return {
        "renewableTargets": final_renewable_targets,
        "gridStorageTargets": final_grid_storage_targets,
        "balanceTargets": final_balance_targets,
        "converterTargets": {
            key: _clamp_converter_target_kw(
                converter_rows_by_key.get(key, {}),
                target_kw,
            )
            for key, target_kw in final_converter_targets.items()
        },
        "dieselTargets": diesel_targets,
        "components": component_summaries,
        "dcGroups": dc_group_summaries,
        "dieselEffectKw": sum(
            _finite_number(row.get("candidatePowerEffectKw"))
            for row in component_summaries
        ),
        "dieselTargetKw": sum(
            _finite_number(row.get("predictedDieselKw"))
            for row in component_summaries
        ),
    }


def _metric_target(row: Mapping[str, Any], fallback_key: str = "currentKw") -> Optional[float]:
    for key in ("commandKw", "targetKw", "projectedTargetKw", fallback_key):
        value = _number(row.get(key))
        if value is not None and math.isfinite(value):
            return value
    return None


def _sum_metric(
    rows: Sequence[Mapping[str, Any]],
    key: str,
    *,
    fallback_key: str = "currentKw",
) -> float:
    total = 0.0
    for row in rows:
        value = (
            _metric_target(row, fallback_key)
            if key == "target"
            else _number(row.get(key))
        )
        if value is not None and math.isfinite(value):
            total += value
    return total


def _sum_optional_metric(
    rows: Sequence[Mapping[str, Any]],
    key: str,
) -> Optional[float]:
    if not rows:
        return 0.0
    values = [_number(row.get(key)) for row in rows]
    if any(value is None or not math.isfinite(value) for value in values):
        return None
    return sum(float(value) for value in values if value is not None)


def _task8_side_metrics(command_rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    online = [row for row in command_rows if row.get("online")]

    def storage_inventory(side: str, role: str) -> List[Mapping[str, Any]]:
        return [
            row
            for row in command_rows
            if row.get("technology") == "storage"
            and row.get("role") == role
            and row.get("connectionSide") == side
        ]

    def renewable(side: str, technology: str) -> List[Mapping[str, Any]]:
        return [
            row
            for row in online
            if row.get("technology") == technology
            and row.get("connectionSide") == side
        ]

    def storage(side: str, role: str) -> List[Mapping[str, Any]]:
        return [
            row
            for row in online
            if row.get("role") == role
            and row.get("connectionSide") == side
        ]

    def diesel(side: str) -> List[Mapping[str, Any]]:
        return [
            row
            for row in online
            if row.get("category") == "柴油发电"
            and row.get("connectionSide") == side
        ]

    ac_wind = renewable("AC", "wind")
    dc_wind = renewable("DC", "wind")
    ac_pv = renewable("AC", "pv")
    dc_pv = renewable("DC", "pv")
    ac_grid = storage("AC", "grid_following")
    dc_grid = storage("DC", "grid_following")
    ac_balance = storage("AC", "balance")
    dc_balance = storage("DC", "balance")
    ac_grid_inventory = storage_inventory("AC", "grid_following")
    dc_grid_inventory = storage_inventory("DC", "grid_following")
    ac_balance_inventory = storage_inventory("AC", "balance")
    dc_balance_inventory = storage_inventory("DC", "balance")
    ac_diesel = diesel("AC")
    dc_diesel = diesel("DC")

    ac_wind_current = _sum_metric(ac_wind, "currentKw")
    ac_wind_target = _sum_metric(ac_wind, "target")
    dc_wind_current = _sum_metric(dc_wind, "currentKw")
    dc_wind_target = _sum_metric(dc_wind, "target")
    ac_pv_current = _sum_metric(ac_pv, "currentKw")
    ac_pv_target = _sum_metric(ac_pv, "target")
    dc_pv_current = _sum_metric(dc_pv, "currentKw")
    dc_pv_target = _sum_metric(dc_pv, "target")
    ac_wind_max_available = _sum_optional_metric(ac_wind, "weatherAvailableKw")
    dc_wind_max_available = _sum_optional_metric(dc_wind, "weatherAvailableKw")
    ac_pv_max_available = _sum_optional_metric(ac_pv, "weatherAvailableKw")
    dc_pv_max_available = _sum_optional_metric(dc_pv, "weatherAvailableKw")
    ac_renewable_max_available = _sum_known(
        (ac_wind_max_available, ac_pv_max_available)
    )
    dc_renewable_max_available = _sum_known(
        (dc_wind_max_available, dc_pv_max_available)
    )
    total_wind_max_available = _sum_known(
        (ac_wind_max_available, dc_wind_max_available)
    )
    total_pv_max_available = _sum_known(
        (ac_pv_max_available, dc_pv_max_available)
    )
    total_renewable_max_available = _sum_known(
        (ac_renewable_max_available, dc_renewable_max_available)
    )
    ac_renewable_current = ac_wind_current + ac_pv_current
    ac_renewable_target = ac_wind_target + ac_pv_target
    dc_renewable_current = dc_wind_current + dc_pv_current
    dc_renewable_target = dc_wind_target + dc_pv_target
    ac_grid_current = _sum_metric(ac_grid, "currentKw")
    ac_grid_target = _sum_metric(ac_grid, "target")
    dc_grid_current = _sum_metric(dc_grid, "currentKw")
    dc_grid_target = _sum_metric(dc_grid, "target")
    ac_balance_current = _sum_metric(ac_balance, "currentKw")
    ac_balance_target = _sum_metric(ac_balance, "target")
    dc_balance_current = _sum_metric(dc_balance, "currentKw")
    dc_balance_target = _sum_metric(dc_balance, "target")
    ac_grid_soc = _capacity_weighted_soc(ac_grid)
    dc_grid_soc = _capacity_weighted_soc(dc_grid)
    ac_balance_soc = _capacity_weighted_soc(ac_balance)
    dc_balance_soc = _capacity_weighted_soc(dc_balance)
    ac_diesel_current = _sum_metric(ac_diesel, "currentKw")
    ac_diesel_min = _sum_metric(ac_diesel, "minKw")
    ac_diesel_target = _sum_metric(ac_diesel, "target")
    dc_diesel_current = _sum_metric(dc_diesel, "currentKw")
    dc_diesel_min = _sum_metric(dc_diesel, "minKw")
    dc_diesel_target = _sum_metric(dc_diesel, "target")
    return {
        "onlineAcRenewableCount": len(ac_wind) + len(ac_pv),
        "onlineDcRenewableCount": len(dc_wind) + len(dc_pv),
        "onlineAcWindCount": len(ac_wind),
        "onlineDcWindCount": len(dc_wind),
        "onlineAcPvCount": len(ac_pv),
        "onlineDcPvCount": len(dc_pv),
        "acGridFollowingStorageCount": len(ac_grid_inventory),
        "dcGridFollowingStorageCount": len(dc_grid_inventory),
        "acGridFormingStorageCount": len(ac_balance_inventory),
        "dcGridFormingStorageCount": len(dc_balance_inventory),
        "onlineAcGridFollowingStorageCount": len(ac_grid),
        "onlineDcGridFollowingStorageCount": len(dc_grid),
        "onlineAcGridFormingStorageCount": len(ac_balance),
        "onlineDcGridFormingStorageCount": len(dc_balance),
        "onlineAcDieselCount": len(ac_diesel),
        "onlineDcDieselCount": len(dc_diesel),
        "acWindCurrentKw": ac_wind_current,
        "acWindTargetKw": ac_wind_target,
        "acWindMaxAvailableKw": ac_wind_max_available,
        "dcWindCurrentKw": dc_wind_current,
        "dcWindTargetKw": dc_wind_target,
        "dcWindMaxAvailableKw": dc_wind_max_available,
        "acPvCurrentKw": ac_pv_current,
        "acPvTargetKw": ac_pv_target,
        "acPvMaxAvailableKw": ac_pv_max_available,
        "dcPvCurrentKw": dc_pv_current,
        "dcPvTargetKw": dc_pv_target,
        "dcPvMaxAvailableKw": dc_pv_max_available,
        "acGridStorageCurrentKw": ac_grid_current,
        "acGridStorageTargetKw": ac_grid_target,
        "acGridStorageSoc": ac_grid_soc,
        "dcGridStorageCurrentKw": dc_grid_current,
        "dcGridStorageTargetKw": dc_grid_target,
        "dcGridStorageSoc": dc_grid_soc,
        "acBalanceStorageCurrentKw": ac_balance_current,
        "acBalanceStorageTargetKw": ac_balance_target,
        "dcBalanceStorageCurrentKw": dc_balance_current,
        "dcBalanceStorageTargetKw": dc_balance_target,
        "acBalanceStorageSoc": ac_balance_soc,
        "dcBalanceStorageSoc": dc_balance_soc,
        "acRenewableCurrentKw": ac_renewable_current,
        "acRenewableTargetKw": ac_renewable_target,
        "acRenewableMaxAvailableKw": ac_renewable_max_available,
        "dcRenewableCurrentKw": dc_renewable_current,
        "dcRenewableTargetKw": dc_renewable_target,
        "dcRenewableMaxAvailableKw": dc_renewable_max_available,
        "acGridFollowingStorageCurrentKw": ac_grid_current,
        "acGridFollowingStorageTargetKw": ac_grid_target,
        "acGridFollowingStorageSoc": ac_grid_soc,
        "dcGridFollowingStorageCurrentKw": dc_grid_current,
        "dcGridFollowingStorageTargetKw": dc_grid_target,
        "dcGridFollowingStorageSoc": dc_grid_soc,
        "acGridFormingStorageCurrentKw": ac_balance_current,
        "acGridFormingStorageTargetKw": ac_balance_target,
        "acGridFormingStorageSoc": ac_balance_soc,
        "dcGridFormingStorageCurrentKw": dc_balance_current,
        "dcGridFormingStorageTargetKw": dc_balance_target,
        "dcGridFormingStorageSoc": dc_balance_soc,
        "acStorageCurrentKw": ac_grid_current + ac_balance_current,
        "acStorageTargetKw": ac_grid_target + ac_balance_target,
        "acStorageSoc": _capacity_weighted_soc([*ac_grid, *ac_balance]),
        "dcStorageCurrentKw": dc_grid_current + dc_balance_current,
        "dcStorageTargetKw": dc_grid_target + dc_balance_target,
        "dcStorageSoc": _capacity_weighted_soc([*dc_grid, *dc_balance]),
        "acDieselCurrentKw": ac_diesel_current,
        "acDieselMinKw": ac_diesel_min,
        "acDieselTargetKw": ac_diesel_target,
        "dcDieselCurrentKw": dc_diesel_current,
        "dcDieselMinKw": dc_diesel_min,
        "dcDieselTargetKw": dc_diesel_target,
        "totalRenewableCurrentKw": ac_renewable_current + dc_renewable_current,
        "totalRenewableTargetKw": ac_renewable_target + dc_renewable_target,
        "totalRenewableMaxAvailableKw": total_renewable_max_available,
        "totalWindCurrentKw": ac_wind_current + dc_wind_current,
        "totalWindTargetKw": ac_wind_target + dc_wind_target,
        "totalWindMaxAvailableKw": total_wind_max_available,
        "totalPvCurrentKw": ac_pv_current + dc_pv_current,
        "totalPvTargetKw": ac_pv_target + dc_pv_target,
        "totalPvMaxAvailableKw": total_pv_max_available,
        "totalGridFollowingStorageCurrentKw": ac_grid_current + dc_grid_current,
        "totalGridFollowingStorageTargetKw": ac_grid_target + dc_grid_target,
        "totalGridFollowingStorageSoc": _capacity_weighted_soc([*ac_grid, *dc_grid]),
        "totalGridFormingStorageCurrentKw": ac_balance_current + dc_balance_current,
        "totalGridFormingStorageTargetKw": ac_balance_target + dc_balance_target,
        "totalGridFormingStorageSoc": _capacity_weighted_soc([*ac_balance, *dc_balance]),
        "totalStorageCurrentKw": (
            ac_grid_current + dc_grid_current + ac_balance_current + dc_balance_current
        ),
        "totalStorageTargetKw": (
            ac_grid_target + dc_grid_target + ac_balance_target + dc_balance_target
        ),
        "totalStorageSoc": _capacity_weighted_soc(
            [*ac_grid, *dc_grid, *ac_balance, *dc_balance]
        ),
        "totalDieselCurrentKw": ac_diesel_current + dc_diesel_current,
        "totalDieselMinKw": ac_diesel_min + dc_diesel_min,
        "totalDieselTargetKw": ac_diesel_target + dc_diesel_target,
    }


def _dc_transfer_group_metrics(
    topology: ResourceTopology,
    command_rows: Sequence[Mapping[str, Any]],
    dc_load_kw: Mapping[str, float],
    *,
    converter_step_ratio: float,
) -> Tuple[List[Dict[str, Any]], float]:
    groups: List[Dict[str, Any]] = []
    dc_renewable_to_ac_kw = 0.0
    active_group_ids = _active_dc_transfer_group_ids(topology, command_rows)
    rows_by_group: Dict[str, List[Mapping[str, Any]]] = {}
    for row in command_rows:
        group_id = str(row.get("dcTransferGroupId", ""))
        if group_id:
            rows_by_group.setdefault(group_id, []).append(row)

    for group_id in sorted(topology.dc_transfer_groups, key=_natural_topology_identity):
        rows = [row for row in rows_by_group.get(group_id, []) if row.get("online")]
        converters = [
            row
            for row in rows
            if _is_grid_converter_row(row)
            and row.get("commandable") is not False
        ]
        group = topology.dc_transfer_groups[group_id]
        dc_rows = [row for row in rows if row.get("connectionSide") == "DC"]
        renewables = [
            row for row in dc_rows if row.get("technology") in {"wind", "pv"}
        ]
        wind = [row for row in renewables if row.get("technology") == "wind"]
        pv = [row for row in renewables if row.get("technology") == "pv"]
        all_storage = [
            row
            for row in dc_rows
            if row.get("technology") == "storage"
            and row.get("resourceIdentityValid") is not False
        ]
        grid_storage = [row for row in dc_rows if row.get("role") == "grid_following"]
        balance_storage = [row for row in dc_rows if row.get("role") == "balance"]
        affected = sorted(
            (*renewables, *all_storage, *converters),
            key=lambda item: (
                _natural_topology_identity(item.get("dev_type", "")),
                _natural_topology_identity(item.get("dev_name", "")),
            ),
        )
        if group_id not in active_group_ids:
            reasons = {
                str(row.get("statusLabel", ""))
                for row in affected
                if str(row.get("statusLabel", "")).strip()
            }
            if not rows:
                reasons.add("no online resources in transfer group")
            if not converters:
                reasons.add("no active ACDC transfer path")
            if not dc_rows:
                reasons.add("no active DC resources in transfer group")
            renewable_current_kw = _sum_metric(renewables, "currentKw")
            renewable_target_kw = _sum_metric(renewables, "target")
            groups.append(
                _json_safe_copy(
                    {
                        "groupId": group_id,
                        "active": False,
                        "dcNodes": list(group.dc_nodes),
                        "acComponentIds": list(group.ac_component_ids),
                        "converterDevices": [
                            {"dev_type": dev_type, "dev_name": dev_name}
                            for dev_type, dev_name in group.converter_keys
                        ],
                        "currentWindKw": _sum_metric(wind, "currentKw"),
                        "targetWindKw": _sum_metric(wind, "target"),
                        "currentPvKw": _sum_metric(pv, "currentKw"),
                        "targetPvKw": _sum_metric(pv, "target"),
                        "currentRenewableKw": renewable_current_kw,
                        "targetRenewableKw": renewable_target_kw,
                        "localLoadKw": max(0.0, _finite_number(dc_load_kw.get(group_id))),
                        "currentGridStorageKw": _sum_metric(grid_storage, "currentKw"),
                        "targetGridStorageKw": _sum_metric(grid_storage, "target"),
                        "gridStorageSoc": _capacity_weighted_soc(grid_storage),
                        "currentBalanceStorageKw": _sum_metric(balance_storage, "currentKw"),
                        "targetBalanceStorageKw": sum(
                            _finite_number(row.get("projectedTargetKw"))
                            for row in balance_storage
                            if _number(row.get("projectedTargetKw")) is not None
                        ),
                        "balanceStorageSoc": _capacity_weighted_soc(balance_storage),
                        "currentAcdcExportKw": 0.0,
                        "finalAcdcExportKw": 0.0,
                        "acdcCapacityKw": 0.0,
                        "remainingAcdcHeadroomKw": 0.0,
                        "stepAcdcHeadroomKw": 0.0,
                        "renewableDeliveredThroughAcdcKw": 0.0,
                        "currentRenewableDeliveredThroughAcdcKw": 0.0,
                        "finalRenewableDeliveredThroughAcdcKw": 0.0,
                        "curtailedRenewableKw": max(
                            0.0,
                            renewable_current_kw - renewable_target_kw,
                        ),
                        "blockedRenewableKw": 0.0,
                        "reasons": sorted(reasons),
                        "affectedDevices": [
                            {
                                "dev_type": str(row.get("dev_type", "")),
                                "dev_name": str(row.get("dev_name", "")),
                                "side": str(row.get("connectionSide", "")),
                                "role": str(row.get("role", "")),
                                "technology": str(row.get("technology", "")),
                                "bus": str(row.get("busbarName", "")),
                            }
                            for row in affected
                        ],
                    }
                )
            )
            continue
        current_export_kw = sum(
            max(0.0, -_finite_number(row.get("currentKw")))
            for row in converters
            if row.get("currentKw") is not None
        )
        final_export_kw = sum(
            max(0.0, -_finite_number(row.get("commandKw")))
            for row in converters
            if _number(row.get("commandKw")) is not None
        )
        capacity_kw = sum(
            max(0.0, _finite_number(row.get("transferCapacityKw")))
            for row in converters
        )
        renewable_current_kw = _sum_metric(renewables, "currentKw")
        renewable_target_kw = _sum_metric(renewables, "target")
        local_load_kw = max(0.0, _finite_number(dc_load_kw.get(group_id)))
        current_storage_charge_kw = sum(
            max(0.0, -_finite_number(row.get("currentKw")))
            for row in all_storage
            if row.get("currentKw") is not None
        )
        final_storage_charge_kw = sum(
            max(0.0, -_finite_number(_metric_target(row)))
            for row in all_storage
        )
        current_renewable_exportable_kw = max(
            0.0,
            renewable_current_kw - local_load_kw - current_storage_charge_kw,
        )
        final_renewable_exportable_kw = max(
            0.0,
            renewable_target_kw - local_load_kw - final_storage_charge_kw,
        )
        delivered_through_acdc_kw = min(current_export_kw, current_renewable_exportable_kw)
        final_delivered_through_acdc_kw = min(final_export_kw, final_renewable_exportable_kw)
        dc_renewable_to_ac_kw += delivered_through_acdc_kw
        blocked_kw = sum(
            max(
                0.0,
                _finite_number(row.get("capacityKw"))
                - _finite_number(_metric_target(row)),
            )
            for row in renewables
        )
        step_headroom_kw = sum(
            min(
                max(
                    0.0,
                    _finite_number(row.get("transferCapacityKw"))
                    - max(0.0, -_finite_number(row.get("commandKw"))),
                ),
                max(
                    0.0,
                    converter_step_ratio
                    * _finite_number(row.get("transferCapacityKw")),
                ),
            )
            for row in converters
        )
        groups.append(
            _json_safe_copy(
                {
                    "groupId": group_id,
                    "active": True,
                    "dcNodes": list(group.dc_nodes),
                    "acComponentIds": list(group.ac_component_ids),
                    "converterDevices": [
                        {"dev_type": dev_type, "dev_name": dev_name}
                        for dev_type, dev_name in group.converter_keys
                    ],
                    "currentWindKw": _sum_metric(wind, "currentKw"),
                    "targetWindKw": _sum_metric(wind, "target"),
                    "currentPvKw": _sum_metric(pv, "currentKw"),
                    "targetPvKw": _sum_metric(pv, "target"),
                    "currentRenewableKw": renewable_current_kw,
                    "targetRenewableKw": renewable_target_kw,
                    "localLoadKw": local_load_kw,
                    "currentGridStorageKw": _sum_metric(grid_storage, "currentKw"),
                    "targetGridStorageKw": _sum_metric(grid_storage, "target"),
                    "gridStorageSoc": _capacity_weighted_soc(grid_storage),
                    "currentBalanceStorageKw": _sum_metric(balance_storage, "currentKw"),
                    "targetBalanceStorageKw": sum(
                        _finite_number(row.get("projectedTargetKw"))
                        for row in balance_storage
                        if _number(row.get("projectedTargetKw")) is not None
                    ),
                    "balanceStorageSoc": _capacity_weighted_soc(balance_storage),
                    "currentAcdcExportKw": current_export_kw,
                    "finalAcdcExportKw": final_export_kw,
                    "acdcCapacityKw": capacity_kw,
                    "remainingAcdcHeadroomKw": max(0.0, capacity_kw - final_export_kw),
                    "stepAcdcHeadroomKw": step_headroom_kw,
                    "renewableDeliveredThroughAcdcKw": delivered_through_acdc_kw,
                    "currentRenewableDeliveredThroughAcdcKw": delivered_through_acdc_kw,
                    "finalRenewableDeliveredThroughAcdcKw": final_delivered_through_acdc_kw,
                    "curtailedRenewableKw": max(0.0, renewable_current_kw - renewable_target_kw),
                    "blockedRenewableKw": blocked_kw,
                    "reasons": sorted(
                        {
                            str(row.get("statusLabel", ""))
                            for row in affected
                            if str(row.get("statusLabel", "")).strip()
                        }
                    ),
                    "affectedDevices": [
                        {
                            "dev_type": str(row.get("dev_type", "")),
                            "dev_name": str(row.get("dev_name", "")),
                            "side": str(row.get("connectionSide", "")),
                            "role": str(row.get("role", "")),
                            "technology": str(row.get("technology", "")),
                            "bus": str(row.get("busbarName", "")),
                        }
                        for row in affected
                    ],
                }
            )
        )
    return groups, dc_renewable_to_ac_kw


def _rebalance_dc_projection_targets(
    topology: ResourceTopology,
    renewable_rows: Sequence[Mapping[str, Any]],
    storage_rows: Sequence[Mapping[str, Any]],
    converter_rows: Sequence[Mapping[str, Any]],
    renewable_targets: Mapping[Tuple[str, str], Any],
    grid_storage_targets: Mapping[Tuple[str, str], Any],
    balance_targets: Mapping[Tuple[str, str], Any],
    converter_targets: Mapping[Tuple[str, str], Any],
    *,
    dc_load_kw: Optional[Mapping[str, float]] = None,
) -> Tuple[
    Dict[Tuple[str, str], Any],
    Dict[Tuple[str, str], Any],
    List[Dict[str, Any]],
]:
    """Close each DC group balance after AC-side rollback.

    Component validation can roll back an ACDC export or a renewable target
    after the first DC projection. Recompute the indirect balance-storage
    projection, and restore only a same-group ACDC export change when it is
    the remaining source of a group residual. Never borrow an actor from
    another DC transfer group.
    """
    final_balance_targets = dict(balance_targets)
    final_converter_targets = dict(converter_targets)
    group_summaries: List[Dict[str, Any]] = []

    def key_for(row: Mapping[str, Any]) -> Tuple[str, str]:
        return str(row.get("dev_type", "")), str(row.get("dev_name", ""))

    for group_id, group in sorted(
        topology.dc_transfer_groups.items(),
        key=lambda item: _natural_topology_identity(item[0]),
    ):
        group_renewables = [
            row
            for row in renewable_rows
            if row.get("connectionSide") == "DC"
            and str(row.get("dcTransferGroupId", "")) == group_id
        ]
        group_storage = [
            row
            for row in storage_rows
            if row.get("connectionSide") == "DC"
            and str(row.get("dcTransferGroupId", "")) == group_id
            and row.get("role") in {"grid_following", "balance"}
        ]
        group_balance = [
            row
            for row in group_storage
            if row.get("role") == "balance"
            and row.get("stateEligible")
            and _number(row.get("currentKw")) is not None
        ]
        group_converters = [
            row
            for row in converter_rows
            if str(row.get("dcTransferGroupId", "")) == group_id
        ]

        def target_for(row: Mapping[str, Any]) -> Optional[float]:
            key = key_for(row)
            if row.get("role") == "grid_following":
                return _number(
                    grid_storage_targets.get(key), row.get("currentKw")
                )
            return _number(
                final_balance_targets.get(key), row.get("currentKw")
            )

        renewable_current_values = [
            _number(row.get("planningCurrentKw", row.get("currentKw")))
            for row in group_renewables
        ]
        renewable_target_values = [
            _number(
                renewable_targets.get(key_for(row)),
                row.get("planningCurrentKw", row.get("currentKw")),
            )
            for row in group_renewables
        ]
        storage_current_values = [
            _number(row.get("currentKw")) for row in group_storage
        ]
        storage_target_values = [target_for(row) for row in group_storage]
        converter_current_values = [
            _number(row.get("currentKw")) for row in group_converters
        ]
        converter_target_values = [
            _number(converter_targets.get(key_for(row)), row.get("currentKw"))
            for row in group_converters
        ]
        data_complete = not any(
            value is None
            for values in (
                renewable_current_values,
                renewable_target_values,
                storage_current_values,
                storage_target_values,
                converter_current_values,
                converter_target_values,
            )
            for value in values
        )
        local_load_value_kw = _finite_number((dc_load_kw or {}).get(group_id))
        if not data_complete:
            group_summaries.append(
                {
                    "dcTransferGroupId": group_id,
                    "acComponentIds": list(group.ac_component_ids),
                    "renewableCurrentKw": _sum_known(renewable_current_values),
                    "renewableTargetKw": _sum_known(renewable_target_values),
                    "renewableDeltaKw": None,
                    "storageCurrentKw": _sum_known(storage_current_values),
                    "storageTargetKw": _sum_known(storage_target_values),
                    "storageDeltaKw": None,
                    "localLoadKw": local_load_value_kw,
                    "locallyAbsorbedKw": None,
                    "acdcCurrentKw": _sum_known(
                        _converter_system_power_kw(row, value)
                        for row, value in zip(group_converters, converter_current_values)
                    ),
                    "acdcTargetKw": _sum_known(
                        _converter_system_power_kw(row, value)
                        for row, value in zip(group_converters, converter_target_values)
                    ),
                    "acdcExportDeltaKw": None,
                    "residualKw": None,
                    "dataComplete": False,
                }
            )
            continue

        renewable_delta = sum(
            target - current
            for target, current in zip(
                renewable_target_values,
                renewable_current_values,
            )
        )
        grid_storage_delta = sum(
            target - current
            for row, target, current in zip(
                group_storage,
                storage_target_values,
                storage_current_values,
            )
            if row.get("role") == "grid_following"
        )
        storage_delta = sum(
            target - current
            for target, current in zip(
                storage_target_values,
                storage_current_values,
            )
        )
        export_delta = sum(
            _converter_ac_injection_delta_kw(row, current, target)
            for row, current, target in zip(
                group_converters,
                converter_current_values,
                converter_target_values,
            )
        )
        local_sink_headroom_kw = max(
            0.0,
            local_load_value_kw
            - sum(
                current for current in renewable_current_values
            )
            - sum(
                current
                for row, current in zip(group_storage, storage_current_values)
                if row.get("role") == "grid_following"
            ),
        )
        locally_absorbed_kw = min(
            max(0.0, renewable_delta + grid_storage_delta),
            local_sink_headroom_kw,
        )
        residual = (
            renewable_delta
            + storage_delta
            - locally_absorbed_kw
            - export_delta
        )

        if group_balance and abs(residual) > EPSILON:
            remaining = abs(residual)
            candidates: List[Tuple[Mapping[str, Any], float]] = []
            for row in group_balance:
                key = key_for(row)
                current = _finite_number(row.get("currentKw"))
                target = _finite_number(final_balance_targets.get(key), current)
                signed_min, signed_max = _grid_storage_signed_power_bounds_kw(row)
                margin = (
                    max(0.0, signed_max - target)
                    if residual < 0.0
                    else max(0.0, target - signed_min)
                )
                if margin > EPSILON:
                    candidates.append((row, margin))
            total_margin = sum(margin for _, margin in candidates)
            if total_margin > EPSILON:
                accepted = min(remaining, total_margin)
                for row, margin in candidates:
                    allocation = accepted * margin / total_margin
                    key = key_for(row)
                    current = _finite_number(row.get("currentKw"))
                    target = _finite_number(final_balance_targets.get(key), current)
                    final_balance_targets[key] = target + (
                        allocation if residual < 0.0 else -allocation
                    )
                residual = residual + accepted if residual < 0.0 else residual - accepted

        # Re-read every final target after the balance-storage projection. The
        # projection above mutates final_balance_targets, so keeping the
        # original storage_target_values would make the reported residual
        # inconsistent with the targets that will be published.
        storage_target_values = [target_for(row) for row in group_storage]
        storage_delta = sum(
            target - current
            for target, current in zip(storage_target_values, storage_current_values)
        )
        grid_storage_delta = sum(
            target - current
            for row, target, current in zip(
                group_storage,
                storage_target_values,
                storage_current_values,
            )
            if row.get("role") == "grid_following"
        )
        locally_absorbed_kw = min(
            max(0.0, renewable_delta + grid_storage_delta),
            local_sink_headroom_kw,
        )
        residual = (
            renewable_delta
            + storage_delta
            - locally_absorbed_kw
            - export_delta
        )

        # If the same DC group still has a residual because its converter
        # target was reduced by AC-side validation, restore only that change.
        # Do not restore renewable or storage candidates here: those are the
        # local control actions selected by the side-specific policy.
        if abs(residual) > EPSILON:
            for row in group_converters:
                if abs(residual) <= EPSILON:
                    break
                key = key_for(row)
                current_kw = _number(row.get("currentKw"))
                target_kw = _number(final_converter_targets.get(key), current_kw)
                if current_kw is None or target_kw is None:
                    continue
                current_export_kw = max(
                    0.0,
                    _converter_ac_injection_kw(row, current_kw),
                )
                target_export_kw = max(
                    0.0,
                    _converter_ac_injection_kw(row, target_kw),
                )
                export_delta_kw = target_export_kw - current_export_kw
                if residual > 0.0 and export_delta_kw < -EPSILON:
                    restore_kw = min(residual, -export_delta_kw)
                    final_converter_targets[key] = _clamp_converter_target_kw(
                        row,
                        _converter_power_from_ac_injection_kw(
                            row,
                            target_export_kw + restore_kw,
                        ),
                    )
                    residual -= restore_kw
                elif residual < 0.0 and export_delta_kw > EPSILON:
                    restore_kw = min(-residual, export_delta_kw)
                    final_converter_targets[key] = _clamp_converter_target_kw(
                        row,
                        _converter_power_from_ac_injection_kw(
                            row,
                            max(0.0, target_export_kw - restore_kw),
                        ),
                    )
                    residual += restore_kw

        # The converter repair changes only the export term, but recompute all
        # terms once more so metrics and command validation use one equation.
        converter_target_values = [
            _number(final_converter_targets.get(key_for(row)), row.get("currentKw"))
            for row in group_converters
        ]
        export_delta = sum(
            _converter_ac_injection_delta_kw(row, current, target)
            for row, current, target in zip(
                group_converters,
                converter_current_values,
                converter_target_values,
            )
        )
        residual = (
            renewable_delta
            + storage_delta
            - locally_absorbed_kw
            - export_delta
        )

        group_summaries.append(
            {
                "dcTransferGroupId": group_id,
                "acComponentIds": list(group.ac_component_ids),
                "renewableCurrentKw": sum(renewable_current_values),
                "renewableTargetKw": sum(renewable_target_values),
                "renewableDeltaKw": renewable_delta,
                "storageCurrentKw": sum(storage_current_values),
                "storageTargetKw": sum(storage_target_values),
                "storageDeltaKw": storage_delta,
                "localLoadKw": local_load_value_kw,
                "locallyAbsorbedKw": locally_absorbed_kw,
                "acdcCurrentKw": sum(
                    _finite_number(_converter_system_power_kw(row, value))
                    for row, value in zip(group_converters, converter_current_values)
                ),
                "acdcTargetKw": sum(
                    _finite_number(_converter_system_power_kw(row, value))
                    for row, value in zip(group_converters, converter_target_values)
                ),
                "acdcExportDeltaKw": export_delta,
                "residualKw": residual,
                "dataComplete": True,
            }
        )
    return final_balance_targets, final_converter_targets, group_summaries


def _task8_decision_detail(
    command_rows: Sequence[Mapping[str, Any]],
    metrics: Mapping[str, Any],
) -> List[str]:
    rows = sorted(
        command_rows,
        key=lambda row: (
            _natural_topology_identity(row.get("connectionSide", "")),
            _natural_topology_identity(row.get("dcTransferGroupId", "")),
            _natural_topology_identity(row.get("dev_type", "")),
            _natural_topology_identity(row.get("dev_name", "")),
        ),
    )

    def path_text(row: Mapping[str, Any]) -> str:
        path = row.get("activePath") or row.get("structuralPath") or ()
        return ">".join(f"{dev_type}:{dev_name}" for dev_type, dev_name in path) or "local"

    def device_text(row: Mapping[str, Any]) -> str:
        current_kw = _number(row.get("currentKw"))
        target_kw = _metric_target(row)
        candidate_delta = (
            target_kw - current_kw
            if current_kw is not None and target_kw is not None
            else None
        )
        accepted_delta = candidate_delta if candidate_delta is not None else 0.0
        limit = (
            row.get("transferCapacityKw")
            if _is_grid_converter_row(row)
            else row.get("capacityKw", row.get("maxDischargePowerKw"))
        )
        return (
            f"device={row.get('dev_name', '')} type={row.get('dev_type', '')} "
            f"side={row.get('connectionSide', '')} bus={row.get('busbarName', '')} "
            f"group={row.get('dcTransferGroupId', '')} path={path_text(row)} "
            f"currentKw={current_kw if current_kw is not None else 'None'} "
            f"candidateDeltaKw={candidate_delta if candidate_delta is not None else 'None'} "
            f"acceptedDeltaKw={accepted_delta} limit={limit if limit is not None else 'None'} "
            f"reason={row.get('statusLabel', 'hold')}"
        )

    detail: List[str] = [
        f"phase=topology {device_text(row)}"
        for row in rows
        if row.get("technology") in {"wind", "pv", "storage"}
        or row.get("category") == "柴油发电"
        or _is_grid_converter_row(row)
    ]
    detail.extend(
        [
            "phase=side/role totals "
            f"side=AC windCurrentKw={metrics.get('acWindCurrentKw')} "
            f"pvCurrentKw={metrics.get('acPvCurrentKw')} "
            f"gridStorageCurrentKw={metrics.get('acGridStorageCurrentKw')} "
            f"balanceStorageCurrentKw={metrics.get('acBalanceStorageCurrentKw')}",
            "phase=side/role totals "
            f"side=DC windCurrentKw={metrics.get('dcWindCurrentKw')} "
            f"pvCurrentKw={metrics.get('dcPvCurrentKw')} "
            f"gridStorageCurrentKw={metrics.get('dcGridStorageCurrentKw')} "
            f"balanceStorageCurrentKw={metrics.get('dcBalanceStorageCurrentKw')}",
        ]
    )
    converters = [
        row for row in rows if _is_grid_converter_row(row)
    ]
    detail.extend(
        [f"phase=ACDC balance candidate {device_text(row)}" for row in converters]
        or ["phase=ACDC balance candidate device=none side= bus= group= path=local currentKw=None candidateDeltaKw=None acceptedDeltaKw=0.0 limit=None reason=hold"]
    )
    detail.extend(
        f"phase=direct-storage allocation {device_text(row)}"
        for row in rows
        if row.get("role") == "grid_following"
    )
    detail.extend(
        "phase=ac-component validation "
        f"component={row.get('gridComponentId', '')} "
        f"dieselCurrentKw={row.get('dieselCurrentKw')} "
        f"dieselMinKw={row.get('dieselMinKw')} "
        f"candidateEffectKw={row.get('candidatePowerEffectKw')} "
        f"predictedDieselKw={row.get('predictedDieselKw')} "
        f"commandedDieselKw={row.get('commandedDieselKw')} "
        f"rollbackKw={row.get('rollbackKw')} "
        f"residualKw={row.get('boundaryResidualKw')}"
        for row in metrics.get("acComponentDispatch", [])
        if isinstance(row, Mapping)
    )
    detail.extend(
        "phase=direct-grid-forming group "
        f"group={row.get('dcTransferGroupId', '')} "
        f"renewableDeltaKw={row.get('renewableDeltaKw')} "
        f"storageDeltaKw={row.get('storageDeltaKw')} "
        f"acdcExportDeltaKw={row.get('acdcExportDeltaKw')} "
        f"residualKw={row.get('residualKw')}"
        for row in metrics.get("directGridFormingDcGroups", [])
        if isinstance(row, Mapping)
    )
    detail.extend(
        "phase=direct-dispatch blocked "
        f"device={row.get('dev_name', '')} type={row.get('dev_type', '')} "
        f"side={row.get('side', '')} group={row.get('dcTransferGroupId', '')} "
        f"reason={row.get('reason', '')}"
        for row in metrics.get("directDispatchBlocks", [])
        if isinstance(row, Mapping)
    )
    for row in rows:
        if row.get("technology") not in {"wind", "pv"}:
            continue
        sink = (
            "same-group-acdc"
            if row.get("connectionSide") == "DC" and row.get("dcTransferGroupId")
            else "local-ac"
            if row.get("connectionSide") == "AC"
            else "local"
        )
        detail.append(
            f"phase=renewable sink allocation legalSink={sink} "
            f"acdcReservationKw={metrics.get('dcRenewableToAcKw')} {device_text(row)}"
        )
    detail.extend(
        f"phase=unified validation {device_text(row)}"
        for row in rows
        if row.get("strategyCommand") is not False or row.get("role") == "balance"
    )
    commands = [
        row
        for row in rows
        if row.get("online")
        and row.get("commandable") is not False
        and row.get("strategyCommand") is not False
        and row.get("set_type")
    ]
    for loop in ("open-loop-preview", "closed-loop-command"):
        if not commands:
            detail.append(
                f"phase=dispatch result loop={loop} device=none side= bus= group= path=local currentKw=None candidateDeltaKw=None acceptedDeltaKw=0.0 limit=None reason=hold"
            )
            continue
        detail.extend(
            f"phase=dispatch result loop={loop} {device_text(row)}"
            for row in commands
        )
    return detail


def _source_label(source: str) -> str:
    return {
        "trainee-live": "学员台实时交换数据",
        "trainee-cache": "学员台最近一次有效交换数据",
        "remote": "实时快照",
        "cached": "最近一次有效实时快照",
        "local": "学员台本地数据",
    }.get(source, source)


def _optimization_supported_row(row: Mapping[str, Any]) -> bool:
    return bool(
        row.get("technology") in {"wind", "pv", "storage"}
        or row.get("category") == "柴油发电"
        or _is_grid_converter_row(row)
    )


def _apply_optimization_targets(
    command_rows: Sequence[MutableMapping[str, Any]],
    result: RenewableDispatchOptimizationResult,
    *,
    apply_targets: bool = True,
) -> None:
    island_by_device = {
        key: island.island_id
        for island in result.islands
        for key in island.device_keys
    }
    lower_by_device = {
        key: value
        for island in result.islands
        for key, value in island.active_lower_by_device.items()
    }
    upper_by_device = {
        key: value
        for island in result.islands
        for key, value in island.active_upper_by_device.items()
    }
    failed_devices = {
        key
        for island in result.islands
        if not island.success
        for key in island.device_keys
    }
    failed_devices.update(result.unassigned_devices)
    for row in command_rows:
        if not _optimization_supported_row(row):
            continue
        key = (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
        current = _number(row.get("planningCurrentKw", row.get("currentKw")))
        optimization_target = _number(result.targets.get(key))
        optimization_lower = _number(lower_by_device.get(key))
        optimization_upper = _number(upper_by_device.get(key))
        target = optimization_target
        if _is_grid_converter_row(row):
            # Optimizer targets are positive DC-to-AC. Command rows retain the
            # P_AC convention until dispatch selects p_ac_set or p_dc_set.
            if optimization_lower is not None and optimization_upper is not None:
                row["optimizationLowerSystemKw"] = optimization_lower
                row["optimizationUpperSystemKw"] = optimization_upper
                converted_bounds = (
                    converter_power_in_ac_terminal_convention(
                        optimization_lower,
                        _converter_direction(row),
                        "P_DC",
                    ),
                    converter_power_in_ac_terminal_convention(
                        optimization_upper,
                        _converter_direction(row),
                        "P_DC",
                    ),
                )
                row["optimizationLowerKw"] = min(converted_bounds)
                row["optimizationUpperKw"] = max(converted_bounds)
            if optimization_target is not None:
                row["optimizationSuggestedSystemKw"] = optimization_target
                target = converter_power_in_ac_terminal_convention(
                    optimization_target,
                    _converter_direction(row),
                    "P_DC",
                )
        elif optimization_lower is not None and optimization_upper is not None:
            row["optimizationLowerKw"] = optimization_lower
            row["optimizationUpperKw"] = optimization_upper
        row["optimizationIslandId"] = island_by_device.get(key, "")
        row["optimizationStatus"] = (
            "optimal"
            if target is not None
            else "failed"
            if key in failed_devices
            else "not-dispatchable"
        )
        row["optimizationSuggestedKw"] = target
        if not apply_targets:
            continue
        if target is None:
            row["strategyCommand"] = False
            row["commandKw"] = current
            if row.get("technology") == "storage":
                row["targetKw"] = current
                row["projectedTargetKw"] = current
            continue
        direct_dispatch = bool(row.get("commandable") and row.get("set_type"))
        row["commandKw"] = target
        row["targetKw"] = target
        if row.get("technology") == "storage":
            row["projectedTargetKw"] = target
        if row.get("technology") in {"wind", "pv"}:
            available = result.available_by_renewable.get(key)
            if available is not None:
                row["availableKw"] = available
                row["optimizationAvailableKw"] = available
                row["optimizationCurtailmentKw"] = max(0.0, available - target)
            row["recoveryKw"] = (
                max(0.0, target - current) if current is not None else 0.0
            )
        changed = bool(
            current is not None
            and abs(target - current) > 1e-4
            and row.get("online")
            and direct_dispatch
        )
        row["strategyTargetChanged"] = changed
        # Each generation is a complete replacement snapshot.  A valid target
        # must remain present even when it equals the current measurement.
        row["strategyCommand"] = bool(row.get("online") and direct_dispatch)
        row["statusLabel"] = (
            f"{row.get('statusLabel', '')}·"
            f"{'拓扑岛优化' if direct_dispatch else '拓扑岛优化预测'}"
            if str(row.get("statusLabel", "")).strip()
            else "拓扑岛优化" if direct_dispatch else "拓扑岛优化预测"
        )


def _optimization_balance_delta_warnings(
    result: RenewableDispatchOptimizationResult,
) -> List[str]:
    warnings: List[str] = []
    for island in result.islands:
        if (
            island.max_balance_delta_kw <= EPSILON
            or (
                "balance_slack" not in island.status
                and "balance_delta_fallback" not in island.status
            )
        ):
            continue
        delta_ac = island.balance_delta_by_side.get("AC", 0.0)
        delta_dc = island.balance_delta_by_side.get("DC", 0.0)
        threshold_detail = (
            f"超过大失衡告警阈值{result.balance_delta_warning_kw:.3f} kW"
            if island.max_balance_delta_kw > result.balance_delta_warning_kw
            else f"未超过大失衡阈值{result.balance_delta_warning_kw:.3f} kW"
        )
        warnings.append(
            f"优化岛{island.island_id}在设备物理与安全边界内无法精确配平，"
            "按最小功率平衡松弛继续形成策略："
            f"delta_ac={delta_ac:.3f} kW，delta_dc={delta_dc:.3f} kW，"
            f"{threshold_detail}；"
            "请检查可调资源余量、设备边界、拓扑状态及实时量测一致性"
        )
    return warnings


def _optimization_metrics(
    result: RenewableDispatchOptimizationResult,
) -> Dict[str, Any]:
    step_override_devices = sorted(
        {
            key
            for island in result.islands
            for key in island.step_override_devices
        }
    )
    return {
        "optimizationEnabled": True,
        "optimizationApplied": True,
        "optimizationMode": "active",
        "optimizationMethod": "scipy-lsq-slsqp",
        "optimizationObjective": (
            "renewable_curtailment+diesel_output+"
            "curtailment_square+source_storage_adjustment_square+"
            "large_weight_balance_delta_square"
        ),
        "optimizationIslandCount": len(result.islands),
        "optimizationSuccessfulIslandCount": sum(
            1 for island in result.islands if island.success
        ),
        "optimizationAllIslandsSuccessful": result.all_success,
        "optimizationMaxBalanceResidualKw": result.max_balance_residual_kw,
        "optimizationMaxBalanceDeltaKw": max(
            (island.max_balance_delta_kw for island in result.islands),
            default=0.0,
        ),
        "optimizationBalanceDeltaWarningThresholdKw": (
            result.balance_delta_warning_kw
        ),
        "optimizationLargeBalanceDelta": any(
            island.max_balance_delta_kw > result.balance_delta_warning_kw
            for island in result.islands
        ),
        "optimizationIterations": result.iterations,
        "optimizationVariableCount": result.variable_count,
        "optimizationConstraintCount": result.constraint_count,
        "optimizationEqualityConstraintCount": result.equality_constraint_count,
        "optimizationInequalityConstraintCount": result.inequality_constraint_count,
        "optimizationBoundCount": result.bound_count,
        "optimizationBuildMilliseconds": result.build_seconds * 1000.0,
        "optimizationSolverMilliseconds": result.solver_seconds * 1000.0,
        "optimizationStorageBalanceMilliseconds": (
            result.storage_balance_seconds * 1000.0
        ),
        "optimizationPostprocessMilliseconds": result.postprocess_seconds * 1000.0,
        "optimizationSolveMilliseconds": result.solve_seconds * 1000.0,
        "optimizationStepOverrideApplied": any(
            island.step_override_applied for island in result.islands
        ),
        "optimizationStepOverrideDevices": [
            {"dev_type": dev_type, "dev_name": dev_name}
            for dev_type, dev_name in step_override_devices
        ],
        "optimizationUnassignedDevices": [
            {"dev_type": dev_type, "dev_name": dev_name}
            for dev_type, dev_name in result.unassigned_devices
        ],
        "optimizationIslands": [
            {
                "islandId": island.island_id,
                "componentIds": list(island.component_ids),
                "devices": [
                    {"dev_type": dev_type, "dev_name": dev_name}
                    for dev_type, dev_name in island.device_keys
                ],
                "success": island.success,
                "status": island.status,
                "message": island.message,
                "objectiveValue": island.objective_value,
                "renewableCurtailmentKw": island.renewable_curtailment_kw,
                "dieselTargetKw": island.diesel_target_kw,
                "balanceResidualByComponent": dict(
                    island.balance_residual_by_component
                ),
                "balanceResidualBySide": dict(
                    island.balance_residual_by_component
                ),
                "balanceDeltaBySide": dict(island.balance_delta_by_side),
                "deltaAcKw": island.balance_delta_by_side.get("AC", 0.0),
                "deltaDcKw": island.balance_delta_by_side.get("DC", 0.0),
                "maxBalanceDeltaKw": island.max_balance_delta_kw,
                "largeBalanceDelta": (
                    island.max_balance_delta_kw > result.balance_delta_warning_kw
                ),
                "balanceDeltaSquareWeight": island.balance_delta_square_weight,
                "curtailmentSquareWeight": island.curtailment_square_weight,
                "adjustmentSquareWeight": island.adjustment_square_weight,
                "stepOverrideApplied": island.step_override_applied,
                "stepOverrideDevices": [
                    {"dev_type": dev_type, "dev_name": dev_name}
                    for dev_type, dev_name in island.step_override_devices
                ],
                "iterations": island.iterations,
                "variableCount": island.variable_count,
                "constraintCount": island.constraint_count,
                "equalityConstraintCount": island.equality_constraint_count,
                "inequalityConstraintCount": island.inequality_constraint_count,
                "boundCount": island.bound_count,
                "buildMilliseconds": island.build_seconds * 1000.0,
                "solverMilliseconds": island.solver_seconds * 1000.0,
                "storageBalanceMilliseconds": (
                    island.storage_balance_seconds * 1000.0
                ),
                "postprocessMilliseconds": island.postprocess_seconds * 1000.0,
                "solveMilliseconds": island.solve_seconds * 1000.0,
            }
            for island in result.islands
        ],
    }


def _optimization_performance_diagnostics(
    result: RenewableDispatchOptimizationResult,
) -> Dict[str, Any]:
    solved_islands = sum(1 for island in result.islands if island.success)
    statuses = {str(island.status) for island in result.islands}
    if result.unassigned_devices:
        statuses.add("unassigned_devices")
    return {
        "success": result.all_success,
        "status": ",".join(sorted(statuses)) if statuses else "no_problem",
        "iterations": result.iterations,
        "variableCount": result.variable_count,
        "constraintCount": result.constraint_count,
        "equalityConstraintCount": result.equality_constraint_count,
        "inequalityConstraintCount": result.inequality_constraint_count,
        "boundCount": result.bound_count,
        "unassignedDeviceCount": len(result.unassigned_devices),
        "islandCount": len(result.islands),
        "solvedIslandCount": solved_islands,
        "failedIslandCount": len(result.islands) - solved_islands,
        "maxBalanceResidualKw": result.max_balance_residual_kw,
        "islands": [
            {
                "islandId": island.island_id,
                "success": island.success,
                "status": island.status,
                "iterations": island.iterations,
                "variableCount": island.variable_count,
                "constraintCount": island.constraint_count,
                "boundCount": island.bound_count,
                "solveMs": island.solve_seconds * 1000.0,
            }
            for island in result.islands
        ],
    }


def _optimization_decision_detail(
    result: RenewableDispatchOptimizationResult,
    command_rows: Sequence[Mapping[str, Any]],
    quality_payload: Mapping[str, Any],
    settings: RenewableControlSettings,
) -> List[str]:
    detail = [
        "控制架构：按活动开关、设备投退和AC/DC变流器连接关系构造交直流拓扑岛，逐岛调用SciPy求解",
        (
            "目标函数：最小化新能源弃电总和、柴发出力总和，附加小权重弃电平方项、"
            "更小权重的其他电源/储能调节平方项，以及大权重的delta_ac/delta_dc平方项"
        ),
        (
            "功率平衡：每个混合拓扑岛分别建立一条交流侧和一条直流侧方程；"
            "ACDC与DCAC采用相同端口符号：P_AC正向AC→DC，交流侧系数-1、直流侧系数+1；"
            "允许在设备有功上下限内双向调节；"
            "风机、储能和光伏内部变流器不作为边界变量"
        ),
        (
            "死区语义：柴发和构网储能的功率上下限向内收缩形成保护带；"
            "不缩放普通调节步长，也不因调节量较小而冻结控制指令"
        ),
        (
            "SOC分段限额：按配置曲线线性插值得到当前SOC下允许的最大充电、"
            "放电功率，并与物理边界、能量边界和单周期最大调节量取交集；"
            "低SOC不再另设目标必须为零的独立规则"
        ),
        (
            f"SOC越界约束：SOC低于下限-{settings.soc_deadband * 100:.2f}%或高于上限+"
            f"{settings.soc_deadband * 100:.2f}%时，先按越限能量折算纠偏功率；纠偏功率"
            f"最小值为有效储能步长的{settings.storage_soc_correction_step_scale * 100:.2f}%，"
            "最大值为一个有效储能步长，再据此限制每轮目标变化；若当前仍处于禁止充电或禁止放电区，"
            "则优先投影到硬安全边界；严重越限通过多轮连续纠偏逐步逼近设备保护带内的"
            "最大安全功率；"
            f"跟网储能单周期最大调节量按设备功率容量的{settings.storage_step_ratio * 100:.2f}%计算；"
            "构网储能正常配平不受普通步长约束，但SOC越界纠偏受上述储能步长约束；"
            "柴发和AC/DC变流器不受普通步长约束"
        ),
        (
            "步长可行性：先严格使用单周期普通步长；仅当SOC或设备保护边界"
            "要求强制校正且普通模型无解时，才在物理安全边界内放宽配平步长，"
            "SOC强制充放电边界始终不放宽"
        ),
        (
            f"求解汇总：拓扑岛 {len(result.islands)} 个，成功 "
            f"{sum(1 for island in result.islands if island.success)} 个，"
            f"最大调节功率平衡残差 {result.max_balance_residual_kw:.6g} kW，"
            f"总耗时 {result.solve_seconds * 1000.0:.3f} ms"
        ),
    ]
    for island in result.islands:
        override_text = ""
        if island.step_override_applied:
            override_names = ",".join(
                f"{dev_type}.{dev_name}"
                for dev_type, dev_name in island.step_override_devices
            )
            override_text = f"，安全步长回退设备 {override_names or '--'}"
        detail.append(
            f"优化岛 {island.island_id}：状态 {island.status}，"
            f"分量 {','.join(island.component_ids)}，弃电 "
            f"{island.renewable_curtailment_kw:.3f} kW，柴发目标 "
            f"{island.diesel_target_kw:.3f} kW，"
            f"delta_ac {island.balance_delta_by_side.get('AC', 0.0):.3f} kW，"
            f"delta_dc {island.balance_delta_by_side.get('DC', 0.0):.3f} kW，"
            f"迭代 {island.iterations} 次，"
            f"耗时 {island.solve_seconds * 1000.0:.3f} ms{override_text}"
        )
    for row in command_rows:
        if row.get("strategyCommand") is False:
            continue
        current = _number(row.get("planningCurrentKw", row.get("currentKw")))
        target = _number(row.get("commandKw"))
        if current is None or target is None:
            continue
        detail.append(
            f"优化指令：{row.get('dev_type', '')}.{row.get('dev_name', '')} "
            f"{current:.3f} -> {target:.3f} kW，调节量 {target - current:.3f} kW"
        )
    detail.extend(
        f"数据告警：{issue}"
        for issue in quality_payload.get("issues", [])
    )
    return detail


def calculate_renewable_control_plan(
    snapshot: Mapping[str, Any],
    settings: Optional[RenewableControlSettings] = None,
    *,
    data_source: str = "remote",
    snapshot_age_seconds: float = 0.0,
) -> Dict[str, Any]:
    plan_started = time.perf_counter()
    configured_settings = (settings or RenewableControlSettings()).normalized()
    renewable_effective_decision_step_ratio = configured_settings.step_coefficient
    storage_effective_decision_step_ratio = configured_settings.storage_step_ratio
    settings = configured_settings
    quality = _Quality(data_source, snapshot_age_seconds)
    measurements = _measurement_index(snapshot)
    load_kw = _load_boundary(snapshot, measurements, quality)
    wind_measurement = _measured(measurements, "Environment", "weather", ("WIND_SPEED",))
    irradiance_measurement = _measured(measurements, "Environment", "weather", ("SOLAR_IRRADIANCE",))
    temperature_measurement = _measured(measurements, "Environment", "weather", ("AIR_TEMP",))
    observed_wind_speed = _observed_environment_value(
        snapshot,
        wind_measurement,
        "wind_speed_mps",
    )
    observed_irradiance = _observed_environment_value(
        snapshot,
        irradiance_measurement,
        "solar_irradiance_w_m2",
    )
    observed_air_temperature = _observed_environment_value(
        snapshot,
        temperature_measurement,
        "air_temp_c",
    )
    wind_speed = observed_wind_speed
    irradiance = observed_irradiance
    air_temperature = observed_air_temperature
    quality.input(
        "windSpeed",
        observed_wind_speed,
        "scada_or_curve_boundary",
        observed_wind_speed is not None,
    )
    quality.input(
        "solarIrradiance",
        observed_irradiance,
        "scada_or_curve_boundary",
        observed_irradiance is not None,
    )
    quality.input(
        "airTemperature",
        observed_air_temperature,
        "scada_or_curve_boundary",
        observed_air_temperature is not None,
    )

    identity_diagnostics = _duplicate_typed_identities(snapshot)
    renewable_specs, storage_specs, resource_refs = _linked_resource_specs(
        snapshot,
        quality,
        identity_diagnostics,
    )
    resource_keys = {
        (spec.dev_type, spec.dev_name)
        for spec in (*renewable_specs, *storage_specs)
    }
    diesel_rows = _diesel_rows(snapshot, measurements, resource_keys, quality)
    diesel_refs = [
        ResourceRef(
            "diesel",
            str(row.get("model_block", "")),
            str(row.get("dev_name", "")),
        )
        for row in diesel_rows
    ]
    topology_started = time.perf_counter()
    input_processing_seconds = topology_started - plan_started
    resource_topology = resolve_resource_topology(
        snapshot,
        (*resource_refs, *diesel_refs),
    )
    topology_finished = time.perf_counter()
    topology_analysis_seconds = topology_finished - topology_started
    converter_group_ids = {
        converter_key: group_id
        for group_id, group in resource_topology.dc_transfer_groups.items()
        for converter_key in group.converter_keys
    }
    renewable_rows = _renewable_rows(
        snapshot,
        measurements,
        renewable_specs,
        resource_topology.resources,
        quality,
        observed_wind_speed=observed_wind_speed,
        observed_solar_irradiance=observed_irradiance,
        observed_air_temperature=observed_air_temperature,
    )
    _annotate_diesel_topology(
        diesel_rows,
        resource_topology.resources,
        resource_topology.device_component_ids,
    )
    storage_rows = _storage_rows(
        snapshot,
        measurements,
        settings,
        quality,
        storage_specs,
        resource_topology.resources,
        resource_topology.dc_transfer_groups,
    )
    internal_converter_keys = {
        converter_key
        for connection in resource_topology.resources.values()
        if connection.technology in {"wind", "pv", "storage"}
        for converter_key in connection.converter_path
    }
    dispatchable_converter_keys = structured_grid_converter_keys(snapshot)
    converter_inventory_rows = sorted(
        _converter_rows(
            snapshot,
            measurements,
            converter_group_ids=converter_group_ids,
            internal_converter_keys=internal_converter_keys,
            grid_converter_keys=dispatchable_converter_keys,
            identity_diagnostics=identity_diagnostics,
            quality=quality,
        ),
        key=_converter_row_sort_key,
    )
    fail_closed_scopes = _apply_grid_forming_fail_closed_scopes(
        renewable_rows,
        storage_rows,
        converter_inventory_rows,
        diesel_rows,
        quality,
    )
    all_converter_rows = [
        row for row in converter_inventory_rows if row.get("commandable")
    ]
    converter_validation_rows = [
        row
        for row in converter_inventory_rows
        if row.get("online")
        and row.get("converterRole") == "grid"
        and str(row.get("dcTransferGroupId", ""))
    ]
    diagnostic_converter_rows = [
        row for row in converter_inventory_rows if not row.get("commandable")
    ]

    strategy_online_renewable = [row for row in renewable_rows if row["online"]]
    online_diesel = [row for row in diesel_rows if row["online"]]
    measured_diesel = [row for row in online_diesel if row.get("currentKw") is not None]
    diesel_current = (
        sum(_finite_number(row.get("currentKw")) for row in measured_diesel)
        if measured_diesel
        else None
    )
    diesel_min = sum(max(0.0, _finite_number(row.get("minKw"))) for row in online_diesel)
    diesel_capacity = sum(
        max(0.0, _finite_number(row.get("capacityKw"))) for row in online_diesel
    )
    diesel_deadband_kw = (
        settings.diesel_power_protection_ratio * diesel_capacity
    )
    diesel_deadband_lower_kw = diesel_min
    diesel_deadband_upper_kw = diesel_min + diesel_deadband_kw

    online_ac_balance_storage = [
        row
        for row in storage_rows
        if row["online"] and row.get("role") == "balance" and row.get("connectionSide") == "AC"
    ]
    online_dc_balance_storage = [
        row
        for row in storage_rows
        if row["online"]
        and row.get("role") == "balance"
        and row.get("connectionSide") == "DC"
        and row.get("stateEligible")
    ]
    online_ac_grid_following_storage = [
        row
        for row in storage_rows
        if row["online"] and row.get("role") == "grid_following" and row.get("connectionSide") == "AC"
    ]
    online_dc_grid_following_storage = [
        row
        for row in storage_rows
        if row["online"] and row.get("role") == "grid_following" and row.get("connectionSide") == "DC"
    ]
    ac_balance_storage_current = sum(
        _finite_number(row.get("currentKw"))
        for row in online_ac_balance_storage
        if row.get("currentKw") is not None
    )
    dc_balance_storage_current = sum(
        _finite_number(row.get("currentKw"))
        for row in online_dc_balance_storage
        if row.get("currentKw") is not None
    )
    ac_grid_following_storage_current = sum(
        _finite_number(row.get("currentKw"))
        for row in online_ac_grid_following_storage
        if row.get("currentKw") is not None
    )
    dc_grid_following_storage_current = sum(
        _finite_number(row.get("currentKw"))
        for row in online_dc_grid_following_storage
        if row.get("currentKw") is not None
    )

    ac_bus_rows = _device_state_rows(snapshot, "ACRealBs")
    online_ac_buses = [row for row in ac_bus_rows if _is_online(row, measurements)]
    ac_load_devices = [
        device
        for device in snapshot.get("devices", []) or []
        if isinstance(device, Mapping) and _device_model_block(device) == "ACLoad"
    ]
    online_ac_loads = [device for device in ac_load_devices if _is_online(device, measurements)]
    ac_side_fully_offline = bool(ac_bus_rows) and not online_ac_buses and not online_diesel and not online_ac_loads

    storage_group_set = {
        str(row.get("dcTransferGroupId", ""))
        for row in online_dc_balance_storage
        if str(row.get("dcTransferGroupId", ""))
    }
    candidate_group_ids = sorted(
        (
            group_id
            for group_id in storage_group_set
            if group_id in resource_topology.dc_transfer_groups
        ),
        key=lambda group_id: _dc_transfer_group_sort_key(
            resource_topology,
            group_id,
        ),
    )
    primary_control_group_id = candidate_group_ids[0] if candidate_group_ids else ""
    if primary_control_group_id:
        normal_online_storage = [
            row
            for row in online_dc_balance_storage
            if row.get("dcTransferGroupId") == primary_control_group_id
        ]
        normal_converter_rows = [
            row
            for row in all_converter_rows
            if row.get("dcTransferGroupId") == primary_control_group_id
        ]
        held_normal_converter_rows = [
            row for row in all_converter_rows if row not in normal_converter_rows
        ]
    elif all_converter_rows:
        normal_online_storage = []
        normal_converter_rows = []
        held_normal_converter_rows = list(all_converter_rows)
    else:
        normal_online_storage = list(online_dc_balance_storage)
        normal_converter_rows = []
        held_normal_converter_rows = []

    dc_renewable_rows = [
        row
        for row in strategy_online_renewable
        if row.get("connectionSide") == "DC" and row.get("gridComponentId")
    ]
    island_components = _renewable_storage_island_components(
        dc_renewable_rows,
        online_dc_balance_storage,
        converter_validation_rows,
    )
    renewable_storage_island = bool(
        ac_side_fully_offline
        and island_components
    )
    primary_island_component = island_components[0] if renewable_storage_island else None
    island_online_renewable = [
        row
        for component in island_components
        for row in component.renewable_rows
    ]
    island_online_storage = [
        row
        for component in island_components
        for row in component.storage_rows
    ]
    island_converter_keys = {
        (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
        for component in island_components
        for row in component.converter_rows
    }
    if primary_island_component is not None:
        online_storage = list(primary_island_component.storage_rows)
        online_renewable = list(primary_island_component.renewable_rows)
        converter_rows = list(primary_island_component.converter_rows)
        held_converter_rows = [
            row
            for row in all_converter_rows
            if (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
            not in island_converter_keys
        ]
    else:
        online_storage = normal_online_storage
        online_renewable = strategy_online_renewable
        converter_rows = normal_converter_rows
        held_converter_rows = held_normal_converter_rows
    renewable_metric_rows = (
        island_online_renewable
        if renewable_storage_island
        else online_renewable
    )
    operating_mode = (
        "renewable_storage_island"
        if renewable_storage_island
        else "diesel_reference"
        if online_diesel
        else "blocked_no_diesel"
    )

    missing_renewable_power = [
        row for row in renewable_metric_rows if row.get("currentKw") is None
    ]
    for row in missing_renewable_power:
        quality.add(
            f"{row['category']}{row['dev_name']}缺少有效实时有功，已仅闭锁该设备所在优化岛",
        )
    capability_unknown_rows = [
        row
        for row in renewable_metric_rows
        if row.get("environmentKnown") and not row.get("capabilityKnown")
    ]
    for row in capability_unknown_rows:
        quality.add(
            f"{row['category']}{row['dev_name']}缺少计算最大可发所需的有效模型参数，已仅闭锁该设备",
        )
    renewable_current = sum(
        _finite_number(row.get("currentKw")) for row in renewable_metric_rows
    )
    renewable_capacity = sum(
        max(0.0, _finite_number(row.get("capacityKw")))
        for row in renewable_metric_rows
    )
    wind_current = sum(
        _finite_number(row.get("currentKw"))
        for row in renewable_metric_rows
        if row.get("technology") == "wind"
    )
    pv_current = sum(
        _finite_number(row.get("currentKw"))
        for row in renewable_metric_rows
        if row.get("technology") == "pv"
    )

    measured_storage = [row for row in online_storage if row.get("currentKw") is not None]
    storage_current = (
        sum(_finite_number(row.get("currentKw")) for row in measured_storage)
        if measured_storage
        else None
    )
    grid_forming_storage_charge_capacity_kw = sum(
        max(0.0, _finite_number(row.get("maxChargePowerKw")))
        for row in online_storage
        if row.get("role") == "balance"
    )
    grid_forming_storage_discharge_capacity_kw = sum(
        max(0.0, _finite_number(row.get("maxDischargePowerKw")))
        for row in online_storage
        if row.get("role") == "balance"
    )
    grid_forming_storage_charge_protection_kw = (
        settings.grid_forming_storage_protection_ratio
        * grid_forming_storage_charge_capacity_kw
    )
    grid_forming_storage_discharge_protection_kw = (
        settings.grid_forming_storage_protection_ratio
        * grid_forming_storage_discharge_capacity_kw
    )
    storage_control_horizon_minutes = max(
        (_finite_number(row.get("controlHorizonMinutes")) for row in online_storage),
        default=_storage_control_horizon_minutes(snapshot, settings),
    )
    known_soc = [
        _finite_number(row.get("soc"))
        for row in online_storage
        if row.get("socKnown") and row.get("soc") is not None
    ]
    storage_soc = sum(known_soc) / len(known_soc) if known_soc else None
    known_soc_rows = [row for row in online_storage if row.get("socKnown") and row.get("soc") is not None]
    storage_soc_lower_limit = (
        sum(_finite_number(row.get("socMin")) for row in known_soc_rows) / len(known_soc_rows)
        if known_soc_rows
        else None
    )
    storage_soc_upper_limit = (
        sum(_finite_number(row.get("socMax")) for row in known_soc_rows) / len(known_soc_rows)
        if known_soc_rows
        else None
    )
    storage_soc_region = (
        "unknown"
        if storage_soc is None or storage_soc_lower_limit is None or storage_soc_upper_limit is None
        else "below_lower"
        if storage_soc < storage_soc_lower_limit
        else "low_guard"
        if storage_soc < storage_soc_lower_limit + settings.soc_deadband
        else "above_upper"
        if storage_soc > storage_soc_upper_limit
        else "high_guard"
        if storage_soc > storage_soc_upper_limit - settings.soc_deadband
        else "normal"
    )
    soc_upper_deadband_threshold = (
        min(1.0, storage_soc_upper_limit + settings.soc_deadband)
        if storage_soc_upper_limit is not None
        else None
    )
    soc_lower_deadband_threshold = (
        max(0.0, storage_soc_lower_limit - settings.soc_deadband)
        if storage_soc_lower_limit is not None
        else None
    )
    soc_above_upper_deadband = bool(
        storage_soc is not None
        and soc_upper_deadband_threshold is not None
        and (
            storage_soc > soc_upper_deadband_threshold + EPSILON
            or (
                soc_upper_deadband_threshold >= 1.0 - EPSILON
                and storage_soc >= 1.0 - EPSILON
            )
        )
    )
    soc_below_lower_deadband = bool(
        storage_soc is not None
        and soc_lower_deadband_threshold is not None
        and (
            storage_soc < soc_lower_deadband_threshold - EPSILON
            or (
                soc_lower_deadband_threshold <= EPSILON
                and storage_soc <= EPSILON
            )
        )
    )
    storage_above_upper = [row for row in online_storage if row.get("socConstraint") == "above_upper"]
    storage_below_lower = [row for row in online_storage if row.get("socConstraint") == "below_lower"]
    raw_charge_before_derating = sum(
        max(0.0, _finite_number(row.get("chargePowerBeforeDerating"))) for row in online_storage
    )
    raw_discharge_before_derating = sum(
        max(0.0, _finite_number(row.get("dischargePowerBeforeDerating"))) for row in online_storage
    )
    raw_charge = sum(max(0.0, _finite_number(row.get("chargePower"))) for row in online_storage)
    raw_discharge = sum(max(0.0, _finite_number(row.get("dischargePower"))) for row in online_storage)
    charge_derating_capacity = sum(
        max(0.0, _finite_number(row.get("maxChargePowerKw"))) for row in online_storage
    )
    discharge_derating_capacity = sum(
        max(0.0, _finite_number(row.get("maxDischargePowerKw"))) for row in online_storage
    )
    storage_charge_derating_factor = (
        sum(
            max(0.0, _finite_number(row.get("maxChargePowerKw")))
            * _clamp(_finite_number(row.get("chargeDeratingFactor")), 0.0, 1.0)
            for row in online_storage
        )
        / charge_derating_capacity
        if charge_derating_capacity > EPSILON
        else 1.0
    )
    storage_discharge_derating_factor = (
        sum(
            max(0.0, _finite_number(row.get("maxDischargePowerKw")))
            * _clamp(_finite_number(row.get("dischargeDeratingFactor")), 0.0, 1.0)
            for row in online_storage
        )
        / discharge_derating_capacity
        if discharge_derating_capacity > EPSILON
        else 1.0
    )
    storage_charge_derating_active = any(row.get("chargeDeratingActive") for row in online_storage)
    storage_discharge_derating_active = any(row.get("dischargeDeratingActive") for row in online_storage)
    converter_rows = _resolve_converter_capacities(converter_rows)

    measured_converters = [row for row in converter_rows if row.get("currentKw") is not None]
    converter_current = sum(_finite_number(row.get("currentKw")) for row in measured_converters) if measured_converters else None
    if converter_rows and len(measured_converters) != len(converter_rows):
        quality.add("部分在线功率控制型交直流变流器缺少有效实时有功，相关设备不参与本轮优化")
    if any(_finite_number(row.get("transferCapacityKw")) <= 0 for row in converter_rows):
        quality.add("部分在线功率控制型交直流变流器缺少有效容量边界，相关设备不参与本轮优化")
    converter_limit = _parallel_converter_limit(converter_rows)
    storage_power_capacity = max(raw_charge, raw_discharge)
    if converter_rows and math.isfinite(converter_limit):
        storage_power_capacity = (
            min(storage_power_capacity, converter_limit)
            if storage_power_capacity > EPSILON
            else converter_limit
        )
    converter_base_step_kw = (
        settings.converter_step_ratio * converter_limit
        if converter_rows and math.isfinite(converter_limit)
        else 0.0
    )
    if online_storage and not converter_rows and not renewable_storage_island:
        quality.add(
            "无在线功率控制型交直流变流器；交流侧设备仍可独立优化，直流分量按本地平衡约束处理",
        )
    if ac_side_fully_offline and not online_storage:
        quality.add(
            "交流侧全部退运且没有在线储能，相关优化岛将保持或闭锁",
            blocked=True,
        )
    if not online_diesel and not renewable_storage_island:
        quality.add("没有在线柴油发电机，优化器将由岛内其他构网电源或储能承担平衡")
    elif len(measured_diesel) != len(online_diesel):
        quality.add("部分在线柴油发电机缺少有效实时有功，相关柴油机不参与本轮优化")
    diesel_current_for_control = diesel_current if diesel_current is not None else diesel_min
    if online_storage and len(measured_storage) != len(online_storage):
        quality.add("部分在线储能缺少有效实时有功，相关储能不参与本轮优化")
    storage_current_for_control = (
        storage_current
        if storage_current is not None
        else -converter_current
        if converter_current is not None
        else 0.0
    )
    storage_charge_current_kw = max(0.0, -storage_current_for_control)
    storage_discharge_current_kw = max(0.0, storage_current_for_control)
    storage_charge_derating_excess_kw = max(0.0, storage_charge_current_kw - raw_charge)
    storage_discharge_derating_excess_kw = max(0.0, storage_discharge_current_kw - raw_discharge)
    storage_charge_derating_headroom_kw = max(0.0, raw_charge - storage_charge_current_kw)
    storage_discharge_derating_headroom_kw = max(0.0, raw_discharge - storage_discharge_current_kw)
    converter_current_for_control = (
        converter_current
        if converter_rows and converter_current is not None and len(measured_converters) == len(converter_rows)
        else -storage_current_for_control
        if converter_rows
        else 0.0
    )
    converter_reverse_power_detected = False
    diesel_down_margin = diesel_current_for_control - diesel_min
    diesel_floor_deficit_kw = max(0.0, diesel_min - diesel_current_for_control)
    diesel_deadband_entry_gap_kw = max(
        0.0,
        diesel_deadband_upper_kw - diesel_current_for_control,
    )
    diesel_floor_correction_request_kw = (
        min(
            diesel_deadband_entry_gap_kw,
            max(0.0, -converter_current_for_control),
        )
        if diesel_floor_deficit_kw > EPSILON
        else 0.0
    )
    diesel_up_margin = max(0.0, diesel_capacity - diesel_current_for_control) if diesel_capacity > EPSILON else 0.0
    storage_min_target = -raw_charge if converter_rows else storage_current_for_control
    storage_max_target = raw_discharge if converter_rows else storage_current_for_control
    converter_lower_target = sum(
        _converter_signed_bounds_kw(row)[0] for row in converter_rows
    )
    converter_upper_target = sum(
        _converter_signed_bounds_kw(row)[1] for row in converter_rows
    )
    if converter_rows and math.isfinite(converter_limit):
        # ACDC is an independent AC/DC coupling actuator, not a storage
        # inverter. Its signed target must be checked against its own
        # capacity, while storage SOC/power bounds remain local to storage.
        # Coupling the two aggregate targets here incorrectly assumes that
        # every storage-watt change must be supplied by ACDC, even when the
        # DC group can rebalance through local renewable output or load.
        if (
            converter_current_for_control < converter_lower_target - 0.001
            or converter_current_for_control > converter_upper_target + 0.001
        ):
            quality.add("交直流变流器实时有功已经超过并联容量边界，优化器将优先校正到物理边界")
        elif abs(converter_current_for_control) > EPSILON:
            # Preserve the legacy incremental capacity check only when the
            # converter is actually carrying power. A zero-power ACDC cannot
            # establish a storage/converter pairing for this projection.
            converter_storage_baseline = (
                storage_current_for_control + converter_current_for_control
            )
            converter_storage_min = converter_storage_baseline - converter_upper_target
            converter_storage_max = converter_storage_baseline - converter_lower_target
            storage_min_target = max(storage_min_target, converter_storage_min)
            storage_max_target = min(storage_max_target, converter_storage_max)
            if storage_min_target > storage_max_target + EPSILON:
                quality.add(
                    "旧投影策略的储能与变流器边界没有交集，最终指令改由逐岛优化可行性判定",
                )
                fallback_storage_target = _clamp(
                    storage_current_for_control,
                    -raw_charge,
                    raw_discharge,
                )
                storage_min_target = fallback_storage_target
                storage_max_target = fallback_storage_target
    total_charge = max(0.0, -storage_min_target) if converter_rows else 0.0
    total_discharge = max(0.0, storage_max_target) if converter_rows else 0.0
    renewable_balance_limit = 0.0
    diesel_control_region = (
        "high"
        if diesel_current_for_control > diesel_deadband_upper_kw + EPSILON
        else "low"
        if diesel_current_for_control < diesel_deadband_lower_kw - EPSILON
        else "deadband"
    )
    diesel_boundary_distance_kw = (
        diesel_floor_deficit_kw
        if diesel_control_region == "low"
        else max(0.0, diesel_current_for_control - diesel_deadband_upper_kw)
        if diesel_control_region == "high"
        else 0.0
    )
    lower_soc_deadband_active = (
        storage_soc is not None
        and storage_soc_lower_limit is not None
        and storage_soc_lower_limit - settings.soc_deadband - EPSILON
        <= storage_soc
        <= storage_soc_lower_limit + settings.soc_deadband + EPSILON
    )
    upper_soc_deadband_active = (
        storage_soc is not None
        and storage_soc_upper_limit is not None
        and storage_soc_upper_limit - settings.soc_deadband - EPSILON
        <= storage_soc
        <= storage_soc_upper_limit + settings.soc_deadband + EPSILON
    )
    diesel_deadband_active = diesel_control_region == "deadband"
    renewable_upper_boundary_distance = (
        max(0.0, storage_soc - storage_soc_upper_limit)
        if storage_soc is not None and storage_soc_upper_limit is not None
        else 0.0
    )
    renewable_storage_charge_excess_kw = max(
        0.0,
        -storage_current_for_control
        - grid_forming_storage_charge_protection_kw,
    )
    renewable_storage_charging_active = renewable_storage_charge_excess_kw > EPSILON
    renewable_recovery_boundary_scale = 1.0
    renewable_recovery_capacity_step_kw = sum(
        min(
            max(0.0, _finite_number(row.get("capacityKw")) - _finite_number(row.get("planningCurrentKw"))),
            settings.step_coefficient * max(0.0, _finite_number(row.get("capacityKw"))),
        )
        for row in online_renewable
        if row.get("commandable") and row.get("planningCurrentKw") is not None
    )
    renewable_recovery_derating_scale = (
        min(
            1.0,
            storage_charge_derating_headroom_kw / renewable_recovery_capacity_step_kw,
        )
        if storage_charge_derating_active and renewable_recovery_capacity_step_kw > EPSILON
        else 1.0
    )
    renewable_recovery_step_scale = min(
        renewable_recovery_boundary_scale,
        renewable_recovery_derating_scale,
    )
    renewable_recovery_effective_step_ratio = settings.step_coefficient * renewable_recovery_step_scale
    renewable_recovery_step_request_kw = sum(
        min(
            max(0.0, _finite_number(row.get("capacityKw")) - _finite_number(row.get("planningCurrentKw"))),
            renewable_recovery_effective_step_ratio * max(0.0, _finite_number(row.get("capacityKw"))),
        )
        for row in online_renewable
        if row.get("commandable") and row.get("planningCurrentKw") is not None
    )
    renewable_curtail_base_steps = {
        (row["dev_type"], row["dev_name"]): min(
            max(0.0, _finite_number(row.get("planningCurrentKw"))),
            settings.step_coefficient * max(0.0, _finite_number(row.get("capacityKw"))),
        )
        for row in online_renewable
        if row.get("commandable") and row.get("planningCurrentKw") is not None
    }
    renewable_commandable_rows = [
        row
        for row in online_renewable
        if row.get("commandable") and row.get("planningCurrentKw") is not None
    ]
    renewable_commandable_current_kw = sum(
        max(0.0, _finite_number(row.get("planningCurrentKw")))
        for row in renewable_commandable_rows
    )
    renewable_curtail_capacity_step_kw = sum(renewable_curtail_base_steps.values())
    renewable_curtail_step_request_kw = min(
        renewable_curtail_capacity_step_kw,
        renewable_storage_charge_excess_kw,
    )
    renewable_curtail_step_scale = (
        renewable_curtail_step_request_kw / renewable_curtail_capacity_step_kw
        if renewable_curtail_capacity_step_kw > EPSILON
        else 0.0
    )
    renewable_curtail_effective_step_ratio = settings.step_coefficient * renewable_curtail_step_scale
    renewable_derating_curtail_step_request_kw = min(
        renewable_curtail_capacity_step_kw,
        storage_charge_derating_excess_kw,
    )
    renewable_derating_curtail_step_scale = (
        renewable_derating_curtail_step_request_kw / renewable_curtail_capacity_step_kw
        if renewable_curtail_capacity_step_kw > EPSILON
        else 0.0
    )
    renewable_raise_blocked_by_diesel_guard = bool(
        not renewable_storage_island
        and storage_soc is not None
        and storage_soc_lower_limit is not None
        and storage_soc > storage_soc_lower_limit + EPSILON
        and diesel_current_for_control < diesel_deadband_upper_kw - EPSILON
    )
    renewable_curtailment_required_by_charging = bool(
        renewable_raise_blocked_by_diesel_guard
        and storage_charge_current_kw > EPSILON
    )
    renewable_diesel_guard_curtail_request_kw = (
        min(renewable_curtail_capacity_step_kw, storage_charge_current_kw)
        if renewable_curtailment_required_by_charging
        else 0.0
    )
    renewable_diesel_guard_curtail_scale = (
        renewable_diesel_guard_curtail_request_kw
        / renewable_curtail_capacity_step_kw
        if renewable_curtail_capacity_step_kw > EPSILON
        else 0.0
    )
    high_soc_guard = storage_soc_region in {"high_guard", "above_upper"}
    soc_at_or_above_upper = (
        storage_soc is not None
        and storage_soc_upper_limit is not None
        and storage_soc >= storage_soc_upper_limit - EPSILON
    )
    soc_at_or_below_lower = (
        storage_soc is not None
        and storage_soc_lower_limit is not None
        and storage_soc <= storage_soc_lower_limit + EPSILON
    )
    storage_control_action = "hold"
    raw_converter_desired_target = converter_current_for_control
    emergency_charge_requested = bool(soc_below_lower_deadband)
    diesel_emergency_charge_allowed = False
    if renewable_storage_island and converter_rows:
        raw_converter_desired_target = 0.0
        storage_control_action = (
            "stop_acdc_export_renewable_storage_island"
            if converter_current_for_control < -EPSILON
            else "hold_acdc_zero_renewable_storage_island"
        )
    elif not converter_rows or storage_soc is None:
        storage_control_action = "hold"
    elif soc_below_lower_deadband:
        raw_converter_desired_target = 0.0
        storage_control_action = (
            "stop_discharge_below_soc_lower_deadband"
            if converter_current_for_control < -EPSILON
            else "reverse_power_forbidden_below_soc_lower_deadband"
        )
    elif soc_at_or_below_lower:
        raw_converter_desired_target = 0.0
        storage_control_action = (
            "stop_discharge_at_soc_lower"
            if converter_current_for_control < -EPSILON
            else "stop_reverse_power_at_soc_lower"
            if converter_current_for_control > EPSILON
            else "hold_at_soc_lower"
        )
    elif soc_above_upper_deadband and diesel_control_region != "low":
        high_soc_diesel_margin_kw = max(0.0, diesel_down_margin)
        raw_converter_desired_target = max(
            converter_lower_target,
            converter_current_for_control - high_soc_diesel_margin_kw,
        )
        storage_control_action = (
            "increase_discharge_above_soc_upper_deadband"
            if raw_converter_desired_target < converter_current_for_control - EPSILON
            else "hold_at_diesel_floor_above_soc_upper_deadband"
        )
    elif diesel_control_region == "low":
        raw_converter_desired_target = min(
            0.0,
            converter_current_for_control + diesel_floor_correction_request_kw,
        )
        storage_control_action = (
            "reduce_discharge_low_diesel"
            if diesel_floor_correction_request_kw > EPSILON
            else "stop_reverse_power_low_diesel"
            if converter_current_for_control > EPSILON
            else "hold_low_diesel"
        )
    elif diesel_control_region == "deadband":
        raw_converter_desired_target = converter_current_for_control
        storage_control_action = "hold"
    elif soc_at_or_above_upper:
        if converter_current_for_control > EPSILON:
            raw_converter_desired_target = 0.0
            storage_control_action = "stop_reverse_power_at_soc_upper"
        else:
            raw_converter_desired_target = max(
                converter_lower_target,
                converter_current_for_control - max(0.0, diesel_down_margin),
            )
            storage_control_action = "increase_discharge"
    elif diesel_control_region == "high":
        raw_converter_desired_target = max(
            converter_lower_target,
            converter_current_for_control - max(0.0, diesel_down_margin),
        )
        storage_control_action = "increase_discharge"

    if converter_reverse_power_detected and raw_converter_desired_target >= -EPSILON:
        storage_control_action = "stop_reverse_power"

    bounded_raw_converter_desired_target = _clamp(
        raw_converter_desired_target,
        converter_lower_target,
        converter_upper_target,
    )
    converter_hard_limit_applied = converter_reverse_power_detected or (
        abs(bounded_raw_converter_desired_target - raw_converter_desired_target) > 0.001
    )

    raw_desired_storage_target = (
        storage_current_for_control
        + converter_current_for_control
        - bounded_raw_converter_desired_target
        if converter_rows
        else storage_current_for_control
    )
    desired_storage_target = _clamp(
        raw_desired_storage_target,
        storage_min_target,
        storage_max_target,
    )
    unbounded_storage_constrained_converter_target = (
        storage_current_for_control
        + converter_current_for_control
        - desired_storage_target
        if converter_rows
        else 0.0
    )
    storage_constrained_converter_target = _clamp(
        unbounded_storage_constrained_converter_target,
        converter_lower_target,
        converter_upper_target,
    )
    converter_hard_limit_applied = converter_hard_limit_applied or (
        abs(
            storage_constrained_converter_target
            - unbounded_storage_constrained_converter_target
        )
        > 0.001
    )
    strategy_converter_delta = (
        bounded_raw_converter_desired_target - converter_current_for_control
    )
    storage_constrained_converter_delta = (
        storage_constrained_converter_target - converter_current_for_control
    )
    storage_charge_derating_candidate_limited = bool(
        storage_charge_derating_active
        and raw_desired_storage_target < storage_min_target - EPSILON
    )
    storage_discharge_derating_candidate_limited = bool(
        storage_discharge_derating_active
        and raw_desired_storage_target > storage_max_target + EPSILON
    )
    converter_storage_constraint_conflict = bool(
        abs(storage_constrained_converter_delta) > EPSILON
        and (
            abs(strategy_converter_delta) <= EPSILON
            or (
                strategy_converter_delta > EPSILON
                and storage_constrained_converter_delta < -EPSILON
            )
            or (
                strategy_converter_delta < -EPSILON
                and storage_constrained_converter_delta > EPSILON
            )
        )
    )
    converter_charge_safety_target = _clamp(
        storage_current_for_control + converter_current_for_control + raw_charge,
        converter_lower_target,
        converter_upper_target,
    )
    converter_charge_safety_storage_kw = (
        storage_current_for_control
        + converter_current_for_control
        - converter_charge_safety_target
    )
    storage_charge_derating_acdc_request_kw = max(
        0.0,
        converter_current_for_control - converter_charge_safety_target,
    )
    storage_charge_derating_acdc_allowed = bool(
        storage_charge_derating_acdc_request_kw > EPSILON
        and storage_charge_derating_acdc_request_kw <= diesel_down_margin + EPSILON
        and converter_charge_safety_storage_kw >= -raw_charge - EPSILON
    )
    storage_derating_constraint_override = False
    storage_charge_derating_actuator = "none"
    storage_discharge_derating_actuator = "none"
    if storage_discharge_derating_candidate_limited:
        converter_desired_target = storage_constrained_converter_target
        storage_derating_constraint_override = converter_storage_constraint_conflict
        storage_discharge_derating_actuator = "acdc"
    elif storage_charge_derating_candidate_limited and storage_charge_derating_acdc_allowed:
        converter_desired_target = storage_constrained_converter_target
        storage_derating_constraint_override = converter_storage_constraint_conflict
        storage_charge_derating_actuator = "acdc"
    elif storage_charge_derating_candidate_limited:
        converter_desired_target = bounded_raw_converter_desired_target
        storage_charge_derating_actuator = "renewable"
    else:
        converter_desired_target = (
            bounded_raw_converter_desired_target
            if converter_storage_constraint_conflict
            else storage_constrained_converter_target
        )
    if renewable_storage_island:
        converter_desired_target = 0.0
        storage_derating_constraint_override = False
        storage_charge_derating_actuator = (
            "renewable"
            if storage_charge_derating_candidate_limited or storage_charge_derating_excess_kw > EPSILON
            else "none"
        )
        storage_discharge_derating_actuator = "none"
    converter_step_direction = (
        "increase"
        if converter_desired_target > converter_current_for_control + EPSILON
        else "decrease"
        if converter_desired_target < converter_current_for_control - EPSILON
        else "hold"
    )
    # p_ac_set is positive from AC to DC, so a smaller target increases
    # physical DC-to-AC export.
    converter_export_step_direction = (
        "increase_export"
        if converter_desired_target < converter_current_for_control - EPSILON
        else "decrease_export"
        if converter_desired_target > converter_current_for_control + EPSILON
        else "hold"
    )
    diesel_boundary_action_toward_hold = (
        diesel_control_region == "low"
        and storage_control_action == "reduce_discharge_low_diesel"
        and converter_step_direction == "decrease"
    ) or (
        diesel_control_region == "high"
        and storage_control_action == "increase_discharge"
        and converter_step_direction == "increase"
    )
    diesel_boundary_approach_active = bool(
        diesel_boundary_action_toward_hold
        and converter_base_step_kw > EPSILON
        and diesel_boundary_distance_kw <= converter_base_step_kw + EPSILON
    )
    converter_slow_export_increase = False
    converter_emergency_stop_active = bool(
        soc_below_lower_deadband
        and converter_export_step_direction == "decrease_export"
    )
    converter_island_zero_override = bool(
        renewable_storage_island
        and converter_rows
        and abs(converter_current_for_control) > EPSILON
    )
    converter_step_scale = 1.0
    converter_step_kw = converter_base_step_kw * converter_step_scale
    normal_stepped_converter_target = (
        converter_desired_target
        if converter_emergency_stop_active or converter_island_zero_override
        else _move_toward(converter_current_for_control, converter_desired_target, converter_step_kw)
        if converter_rows
        else 0.0
    )
    converter_charge_derating_safety_override = bool(
        storage_charge_derating_excess_kw > EPSILON
        and storage_charge_derating_acdc_allowed
        and normal_stepped_converter_target > converter_charge_safety_target + EPSILON
    )
    stepped_converter_target = (
        converter_charge_safety_target
        if converter_charge_derating_safety_override
        else normal_stepped_converter_target
    )
    converter_target = _clamp(
        stepped_converter_target,
        converter_lower_target,
        converter_upper_target,
    )
    converter_hard_limit_applied = converter_hard_limit_applied or (
        abs(converter_target - stepped_converter_target) > 0.001
    )
    converter_applied_step_kw = abs(converter_target - converter_current_for_control)
    storage_target = (
        storage_current_for_control + converter_current_for_control - converter_target
        if converter_rows
        else storage_current_for_control
    )
    storage_predicted_charge_after_acdc_kw = max(0.0, -storage_target)
    storage_charge_derating_residual_kw = max(
        0.0,
        storage_predicted_charge_after_acdc_kw - raw_charge,
    )
    storage_high_soc_discharge_request_kw = (
        min(
            renewable_curtail_capacity_step_kw,
            max(
                0.0,
                renewable_commandable_current_kw - storage_charge_derating_residual_kw,
            ),
        )
        if soc_above_upper_deadband and storage_target <= EPSILON
        else 0.0
    )
    renewable_charge_safety_curtail_required_kw = (
        storage_charge_derating_residual_kw + storage_high_soc_discharge_request_kw
    )
    renewable_charge_safety_curtail_request_kw = min(
        renewable_commandable_current_kw,
        renewable_charge_safety_curtail_required_kw,
    )
    renewable_charge_safety_allocations = _allocate(
        renewable_commandable_rows,
        renewable_charge_safety_curtail_request_kw,
        "planningCurrentKw",
    )
    renewable_charge_safety_by_device = {
        (row["dev_type"], row["dev_name"]): amount
        for row, amount in zip(renewable_commandable_rows, renewable_charge_safety_allocations)
    }
    renewable_charge_safety_curtail_delivered_kw = sum(renewable_charge_safety_allocations)
    renewable_charge_safety_curtail_shortfall_kw = max(
        0.0,
        renewable_charge_safety_curtail_required_kw
        - renewable_charge_safety_curtail_delivered_kw,
    )
    storage_charge_derating_safety_override = bool(
        renewable_charge_safety_curtail_required_kw > EPSILON
        or converter_charge_derating_safety_override
    )
    if storage_charge_derating_excess_kw > EPSILON and storage_charge_derating_actuator == "none":
        storage_charge_derating_actuator = (
            "acdc"
            if converter_target < converter_current_for_control - EPSILON
            else "renewable"
        )
    if storage_discharge_derating_excess_kw > EPSILON and storage_discharge_derating_actuator == "none":
        storage_discharge_derating_actuator = "acdc"
    storage_candidate_target = desired_storage_target
    storage_deadband_action = storage_control_action
    converter_step_limited = (
        abs(converter_target - converter_desired_target)
        > settings.optimization_bound_tolerance_kw
    )

    # The ACDC and renewable controllers are independent feedback loops. Keep
    # the legacy metrics at zero for API compatibility, but do not use them to
    # replace, absorb, scale, or otherwise combine the two strategies.
    renewable_discharge_replacement_kw = 0.0
    renewable_absorption_required_kw = 0.0
    storage_renewable_coordination_kw = 0.0
    renewable_storage_coordination_active = False
    high_soc_storage_balance_limit_kw = 0.0
    high_soc_storage_balance_limited = False
    high_soc_required_curtail_kw = 0.0

    if renewable_storage_island:
        if storage_soc is None or storage_soc_upper_limit is None:
            renewable_control_action = "hold_unknown_soc"
        elif storage_soc >= storage_soc_upper_limit - EPSILON:
            renewable_control_action = "curtail_one_step_storage_island_full_soc"
        elif raw_charge <= EPSILON:
            renewable_control_action = "curtail_one_step_storage_island_no_charge_capacity"
        elif storage_charge_derating_residual_kw > EPSILON:
            renewable_control_action = "curtail_charge_safety"
        else:
            renewable_control_action = "recover_one_step_storage_island"
    elif storage_soc is None or storage_soc_upper_limit is None:
        renewable_control_action = "hold_unknown_soc"
    elif soc_below_lower_deadband:
        renewable_control_action = "recover_one_step_below_soc_lower_deadband"
    elif soc_above_upper_deadband:
        renewable_control_action = (
            "curtail_charge_safety"
            if renewable_charge_safety_curtail_required_kw > EPSILON
            else "hold_above_soc_upper_deadband_while_acdc_discharges"
            if storage_target > EPSILON
            else "curtail_one_step_above_soc_upper_deadband"
        )
    elif storage_charge_derating_residual_kw > EPSILON:
        renewable_control_action = "curtail_charge_safety"
    elif (
        storage_charge_derating_excess_kw > EPSILON
        and storage_charge_derating_actuator == "renewable"
    ):
        renewable_control_action = "curtail_one_step_charge_derating"
    elif (
        storage_charge_derating_excess_kw > EPSILON
        and storage_charge_derating_actuator == "acdc"
    ):
        renewable_control_action = "hold_charge_derating_while_acdc_corrects"
    elif renewable_curtailment_required_by_charging:
        renewable_control_action = "curtail_one_step_low_diesel_charging"
    elif renewable_raise_blocked_by_diesel_guard:
        renewable_control_action = "hold_low_diesel_no_charge"
    elif storage_soc < storage_soc_upper_limit - EPSILON:
        renewable_control_action = "recover_one_step"
    elif (
        renewable_storage_charging_active
        and diesel_current_for_control <= diesel_min + diesel_deadband_kw + EPSILON
    ):
        renewable_control_action = "curtail_one_step_full_soc"
    elif renewable_storage_charging_active:
        renewable_control_action = "hold_full_soc_high_diesel_charging"
    elif diesel_current_for_control <= diesel_min + diesel_deadband_kw + EPSILON:
        renewable_control_action = "hold_full_soc_no_charge"
    else:
        renewable_control_action = "recover_one_step"

    renewable_step_direction = (
        "increase"
        if renewable_control_action in {
            "recover_one_step",
            "recover_one_step_below_soc_lower_deadband",
            "recover_one_step_storage_island",
        }
        else "decrease"
        if renewable_control_action in {
            "curtail_one_step_full_soc",
            "curtail_one_step_storage_island_full_soc",
            "curtail_one_step_storage_island_no_charge_capacity",
            "curtail_one_step_above_soc_upper_deadband",
            "curtail_one_step_charge_derating",
            "curtail_one_step_low_diesel_charging",
            "curtail_charge_safety",
        }
        else "hold"
    )
    renewable_step_scale = (
        1.0
        if renewable_control_action in {
            "recover_one_step_below_soc_lower_deadband",
            "curtail_one_step_above_soc_upper_deadband",
            "curtail_one_step_storage_island_full_soc",
            "curtail_one_step_storage_island_no_charge_capacity",
        }
        else renewable_recovery_step_scale
        if renewable_control_action in {"recover_one_step", "recover_one_step_storage_island"}
        else renewable_curtail_step_scale
        if renewable_control_action == "curtail_one_step_full_soc"
        else renewable_derating_curtail_step_scale
        if renewable_control_action == "curtail_one_step_charge_derating"
        else renewable_diesel_guard_curtail_scale
        if renewable_control_action == "curtail_one_step_low_diesel_charging"
        else (
            renewable_charge_safety_curtail_delivered_kw
            / renewable_curtail_capacity_step_kw
        )
        if renewable_control_action == "curtail_charge_safety"
        and renewable_curtail_capacity_step_kw > EPSILON
        else 0.0
    )
    renewable_effective_step_ratio = settings.step_coefficient * renewable_step_scale
    renewable_target_by_device: Dict[Tuple[str, str], Optional[float]] = {}
    for row in online_renewable:
        key = (row["dev_type"], row["dev_name"])
        if row.get("planningCurrentKw") is None:
            renewable_target_by_device[key] = None
            continue
        current_kw = _finite_number(row.get("planningCurrentKw"))
        capacity_kw = max(0.0, _finite_number(row.get("capacityKw")))
        step_kw = renewable_effective_step_ratio * capacity_kw
        if not row.get("commandable"):
            renewable_target_by_device[key] = current_kw
            continue
        elif renewable_control_action == "curtail_charge_safety":
            target_kw = max(
                0.0,
                current_kw - renewable_charge_safety_by_device.get(key, 0.0),
            )
        elif renewable_control_action in {
            "curtail_one_step_above_soc_upper_deadband",
            "curtail_one_step_storage_island_full_soc",
            "curtail_one_step_storage_island_no_charge_capacity",
        }:
            target_kw = max(0.0, current_kw - step_kw)
        elif renewable_control_action == "curtail_one_step_full_soc":
            target_kw = max(
                0.0,
                current_kw
                - renewable_curtail_base_steps.get(key, 0.0) * renewable_curtail_step_scale,
            )
        elif renewable_control_action == "curtail_one_step_charge_derating":
            target_kw = max(
                0.0,
                current_kw
                - renewable_curtail_base_steps.get(key, 0.0)
                * renewable_derating_curtail_step_scale,
            )
        elif renewable_control_action == "curtail_one_step_low_diesel_charging":
            target_kw = max(
                0.0,
                current_kw
                - renewable_curtail_base_steps.get(key, 0.0)
                * renewable_diesel_guard_curtail_scale,
            )
        elif renewable_control_action in {
            "recover_one_step",
            "recover_one_step_below_soc_lower_deadband",
            "recover_one_step_storage_island",
        }:
            target_kw = min(capacity_kw, current_kw + step_kw)
        else:
            target_kw = current_kw
        renewable_target_by_device[key] = _clamp(target_kw, 0.0, capacity_kw) if capacity_kw > EPSILON else 0.0

    # Preserve the first-stage diesel/SOC decision as a hard renewable upper
    # bound for every later topology repair and optimization pass.
    if renewable_raise_blocked_by_diesel_guard:
        for row in online_renewable:
            key = (row["dev_type"], row["dev_name"])
            current_kw = _number(row.get("planningCurrentKw"))
            target_kw = _number(renewable_target_by_device.get(key))
            if current_kw is None:
                continue
            row["dispatchUpperKw"] = min(
                current_kw,
                target_kw if target_kw is not None else current_kw,
            )
            row["dispatchUpperReason"] = (
                "diesel_guard_storage_charging_curtailment"
                if renewable_curtailment_required_by_charging
                else "diesel_guard_no_renewable_recovery"
            )

    island_component_plans: List[Dict[str, Any]] = []
    island_control_action_by_component: Dict[Tuple[str, str], str] = {}
    island_control_action_by_resource: Dict[Tuple[str, str], str] = {}
    island_control_action_by_converter: Dict[Tuple[str, str], str] = {}
    secondary_island_converter_rows: List[Mapping[str, Any]] = []
    if primary_island_component is not None:
        primary_plan = _plan_renewable_storage_island_component(
            primary_island_component,
            settings,
        )
        primary_targets = {
            (str(row.get("dev_type", "")), str(row.get("dev_name", ""))): renewable_target_by_device.get(
                (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
            )
            for row in primary_island_component.renewable_rows
        }
        primary_plan["action"] = renewable_control_action
        primary_plan["renewableTargets"] = primary_targets
        primary_plan["renewableTargetKw"] = sum(
            _finite_number(target) for target in primary_targets.values()
        )
        island_component_plans.append(primary_plan)

        for component in island_components:
            component_key = (
                component.grid_component_id,
                component.dc_transfer_group_id,
            )
            component_plan = (
                primary_plan
                if component is primary_island_component
                else _plan_renewable_storage_island_component(component, settings)
            )
            action = str(component_plan["action"])
            island_control_action_by_component[component_key] = action
            for row in component.renewable_rows:
                resource_key = (
                    str(row.get("dev_type", "")),
                    str(row.get("dev_name", "")),
                )
                island_control_action_by_resource[resource_key] = action
            for row in component.converter_rows:
                converter_key = (
                    str(row.get("dev_type", "")),
                    str(row.get("dev_name", "")),
                )
                island_control_action_by_converter[converter_key] = action

            if component is primary_island_component:
                continue
            renewable_target_by_device.update(component_plan["renewableTargets"])
            island_component_plans.append(component_plan)
            secondary_island_converter_rows.extend(component.converter_rows)

    renewable_target = sum(_finite_number(value) for value in renewable_target_by_device.values())
    renewable_delta = renewable_target - renewable_current
    storage_delta = storage_target - storage_current_for_control

    base_converter_direction = (
        1.0 if converter_target > 0 else -1.0 if converter_target < 0 else 0.0
    )
    base_converter_allocations = [
        value * base_converter_direction
        for value in _allocate_converters(converter_rows, abs(converter_target))
    ]
    converter_target = sum(base_converter_allocations) if converter_rows else 0.0
    base_converter_targets: Dict[Tuple[str, str], float] = {
        (str(row.get("dev_type", "")), str(row.get("dev_name", ""))): allocation_kw
        for row, allocation_kw in zip(converter_rows, base_converter_allocations)
    }
    for row in secondary_island_converter_rows:
        base_converter_targets[
            (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
        ] = 0.0
    for row in held_converter_rows:
        current_kw = _number(row.get("currentKw"))
        base_converter_targets[
            (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
        ] = (
            _clamp_converter_target_kw(row, current_kw)
            if current_kw is not None
            else 0.0
        )
    for row in all_converter_rows:
        key = (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
        current_kw = _number(row.get("currentKw"))
        base_converter_targets.setdefault(
            key,
            _clamp_converter_target_kw(row, current_kw)
            if current_kw is not None
            else 0.0,
        )
    base_converter_effect_kw = sum(
        _converter_ac_injection_delta_kw(
            row,
            current_kw,
            base_converter_targets.get(
                (str(row.get("dev_type", "")), str(row.get("dev_name", ""))),
                current_kw,
            ),
        )
        for row in all_converter_rows
        if (current_kw := _number(row.get("currentKw"))) is not None
    )

    direct_storage_plan = _plan_direct_grid_storage_dispatch(
        storage_rows,
        all_converter_rows,
        base_converter_targets,
        settings,
        diesel_current_kw=diesel_current_for_control,
        diesel_min_kw=diesel_min,
        diesel_deadband_upper_kw=diesel_deadband_upper_kw,
        balance_effect_kw=base_converter_effect_kw,
        enabled=bool(online_diesel) and not renewable_storage_island,
    )
    direct_storage_states = direct_storage_plan["storageStates"]
    direct_storage_targets = direct_storage_plan["storageTargets"]
    final_converter_targets = {
        **base_converter_targets,
        **direct_storage_plan["converterTargets"],
    }
    pre_side_aware_converter_targets = dict(final_converter_targets)
    side_aware_plan: Optional[Dict[str, Any]] = None
    side_aware_ac_actor = any(
        row.get("commandable")
        and row.get("connectionSide") == "AC"
        and row.get("role") != "balance"
        for row in (*renewable_rows, *storage_rows)
    )
    side_aware_dc_actor_groups = {
        str(row.get("dcTransferGroupId", ""))
        for row in (*renewable_rows, *storage_rows)
        if row.get("commandable")
        and row.get("connectionSide") == "DC"
        and row.get("role") != "balance"
        and str(row.get("dcTransferGroupId", ""))
    }
    side_aware_balance_protection = any(
        row.get("stateEligible")
        and row.get("role") == "balance"
        and _number(row.get("currentKw")) is not None
        and (
            _finite_number(row.get("currentKw"))
            < _grid_storage_signed_power_bounds_kw(row)[0] - EPSILON
            or _finite_number(row.get("currentKw"))
            > _grid_storage_signed_power_bounds_kw(row)[1] + EPSILON
        )
        for row in storage_rows
    )
    side_aware_balance_recovery = any(
        row.get("stateEligible")
        and row.get("role") == "balance"
        and (
            row.get("connectionSide") == "AC"
            and side_aware_ac_actor
            and any(
                renewable.get("commandable")
                and renewable.get("connectionSide") == "AC"
                and _finite_number(renewable.get("headroomKw")) > EPSILON
                for renewable in renewable_rows
            )
            or row.get("connectionSide") == "DC"
            and str(row.get("dcTransferGroupId", ""))
            in side_aware_dc_actor_groups
            and any(
                renewable.get("commandable")
                and renewable.get("connectionSide") == "DC"
                and renewable.get("dcTransferGroupId")
                == row.get("dcTransferGroupId")
                and _finite_number(renewable.get("headroomKw")) > EPSILON
                for renewable in renewable_rows
            )
        )
        for row in storage_rows
    )
    if online_diesel and not renewable_storage_island and (
        side_aware_balance_protection
        or side_aware_balance_recovery
        or not any(
            row.get("stateEligible") and row.get("role") == "balance"
            for row in storage_rows
        )
    ):
        side_aware_plan = _side_aware_renewable_recovery_plan(
            snapshot,
            measurements,
            settings,
            resource_topology,
            renewable_rows,
            storage_rows,
            converter_validation_rows,
            direct_storage_targets,
            final_converter_targets,
            renewable_target_by_device,
            renewable_control_action == "hold_unknown_soc",
            diesel_current_kw=diesel_current_for_control,
            diesel_min_kw=diesel_min,
            diesel_deadband_upper_kw=diesel_deadband_upper_kw,
        )
        renewable_target_by_device = side_aware_plan["renewableTargets"]
        renewable_target = sum(
            _finite_number(value) for value in renewable_target_by_device.values()
        )
        renewable_delta = renewable_target - renewable_current
        direct_storage_targets = side_aware_plan["storageTargets"]
        direct_storage_states = side_aware_plan["storageStates"]
        final_converter_targets = side_aware_plan["converterTargets"]
        balance_rows_by_dc_group: Dict[str, List[Mapping[str, Any]]] = {}
        for balance_row in storage_rows:
            if (
                balance_row.get("role") != "balance"
                or balance_row.get("connectionSide") != "DC"
            ):
                continue
            group_id = str(balance_row.get("dcTransferGroupId", ""))
            if group_id:
                balance_rows_by_dc_group.setdefault(group_id, []).append(balance_row)
        for converter_row in all_converter_rows:
            key = (
                str(converter_row.get("dev_type", "")),
                str(converter_row.get("dev_name", "")),
            )
            initial_target_kw = _number(pre_side_aware_converter_targets.get(key))
            side_target_kw = _number(final_converter_targets.get(key))
            if initial_target_kw is None or side_target_kw is None:
                continue
            group_rows = balance_rows_by_dc_group.get(
                str(converter_row.get("dcTransferGroupId", "")),
                [],
            )
            reduce_export_required = any(
                _number(row.get("currentKw")) is not None
                and _finite_number(row.get("currentKw"))
                > _grid_storage_signed_power_bounds_kw(row)[1] + EPSILON
                for row in group_rows
            )
            increase_export_required = any(
                _number(row.get("currentKw")) is not None
                and _finite_number(row.get("currentKw"))
                < _grid_storage_signed_power_bounds_kw(row)[0] - EPSILON
                for row in group_rows
            )
            if reduce_export_required and not increase_export_required:
                final_converter_targets[key] = max(
                    initial_target_kw,
                    side_target_kw,
                )
    projected_balance_targets = (
        side_aware_plan.get("projectedBalanceTargets", {})
        if side_aware_plan is not None
        else {}
    )
    _ac_load_for_dispatch_validation, dc_load_for_dispatch_validation = (
        _active_load_budgets(
            snapshot,
            measurements,
            resource_topology.dc_transfer_groups,
        )
    )
    direct_grid_forming_plan = _plan_direct_grid_forming_dispatch(
        renewable_rows,
        storage_rows,
        all_converter_rows,
        renewable_target_by_device,
        direct_storage_targets,
        final_converter_targets,
        projected_balance_targets,
        settings,
        diesel_current_kw=diesel_current_for_control,
        diesel_min_kw=diesel_min,
        diesel_deadband_upper_kw=diesel_deadband_upper_kw,
        enabled=bool(online_diesel or renewable_storage_island),
        dc_load_kw=dc_load_for_dispatch_validation,
    )
    renewable_target_by_device = direct_grid_forming_plan["renewableTargets"]
    renewable_target = sum(
        _finite_number(value) for value in renewable_target_by_device.values()
    )
    renewable_delta = renewable_target - renewable_current
    direct_storage_targets = direct_grid_forming_plan["gridStorageTargets"]
    for key, state in direct_storage_states.items():
        state["targetKw"] = direct_storage_targets.get(
            key,
            state.get("targetKw", state.get("currentKw")),
        )
    projected_balance_targets = direct_grid_forming_plan["balanceTargets"]
    projected_balance_targets = _clamp_direct_balance_targets_to_soc_bounds(
        storage_rows,
        projected_balance_targets,
    )
    direct_grid_forming_states = direct_grid_forming_plan["balanceStates"]
    final_converter_targets = direct_grid_forming_plan["converterTargets"]
    component_dispatch_plan = _validate_dispatch_by_ac_component(
        resource_topology,
        diesel_rows,
        renewable_rows,
        storage_rows,
        converter_validation_rows,
        renewable_target_by_device,
        direct_storage_targets,
        projected_balance_targets,
        final_converter_targets,
        settings,
        dc_load_kw=dc_load_for_dispatch_validation,
    )
    renewable_target_by_device = component_dispatch_plan["renewableTargets"]
    direct_storage_targets = component_dispatch_plan["gridStorageTargets"]
    projected_balance_targets = component_dispatch_plan["balanceTargets"]
    final_converter_targets = component_dispatch_plan["converterTargets"]
    projected_balance_targets, final_converter_targets, dc_projection_groups = (
        _rebalance_dc_projection_targets(
            resource_topology,
            renewable_rows,
            storage_rows,
            converter_validation_rows,
            renewable_target_by_device,
            direct_storage_targets,
            projected_balance_targets,
            final_converter_targets,
            dc_load_kw=dc_load_for_dispatch_validation,
        )
    )
    component_dispatch_plan["balanceTargets"] = projected_balance_targets
    component_dispatch_plan["dcGroups"] = dc_projection_groups

    # A DC-group repair may restore an ACDC target that AC-component
    # validation had temporarily rolled back. Refresh the AC-component
    # prediction from the targets that will actually be published; otherwise
    # diesel metrics and diesel commands can describe the pre-repair target.
    original_converter_targets = component_dispatch_plan.get(
        "converterTargets", {}
    )
    converter_target_changed = any(
        abs(
            _finite_number(final_converter_targets.get(key))
            - _finite_number(original_converter_targets.get(key))
        )
        > EPSILON
        for key in set(final_converter_targets) | set(original_converter_targets)
    )
    if converter_target_changed:
        refreshed_component_dispatch = _validate_dispatch_by_ac_component(
            resource_topology,
            diesel_rows,
            renewable_rows,
            storage_rows,
            converter_validation_rows,
            renewable_target_by_device,
            direct_storage_targets,
            projected_balance_targets,
            final_converter_targets,
            settings,
            dc_load_kw=dc_load_for_dispatch_validation,
        )
        component_dispatch_plan = refreshed_component_dispatch
        renewable_target_by_device = refreshed_component_dispatch["renewableTargets"]
        direct_storage_targets = refreshed_component_dispatch["gridStorageTargets"]
        projected_balance_targets = refreshed_component_dispatch["balanceTargets"]
        final_converter_targets = refreshed_component_dispatch["converterTargets"]
        component_dispatch_plan["dcGroups"] = dc_projection_groups

    ac_to_dc_absorption_plan = _apply_ac_to_dc_renewable_absorption(
        resource_topology,
        renewable_rows,
        storage_rows,
        all_converter_rows,
        renewable_target_by_device,
        direct_storage_targets,
        final_converter_targets,
        settings,
    )
    renewable_target_by_device = ac_to_dc_absorption_plan["renewableTargets"]
    direct_storage_targets = ac_to_dc_absorption_plan["storageTargets"]
    final_converter_targets = ac_to_dc_absorption_plan["converterTargets"]
    renewable_target = sum(
        _finite_number(value) for value in renewable_target_by_device.values()
    )
    renewable_delta = renewable_target - renewable_current
    for key, state in direct_storage_states.items():
        state["targetKw"] = direct_storage_targets.get(
            key,
            state.get("targetKw", state.get("currentKw")),
        )
    for key, state in direct_grid_forming_states.items():
        state["targetKw"] = projected_balance_targets.get(
            key,
            state.get("targetKw", state.get("currentKw")),
        )
    direct_grid_forming_plan["dieselEffectKw"] = component_dispatch_plan[
        "dieselEffectKw"
    ]
    direct_grid_forming_plan["dieselTargetKw"] = component_dispatch_plan[
        "dieselTargetKw"
    ]
    direct_grid_forming_plan["balanceTargets"] = projected_balance_targets
    direct_grid_forming_plan["dcGroups"] = component_dispatch_plan["dcGroups"]
    direct_converter_groups = {
        str(row.get("dcTransferGroupId", ""))
        for row in all_converter_rows
        if row.get("commandable")
        and str(row.get("dcTransferGroupId", ""))
        and _number(row.get("currentKw")) is not None
        and (_number(row.get("transferCapacityKw")) or 0.0) > EPSILON
    }
    for state in direct_storage_states.values():
        direct_dispatch_eligible = bool(
            state.get("eligible")
            and (
                state.get("side") == "AC"
                or state.get("side") == "DC"
                and state.get("groupId") in direct_converter_groups
            )
        )
        state["directDispatchEligible"] = direct_dispatch_eligible
        if (
            state.get("side") == "DC"
            and state.get("eligible")
            and not direct_dispatch_eligible
        ):
            row = state["row"]
            quality.add(
                f"直流跟网储能{row.get('dev_name', '')}缺少本传输组有效ACDC容量，"
                "本轮仅禁用该储能直接调节"
            )

    direct_ac_storage_effect_kw = _finite_number(
        direct_storage_plan.get("acEffectKw")
    )
    direct_acdc_effect_kw = _finite_number(
        direct_storage_plan.get("acdcEffectKw")
    )
    if side_aware_plan is not None:
        direct_ac_storage_effect_kw = sum(
            _finite_number(target_kw)
            - _finite_number(
                next(
                    row.get("currentKw")
                    for row in storage_rows
                    if (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
                    == key
                )
            )
            for key, target_kw in direct_storage_targets.items()
            if next(
                row.get("connectionSide")
                for row in storage_rows
                if (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
                == key
            )
            == "AC"
        )
        direct_acdc_effect_kw = sum(
            _finite_number(row.get("currentKw"))
            - _finite_number(
                final_converter_targets.get(
                    (str(row.get("dev_type", "")), str(row.get("dev_name", ""))),
                    row.get("currentKw"),
                )
            )
            for row in all_converter_rows
            if row.get("currentKw") is not None
        )
    if renewable_storage_island:
        current_diesel_violation = 0.0
        candidate_effect = 0.0
        predicted_diesel = 0.0
        diesel_target = 0.0
        diesel_residual = 0.0
        diesel_boundary_error = 0.0
        predicted_diesel_violation = 0.0
        diesel_violation_improved = True
        diesel_validation_status = "not_applicable"
    else:
        current_diesel_violation = _diesel_boundary_violation(
            diesel_current_for_control,
            diesel_min,
            diesel_capacity,
        )
        candidate_effect = _finite_number(
            direct_grid_forming_plan.get("dieselEffectKw")
        )
        predicted_diesel = diesel_current_for_control - candidate_effect
        diesel_target = _finite_number(
            direct_grid_forming_plan.get("dieselTargetKw"),
            predicted_diesel,
        )
        diesel_residual = diesel_target
        diesel_boundary_error = diesel_target - diesel_min
        predicted_diesel_violation = _diesel_boundary_violation(diesel_target, diesel_min, diesel_capacity)
        diesel_violation_improved = (
            predicted_diesel_violation + 0.001 < current_diesel_violation
            if current_diesel_violation > 0.001
            else predicted_diesel_violation <= 0.001
        )
        if predicted_diesel_violation <= 0.001:
            diesel_validation_status = "within_bounds"
        elif current_diesel_violation > 0.001 and diesel_violation_improved:
            diesel_validation_status = "improved"
        else:
            diesel_validation_status = "feedback_pending"
    unserved_kw = 0.0
    surplus_kw = 0.0

    storage_allocations = (
        [-value for value in _allocate(online_storage, -storage_target, "chargePower")]
        if storage_target < 0
        else _allocate(online_storage, storage_target, "dischargePower")
    )
    storage_by_key = {
        (row["dev_type"], row["dev_name"]): storage_allocations[index]
        for index, row in enumerate(online_storage)
    }

    diesel_dispatch = [{**row, "headroomKw": max(0.0, row["capacityKw"] - row["minKw"])} for row in online_diesel]
    diesel_additional = max(0.0, diesel_target - diesel_min)
    diesel_headroom = sum(row["headroomKw"] for row in diesel_dispatch)
    diesel_additional_allocations = (
        _allocate(diesel_dispatch, diesel_additional, "headroomKw")
        if diesel_headroom > 0
        else [diesel_additional / max(1, len(diesel_dispatch)) for _ in diesel_dispatch]
    )
    fallback_diesel_by_name = {
        row["dev_name"]: row["minKw"] + diesel_additional_allocations[index]
        for index, row in enumerate(diesel_dispatch)
    }
    diesel_by_name = {
        **fallback_diesel_by_name,
        **component_dispatch_plan.get("dieselTargets", {}),
    }

    converter_allocations = [
        _clamp_converter_target_kw(
            row,
            final_converter_targets.get(
                (str(row.get("dev_type", "")), str(row.get("dev_name", ""))),
                base_converter_allocations[index],
            ),
        )
        for index, row in enumerate(converter_rows)
    ]

    active_dc_transfer_group_ids = _active_dc_transfer_group_ids(
        resource_topology,
        (*renewable_rows, *storage_rows, *all_converter_rows),
    )

    command_rows: List[Dict[str, Any]] = []
    for row in renewable_rows:
        key = (row["dev_type"], row["dev_name"])
        dc_group_command_safe = (
            row.get("connectionSide") != "DC"
            or str(row.get("dcTransferGroupId", "")) in active_dc_transfer_group_ids
        )
        strategy_command = (
            row["commandable"] and row["capabilityKnown"]
            if row["environmentKnown"]
            else row["commandable"] and row.get("planningCurrentKw") is not None and _finite_number(row.get("capacityKw")) > 0
        )
        strategy_command = bool(strategy_command and dc_group_command_safe)
        command_rows.append(
            {
                **row,
                "islandControlAction": island_control_action_by_resource.get(key, ""),
                "recoveryKw": max(
                    0.0,
                    _finite_number(renewable_target_by_device.get(key)) - _finite_number(row.get("currentKw")),
                ),
                "strategyCommand": strategy_command,
                "commandKw": (
                    renewable_target_by_device.get(key)
                    if row.get("online") and key in renewable_target_by_device
                    else _finite_number(row.get("planningCurrentKw"))
                    if row.get("online") and row.get("planningCurrentKw") is not None
                    else None
                    if row.get("online")
                    else 0.0
                ),
            }
        )
    for row in storage_rows:
        key = (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
        current_kw = _number(row.get("currentKw"))
        is_grid_following = row.get("role") == "grid_following"
        is_grid_forming = row.get("role") == "balance"
        direct_state = (
            direct_storage_states.get(key, {})
            if is_grid_following
            else direct_grid_forming_states.get(key, {})
        )
        dc_group_command_safe = (
            row.get("connectionSide") != "DC"
            or str(row.get("dcTransferGroupId", "")) in active_dc_transfer_group_ids
        )
        direct_target_kw = (
            direct_storage_targets.get(key, current_kw)
            if is_grid_following
            else None
        )
        projected_target_kw = (
            projected_balance_targets.get(
                key,
                storage_by_key.get(
                    key,
                    current_kw if row.get("deviceOnline") else 0.0,
                ),
            )
            if is_grid_forming
            else None
        )
        direct_changed = bool(
            is_grid_following
            and row.get("commandable")
            and dc_group_command_safe
            and direct_state.get("directDispatchEligible")
            and current_kw is not None
            and direct_target_kw is not None
            and abs(_finite_number(direct_target_kw) - current_kw) > EPSILON
        )
        grid_forming_dispatch = bool(
            is_grid_forming
            and row.get("commandable")
            and dc_group_command_safe
            and direct_state.get("directDispatchEligible")
            and current_kw is not None
            and projected_target_kw is not None
        )
        command_kw = (
            direct_target_kw
            if is_grid_following
            else projected_target_kw
        )
        command_rows.append(
            {
                **row,
                "indirectControlDevices": (
                    side_aware_plan.get("indirectControlDevices", {}).get(
                        key,
                        row.get("indirectControlDevices", []),
                    )
                    if side_aware_plan is not None
                    else row.get("indirectControlDevices", [])
                ),
                "commandable": bool(
                    row.get("commandable")
                    and dc_group_command_safe
                    and (
                        (not is_grid_following and not is_grid_forming)
                        or direct_state.get("directDispatchEligible")
                    )
                ),
                "islandControlAction": island_control_action_by_component.get(
                    (
                        str(row.get("gridComponentId", "")),
                        str(row.get("dcTransferGroupId", "")),
                    ),
                    "",
                ),
                "planningCurrentKw": current_kw,
                "targetKw": (
                    direct_target_kw
                    if is_grid_following
                    else projected_target_kw
                ),
                "projectedTargetKw": projected_target_kw,
                "signedMinTargetKw": direct_state.get(
                    "signedMinTargetKw",
                    -max(0.0, _finite_number(row.get("chargePower"))),
                ),
                "signedMaxTargetKw": direct_state.get(
                    "signedMaxTargetKw",
                    max(0.0, _finite_number(row.get("dischargePower"))),
                ),
                "chargeMarginKw": _finite_number(
                    direct_state.get("chargeMarginKw")
                ),
                "dischargeMarginKw": _finite_number(
                    direct_state.get("dischargeMarginKw")
                ),
                "gridStorageStepKw": _finite_number(
                    direct_state.get("stepKw")
                ),
                "gridStorageStepScale": _finite_number(
                    direct_state.get("stepScale"),
                    1.0,
                ),
                "directDispatchEligible": bool(
                    direct_state.get("directDispatchEligible")
                ),
                "strategyCommand": direct_changed or grid_forming_dispatch,
                "availableKw": (
                    max(
                        _finite_number(row.get("chargePower")),
                        _finite_number(row.get("dischargePower")),
                    )
                    if row["online"]
                    else 0.0
                ),
                "commandKw": command_kw,
            }
        )
    command_rows.extend(
        {
            **row,
            "commandable": bool(
                row.get("commandable") and not renewable_storage_island
            ),
            "strategyCommand": bool(
                row.get("commandable") and not renewable_storage_island
            ),
            "availableKw": row["capacityKw"],
            "commandKw": diesel_by_name.get(row["dev_name"], row["minKw"]) if row["online"] else 0.0,
        }
        for row in diesel_rows
    )
    command_rows.extend(
        {
            **row,
            "islandControlAction": island_control_action_by_converter.get(
                (str(row.get("dev_type", "")), str(row.get("dev_name", ""))),
                "",
            ),
            "ratedAvailableKw": row["transferCapacityKw"]
            if row["transferCapacityKw"] > 0
            else max(total_charge, total_discharge) / max(1, len(converter_rows)),
            "availableKw": row["transferCapacityKw"]
            if row["transferCapacityKw"] > 0
            else max(total_charge, total_discharge) / max(1, len(converter_rows)),
            "strategyCommand": str(row.get("dcTransferGroupId", ""))
            in active_dc_transfer_group_ids,
            "commandKw": converter_allocations[index],
        }
        for index, row in enumerate(converter_rows)
    )
    command_rows.extend(
        {
            **row,
            "islandControlAction": island_control_action_by_converter.get(
                (str(row.get("dev_type", "")), str(row.get("dev_name", ""))),
                "",
            ),
            "ratedAvailableKw": row["transferCapacityKw"],
            "availableKw": row["transferCapacityKw"],
            "strategyCommand": str(row.get("dcTransferGroupId", ""))
            in active_dc_transfer_group_ids,
            "commandKw": 0.0,
            "statusLabel": f"{row.get('statusLabel', '')}·新能源储能孤岛归零",
        }
        for row in secondary_island_converter_rows
    )
    for row in held_converter_rows:
        current_kw = _number(row.get("currentKw"))
        key = (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
        final_target_kw = _clamp_converter_target_kw(
            row,
            final_converter_targets.get(
                key,
                current_kw,
            ),
        )
        direct_changed = bool(
            current_kw is not None
            and abs(final_target_kw - current_kw) > EPSILON
        )
        dc_group_command_safe = (
            str(row.get("dcTransferGroupId", "")) in active_dc_transfer_group_ids
        )
        command_rows.append(
            {
                **row,
                "ratedAvailableKw": row["transferCapacityKw"],
                "availableKw": row["transferCapacityKw"],
                "strategyCommand": dc_group_command_safe
                and direct_changed,
                "commandKw": final_target_kw,
                "statusLabel": (
                    f"{row.get('statusLabel', '')}·直控储能同组配对"
                    if direct_changed
                    else f"{row.get('statusLabel', '')}·分组隔离保持"
                ),
            }
        )
    command_rows.extend(
        {
            **row,
            "ratedAvailableKw": row["transferCapacityKw"],
            "availableKw": row["transferCapacityKw"],
            "strategyCommand": False,
            "commandKw": row.get("currentKw") if row.get("online") else 0.0,
        }
        for row in diagnostic_converter_rows
    )

    blocked_optimization_component_ids = _blocked_optimization_component_ids(
        resource_topology,
        fail_closed_scopes,
        renewable_rows,
        storage_rows,
        diesel_rows,
        converter_inventory_rows,
        quality,
    )
    optimization_started = time.perf_counter()
    strategy_preparation_seconds = optimization_started - topology_finished
    optimization_result = optimize_topology_islands(
        resource_topology,
        renewable_rows=renewable_rows,
        diesel_rows=diesel_rows,
        storage_rows=storage_rows,
        converter_rows=all_converter_rows,
        step_coefficient=settings.step_coefficient,
        converter_step_ratio=settings.converter_step_ratio,
        storage_step_ratio=settings.storage_step_ratio,
        storage_soc_correction_step_scale=(
            settings.storage_soc_correction_step_scale
        ),
        diesel_power_protection_ratio=(
            settings.diesel_power_protection_ratio
        ),
        grid_forming_storage_protection_ratio=(
            settings.grid_forming_storage_protection_ratio
        ),
        soc_deadband=settings.soc_deadband,
        renewable_curtailment_weight=(
            settings.optimization_renewable_curtailment_weight
        ),
        diesel_output_weight=settings.optimization_diesel_output_weight,
        curtailment_square_weight=(
            settings.optimization_curtailment_square_weight
        ),
        source_storage_adjustment_square_weight=(
            settings.optimization_source_storage_adjustment_square_weight
        ),
        balance_delta_square_weight=(
            settings.optimization_balance_delta_square_weight
        ),
        balance_delta_warning_kw=(
            settings.optimization_balance_delta_warning_kw
        ),
        balance_tolerance_kw=settings.optimization_balance_tolerance_kw,
        bound_tolerance_kw=settings.optimization_bound_tolerance_kw,
        optimization_ftol=settings.optimization_ftol,
        optimization_max_iterations=settings.optimization_max_iterations,
        blocked_component_ids=blocked_optimization_component_ids,
    )
    optimization_finished = time.perf_counter()
    optimization_total_seconds = optimization_finished - optimization_started
    # The optimizer owns the final per-device targets. Its variable bounds
    # already combine topology eligibility, physical limits, SOC segmented
    # limits, one-cycle maximum deltas, deadband guards and SOC emergency
    # correction. A failed or unassigned device is held at its live value.
    _apply_optimization_targets(
        command_rows,
        optimization_result,
        apply_targets=True,
    )

    # With the AC side fully retired, the island state machine is the only
    # source of a renewable ramp command. The steady-state optimizer preserves
    # the live island balance, so it would otherwise undo that one-step
    # curtail/recovery preview by returning both renewable and balance storage
    # to their live values. Reapply the state-machine target and its balancing
    # storage projection after optimization.
    if renewable_storage_island:
        island_plan_by_resource = {
            resource_key: component_plan
            for component_plan in island_component_plans
            for resource_key in component_plan.get("renewableTargets", {})
        }
        for row in command_rows:
            key = (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
            component_plan = island_plan_by_resource.get(key)
            if component_plan is None:
                continue
            target = _number(component_plan.get("renewableTargets", {}).get(key))
            current = _number(row.get("planningCurrentKw", row.get("currentKw")))
            if target is None:
                continue
            row["commandKw"] = target
            row["targetKw"] = target
            row["optimizationSuggestedKw"] = target
            row["strategyTargetChanged"] = bool(
                row.get("online")
                and row.get("commandable")
                and row.get("set_type")
                and current is not None
                and abs(target - current) > EPSILON
            )
            row["strategyCommand"] = bool(
                row.get("online")
                and row.get("commandable")
                and row.get("set_type")
                and current is not None
            )
        for component_plan in island_component_plans:
            component_key = (
                str(component_plan.get("gridComponentId", "")),
                str(component_plan.get("dcTransferGroupId", "")),
            )
            renewable_delta_kw = sum(
                _finite_number(target)
                - _finite_number(
                    next(
                        (
                            row.get("planningCurrentKw", row.get("currentKw"))
                            for row in command_rows
                            if (
                                str(row.get("dev_type", "")),
                                str(row.get("dev_name", "")),
                            )
                            == resource_key
                        ),
                        0.0,
                    )
                )
                for resource_key, target in component_plan.get(
                    "renewableTargets", {}
                ).items()
            )
            balance_rows = [
                row
                for row in command_rows
                if row.get("technology") == "storage"
                and row.get("role") == "balance"
                and (
                    str(row.get("gridComponentId", "")),
                    str(row.get("dcTransferGroupId", "")),
                )
                == component_key
            ]
            if not balance_rows or abs(renewable_delta_kw) <= EPSILON:
                continue
            total_capacity = sum(
                max(
                    EPSILON,
                    _finite_number(row.get("maxChargePowerKw")),
                    _finite_number(row.get("maxDischargePowerKw")),
                )
                for row in balance_rows
            )
            for row in balance_rows:
                current = _finite_number(row.get("currentKw"))
                capacity = max(
                    EPSILON,
                    _finite_number(row.get("maxChargePowerKw")),
                    _finite_number(row.get("maxDischargePowerKw")),
                )
                target = current - renewable_delta_kw * capacity / total_capacity
                lower = _number(row.get("signedMinTargetKw"))
                upper = _number(row.get("signedMaxTargetKw"))
                if lower is not None and upper is not None:
                    target = _clamp(target, lower, upper)
                row["commandKw"] = target
                row["targetKw"] = target
                row["projectedTargetKw"] = target
                row["optimizationSuggestedKw"] = target

    renewable_target_by_device = {
        (str(row.get("dev_type", "")), str(row.get("dev_name", ""))): float(row["commandKw"])
        for row in command_rows
        if row.get("technology") in {"wind", "pv"}
        and row.get("online")
        and _number(row.get("commandKw")) is not None
    }
    direct_storage_targets = {
        (str(row.get("dev_type", "")), str(row.get("dev_name", ""))): float(row["commandKw"])
        for row in command_rows
        if row.get("technology") == "storage"
        and row.get("role") == "grid_following"
        and row.get("online")
        and _number(row.get("commandKw")) is not None
    }
    projected_balance_targets = {
        (str(row.get("dev_type", "")), str(row.get("dev_name", ""))): float(row["commandKw"])
        for row in command_rows
        if row.get("technology") == "storage"
        and row.get("role") == "balance"
        and row.get("online")
        and _number(row.get("commandKw")) is not None
    }
    final_converter_targets = {
        (str(row.get("dev_type", "")), str(row.get("dev_name", ""))): float(row["commandKw"])
        for row in command_rows
        if _is_grid_converter_row(row)
        and row.get("online")
        and _number(row.get("commandKw")) is not None
    }
    diesel_by_name = {
        str(row.get("dev_name", "")): float(row["commandKw"])
        for row in command_rows
        if row.get("category") == "柴油发电"
        and row.get("online")
        and _number(row.get("commandKw")) is not None
    }
    renewable_target = sum(renewable_target_by_device.values())
    renewable_delta = renewable_target - renewable_current
    storage_target = sum(
        float(row["commandKw"])
        for row in command_rows
        if row.get("technology") == "storage"
        and row.get("online")
        and _number(row.get("commandKw")) is not None
    )
    diesel_target = sum(diesel_by_name.values())
    predicted_diesel = diesel_target
    diesel_residual = diesel_target
    candidate_effect = (
        diesel_current_for_control - diesel_target if online_diesel else 0.0
    )
    diesel_boundary_error = diesel_target - diesel_min
    current_diesel_violation = (
        _diesel_boundary_violation(
            diesel_current_for_control,
            diesel_min,
            diesel_capacity,
        )
        if online_diesel
        else 0.0
    )
    predicted_diesel_violation = (
        _diesel_boundary_violation(diesel_target, diesel_min, diesel_capacity)
        if online_diesel
        else 0.0
    )
    diesel_violation_improved = (
        predicted_diesel_violation + 0.001 < current_diesel_violation
        if current_diesel_violation > 0.001
        else predicted_diesel_violation <= 0.001
    )
    diesel_validation_status = (
        "not_applicable"
        if not online_diesel
        else "within_bounds"
        if predicted_diesel_violation <= 0.001
        else "improved"
        if diesel_violation_improved
        else "feedback_pending"
    )
    aggregate_converter_values = [
        (row, current_kw, target_kw)
        for row in command_rows
        if _is_grid_converter_row(row)
        and row.get("online")
        and row.get("commandable") is not False
        and (
            not renewable_storage_island
            or row.get("strategyCommand") is not False
        )
        and row.get("set_type")
        and (current_kw := _number(row.get("currentKw"))) is not None
        and (target_kw := _number(row.get("commandKw"))) is not None
    ]
    aggregate_converter_current_kw = (
        sum(
            _finite_number(_converter_system_power_kw(row, current_kw))
            for row, current_kw, _target_kw in aggregate_converter_values
        )
        if aggregate_converter_values
        else None
    )
    aggregate_converter_target_kw = sum(
        _finite_number(_converter_system_power_kw(row, target_kw))
        for row, _current_kw, target_kw in aggregate_converter_values
    )
    aggregate_converter_lower_limit_kw = sum(
        -_converter_signed_bounds_kw(row)[1] for row in all_converter_rows
    )
    aggregate_converter_upper_limit_kw = sum(
        -_converter_signed_bounds_kw(row)[0] for row in all_converter_rows
    )
    aggregate_converter_capacity_kw = sum(
        max(abs(lower_kw), abs(upper_kw))
        for row in all_converter_rows
        for lower_kw, upper_kw in [_converter_signed_bounds_kw(row)]
    )

    storage_charge_derating_residual_kw = sum(
        max(
            0.0,
            _finite_number(row.get("signedMinTargetKw"))
            - _finite_number(_metric_target(row), row.get("currentKw")),
        )
        for row in command_rows
        if row.get("technology") == "storage"
        and row.get("online")
        and _metric_target(row) is not None
    )

    if renewable_control_action == "curtail_charge_safety":
        final_safety_curtail_kw = sum(
            max(
                0.0,
                _finite_number(row.get("planningCurrentKw", row.get("currentKw")))
                - _finite_number(
                    renewable_target_by_device.get(
                        (str(row.get("dev_type", "")), str(row.get("dev_name", ""))),
                        row.get("planningCurrentKw", row.get("currentKw")),
                    )
                ),
            )
            for row in online_renewable
            if _number(row.get("planningCurrentKw", row.get("currentKw")))
            is not None
        )
        renewable_charge_safety_curtail_delivered_kw = min(
            renewable_charge_safety_curtail_required_kw,
            final_safety_curtail_kw,
        )
        renewable_charge_safety_curtail_shortfall_kw = max(
            0.0,
            renewable_charge_safety_curtail_required_kw
            - renewable_charge_safety_curtail_delivered_kw,
        )
        renewable_step_scale = (
            renewable_charge_safety_curtail_delivered_kw
            / renewable_curtail_capacity_step_kw
            if renewable_curtail_capacity_step_kw > EPSILON
            else 0.0
        )
        renewable_effective_step_ratio = settings.step_coefficient * renewable_step_scale

    hydrogen_plan = _hydrogen_post_dispatch_plan(
        snapshot,
        measurements,
        settings,
        resource_topology,
        command_rows,
        storage_rows,
        diesel_current_kw=diesel_target,
        diesel_capacity_kw=sum(
            _finite_number(row.get("ratedCapacityKw")) for row in online_diesel
        ),
        diesel_unit_count=len(online_diesel),
        diesel_input_valid=bool(
            online_diesel
            and len(measured_diesel) == len(online_diesel)
        ),
        apply_electrical_corrections=settings.hydrogen_closed_loop_enabled,
    )
    diesel_by_name = {
        str(row.get("dev_name", "")): float(row["commandKw"])
        for row in command_rows
        if row.get("category") == "柴油发电"
        and row.get("online")
        and _number(row.get("commandKw")) is not None
    }
    diesel_target = sum(diesel_by_name.values())
    predicted_diesel = diesel_target
    diesel_residual = diesel_target
    candidate_effect = (
        diesel_current_for_control - diesel_target if online_diesel else 0.0
    )
    diesel_boundary_error = diesel_target - diesel_min
    predicted_diesel_violation = (
        _diesel_boundary_violation(diesel_target, diesel_min, diesel_capacity)
        if online_diesel
        else 0.0
    )
    diesel_violation_improved = (
        predicted_diesel_violation + 0.001 < current_diesel_violation
        if current_diesel_violation > 0.001
        else predicted_diesel_violation <= 0.001
    )
    diesel_validation_status = (
        "not_applicable"
        if not online_diesel
        else "within_bounds"
        if predicted_diesel_violation <= 0.001
        else "improved"
        if diesel_violation_improved
        else "feedback_pending"
    )
    final_converter_targets = {
        (str(row.get("dev_type", "")), str(row.get("dev_name", ""))): float(row["commandKw"])
        for row in command_rows
        if _is_grid_converter_row(row)
        and row.get("online")
        and _number(row.get("commandKw")) is not None
    }
    aggregate_converter_values = [
        (row, current_kw, target_kw)
        for row in command_rows
        if _is_grid_converter_row(row)
        and row.get("online")
        and row.get("commandable") is not False
        and row.get("set_type")
        and (current_kw := _number(row.get("currentKw"))) is not None
        and (target_kw := _number(row.get("commandKw"))) is not None
    ]
    aggregate_converter_target_kw = sum(
        _finite_number(_converter_system_power_kw(row, target_kw))
        for row, _current_kw, target_kw in aggregate_converter_values
    )
    converter_applied_step_kw = (
        abs(aggregate_converter_target_kw - aggregate_converter_current_kw)
        if aggregate_converter_current_kw is not None
        else 0.0
    )

    def dispatch_commands_from_rows(
        rows: Sequence[Mapping[str, Any]],
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        candidates = [
            {
                "dev_type": row["dev_type"],
                "dev_name": row["dev_name"],
                "set_type": row["set_type"],
                "set_value": _command_number(_dispatch_setpoint_value(row)),
            }
            for row in rows
            if row.get("online")
            and row.get("commandable") is not False
            and row.get("strategyCommand") is not False
            and row.get("dispatchEnabled") is not False
            and row.get("set_type")
            and isinstance(row.get("commandKw"), (int, float))
            and math.isfinite(float(row["commandKw"]))
        ]
        return _deduplicate_dispatch_commands(candidates)

    commands, duplicate_commands = dispatch_commands_from_rows(command_rows)
    if quality.blocked:
        commands = []

    warnings: List[str] = []
    warnings.extend(str(item) for item in hydrogen_plan.get("warnings", []))
    if any(
        row.get("technology") == "wind"
        and row.get("online")
        and not row.get("weatherAvailableKnown")
        for row in renewable_rows
    ):
        warnings.append(
            "风电理论可发统计缺少有效风速或设备风速参数；不影响本轮控制优化"
        )
    if any(
        row.get("technology") == "pv"
        and row.get("online")
        and not row.get("weatherAvailableKnown")
        for row in renewable_rows
    ):
        warnings.append(
            "光伏理论可发统计缺少有效辐照度或设备参考参数；不影响本轮控制优化"
        )
    warnings.extend(
        _optimization_balance_delta_warnings(optimization_result)
    )
    warnings.extend(
        f"优化岛{island.island_id}求解失败，岛内设备保持当前值：{island.message}"
        for island in optimization_result.islands
        if not island.success
    )
    if optimization_result.unassigned_devices:
        warnings.append(
            "部分在线可控设备缺少完整拓扑或边界，未纳入优化："
            + "、".join(
                f"{dev_type}.{dev_name}"
                for dev_type, dev_name in optimization_result.unassigned_devices
            )
        )
    # The pre-optimization renewable shortfall may be resolved by the unified
    # optimizer through storage or converter targets. Warn only when the final
    # SOC-derated storage target still remains outside its safe charging range.
    if storage_charge_derating_residual_kw > EPSILON:
        warnings.append(
            f"储能充电保护仍有 {storage_charge_derating_residual_kw:.2f} kW 未完成校正，已下发当前可实现的最大安全目标"
        )
    if any(row.get("conflict") for row in duplicate_commands):
        warnings.append("检测到同一遥调点存在多个候选值，已按最终校核结果去重")
    warnings.extend(issue for issue in quality.issues if issue not in warnings)

    wind_available = sum(
        max(0.0, _finite_number(row.get("capacityKw")))
        for row in renewable_rows
        if row.get("technology") == "wind" and row.get("online")
    )
    pv_available = sum(
        max(0.0, _finite_number(row.get("capacityKw")))
        for row in renewable_rows
        if row.get("technology") == "pv" and row.get("online")
    )
    available_renewable = sum(
        optimization_result.available_by_renewable.values()
    )
    curtail_kw = sum(
        optimization_result.curtailment_by_renewable.values()
    )
    recovery_kw = max(0.0, renewable_delta)
    recovery_candidate_count = sum(
        1
        for row in online_renewable
        if row.get("commandable") and _finite_number(row.get("capacityKw")) > _finite_number(row.get("currentKw")) + EPSILON
    )
    clock = _measurement_sample_clock(snapshot)
    time_text = str(clock.get("time", "--"))
    run_id = int(_number(clock.get("run_id"), 0.0) or 0)
    clock_key = f"{run_id}|{clock.get('absolute_minute', clock.get('minute', ''))}|{time_text}"
    quality_payload = quality.payload()
    island_component_metrics = [
        {
            "gridComponentId": str(plan.get("gridComponentId", "")),
            "dcTransferGroupId": str(plan.get("dcTransferGroupId", "")),
            "action": str(plan.get("action", "")),
            "storageSoc": plan.get("storageSoc"),
            "storageSocUpperLimit": plan.get("storageSocUpperLimit"),
            "renewableCurrentKw": _finite_number(plan.get("renewableCurrentKw")),
            "renewableTargetKw": _finite_number(plan.get("renewableTargetKw")),
            "converterTargetKw": _finite_number(plan.get("converterTargetKw")),
            "converterDevices": [
                {"dev_type": dev_type, "dev_name": dev_name}
                for dev_type, dev_name in plan.get("converterKeys", [])
            ],
        }
        for plan in island_component_plans
    ]
    ac_grid_following_storage_target = sum(
        _finite_number(
            direct_storage_targets.get(
                (str(row.get("dev_type", "")), str(row.get("dev_name", ""))),
                row.get("currentKw"),
            )
        )
        for row in online_ac_grid_following_storage
        if row.get("currentKw") is not None
    )
    dc_grid_following_storage_target = sum(
        _finite_number(
            direct_storage_targets.get(
                (str(row.get("dev_type", "")), str(row.get("dev_name", ""))),
                row.get("currentKw"),
            )
        )
        for row in online_dc_grid_following_storage
        if row.get("currentKw") is not None
    )
    task8_side_metrics = _task8_side_metrics(command_rows)
    direct_dispatch_blocks = [
        {
            "dev_type": str(row.get("dev_type", "")),
            "dev_name": str(row.get("dev_name", "")),
            "side": str(row.get("connectionSide", "")),
            "dcTransferGroupId": str(row.get("dcTransferGroupId", "")),
            "reason": str(row.get("directDispatchBlockedReason", "")),
        }
        for row in command_rows
        if str(row.get("directDispatchBlockedReason", "")).strip()
    ]
    _ac_load_for_transfer_metrics, dc_load_for_transfer_metrics = _active_load_budgets(
        snapshot,
        measurements,
        resource_topology.dc_transfer_groups,
    )
    load_side_metrics = _active_load_side_metrics(snapshot, measurements)
    side_total_load_kw = _sum_known(
        (load_side_metrics.get("acLoadKw"), load_side_metrics.get("dcLoadKw"))
    )
    dc_transfer_groups_metric, dc_renewable_to_ac_kw = _dc_transfer_group_metrics(
        resource_topology,
        command_rows,
        dc_load_for_transfer_metrics,
        converter_step_ratio=settings.converter_step_ratio,
    )
    online_storage_metric_rows = [
        row
        for row in command_rows
        if row.get("online")
        and row.get("technology") == "storage"
        and row.get("dev_type") in {"ACGenerator", "DCGenerator"}
        and row.get("resourceIdentityValid") is not False
    ]
    measured_storage_metric_rows = [
        row for row in online_storage_metric_rows if row.get("currentKw") is not None
    ]
    metric_storage_current = (
        sum(_finite_number(row.get("currentKw")) for row in measured_storage_metric_rows)
        if measured_storage_metric_rows
        else None
    )
    metric_storage_soc = _capacity_weighted_soc(online_storage_metric_rows)
    metrics = {
        **_optimization_metrics(optimization_result),
        "operatingMode": operating_mode,
        "acSideFullyOffline": ac_side_fully_offline,
        "renewableStorageIsland": renewable_storage_island,
        "renewableStorageIslandComponentCount": len(island_component_metrics),
        "renewableStorageIslandComponents": island_component_metrics,
        "acBusCount": len(ac_bus_rows),
        "onlineAcBusCount": len(online_ac_buses),
        "acLoadCount": len(ac_load_devices),
        "onlineAcLoadCount": len(online_ac_loads),
        "onlineDieselCount": len(online_diesel),
        "onlineStorageCount": len(island_online_storage) if renewable_storage_island else len(online_storage),
        "onlineAcBalanceStorageCount": len(online_ac_balance_storage),
        "onlineDcBalanceStorageCount": len(online_dc_balance_storage),
        "onlineAcGridFollowingStorageCount": len(online_ac_grid_following_storage),
        "onlineDcGridFollowingStorageCount": len(online_dc_grid_following_storage),
        "onlineAcdcConverterCount": len(
            [row for row in all_converter_rows if row.get("online")]
        ),
        "acBalanceStorageCurrentKw": ac_balance_storage_current,
        "dcBalanceStorageCurrentKw": dc_balance_storage_current,
        "acGridFollowingStorageCurrentKw": ac_grid_following_storage_current,
        "dcGridFollowingStorageCurrentKw": dc_grid_following_storage_current,
        "acGridFollowingStorageTargetKw": ac_grid_following_storage_target,
        "dcGridFollowingStorageTargetKw": dc_grid_following_storage_target,
        **task8_side_metrics,
        **load_side_metrics,
        "totalLoadKw": side_total_load_kw if side_total_load_kw is not None else load_kw,
        "dcRenewableToAcKw": dc_renewable_to_ac_kw,
        "dcTransferGroups": dc_transfer_groups_metric,
        "directStorageControlAction": direct_storage_plan["action"],
        "directStorageCorrectionRequestKw": _finite_number(
            direct_storage_plan.get("requestedKw")
        ),
        "directStorageCorrectionAcceptedKw": _finite_number(
            direct_storage_plan.get("acceptedKw")
        ),
        "directStorageCorrectionResidualKw": _finite_number(
            direct_storage_plan.get("residualKw")
        ),
        "directStorageAcEffectKw": direct_ac_storage_effect_kw,
        "directStorageAcdcEffectKw": direct_acdc_effect_kw,
        "directStorageDcGroups": copy.deepcopy(direct_storage_plan["groups"]),
        "directGridFormingAction": str(direct_grid_forming_plan.get("action", "hold")),
        "directGridFormingDcGroups": copy.deepcopy(
            direct_grid_forming_plan.get("dcGroups", [])
        ),
        "acComponentDispatch": copy.deepcopy(
            component_dispatch_plan.get("components", [])
        ),
        "duplicateDispatchCommands": copy.deepcopy(duplicate_commands),
        "directDispatchBlocks": copy.deepcopy(direct_dispatch_blocks),
        "dcBalanceControlGroupIds": (
            sorted(
                {
                    component.dc_transfer_group_id
                    for component in island_components
                }
            )
            if renewable_storage_island
            else sorted(
                {
                    str(row.get("dcTransferGroupId"))
                    for row in online_storage
                    if row.get("dcTransferGroupId")
                }
            )
        ),
        "onlineRenewableCount": len(renewable_metric_rows),
        "availableRenewable": available_renewable,
        "renewableCurrentKw": renewable_current,
        "windCurrentKw": wind_current,
        "pvCurrentKw": pv_current,
        "windAvailable": wind_available,
        "pvAvailable": pv_available,
        "windMaxAvailableKw": task8_side_metrics.get("totalWindMaxAvailableKw"),
        "pvMaxAvailableKw": task8_side_metrics.get("totalPvMaxAvailableKw"),
        "renewableMaxAvailableKw": task8_side_metrics.get(
            "totalRenewableMaxAvailableKw"
        ),
        "storageChargeAvailable": total_charge,
        "storageDischargeAvailable": total_discharge,
        "storageChargeBeforeDeratingKw": raw_charge_before_derating,
        "storageDischargeBeforeDeratingKw": raw_discharge_before_derating,
        "storageChargeDeratingActive": storage_charge_derating_active,
        "storageDischargeDeratingActive": storage_discharge_derating_active,
        "storageChargeDeratingFactor": storage_charge_derating_factor,
        "storageDischargeDeratingFactor": storage_discharge_derating_factor,
        "storageChargeDeratingLimitKw": raw_charge,
        "storageDischargeDeratingLimitKw": raw_discharge,
        "storageChargeDeratingExcessKw": storage_charge_derating_excess_kw,
        "storageDischargeDeratingExcessKw": storage_discharge_derating_excess_kw,
        "storageChargeDeratingHeadroomKw": storage_charge_derating_headroom_kw,
        "storageDischargeDeratingHeadroomKw": storage_discharge_derating_headroom_kw,
        "storageControlHorizonMinutes": storage_control_horizon_minutes,
        "storagePredictedChargeAfterAcdcKw": storage_predicted_charge_after_acdc_kw,
        "storageChargeDeratingResidualKw": storage_charge_derating_residual_kw,
        "storageHighSocDischargeRequestKw": storage_high_soc_discharge_request_kw,
        "storageChargeDeratingSafetyOverride": storage_charge_derating_safety_override,
        "storageChargeDeratingCurve": _derating_curve_payload(settings.storage_charge_derating_curve),
        "storageDischargeDeratingCurve": _derating_curve_payload(settings.storage_discharge_derating_curve),
        "storageChargeDeratingActuator": storage_charge_derating_actuator,
        "storageDischargeDeratingActuator": storage_discharge_derating_actuator,
        "storageChargeDeratingCandidateLimited": storage_charge_derating_candidate_limited,
        "storageDischargeDeratingCandidateLimited": storage_discharge_derating_candidate_limited,
        "storageChargeDeratingAcdcAllowed": storage_charge_derating_acdc_allowed,
        "storageDeratingConstraintOverride": storage_derating_constraint_override,
        "storageCurrentKw": metric_storage_current,
        "storageSoc": metric_storage_soc,
        "storageSocLowerLimit": storage_soc_lower_limit,
        "storageSocUpperLimit": storage_soc_upper_limit,
        "storageSocRegion": storage_soc_region,
        "socDeadband": settings.soc_deadband,
        "hydrogenClosedLoopEnabled": settings.hydrogen_closed_loop_enabled,
        "hydrogenPressureDeadbandRatio": settings.hydrogen_pressure_deadband_ratio,
        "hydrogenControl": hydrogen_plan,
        "onlineElectrolyzerCount": hydrogen_plan.get("onlineElectrolyzerCount", 0),
        "onlineFuelCellCount": hydrogen_plan.get("onlineFuelCellCount", 0),
        "onlineHydrogenStorageCount": hydrogen_plan.get("onlineHydrogenStorageCount", 0),
        "electrolyzerCurrentKw": hydrogen_plan.get("electrolyzerCurrentKw"),
        "electrolyzerTargetKw": hydrogen_plan.get("electrolyzerTargetKw"),
        "electrolyzerFlowCurrentNm3h": hydrogen_plan.get("electrolyzerFlowCurrentNm3h"),
        "electrolyzerFlowTargetNm3h": hydrogen_plan.get("electrolyzerFlowTargetNm3h"),
        "fuelCellCurrentKw": hydrogen_plan.get("fuelCellCurrentKw"),
        "fuelCellTargetKw": hydrogen_plan.get("fuelCellTargetKw"),
        "fuelCellFlowCurrentNm3h": hydrogen_plan.get("fuelCellFlowCurrentNm3h"),
        "fuelCellFlowTargetNm3h": hydrogen_plan.get("fuelCellFlowTargetNm3h"),
        "hydrogenStoragePressureMpa": hydrogen_plan.get("hydrogenStoragePressureMpa"),
        "hydrogenStoragePressureLowGuardMpa": hydrogen_plan.get("hydrogenStoragePressureLowGuardMpa"),
        "hydrogenStoragePressureHighGuardMpa": hydrogen_plan.get("hydrogenStoragePressureHighGuardMpa"),
        "hydrogenStorageGasQuantityNm3": hydrogen_plan.get("hydrogenStorageGasQuantityNm3"),
        "hydrogenStorageSoc": hydrogen_plan.get("hydrogenStorageSoc"),
        "hydrogenStorageFlowNm3h": hydrogen_plan.get("hydrogenStorageFlowNm3h"),
        "lowerSocDeadbandActive": lower_soc_deadband_active,
        "upperSocDeadbandActive": upper_soc_deadband_active,
        "renewableUpperBoundaryDistance": renewable_upper_boundary_distance,
        "renewableStorageChargingActive": renewable_storage_charging_active,
        "renewableRaiseBlockedByDieselGuard": (
            renewable_raise_blocked_by_diesel_guard
        ),
        "renewableCurtailmentRequiredByCharging": (
            renewable_curtailment_required_by_charging
        ),
        "renewableDieselGuardCurtailRequestKw": (
            renewable_diesel_guard_curtail_request_kw
        ),
        "gridFormingStorageProtectionRatio": (
            settings.grid_forming_storage_protection_ratio
        ),
        "gridFormingStorageChargeProtectionKw": (
            grid_forming_storage_charge_protection_kw
        ),
        "gridFormingStorageDischargeProtectionKw": (
            grid_forming_storage_discharge_protection_kw
        ),
        "renewableStorageChargeExcessKw": renewable_storage_charge_excess_kw,
        "socAboveUpperDeadband": soc_above_upper_deadband,
        "socBelowLowerDeadband": soc_below_lower_deadband,
        "socUpperDeadbandThreshold": soc_upper_deadband_threshold,
        "socLowerDeadbandThreshold": soc_lower_deadband_threshold,
        "storageAboveUpperCount": len(storage_above_upper),
        "storageBelowLowerCount": len(storage_below_lower),
        "absorptionLimitKw": renewable_balance_limit,
        "renewableBalanceLimitKw": renewable_balance_limit,
        "renewableRecoveryStepRequestKw": renewable_recovery_step_request_kw,
        "renewableCurtailStepRequestKw": renewable_curtail_step_request_kw,
        "renewableCurtailCapacityStepKw": renewable_curtail_capacity_step_kw,
        "renewableChargeSafetyCurtailRequiredKw": renewable_charge_safety_curtail_required_kw,
        "renewableChargeSafetyCurtailRequestKw": renewable_charge_safety_curtail_request_kw,
        "renewableChargeSafetyCurtailDeliveredKw": renewable_charge_safety_curtail_delivered_kw,
        "renewableChargeSafetyCurtailShortfallKw": renewable_charge_safety_curtail_shortfall_kw,
        "renewableCurtailLimitedByStorageCharge": (
            renewable_curtail_step_request_kw + EPSILON < renewable_curtail_capacity_step_kw
        ),
        "renewableStorageCoordinationActive": renewable_storage_coordination_active,
        "renewableDischargeReplacementKw": renewable_discharge_replacement_kw,
        "renewableAbsorptionRequiredKw": renewable_absorption_required_kw,
        "storageRenewableCoordinationKw": storage_renewable_coordination_kw,
        "highSocStorageBalanceLimitKw": high_soc_storage_balance_limit_kw,
        "highSocStorageBalanceLimited": high_soc_storage_balance_limited,
        "highSocRequiredCurtailKw": high_soc_required_curtail_kw,
        "renewableDeltaKw": renewable_delta,
        "renewableBalancingDeltaKw": renewable_delta,
        "renewableTarget": renewable_target,
        "storageMinTargetKw": storage_min_target,
        "storageMaxTargetKw": storage_max_target,
        "dieselEmergencyChargeAllowed": diesel_emergency_charge_allowed,
        "emergencyChargeRequested": emergency_charge_requested,
        "extremeSocChargeRequested": soc_below_lower_deadband,
        "storageTarget": storage_target,
        "storageDesiredTargetKw": desired_storage_target,
        "storageCandidateTargetKw": storage_candidate_target,
        "storagePowerCapacityKw": storage_power_capacity,
        "storageControlAction": storage_control_action,
        "acdcControlAction": storage_control_action,
        "storageSwitchDeadbandAction": storage_deadband_action,
        "acdcCurrentKw": aggregate_converter_current_kw,
        "acdcCurrentForControlKw": converter_current_for_control,
        "acdcDesiredTargetKw": aggregate_converter_target_kw,
        "acdcTargetKw": aggregate_converter_target_kw,
        "acdcAdjustmentKw": (
            aggregate_converter_target_kw - aggregate_converter_current_kw
            if aggregate_converter_current_kw is not None
            else None
        ),
        "converterRatedCapacityKw": aggregate_converter_capacity_kw,
        "converterReversePowerForbidden": False,
        "converterReversePowerDetected": False,
        "converterBidirectionalEnabled": bool(all_converter_rows),
        "converterSystemPowerConvention": "P_DC",
        "converterSystemPositiveDirection": "DC_TO_AC",
        "converterPositiveDirection": AC_TO_DC,
        "converterDcPositiveDirection": "DC_TO_AC",
        "converterTargetLowerLimitKw": aggregate_converter_lower_limit_kw,
        "converterTargetUpperLimitKw": aggregate_converter_upper_limit_kw,
        "converterHardLimitApplied": converter_hard_limit_applied,
        "converterStorageConstraintTargetKw": storage_constrained_converter_target,
        "converterChargeSafetyTargetKw": converter_charge_safety_target,
        "converterChargeSafetyStorageKw": converter_charge_safety_storage_kw,
        "converterStorageConstraintConflict": converter_storage_constraint_conflict,
        "converterStepRatio": None,
        "converterBaseStepKw": None,
        "converterStepLimited": False,
        "gridFollowingStorageStepRatio": settings.storage_step_ratio,
        "storageEffectiveDecisionStepRatio": storage_effective_decision_step_ratio,
        "converterStepDirection": converter_step_direction,
        "converterExportStepDirection": converter_export_step_direction,
        "converterSlowIncrease": converter_slow_export_increase,
        "converterSlowExportIncrease": converter_slow_export_increase,
        "converterEmergencyStopActive": converter_emergency_stop_active,
        "converterIslandZeroOverride": converter_island_zero_override,
        "converterChargeDeratingSafetyOverride": converter_charge_derating_safety_override,
        "converterStepScale": None,
        "converterStepKw": None,
        "converterAppliedStepKw": converter_applied_step_kw,
        "converterStepLimited": False,
        "dieselResidual": diesel_residual,
        "dieselCurrentKw": diesel_current,
        "dieselMinKw": diesel_min,
        "dieselDownMarginKw": diesel_down_margin,
        "dieselUpMarginKw": diesel_up_margin,
        "dieselPowerProtectionRatio": settings.diesel_power_protection_ratio,
        "dieselDeadbandKw": diesel_deadband_kw,
        "dieselDeadbandLowerKw": diesel_deadband_lower_kw,
        "dieselDeadbandUpperKw": diesel_deadband_upper_kw,
        "dieselDeadbandActive": diesel_deadband_active,
        "dieselControlRegion": diesel_control_region,
        "dieselFloorDeficitKw": diesel_floor_deficit_kw,
        "dieselDeadbandEntryGapKw": diesel_deadband_entry_gap_kw,
        "dieselFloorCorrectionRequestKw": diesel_floor_correction_request_kw,
        "dieselBoundaryApproachActive": diesel_boundary_approach_active,
        "dieselBoundaryDistanceKw": diesel_boundary_distance_kw,
        "dieselTargetKw": diesel_target,
        "dieselBoundaryErrorKw": diesel_boundary_error,
        "dieselCapacityKw": diesel_capacity,
        "dieselCurrentViolationKw": current_diesel_violation,
        "dieselPredictedViolationKw": predicted_diesel_violation,
        "dieselViolationImproved": diesel_violation_improved,
        "dieselValidationStatus": diesel_validation_status,
        "candidatePowerEffectKw": candidate_effect,
        "curtailKw": curtail_kw,
        "loadKw": load_kw,
        "unservedKw": unserved_kw,
        "surplusKw": surplus_kw,
        "windSpeedKnown": wind_speed is not None,
        "solarIrradianceKnown": irradiance is not None,
        "recoveryMode": "capacity-step" if recovery_kw > EPSILON else "none",
        "renewableControlAction": renewable_control_action,
        "renewableCapacityKw": renewable_capacity,
        "renewableStepRatio": settings.step_coefficient,
        "renewableEffectiveDecisionStepRatio": renewable_effective_decision_step_ratio,
        "simulationControlIntervalSeconds": configured_settings.interval_seconds,
        "controlIntervalSeconds": configured_settings.interval_seconds,
        "controlIntervalClock": "simulation",
        "renewableStepDirection": renewable_step_direction,
        "renewableRecoveryStepScale": renewable_recovery_step_scale,
        "renewableRecoveryBoundaryScale": renewable_recovery_boundary_scale,
        "renewableRecoveryDeratingScale": renewable_recovery_derating_scale,
        "renewableRecoveryCapacityStepKw": renewable_recovery_capacity_step_kw,
        "renewableCurtailStepScale": renewable_curtail_step_scale,
        "renewableDeratingCurtailStepScale": renewable_derating_curtail_step_scale,
        "renewableDeratingCurtailStepRequestKw": renewable_derating_curtail_step_request_kw,
        "renewableStepScale": renewable_step_scale,
        "renewableEffectiveStepRatio": renewable_effective_step_ratio,
        "recoveryRequestedKw": recovery_kw,
        "recoveryKw": recovery_kw,
        "recoveryCandidateCount": recovery_candidate_count,
        "largeStepThresholdKw": settings.large_step_threshold_kw,
        "stepCoefficient": settings.step_coefficient,
        "storageConverterCount": len(converter_rows),
    }
    converter_step_reasons = []
    if lower_soc_deadband_active:
        converter_step_reasons.append("SOC下限死区")
    if diesel_deadband_active:
        converter_step_reasons.append("柴发下限死区")
    converter_step_region_text = "、".join(converter_step_reasons)
    if converter_island_zero_override:
        converter_step_reason_text = "交流侧全部退运，跳过常规步长并将ACDC送出目标直接归零"
    elif converter_emergency_stop_active:
        converter_step_reason_text = (
            "SOC低于下限-死区，跳过常规步长限制，ACDC送出直接回退到校核后安全目标"
        )
    elif converter_charge_derating_safety_override:
        converter_step_reason_text = (
            "实时充电超过线性降额边界，跳过常规步长限制，ACDC直接调至充电保护目标"
        )
    elif diesel_boundary_approach_active:
        converter_step_reason_text = (
            f"接近柴发控制分区切换边界（距离 {diesel_boundary_distance_kw:.2f} kW，"
            f"不超过基础步长 {converter_base_step_kw:.2f} kW）；"
            "死区仅保护功率边界，仍使用普通最大步长"
        )
    elif not converter_step_reasons:
        converter_step_reason_text = "使用普通最大步长"
    elif converter_export_step_direction == "increase_export":
        converter_step_reason_text = (
            f"{converter_step_region_text}内增加ACDC送出；死区仅保护功率边界，"
            "仍使用普通最大步长"
        )
    elif converter_export_step_direction == "decrease_export":
        converter_step_reason_text = f"{converter_step_region_text}内降低ACDC送出，保持原步长"
    else:
        converter_step_reason_text = f"{converter_step_region_text}内无功率调整，保持原步长"
    converter_step_application_text = (
        f"保护校核实际变化 {converter_applied_step_kw:.2f} kW"
        if converter_island_zero_override
        or converter_emergency_stop_active
        or converter_charge_derating_safety_override
        else (
            f"实际按 {converter_step_scale * 100:.0f}% 即最大 {converter_step_kw:.2f} kW 调节，"
            f"本轮变化 {converter_applied_step_kw:.2f} kW"
        )
    )
    if renewable_control_action == "curtail_one_step_storage_island_full_soc":
        renewable_step_reason_text = (
            f"交流侧全部退运且储能达到model.e定义的SOC上限 "
            f"{storage_soc_upper_limit * 100:.2f}%，新能源按原步长逐步弃电"
        )
    elif renewable_control_action == "curtail_one_step_storage_island_no_charge_capacity":
        renewable_step_reason_text = (
            "交流侧全部退运，储能线性降额后的允许充电功率已经为零，"
            "新能源按原步长逐步弃电"
        )
    elif renewable_control_action == "recover_one_step_storage_island":
        renewable_step_reason_text = (
            "交流侧全部退运，储能仍有充电空间，新能源按充电降额允许的步长逐步恢复"
        )
    elif renewable_control_action == "recover_one_step_below_soc_lower_deadband":
        renewable_step_reason_text = (
            "SOC低于下限-死区，新能源按原步长恢复，为储能补能创造直流侧功率余量"
        )
    elif renewable_control_action == "curtail_one_step_above_soc_upper_deadband":
        renewable_step_reason_text = (
            "SOC高于上限+死区且ACDC不能继续增加送出，新能源按原步长降低功率，"
            "促使储能减少充电或转为放电"
        )
    elif renewable_control_action == "hold_above_soc_upper_deadband_while_acdc_discharges":
        renewable_step_reason_text = (
            "SOC高于上限+死区，ACDC已增加送出以降低SOC，新能源保持当前出力避免抵消校正"
        )
    elif renewable_control_action == "hold_full_soc_no_charge":
        renewable_step_reason_text = "储能已不再充电，停止继续弃电并保持当前出力"
    elif renewable_control_action == "hold_full_soc_high_diesel_charging":
        renewable_step_reason_text = "SOC已到上限但柴发仍高，暂停新能源动作并等待ACDC回路降低储能充电"
    elif renewable_control_action == "curtail_one_step_low_diesel_charging":
        renewable_step_reason_text = (
            f"储能SOC高于下限且仍充电 {storage_charge_current_kw:.2f} kW，柴发低于"
            f"下限+死区 {diesel_deadband_upper_kw:.2f} kW；新能源禁止上调并按剩余充电功率"
            f"弃电 {renewable_diesel_guard_curtail_request_kw:.2f} kW"
        )
    elif renewable_control_action == "hold_low_diesel_no_charge":
        renewable_step_reason_text = (
            f"储能SOC高于下限且柴发低于下限+死区 {diesel_deadband_upper_kw:.2f} kW；"
            "新能源没有上调空间，储能未充电时保持当前出力"
        )
    elif renewable_control_action == "curtail_charge_safety":
        renewable_step_reason_text = (
            f"ACDC目标作用后预计仍充电 {storage_predicted_charge_after_acdc_kw:.2f} kW，"
            f"超过线性降额上限 {raw_charge:.2f} kW；新能源本轮直接消除剩余超限 "
            f"{storage_charge_derating_residual_kw:.2f} kW"
            + (
                f"，并额外降低 {storage_high_soc_discharge_request_kw:.2f} kW 以推动SOC回落"
                if storage_high_soc_discharge_request_kw > EPSILON
                else ""
            )
        )
    elif renewable_control_action == "curtail_one_step_charge_derating":
        renewable_step_reason_text = (
            f"储能充电 {storage_charge_current_kw:.2f} kW 超过线性降额上限 "
            f"{raw_charge:.2f} kW，且ACDC校正会触发柴发下限，新能源按充电超限量 "
            f"{renewable_derating_curtail_step_request_kw:.2f} kW 渐进降低"
        )
    elif renewable_control_action == "hold_charge_derating_while_acdc_corrects":
        renewable_step_reason_text = (
            f"储能充电超过线性降额上限，ACDC正在承担校正，本轮新能源保持，避免抵消校正"
        )
    elif (
        renewable_control_action == "recover_one_step"
        and renewable_recovery_derating_scale < renewable_recovery_boundary_scale - EPSILON
    ):
        renewable_step_reason_text = (
            f"充电线性降额仅剩 {storage_charge_derating_headroom_kw:.2f} kW 空间，"
            f"新能源恢复步长缩小到基础步长的 {renewable_recovery_step_scale * 100:.1f}%"
        )
    elif not upper_soc_deadband_active:
        renewable_step_reason_text = "不在SOC上限死区，保持原步长"
    elif renewable_step_direction == "increase":
        renewable_step_reason_text = (
            "SOC上限死区内升功率；SOC分段限额负责限制可行功率，"
            "普通步长仍作为单周期最大调节量"
        )
    elif renewable_step_direction == "decrease" and renewable_curtail_step_scale < 1.0 - EPSILON:
        renewable_step_reason_text = (
            f"储能充电超出死区 {renewable_storage_charge_excess_kw:.2f} kW，小于新能源基础降幅 "
            f"{renewable_curtail_capacity_step_kw:.2f} kW，按充电偏差限幅"
        )
    elif renewable_step_direction == "decrease":
        renewable_step_reason_text = (
            f"储能充电超出死区 {renewable_storage_charge_excess_kw:.2f} kW，新能源降功率保持原步长"
        )
    else:
        renewable_step_reason_text = "SOC上限死区内无功率调整，保持原步长"
    converter_rated_capacity_text = f"{aggregate_converter_capacity_kw:.2f}"
    converter_current_p_dc_text = (
        f"{-converter_current:.2f}"
        if converter_current is not None
        else "--"
    )
    converter_current_for_control_p_dc_kw = -converter_current_for_control
    converter_target_p_dc_kw = -converter_target
    storage_constrained_converter_target_p_dc_kw = (
        -storage_constrained_converter_target
    )
    if soc_above_upper_deadband:
        upper_threshold_percent = soc_upper_deadband_threshold * 100.0
        if renewable_control_action == "curtail_charge_safety":
            soc_correction_detail = (
                f"SOC越界校正：当前SOC {storage_soc * 100:.2f}% 高于上限+死区阈值 "
                f"{upper_threshold_percent:.2f}%；ACDC目标作用后储能预计为 {storage_target:.2f} kW，"
                f"新能源再由 {renewable_current:.2f} kW 降至 {renewable_target:.2f} kW，"
                "先消除充电，再建立小幅放电，使SOC持续回落"
            )
        elif storage_target > EPSILON:
            soc_correction_detail = (
                f"SOC越界校正：当前SOC {storage_soc * 100:.2f}% 高于上限+死区阈值 "
                f"{upper_threshold_percent:.2f}%，利用柴发下调余量将ACDC目标由 "
                f"{converter_current_for_control_p_dc_kw:.2f} kW 调至 {converter_target_p_dc_kw:.2f} kW，"
                "新能源保持，持续增加储能放电直至SOC回到阈值以下"
            )
        else:
            soc_correction_detail = (
                f"SOC越界校正：当前SOC {storage_soc * 100:.2f}% 高于上限+死区阈值 "
                f"{upper_threshold_percent:.2f}%，ACDC受柴发下限或容量边界约束不能继续增送，"
                f"新能源目标由 {renewable_current:.2f} kW 降至 {renewable_target:.2f} kW，"
                "促使储能减少充电或转为放电"
            )
    elif soc_below_lower_deadband:
        lower_threshold_percent = soc_lower_deadband_threshold * 100.0
        soc_correction_detail = (
            f"SOC越界校正：当前SOC {storage_soc * 100:.2f}% 低于下限-死区阈值 "
            f"{lower_threshold_percent:.2f}%，ACDC目标由 {converter_current_for_control_p_dc_kw:.2f} kW "
            f"向零调整至 {converter_target_p_dc_kw:.2f} kW，新能源由 {renewable_current:.2f} kW "
            f"恢复至 {renewable_target:.2f} kW，在设备有功边界内促使储能补能"
        )
    else:
        soc_correction_detail = "SOC越界校正：未触发上限+死区或下限-死区强制校正"
    charge_derating_actuator_text = {
        "acdc": "ACDC调节",
        "renewable": "新能源降功率",
        "none": "无需校正",
    }.get(storage_charge_derating_actuator, storage_charge_derating_actuator)
    discharge_derating_actuator_text = {
        "acdc": "ACDC调节",
        "renewable": "新能源调节",
        "none": "无需校正",
    }.get(storage_discharge_derating_actuator, storage_discharge_derating_actuator)
    converter_storage_validation_text = (
        "与状态机方向冲突，但线性降额属于储能保护边界，已由降额目标覆盖"
        if storage_derating_constraint_override
        else "与状态机保持/调节方向冲突，已禁止反向覆盖"
        if converter_storage_constraint_conflict
        else "与状态机调节方向一致"
    )
    operating_mode_detail = (
        f"运行方式：380V实体交流母线 {len(ac_bus_rows)} 个、柴油发电机 {len(diesel_rows)} 台、"
        f"交流负荷 {len(ac_load_devices)} 个均无在线设备，交流侧全部退运，进入新能源储能孤岛"
        if renewable_storage_island
        else "运行方式：采用在线柴油发电机作为交流侧功率调节基准"
        if online_diesel
        else "运行方式：交流侧仍有在线设备，但没有在线柴油发电机，新能源实时控制阻断"
    )
    control_architecture_detail = (
        "控制架构：新能源与储能在直流侧联合运行；ACDC目标强制归零，新能源依据储能SOC及充电能力独立恢复或弃电"
        if renewable_storage_island
        else "控制架构：ACDC与新能源两条策略相互独立生成候选目标，再统一执行SOC、功率和柴油边界校核；不把两条策略增量直接相加"
    )
    control_reference_detail = (
        f"控制基准：时刻 {time_text}，新能源当前 {renewable_current:.2f} kW，储能当前 "
        f"{storage_current_for_control:.2f} kW、SOC {storage_soc * 100 if storage_soc is not None else '--'}%；柴发基准不适用"
        if renewable_storage_island
        else f"控制基准：时刻 {time_text}，新能源当前 {renewable_current:.2f} kW，柴发当前 {diesel_current_for_control:.2f} kW、下限 {diesel_min:.2f} kW"
    )
    diesel_region_detail = (
        "柴发分区：交流侧全部退运，柴油下限调节不参与本轮决策"
        if renewable_storage_island
        else f"柴发分区：下限 {diesel_deadband_lower_kw:.2f} kW，功率保护带上界 {diesel_deadband_upper_kw:.2f} kW（额定容量比例 {settings.diesel_power_protection_ratio * 100:.2f}%）；低于下限逐步降低ACDC送出，保护带内保持，高于保护带才允许增加ACDC送出；当前位于 {diesel_control_region} 区"
    )
    acdc_strategy_detail = (
        f"ACDC策略：交流侧全部退运，实时 {converter_current_p_dc_text} kW，"
        f"跳过常规步长并将目标直接归零至 {converter_target_p_dc_kw:.2f} kW"
        if renewable_storage_island
        else f"ACDC策略：只读取柴发分区与SOC分区，动作 {storage_control_action}；实时 {converter_current_p_dc_text} kW，控制基准 {converter_current_for_control_p_dc_kw:.2f} kW，基础步长 {converter_base_step_kw:.2f} kW，{converter_step_reason_text}，{converter_step_application_text}，目标 {converter_target_p_dc_kw:.2f} kW"
    )
    renewable_strategy_detail = (
        f"新能源策略：新能源储能孤岛中以model.e的SOC上限为满电判据；当前上限 "
        f"{storage_soc_upper_limit * 100 if storage_soc_upper_limit is not None else '--'}%，本轮动作 {renewable_control_action}"
        if renewable_storage_island
        else f"新能源策略：以SOC为主；低于下限-死区时按原步长恢复；高于上限+死区时，仅当ACDC候选目标已经形成有效放电才保持新能源，否则先一次消除剩余充电超限，再按正常步长建立放电；普通上限附近按线性充电边界校核；本轮动作 {renewable_control_action}"
    )
    soc_constraint_detail = (
        "SOC运行约束：新能源储能孤岛中ACDC保持零送出；达到model.e定义的SOC上限后禁止继续充电，并按步长逐步降低新能源出力"
        if renewable_storage_island
        else "SOC运行约束：达到上限禁止充电；超过上限+死区后优先增加ACDC送出，受柴发下限约束时降低新能源；达到下限禁止放电，低于下限-死区后ACDC向零回退并恢复新能源"
    )
    decision_detail = [
        f"数据来源：{_source_label(data_source)}，质量 {quality_payload['status']}，闭环下发{'允许' if quality_payload['dispatchAllowed'] else '禁止'}",
        *_task8_decision_detail(command_rows, metrics),
        (
            f"氢能环节：作为综合新能源策略的一部分始终参与同轮计算，"
            f"当前{'闭环，氢能指令及其对ACDC/柴发的原子修正进入统一下发' if settings.hydrogen_closed_loop_enabled else '开环，仅展示氢能目标且不修正、不下发ACDC或柴发'}；动作 "
            f"{hydrogen_plan.get('action', 'hold')}，本轮电功率增量 "
            f"{_finite_number(hydrogen_plan.get('electricPowerAdjustmentKw')):.2f} kW，目标电功率 "
            f"{_finite_number(hydrogen_plan.get('targetElectricPowerKw')):.2f} kW，目标等效氢流量 "
            f"{_finite_number(hydrogen_plan.get('targetEquivalentFlow')):.2f} Nm3/h，压力死区 "
            f"{settings.hydrogen_pressure_deadband_ratio * 100:.2f}%（按各储氢罐压力范围计算）；"
            f"燃料电池启动需柴发负载率>{settings.fuel_cell_diesel_power_limit_ratio * 100:.2f}%、"
            f"电储平均SOC<{settings.fuel_cell_storage_soc_limit * 100:.2f}%且本氢岛氢储平均SOC>"
            f"{settings.fuel_cell_hydrogen_storage_soc_upper_limit * 100:.2f}%；运行后以氢储平均SOC>"
            f"{settings.fuel_cell_hydrogen_storage_soc_lower_limit * 100:.2f}%维持升出力条件，"
            "任一反向条件成立则按燃料电池步长降出力；储氢罐低压保护优先停机"
        ),
        operating_mode_detail,
        control_architecture_detail,
        control_reference_detail,
        diesel_region_detail,
        f"储能状态：当前 {storage_current_for_control:.2f} kW，SOC {storage_soc * 100 if storage_soc is not None else '--'}%，运行边界 [{storage_soc_lower_limit * 100 if storage_soc_lower_limit is not None else '--'}%, {storage_soc_upper_limit * 100 if storage_soc_upper_limit is not None else '--'}%]",
        f"SOC分区：下限 {storage_soc_lower_limit * 100 if storage_soc_lower_limit is not None else '--'}%，上限 {storage_soc_upper_limit * 100 if storage_soc_upper_limit is not None else '--'}%，死区 {settings.soc_deadband * 100:.2f}%，当前 {storage_soc_region}",
        soc_constraint_detail,
        f"充电线性降额：配置节点 {_derating_curve_text(settings.storage_charge_derating_curve)}；能量校核时域 {storage_control_horizon_minutes:.2f} min；当前因子 {storage_charge_derating_factor * 100:.2f}%，降额前 {raw_charge_before_derating:.2f} kW、允许 {raw_charge:.2f} kW、实时充电 {storage_charge_current_kw:.2f} kW、超限 {storage_charge_derating_excess_kw:.2f} kW；ACDC候选目标作用后预计充电 {storage_predicted_charge_after_acdc_kw:.2f} kW、剩余超限 {storage_charge_derating_residual_kw:.2f} kW，线性插值后由 {charge_derating_actuator_text} 及统一保护校核处理",
        f"放电线性降额：配置节点 {_derating_curve_text(settings.storage_discharge_derating_curve)}；当前因子 {storage_discharge_derating_factor * 100:.2f}%，降额前 {raw_discharge_before_derating:.2f} kW、允许 {raw_discharge:.2f} kW、实时放电 {storage_discharge_current_kw:.2f} kW、超限 {storage_discharge_derating_excess_kw:.2f} kW，线性插值后由 {discharge_derating_actuator_text} 处理",
        soc_correction_detail,
        f"环境策略：风速 {observed_wind_speed if observed_wind_speed is not None else '--'}、太阳辐照度 {observed_irradiance if observed_irradiance is not None else '--'}、温度 {observed_air_temperature if observed_air_temperature is not None else '--'}；仅用于最大可发统计，不参与控制目标计算",
        f"ACDC容量边界：自动控制使用原始并联容量 {converter_rated_capacity_text} kW",
        "ACDC符号约定：系统总功率与总目标统一采用P_DC，正向DC→AC；单台遥调仍按控制端选择P_AC_SET或P_DC_SET并转换符号；"
        f"自动控制目标范围 [{aggregate_converter_lower_limit_kw:.2f}, {aggregate_converter_upper_limit_kw:.2f}] kW",
        f"ACDC后置校核：储能运行边界与充放电线性降额折算目标 {storage_constrained_converter_target_p_dc_kw:.2f} kW，{converter_storage_validation_text}",
        acdc_strategy_detail,
        f"ACDC独立预估：对应储能平衡功率由 {storage_current_for_control:.2f} kW 变为 {storage_target:.2f} kW，柴发反馈参考值 {diesel_target:.2f} kW；该值不叠加新能源动作",
        f"跟网储能直调：动作 {direct_storage_plan['action']}，从既有ACDC/直流平衡候选后的柴发偏差请求 {_finite_number(direct_storage_plan.get('requestedKw')):.2f} kW；交流跟网储能目标 {ac_grid_following_storage_target:.2f} kW，直流跟网储能目标 {dc_grid_following_storage_target:.2f} kW，直流侧仅使用同传输组ACDC增量，交流供电净影响 {direct_ac_storage_effect_kw + direct_acdc_effect_kw:.2f} kW，剩余 {_finite_number(direct_storage_plan.get('residualKw')):.2f} kW",
        renewable_strategy_detail,
        (
            f"固定决策步长：新能源 {renewable_effective_decision_step_ratio * 100:.2f}%/次决策、"
            f"跟网储能 {storage_effective_decision_step_ratio * 100:.2f}%/次决策；"
            f"不按仿真步长、仿真周期或控制周期换算放大"
        ),
        f"新能源目标：当前 {renewable_current:.2f} kW，储能当前 {storage_current_for_control:.2f} kW、构网储能功率保护带 {settings.grid_forming_storage_protection_ratio * 100:.2f}%（充电侧 {grid_forming_storage_charge_protection_kw:.2f} kW）、超出保护带 {renewable_storage_charge_excess_kw:.2f} kW；本次固定最大比例 {settings.step_coefficient * 100:.2f}%，{renewable_step_reason_text}，实际按 {renewable_step_scale * 100:.1f}% 即 {renewable_effective_step_ratio * 100:.2f}% 调节，目标 {renewable_target:.2f} kW",
        f"负荷功率仅用于展示：当前 {load_kw:.2f} kW，不参与新能源、储能、变流器或柴发目标计算",
        f"独立边界检查与统一保护校核：ACDC目标已按设备有功上下限、model.e中的SOC运行边界、储能剩余能量和分段线性充放电降额校核；常规动作遵守步长，充电超限时保护校核可直接消除超限；新能源恢复量同时受充电降额剩余空间约束",
        *[f"数据告警：{issue}" for issue in quality_payload["issues"]],
    ]
    decision_detail.extend(
        _optimization_decision_detail(
            optimization_result,
            command_rows,
            quality_payload,
            settings,
        )
    )
    plan_finished = time.perf_counter()
    performance_diagnostics = {
        "phasesMs": {
            "inputProcessingMs": input_processing_seconds * 1000.0,
            "topologyAnalysisMs": topology_analysis_seconds * 1000.0,
            "strategyPreparationMs": strategy_preparation_seconds * 1000.0,
            "optimizationBuildMs": optimization_result.build_seconds * 1000.0,
            "optimizationSolveMs": optimization_result.solver_seconds * 1000.0,
            "storageBalanceMs": (
                optimization_result.storage_balance_seconds * 1000.0
            ),
            "optimizationPostprocessMs": (
                optimization_result.postprocess_seconds * 1000.0
            ),
            "optimizationTotalMs": optimization_total_seconds * 1000.0,
            "strategyPostprocessMs": (
                plan_finished - optimization_finished
            )
            * 1000.0,
            "planTotalMs": (plan_finished - plan_started) * 1000.0,
        },
        "solver": _optimization_performance_diagnostics(optimization_result),
    }
    return {
        "clockKey": clock_key,
        "time": time_text,
        "weather": {
            "minute": _number(clock.get("absolute_minute", clock.get("minute")), 0.0) or 0.0,
            "windSpeed": wind_speed,
            "windSpeedKnown": wind_speed is not None,
            "solarIrradiance": irradiance,
            "solarIrradianceKnown": irradiance is not None,
            "airTemp": air_temperature,
            "observedWindSpeed": observed_wind_speed,
            "observedSolarIrradiance": observed_irradiance,
            "observedAirTemp": observed_air_temperature,
            "loadKw": load_kw,
        },
        "commandRows": command_rows,
        "commands": commands,
        "warnings": warnings,
        "metrics": metrics,
        "dataQuality": quality_payload,
        "decisionDetail": decision_detail,
        "performanceDiagnostics": performance_diagnostics,
    }


def _compact_log_number(value: Any, unit: str = "kW") -> str:
    number = _number(value)
    if number is None or not math.isfinite(number):
        return "--"
    text = f"{number:.2f}".rstrip("0").rstrip(".")
    return f"{text} {unit}" if unit else text


def _compact_decision_log_detail(plan: Mapping[str, Any]) -> List[str]:
    metrics = plan.get("metrics") if isinstance(plan.get("metrics"), Mapping) else {}
    weather = plan.get("weather") if isinstance(plan.get("weather"), Mapping) else {}
    quality = (
        plan.get("dataQuality")
        if isinstance(plan.get("dataQuality"), Mapping)
        else {}
    )
    commands = plan.get("commands") if isinstance(plan.get("commands"), Sequence) else []
    warnings = plan.get("warnings") if isinstance(plan.get("warnings"), Sequence) else []
    detail = [
        (
            f"数据：{_source_label(str(quality.get('source', '')))}，"
            f"质量 {quality.get('status', '--')}，时刻 {plan.get('time', '--')}"
        ),
        (
            "气象：风速 "
            f"{_compact_log_number(weather.get('observedWindSpeed'), 'm/s')}，"
            "太阳辐照度 "
            f"{_compact_log_number(weather.get('observedSolarIrradiance'), 'W/m2')}；"
            "仅用于最大可发统计，不参与控制"
        ),
        (
            "最大可发：风电最大可发 "
            f"{_compact_log_number(metrics.get('totalWindMaxAvailableKw'))}，"
            "光伏最大可发 "
            f"{_compact_log_number(metrics.get('totalPvMaxAvailableKw'))}，"
            "新能源最大可发 "
            f"{_compact_log_number(metrics.get('totalRenewableMaxAvailableKw'))}"
        ),
        (
            "控制结果：新能源 "
            f"{_compact_log_number(metrics.get('renewableCurrentKw'))} -> "
            f"{_compact_log_number(metrics.get('renewableTarget'))}，储能 "
            f"{_compact_log_number(metrics.get('storageCurrentKw'))} -> "
            f"{_compact_log_number(metrics.get('storageTarget'))}，ACDC "
            f"{_compact_log_number(metrics.get('acdcCurrentKw'))} -> "
            f"{_compact_log_number(metrics.get('acdcTargetKw'))}，柴发 "
            f"{_compact_log_number(metrics.get('dieselCurrentKw'))} -> "
            f"{_compact_log_number(metrics.get('dieselTargetKw'))}"
        ),
        f"指令：生成 {len(commands)} 条遥调策略",
    ]
    warning_text = [str(item).strip() for item in warnings if str(item).strip()]
    if warning_text:
        shown = "；".join(warning_text[:2])
        if len(warning_text) > 2:
            shown += f"；另有 {len(warning_text) - 2} 条"
        detail.append(f"告警：{shown}")
    return detail


def _decision_log_level(plan: Mapping[str, Any]) -> str:
    quality = (
        plan.get("dataQuality")
        if isinstance(plan.get("dataQuality"), Mapping)
        else {}
    )
    warnings = plan.get("warnings")
    has_warning = bool(
        isinstance(warnings, Sequence)
        and not isinstance(warnings, (str, bytes))
        and any(str(item).strip() for item in warnings)
    )
    return "warn" if quality.get("status") != "ok" or has_warning else "info"


_RENEWABLE_READY_IDLE_STATUS = "请选择单次计算或启动实时控制。"
_RENEWABLE_AUTO_RESUMED_STATUS = "接收已就绪，新能源实时控制已自动恢复。"
_USER_CONTROL_BUSY_WAIT_SECONDS = 30.0
_COMPACT_TREND_FIELDS = (
    "sampleKey",
    "runId",
    "stepCount",
    "minute",
    "time",
    "loadKw",
    "dieselKw",
    "storageKw",
    "storageSocPercent",
    "renewableKw",
    "acLoadKw",
    "dcLoadKw",
    "dieselCurrentKw",
    "dieselTargetKw",
    "acRenewableCurrentKw",
    "acRenewableTargetKw",
    "acRenewableMaxAvailableKw",
    "acWindCurrentKw",
    "acWindTargetKw",
    "acWindMaxAvailableKw",
    "acPvCurrentKw",
    "acPvTargetKw",
    "acPvMaxAvailableKw",
    "acStorageCurrentKw",
    "acStorageTargetKw",
    "acStorageSocPercent",
    "dcRenewableCurrentKw",
    "dcRenewableTargetKw",
    "dcRenewableMaxAvailableKw",
    "dcWindCurrentKw",
    "dcWindTargetKw",
    "dcWindMaxAvailableKw",
    "dcPvCurrentKw",
    "dcPvTargetKw",
    "dcPvMaxAvailableKw",
    "dcStorageCurrentKw",
    "dcStorageTargetKw",
    "dcStorageSocPercent",
    "acGridFollowingStorageCurrentKw",
    "acGridFollowingStorageTargetKw",
    "acGridFollowingStorageSocPercent",
    "dcGridFollowingStorageCurrentKw",
    "dcGridFollowingStorageTargetKw",
    "dcGridFollowingStorageSocPercent",
    "acGridFormingStorageCurrentKw",
    "acGridFormingStorageTargetKw",
    "acGridFormingStorageSocPercent",
    "dcGridFormingStorageCurrentKw",
    "dcGridFormingStorageTargetKw",
    "dcGridFormingStorageSocPercent",
    "acDieselCurrentKw",
    "acDieselMinKw",
    "acDieselTargetKw",
    "dcDieselCurrentKw",
    "dcDieselMinKw",
    "dcDieselTargetKw",
    "totalRenewableCurrentKw",
    "totalRenewableTargetKw",
    "totalRenewableMaxAvailableKw",
    "totalWindCurrentKw",
    "totalWindTargetKw",
    "totalWindMaxAvailableKw",
    "totalPvCurrentKw",
    "totalPvTargetKw",
    "totalPvMaxAvailableKw",
    "totalStorageCurrentKw",
    "totalStorageTargetKw",
    "totalStorageSocPercent",
    "totalGridFollowingStorageCurrentKw",
    "totalGridFollowingStorageTargetKw",
    "totalGridFollowingStorageSocPercent",
    "totalGridFormingStorageCurrentKw",
    "totalGridFormingStorageTargetKw",
    "totalGridFormingStorageSocPercent",
    "totalDieselCurrentKw",
    "totalDieselMinKw",
    "totalDieselTargetKw",
    "totalLoadKw",
    "acdcCurrentKw",
    "acdcTargetKw",
    "electrolyzerCurrentKw",
    "electrolyzerTargetKw",
    "electrolyzerFlowCurrentNm3h",
    "electrolyzerFlowTargetNm3h",
    "fuelCellCurrentKw",
    "fuelCellTargetKw",
    "fuelCellFlowCurrentNm3h",
    "fuelCellFlowTargetNm3h",
    "hydrogenStoragePressureMpa",
    "hydrogenStoragePressureLowGuardMpa",
    "hydrogenStoragePressureHighGuardMpa",
    "hydrogenStorageGasQuantityNm3",
    "hydrogenStorageSocPercent",
    "hydrogenStorageFlowNm3h",
    "observedWindSpeed",
    "observedSolarIrradiance",
)


class TraineeRenewableControlLifecycleError(RuntimeError):
    """Raised when a controller request outlives its captured model service."""


def _stale_receive_prerequisite_status(message: Any) -> bool:
    text = str(message or "").strip()
    return (
        "请先启动接收" in text
        or "等待第一份实时数据" in text
        or "接收已停止" in text
        or text.startswith("学员台实时交换状态不可用")
        or text.startswith("学员台尚未收到实时数据")
    )


@dataclass
class _ControllerState:
    model_id: str
    service_instance_id: str
    settings: RenewableControlSettings = field(default_factory=RenewableControlSettings)
    enabled: bool = False
    desired_enabled: bool = False
    loop_mode: str = "open"
    operation_epoch: int = 0
    sending: bool = False
    status: str = _RENEWABLE_READY_IDLE_STATUS
    last_plan: Optional[Dict[str, Any]] = None
    effective_target_snapshot: Optional[Dict[str, Any]] = None
    last_calculated_at: str = ""
    last_sent_at: str = ""
    last_clock_key: str = ""
    last_dispatched_clock_key: str = ""
    last_dispatched_generation_key: Tuple[Any, ...] = ()
    strategy_generation_active: bool = False
    strategy_cancel_pending: bool = False
    strategy_cancel_operation_epoch: int = 0
    pending_dispatch_clock_key: str = ""
    pending_dispatch_generation_key: Tuple[Any, ...] = ()
    last_auto_started: float = 0.0
    last_preview_started: float = 0.0
    control_clock_run_id: Optional[int] = None
    control_clock_anchor_second: Optional[float] = None
    control_clock_last_second: Optional[float] = None
    control_clock_last_step_count: Optional[int] = None
    background_cycle_pending: bool = False
    plan_revision: int = 0
    revision: int = 0
    log_seq: int = 0
    logs: List[Dict[str, Any]] = field(default_factory=list)
    trend: List[Dict[str, Any]] = field(default_factory=list)
    trend_normalized: bool = False
    performance: _CyclePerformanceWindow = field(
        default_factory=_CyclePerformanceWindow,
        repr=False,
    )
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    run_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)


@dataclass
class _TrendCandidate:
    trend: List[Dict[str, Any]]
    trend_normalized: bool
    persistence_reset: bool = False
    persistence_replace_last: bool = False
    persistence_point: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class _SimulationControlClock:
    state: str
    run_id: int
    step_count: int
    absolute_second: float


class TraineeRenewableControlManager:
    """Model-scoped shared control state and background execution."""

    def __init__(
        self,
        services: Any,
        *,
        snapshot_provider: Callable[[Optional[str]], TraineeControlSnapshot],
        receive_status_provider: Callable[[Optional[str]], Mapping[str, Any]],
        command_sink: Callable[[Optional[str], Mapping[str, Any]], Mapping[str, Any]],
        start_worker: bool = True,
    ) -> None:
        self.services = services
        self.snapshot_provider = snapshot_provider
        self.receive_status_provider = receive_status_provider
        self.command_sink = command_sink
        self._states: Dict[str, _ControllerState] = {}
        self._states_by_service_instance: Dict[str, _ControllerState] = {}
        self._states_lock = threading.RLock()
        self._trend_persistence_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._close_lock = threading.Lock()
        self._background_submit_lock = threading.Lock()
        self._closed = False
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="renewable-control")
        self._worker: Optional[threading.Thread] = None
        if start_worker:
            self._worker = threading.Thread(target=self._worker_loop, name="trainee-renewable-control", daemon=True)
            self._worker.start()

    def close(self) -> None:
        current_thread = threading.current_thread()
        if current_thread is self._worker or current_thread.name.startswith("renewable-control_"):
            raise RuntimeError("新能源控制管理器不能从自身后台工作线程中关闭")
        with self._close_lock:
            if self._closed:
                return
            with self._background_submit_lock:
                self._closed = True
            self._stop_event.set()
            self._wake_worker()
            if self._worker and self._worker.is_alive():
                self._worker.join()
            # Provider/transport calls have finite timeouts and run without broad
            # locks; waiting here guarantees no control task outlives its provider.
            self._executor.shutdown(wait=True, cancel_futures=True)
            with self._states_lock:
                states_by_identity = {
                    id(state): state
                    for state in (
                        list(self._states.values())
                        + list(self._states_by_service_instance.values())
                    )
                }
                states = list(states_by_identity.values())
            for state in states:
                with state.lock:
                    state.background_cycle_pending = False

    def _wake_worker(self) -> None:
        self._wake_event.set()

    def _service_for(self, model_id: Optional[str]) -> Any:
        if hasattr(self.services, "service_for"):
            return self.services.service_for(model_id)
        return self.services

    def _service_is_current_registry_instance(self, service: Any) -> bool:
        if hasattr(self.services, "service_for"):
            try:
                current = self.services.service_for(
                    str(getattr(service, "model_id", "default"))
                )
            except KeyError:
                return False
            return current is service
        return self.services is service

    def _model_id(self, model_id: Optional[str]) -> str:
        service = self._service_for(model_id)
        return str(getattr(service, "model_id", model_id or "default"))

    @staticmethod
    def _service_instance_id(service: Any) -> str:
        value = str(getattr(service, "service_instance_id", "") or "").strip()
        return value or f"object:{id(service)}"

    @staticmethod
    def _service_instance_active_locked(service: Any) -> bool:
        checker = getattr(service, "_service_instance_active_locked", None)
        if callable(checker):
            return bool(checker())
        return not bool(getattr(service, "_service_instance_retired", False))

    @staticmethod
    def _persistence_path_for_service(service: Any) -> Optional[Path]:
        runtime_dir = getattr(service, "runtime_dir", None)
        return Path(runtime_dir) / RENEWABLE_CONTROL_STATE_FILE if runtime_dir else None

    @staticmethod
    def _trend_persistence_path_for_service(service: Any) -> Optional[Path]:
        runtime_dir = getattr(service, "runtime_dir", None)
        return Path(runtime_dir) / RENEWABLE_CONTROL_TREND_FILE if runtime_dir else None

    def _load_trend_for_service(self, service: Any) -> List[Dict[str, Any]]:
        path = self._trend_persistence_path_for_service(service)
        if path is None or not path.exists():
            return []
        points: List[Dict[str, Any]] = []
        try:
            with self._trend_persistence_lock:
                lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        parsed_count = 0
        for line in lines:
            if not line.strip():
                continue
            try:
                point = json.loads(line)
            except (ValueError, TypeError):
                continue
            if not isinstance(point, Mapping):
                continue
            parsed_count += 1
            normalized = dict(point)
            if points and self._trend_lifecycle_changed(points[-1], normalized):
                points = []
            sample_key = str(normalized.get("sampleKey", ""))
            if points and sample_key and str(points[-1].get("sampleKey", "")) == sample_key:
                points[-1] = normalized
            else:
                points.append(normalized)
        latest_segment = self._latest_trend_segment(points)
        if parsed_count != len(latest_segment):
            payload = "".join(
                f"{json.dumps(point, ensure_ascii=False, separators=(',', ':'), default=str)}\n"
                for point in latest_segment
            )
            try:
                with self._trend_persistence_lock:
                    path.write_text(payload, encoding="utf-8")
            except OSError:
                pass
        return latest_segment

    @staticmethod
    def _replace_last_trend_record(path: Path, payload: str) -> None:
        encoded = payload.encode("utf-8")
        with path.open("r+b") as stream:
            stream.seek(0, 2)
            size = stream.tell()
            if size <= 0:
                stream.write(encoded)
                return
            position = size - 1
            while position >= 0:
                stream.seek(position)
                if stream.read(1) not in (b"\r", b"\n"):
                    break
                position -= 1
            while position >= 0:
                stream.seek(position)
                if stream.read(1) == b"\n":
                    position += 1
                    break
                position -= 1
            line_start = max(0, position)
            stream.seek(line_start)
            stream.write(encoded)
            stream.truncate()

    def _persist_trend_candidate_for_service(
        self,
        service: Any,
        candidate: _TrendCandidate,
    ) -> None:
        if candidate.persistence_point is None:
            return
        path = self._trend_persistence_path_for_service(service)
        if path is None:
            return
        points = candidate.trend if candidate.persistence_reset else [candidate.persistence_point]
        payload = "".join(
            f"{json.dumps(point, ensure_ascii=False, separators=(',', ':'), default=str)}\n"
            for point in points
        )
        try:
            with self._trend_persistence_lock:
                path.parent.mkdir(parents=True, exist_ok=True)
                if candidate.persistence_reset:
                    path.write_text(payload, encoding="utf-8")
                elif candidate.persistence_replace_last and path.exists():
                    self._replace_last_trend_record(path, payload)
                else:
                    with path.open("a", encoding="utf-8") as stream:
                        stream.write(payload)
        except OSError:
            # Trend persistence must not interrupt realtime control. The complete
            # in-memory history remains available for the current WEB process.
            return

    def _persistence_path(self, model_id: Optional[str]) -> Optional[Path]:
        return self._persistence_path_for_service(self._service_for(model_id))

    @staticmethod
    def _runtime_settings_for_service(service: Any) -> Mapping[str, Any]:
        getter = getattr(service, "web_runtime_settings", None)
        if not callable(getter):
            return {}
        try:
            payload = getter("trainee")
        except (TypeError, ValueError):
            return {}
        if not isinstance(payload, Mapping):
            return {}
        settings = payload.get("effectiveSettings", payload.get("settings", {}))
        return settings if isinstance(settings, Mapping) else {}

    def _collection_interval_seconds_for_service(self, service: Any) -> float:
        settings = self._runtime_settings_for_service(service)
        try:
            interval = float(
                settings.get(
                    "backend_refresh_seconds",
                    DEFAULT_TRAINEE_BACKEND_REFRESH_SECONDS,
                )
            )
        except (TypeError, ValueError):
            interval = DEFAULT_TRAINEE_BACKEND_REFRESH_SECONDS
        if not math.isfinite(interval) or interval <= 0.0:
            return DEFAULT_TRAINEE_BACKEND_REFRESH_SECONDS
        return interval

    @staticmethod
    def _validate_simulation_control_interval(
        control_interval_seconds: Any,
    ) -> float:
        return _simulation_control_interval_seconds(control_interval_seconds)

    @staticmethod
    def _validate_electrolyzer_soc_hysteresis(
        settings: RenewableControlSettings,
    ) -> None:
        if (
            settings.electrolyzer_storage_soc_start_minimum
            <= settings.electrolyzer_storage_soc_stop_maximum + EPSILON
        ):
            raise ValueError("电制氢启机SOC最小值必须大于停机SOC最大值。")

    def validate_runtime_settings_update_for_service(
        self,
        service: Any,
        payload: Mapping[str, Any],
    ) -> None:
        self._state_for_live_service(service)
        values = payload.get("settings", {})
        if not isinstance(values, Mapping):
            return
        if "backend_refresh_seconds" in values:
            try:
                collection_interval = float(values["backend_refresh_seconds"])
            except (TypeError, ValueError) as exc:
                raise ValueError("后台数据刷新周期必须为有效数字。") from exc
            if not math.isfinite(collection_interval) or collection_interval <= 0.0:
                raise ValueError("后台数据刷新周期必须大于 0 系统秒。")

    def runtime_settings_changed_for_service(self, service: Any) -> bool:
        try:
            state = self._state_for_live_service(service)
        except RuntimeError:
            return False
        with state.lock:
            state.last_preview_started = 0.0
            state.revision += 1
        self._wake_worker()
        return True

    def _load_configuration_for_service(
        self,
        service: Any,
    ) -> Tuple[RenewableControlSettings, str, bool]:
        path = self._persistence_path_for_service(service)
        if path is None or not path.exists():
            return RenewableControlSettings(), "open", False
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return RenewableControlSettings(), "open", False
        if not isinstance(payload, Mapping):
            return RenewableControlSettings(), "open", False
        settings_payload = payload.get("settings")
        settings = RenewableControlSettings().updated(
            settings_payload if isinstance(settings_payload, Mapping) else payload
        )
        loop_mode = "closed" if str(payload.get("loopMode", payload.get("loop_mode", "open"))).lower() == "closed" else "open"
        desired_enabled = bool(
            payload.get(
                "desiredEnabled",
                payload.get("desired_enabled", False),
            )
        )
        return settings, loop_mode, desired_enabled

    def _persist_configuration(
        self,
        service: Any,
        settings: RenewableControlSettings,
        loop_mode: str,
        desired_enabled: bool,
    ) -> None:
        path = self._persistence_path_for_service(service)
        if path is None:
            raise RuntimeError("当前模型没有可用的运行目录，无法持久化新能源控制参数")
        payload = {
            "version": 2,
            "modelId": str(getattr(service, "model_id", "default")),
            "loopMode": "closed" if loop_mode == "closed" else "open",
            "desiredEnabled": bool(desired_enabled),
            "settings": settings.payload(),
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        try:
            temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(path)
        except OSError as exc:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise RuntimeError(f"新能源控制参数持久化失败：{exc}") from exc

    def _require_active_service_for_state_locked(
        self,
        service: Any,
        state: _ControllerState,
    ) -> None:
        if (
            self._service_instance_id(service) != state.service_instance_id
            or not self._service_instance_active_locked(service)
        ):
            raise RuntimeError("新能源控制请求所属模型生命周期已失效或已退休，操作已取消。")

    def _state_for_service(self, service: Any) -> _ControllerState:
        normalized = str(getattr(service, "model_id", "default"))
        service_instance_id = self._service_instance_id(service)
        with self._states_lock:
            state = self._states.get(normalized)
            if state is not None and state.service_instance_id == service_instance_id:
                return state
            state = self._states_by_service_instance.get(service_instance_id)
        if state is None:
            settings, loop_mode, desired_enabled = self._load_configuration_for_service(
                service
            )
            persisted_trend = self._load_trend_for_service(service)
            prerequisite = self._receive_prerequisite_for_service(service)
            enabled = bool(desired_enabled and prerequisite["canRun"])
            if enabled:
                status = _RENEWABLE_AUTO_RESUMED_STATUS
            elif desired_enabled:
                prerequisite_status = str(
                    prerequisite.get("prerequisiteStatus") or "接收尚未就绪。"
                ).rstrip("。")
                status = (
                    f"{prerequisite_status}；新能源实时控制将在接收就绪后自动恢复。"
                )
            else:
                status = _RENEWABLE_READY_IDLE_STATUS
            candidate = _ControllerState(
                normalized,
                service_instance_id,
                settings=settings,
                enabled=enabled,
                desired_enabled=desired_enabled,
                loop_mode=loop_mode,
                status=status,
                trend=persisted_trend,
                trend_normalized=bool(persisted_trend),
            )
            with self._states_lock:
                state = self._states_by_service_instance.setdefault(
                    service_instance_id,
                    candidate,
                )
            if state is candidate and state.enabled:
                self._wake_worker()
        with self._states_lock:
            self._states[normalized] = state
            return state

    def _state_for_live_service(self, service: Any) -> _ControllerState:
        if not self._service_is_current_registry_instance(service):
            raise TraineeRenewableControlLifecycleError(
                "新能源控制请求所属模型生命周期已失效或已退休。"
            )
        service_lock = getattr(service, "lock", None)
        with (service_lock if service_lock is not None else nullcontext()):
            if not self._service_instance_active_locked(service):
                raise TraineeRenewableControlLifecycleError(
                    "新能源控制请求所属模型生命周期已失效或已退休。"
                )
            return self._state_for_service(service)

    def _state_for(self, model_id: Optional[str]) -> _ControllerState:
        return self._state_for_service(self._service_for(model_id))

    @staticmethod
    def _service_bound_provider(
        provider: Callable[..., Any],
        method_name: str,
    ) -> Optional[Callable[[Any], Any]]:
        explicit = getattr(provider, "for_service", None)
        if callable(explicit):
            return explicit
        owner = getattr(provider, "__self__", None)
        candidate = getattr(owner, method_name, None)
        return candidate if callable(candidate) else None

    def _service_lifecycle_valid(self, service: Any, state: _ControllerState) -> bool:
        with state.lock:
            service_lock = getattr(service, "lock", None)
            with (service_lock if service_lock is not None else nullcontext()):
                return bool(
                    self._service_instance_id(service) == state.service_instance_id
                    and self._service_instance_active_locked(service)
                )

    def _require_active_service_for_state(
        self,
        service: Any,
        state: _ControllerState,
    ) -> None:
        with state.lock:
            service_lock = getattr(service, "lock", None)
            with (service_lock if service_lock is not None else nullcontext()):
                self._require_active_service_for_state_locked(service, state)

    def _receive_status_for_service(self, service: Any) -> Dict[str, Any]:
        provider = self._service_bound_provider(
            self.receive_status_provider,
            "receive_status_for_service",
        )
        try:
            payload = (
                provider(service)
                if provider is not None
                else self.receive_status_provider(str(getattr(service, "model_id", "default")))
            )
        except Exception as exc:
            return {
                "receiveActive": False,
                "ready": False,
                "canRun": False,
                "prerequisiteStatus": f"学员台实时交换状态不可用：{exc}",
                "revision": 0,
                "connectionSignature": [],
            }
        return dict(payload) if isinstance(payload, Mapping) else {}

    def _receive_status(self, model_id: Optional[str]) -> Dict[str, Any]:
        return self._receive_status_for_service(self._service_for(model_id))

    def _receive_state_signature_for_service(self, service: Any) -> Tuple[Any, ...]:
        status = self._receive_status_for_service(service)
        signature = status.get("connectionSignature", ())
        if not isinstance(signature, Sequence) or isinstance(signature, (str, bytes)):
            signature = ()
        return (
            bool(status.get("receiveActive")),
            bool(status.get("ready")),
            bool(status.get("controlFrozen") or status.get("simulationPaused")),
            int(_number(status.get("receiveEpoch", status.get("connectionEpoch")), 0.0) or 0),
            tuple(signature),
            int(_number(status.get("revision"), 0.0) or 0),
        )

    def _receive_state_signature(self, model_id: Optional[str]) -> Tuple[Any, ...]:
        return self._receive_state_signature_for_service(self._service_for(model_id))

    @classmethod
    def _receive_state_signature_for_view(
        cls,
        view: TraineeControlSnapshot,
    ) -> Tuple[Any, ...]:
        return (
            bool(view.receive_active),
            bool(view.ready),
            cls._snapshot_simulation_paused(view.snapshot),
            int(view.receive_epoch),
            tuple(view.connection_signature),
            int(view.revision),
        )

    def _candidate_generation_guard(
        self,
        service: Any,
        view: TraineeControlSnapshot,
        receive_signature: Tuple[Any, ...],
    ) -> ContextManager[bool]:
        lease = getattr(view, "control_lease", None)
        if lease is not None:
            return lease.guard()
        return nullcontext(
            self._receive_state_signature_for_service(service) == receive_signature
        )

    @staticmethod
    def _view_matches_controller_state(
        view: TraineeControlSnapshot,
        state: _ControllerState,
    ) -> bool:
        lease = getattr(view, "control_lease", None)
        generation = getattr(lease, "generation", None)
        if generation is None:
            return True
        return str(getattr(generation, "service_instance_id", "")) == state.service_instance_id

    def _receive_prerequisite_for_service(self, service: Any) -> Dict[str, Any]:
        status = self._receive_status_for_service(service)
        active = bool(status.get("receiveActive"))
        ready = bool(status.get("ready"))
        control_frozen = bool(
            status.get("controlFrozen") or status.get("simulationPaused")
        )
        can_run = active and ready and bool(status.get("canRun", True))
        can_calculate = can_run and not control_frozen and bool(
            status.get("canCalculate", True)
        )
        can_dispatch = can_calculate and bool(status.get("canDispatch", can_calculate))
        if not active:
            message = str(status.get("prerequisiteStatus") or "请先启动接收。")
        elif not ready:
            message = str(status.get("prerequisiteStatus") or "学员台正在等待第一份实时数据。")
        else:
            message = str(status.get("prerequisiteStatus") or "") if not can_calculate else ""
        normalized = dict(status)
        normalized.update({
            "receiveActive": active,
            "receiveConfigured": active,
            "ready": ready,
            "canRun": can_run,
            "canCalculate": can_calculate,
            "canDispatch": can_dispatch,
            "controlFrozen": control_frozen,
            "simulationPaused": control_frozen,
            "prerequisiteStatus": message,
            "dispatchStatus": (
                ""
                if control_frozen
                else str(status.get("dispatchStatus") or "")
                if not can_dispatch
                else ""
            ),
        })
        return normalized

    @staticmethod
    def _snapshot_simulation_paused(snapshot: Mapping[str, Any]) -> bool:
        clock = snapshot.get("clock") if isinstance(snapshot.get("clock"), Mapping) else {}
        return str(clock.get("state") or "").strip().casefold() == "paused"

    @staticmethod
    def _simulation_control_clock(
        snapshot: Mapping[str, Any],
    ) -> Optional[_SimulationControlClock]:
        clock = snapshot.get("clock")
        if not isinstance(clock, Mapping):
            return None
        absolute_second = _number(clock.get("absolute_second"))
        if absolute_second is None:
            absolute_minute = _number(
                clock.get("absolute_minute", clock.get("minute"))
            )
            if absolute_minute is None:
                return None
            absolute_second = absolute_minute * 60.0
        if not math.isfinite(absolute_second):
            return None
        return _SimulationControlClock(
            state=str(clock.get("state") or "running").strip().casefold(),
            run_id=int(_number(clock.get("run_id"), 0.0) or 0),
            step_count=int(_number(clock.get("step_count"), 0.0) or 0),
            absolute_second=float(absolute_second),
        )

    @staticmethod
    def _simulation_control_due_locked(
        state: _ControllerState,
        clock: Optional[_SimulationControlClock],
        interval_seconds: float,
    ) -> bool:
        if clock is None or clock.state != "running":
            return False
        lifecycle_changed = bool(
            state.control_clock_run_id is not None
            and (
                clock.run_id != state.control_clock_run_id
                or (
                    state.control_clock_last_step_count is not None
                    and clock.step_count < state.control_clock_last_step_count
                )
                or (
                    state.control_clock_last_second is not None
                    and clock.absolute_second
                    < state.control_clock_last_second - EPSILON
                )
                or (
                    state.control_clock_last_step_count is not None
                    and state.control_clock_last_second is not None
                    and clock.step_count == state.control_clock_last_step_count
                    and clock.absolute_second
                    > state.control_clock_last_second + EPSILON
                )
            )
        )
        if state.control_clock_anchor_second is None or lifecycle_changed:
            state.control_clock_run_id = clock.run_id
            state.control_clock_anchor_second = clock.absolute_second
            state.control_clock_last_second = clock.absolute_second
            state.control_clock_last_step_count = clock.step_count
            return False
        state.control_clock_run_id = clock.run_id
        state.control_clock_last_second = clock.absolute_second
        state.control_clock_last_step_count = clock.step_count
        return (
            clock.absolute_second - state.control_clock_anchor_second
            >= max(MINIMUM_CONTROL_INTERVAL_SECONDS, interval_seconds) - EPSILON
        )

    @staticmethod
    def _mark_simulation_control_started_locked(
        state: _ControllerState,
        clock: _SimulationControlClock,
    ) -> None:
        state.control_clock_run_id = clock.run_id
        state.control_clock_anchor_second = clock.absolute_second
        state.control_clock_last_second = clock.absolute_second
        state.control_clock_last_step_count = clock.step_count

    def _receive_prerequisite(self, model_id: Optional[str]) -> Dict[str, Any]:
        return self._receive_prerequisite_for_service(self._service_for(model_id))

    @staticmethod
    def _dispatch_generation_key(
        view: TraineeControlSnapshot,
        receive_signature: Tuple[Any, ...],
    ) -> Tuple[Any, ...]:
        lease = getattr(view, "control_lease", None)
        generation = getattr(lease, "generation", None)
        if generation is None:
            return tuple(receive_signature)
        return (
            str(getattr(generation, "model_id", "")),
            str(getattr(generation, "service_instance_id", "")),
            int(getattr(generation, "receive_epoch", 0)),
            tuple(getattr(generation, "connection_signature", ())),
            int(getattr(generation, "definition_revision", 0)),
            int(getattr(generation, "runtime_revision", 0)),
        )

    def _control_snapshot(self, model_id: Optional[str]) -> TraineeControlSnapshot:
        return self._control_snapshot_for_service(self._service_for(model_id))

    def _control_snapshot_for_service(self, service: Any) -> TraineeControlSnapshot:
        provider = self._service_bound_provider(
            self.snapshot_provider,
            "control_snapshot_for_service",
        )
        view = (
            provider(service)
            if provider is not None
            else self.snapshot_provider(str(getattr(service, "model_id", "default")))
        )
        if not isinstance(view, TraineeControlSnapshot):
            raise RuntimeError("学员台实时交换服务返回了无效快照契约")
        if not view.ready:
            raise RuntimeError(view.error or "学员台尚未收到实时数据")
        if not isinstance(view.snapshot, Mapping):
            raise RuntimeError("学员台实时交换服务返回的快照不是对象")
        return view

    def _reject_without_receive_for_service(
        self,
        service: Any,
        state: _ControllerState,
        *,
        action_label: str,
        record_log: bool,
        raise_on_retired: bool,
    ) -> Optional[Dict[str, Any]]:
        if not self._service_lifecycle_valid(service, state):
            if raise_on_retired:
                self._require_active_service_for_state(service, state)
            return self._serialize_for_service(service, state)
        prerequisite = self._receive_prerequisite_for_service(service)
        if prerequisite["canRun"]:
            return None
        runtime_log_entry = None
        with state.lock:
            service_lock = getattr(service, "lock", None)
            with (service_lock if service_lock is not None else nullcontext()):
                if not (
                    self._service_instance_id(service) == state.service_instance_id
                    and self._service_instance_active_locked(service)
                ):
                    if raise_on_retired:
                        self._require_active_service_for_state_locked(service, state)
                    return self._serialize_for_service(service, state)
                state.enabled = False
                prerequisite_status = str(
                    prerequisite["prerequisiteStatus"] or "接收尚未就绪。"
                ).rstrip("。")
                state.status = (
                    (
                        "接收已停止；"
                        if not prerequisite.get("receiveActive")
                        else ""
                    )
                    + f"{prerequisite_status}；新能源实时控制将在接收就绪后自动恢复。"
                    if state.desired_enabled
                    else str(prerequisite["prerequisiteStatus"])
                )
                if record_log:
                    runtime_log_entry = self._append_log(
                        state,
                        "策略控制",
                        f"{action_label}阻断",
                        state.status,
                        level="warn",
                        simu_time=state.last_plan.get("time", "--") if state.last_plan else "--",
                        persist_runtime=False,
                    )
                state.revision += 1
        if runtime_log_entry is not None:
            self._persist_runtime_log_for_service(service, state, runtime_log_entry)
        self._wake_worker()
        return self._serialize_for_service(service, state)

    def _reject_without_receive(
        self,
        model_id: Optional[str],
        *,
        action_label: str,
        record_log: bool,
    ) -> Optional[Dict[str, Any]]:
        service = self._service_for(model_id)
        state = self._state_for_service(service)
        return self._reject_without_receive_for_service(
            service,
            state,
            action_label=action_label,
            record_log=record_log,
            raise_on_retired=True,
        )

    def receive_state_changed_for_service(self, service: Any) -> Dict[str, Any]:
        state = self._state_for_service(service)
        prerequisite = self._receive_prerequisite_for_service(service)
        runtime_log_entry = None
        with state.lock:
            service_lock = getattr(service, "lock", None)
            with (service_lock if service_lock is not None else nullcontext()):
                self._require_active_service_for_state_locked(service, state)
                if prerequisite["canRun"]:
                    if state.desired_enabled and not state.enabled:
                        state.enabled = True
                        state.operation_epoch += 1
                        state.last_auto_started = 0.0
                        state.last_preview_started = 0.0
                        state.status = _RENEWABLE_AUTO_RESUMED_STATUS
                        runtime_log_entry = self._append_log(
                            state,
                            "策略控制",
                            "自动恢复",
                            state.status,
                            level="ok",
                            simu_time=(
                                state.last_plan.get("time", "--")
                                if state.last_plan
                                else "--"
                            ),
                            persist_runtime=False,
                        )
                        state.revision += 1
                    elif not state.enabled and _stale_receive_prerequisite_status(state.status):
                        state.status = _RENEWABLE_READY_IDLE_STATUS
                        state.revision += 1
                elif state.enabled:
                    state.enabled = False
                    state.operation_epoch += 1
                    prerequisite_status = str(
                        prerequisite.get("prerequisiteStatus") or "接收已停止。"
                    ).rstrip("。")
                    state.status = (
                        f"接收已停止；{prerequisite_status}；新能源实时控制已暂停，"
                        "将在接收就绪后自动恢复。"
                        if state.desired_enabled
                        else "接收已停止，新能源实时控制同步停止。"
                    )
                    runtime_log_entry = self._append_log(
                        state,
                        "策略控制",
                        "接收联动暂停" if state.desired_enabled else "接收联动停止",
                        state.status,
                        level="warn",
                        simu_time=state.last_plan.get("time", "--") if state.last_plan else "--",
                        persist_runtime=False,
                    )
                    state.revision += 1
                elif state.desired_enabled:
                    prerequisite_status = str(
                        prerequisite.get("prerequisiteStatus") or "接收尚未就绪。"
                    ).rstrip("。")
                    next_status = (
                        (
                            "接收已停止；"
                            if not prerequisite.get("receiveActive")
                            else ""
                        )
                        + f"{prerequisite_status}；新能源实时控制将在接收就绪后自动恢复。"
                    )
                    if state.status != next_status:
                        state.status = next_status
                        state.revision += 1
        if runtime_log_entry is not None:
            self._persist_runtime_log_for_service(service, state, runtime_log_entry)
        self._wake_worker()
        return self._serialize_for_service(service, state)

    def receive_state_changed(self, model_id: Optional[str]) -> Dict[str, Any]:
        return self.receive_state_changed_for_service(self._service_for(model_id))

    def _retire_state(self, state: _ControllerState) -> None:
        with state.lock:
            state.operation_epoch += 1
            state.enabled = False
            state.desired_enabled = False
            state.strategy_generation_active = False
            state.strategy_cancel_pending = False
            state.strategy_cancel_operation_epoch = 0
            state.effective_target_snapshot = None
            state.pending_dispatch_clock_key = ""
            state.pending_dispatch_generation_key = ()
        with self._states_lock:
            if self._states.get(state.model_id) is state:
                self._states.pop(state.model_id, None)
            if self._states_by_service_instance.get(state.service_instance_id) is state:
                self._states_by_service_instance.pop(state.service_instance_id, None)
        self._wake_worker()

    def remove_model_for_service(self, service: Any) -> bool:
        """Cancel and remove only the controller lifecycle for this service."""
        service_instance_id = self._service_instance_id(service)
        with self._states_lock:
            state = self._states_by_service_instance.get(service_instance_id)
        if state is None:
            return False
        self._retire_state(state)
        return True

    def _serialize_cancelled_cycle(
        self,
        service: Any,
        state: _ControllerState,
        *,
        clear_sending: bool,
    ) -> Dict[str, Any]:
        if clear_sending:
            with state.lock:
                if state.sending:
                    state.sending = False
                    state.revision += 1
        return self._serialize_for_service(service, state)

    def _busy_cycle_response(
        self,
        service: Any,
        state: _ControllerState,
        *,
        action_label: str,
        record_log: bool,
        disable_control: bool = False,
        raise_on_retired: bool,
    ) -> Dict[str, Any]:
        runtime_log_entry = None
        with state.lock:
            service_lock = getattr(service, "lock", None)
            with (service_lock if service_lock is not None else nullcontext()):
                if not (
                    self._service_instance_id(service) == state.service_instance_id
                    and self._service_instance_active_locked(service)
                ):
                    if raise_on_retired:
                        self._require_active_service_for_state_locked(service, state)
                    return self._serialize_for_service(service, state)
                if disable_control:
                    state.enabled = False
                state.status = f"新能源控制正在执行上一轮计算，本次{action_label}未执行，请稍后重试。"
                if record_log:
                    runtime_log_entry = self._append_log(
                        state,
                        "策略控制",
                        f"{action_label}忙碌阻断",
                        state.status,
                        level="warn",
                        simu_time=state.last_plan.get("time", "--") if state.last_plan else "--",
                        persist_runtime=False,
                    )
                state.revision += 1
        if runtime_log_entry is not None:
            self._persist_runtime_log_for_service(service, state, runtime_log_entry)
        return self._serialize_for_service(service, state)

    def _append_log(
        self,
        state: _ControllerState,
        log_type: str,
        result: str,
        detail: Any,
        *,
        full_detail: Any = None,
        level: str = "info",
        simu_time: str = "--",
        persist_runtime: bool = True,
    ) -> Dict[str, Any]:
        state.log_seq += 1
        normalized_detail = detail if isinstance(detail, str) else "；".join(str(item) for item in detail if item)
        detail_source = detail if full_detail is None else full_detail
        if isinstance(detail_source, str):
            normalized_full_detail = [detail_source] if detail_source.strip() else []
        elif isinstance(detail_source, Sequence):
            normalized_full_detail = [
                str(item).strip()
                for item in detail_source
                if str(item).strip()
            ]
        else:
            detail_text = str(detail_source).strip() if detail_source is not None else ""
            normalized_full_detail = [detail_text] if detail_text else []
        entry = {
            "seq": state.log_seq,
            "wall_time": _now_text(),
            "simu_time": simu_time or "--",
            "type": log_type,
            "target": "新能源优先",
            "result": result,
            "detail": normalized_detail,
            "full_detail": normalized_full_detail,
            "level": level,
        }
        state.logs.insert(0, entry)
        state.logs = state.logs[:300]
        if persist_runtime:
            self._persist_runtime_log(state, entry)
        return entry

    def _persist_runtime_log(
        self,
        state: _ControllerState,
        entry: Mapping[str, Any],
    ) -> None:
        try:
            target = self._service_for(state.model_id)
            self._persist_runtime_log_for_service(target, state, entry)
        except Exception:
            # A runtime-log persistence failure must not interrupt the controller.
            pass

    def _persist_runtime_log_for_service(
        self,
        service: Any,
        state: _ControllerState,
        entry: Mapping[str, Any],
    ) -> None:
        target_lock = getattr(service, "lock", None)
        with (target_lock if target_lock is not None else nullcontext()):
            if (
                self._service_instance_id(service) != state.service_instance_id
                or not self._service_instance_active_locked(service)
            ):
                return
            append_runtime_log = getattr(service, "_append_runtime_log", None)
            if callable(append_runtime_log):
                append_runtime_log(
                    str(entry.get("type", "")),
                    str(entry.get("target", "新能源优先")),
                    str(entry.get("result", "")),
                    str(entry.get("detail", "")),
                    level=str(entry.get("level", "info")),
                    simu_time=str(entry.get("simu_time", "--")),
                )

    @staticmethod
    def _trend_point(plan: Mapping[str, Any], snapshot: Mapping[str, Any]) -> Dict[str, Any]:
        metrics = plan.get("metrics") if isinstance(plan.get("metrics"), Mapping) else {}
        weather = plan.get("weather") if isinstance(plan.get("weather"), Mapping) else {}
        clock = _measurement_sample_clock(snapshot)
        run_id = int(_number(clock.get("run_id"), 0.0) or 0)
        step_count = int(_number(clock.get("step_count"), 0.0) or 0)
        minute = _number(clock.get("absolute_minute", clock.get("minute")), 0.0) or 0.0

        def metric_total(*keys: str) -> Optional[float]:
            values = [_number(metrics.get(key)) for key in keys]
            finite_values = [value for value in values if value is not None and math.isfinite(value)]
            return sum(finite_values) if finite_values else None

        def metric_value(key: str, *fallback_keys: str) -> Optional[float]:
            value = _number(metrics.get(key))
            if value is not None and math.isfinite(value):
                return value
            return metric_total(*fallback_keys)

        def metric_soc_percent(key: str, *fallback_keys: str) -> Optional[float]:
            value = metric_value(key, *fallback_keys)
            return value * 100.0 if value is not None and math.isfinite(value) else None

        point = {
            "sampleKey": f"{run_id}|{minute}|{clock.get('time', '')}",
            "runId": run_id,
            "stepCount": step_count,
            "minute": minute,
            "time": str(clock.get("time", "--")),
            "loadKw": metrics.get("loadKw"),
            "dieselKw": metrics.get("dieselCurrentKw"),
            "storageKw": metrics.get("storageCurrentKw"),
            "storageSocPercent": metric_soc_percent("storageSoc"),
            "renewableKw": metrics.get("renewableCurrentKw"),
            "acLoadKw": metric_value("acLoadKw"),
            "dcLoadKw": metric_value("dcLoadKw"),
            "dieselCurrentKw": metric_value("dieselCurrentKw", "totalDieselCurrentKw"),
            "dieselTargetKw": metric_value("dieselTargetKw", "totalDieselTargetKw"),
            "acRenewableCurrentKw": metric_value("acRenewableCurrentKw", "acWindCurrentKw", "acPvCurrentKw"),
            "acRenewableTargetKw": metric_value("acRenewableTargetKw", "acWindTargetKw", "acPvTargetKw"),
            "acRenewableMaxAvailableKw": metric_value("acRenewableMaxAvailableKw"),
            "acWindCurrentKw": metric_value("acWindCurrentKw"),
            "acWindTargetKw": metric_value("acWindTargetKw"),
            "acWindMaxAvailableKw": metric_value("acWindMaxAvailableKw"),
            "acPvCurrentKw": metric_value("acPvCurrentKw"),
            "acPvTargetKw": metric_value("acPvTargetKw"),
            "acPvMaxAvailableKw": metric_value("acPvMaxAvailableKw"),
            "dcRenewableCurrentKw": metric_value("dcRenewableCurrentKw", "dcWindCurrentKw", "dcPvCurrentKw"),
            "dcRenewableTargetKw": metric_value("dcRenewableTargetKw", "dcWindTargetKw", "dcPvTargetKw"),
            "dcRenewableMaxAvailableKw": metric_value("dcRenewableMaxAvailableKw"),
            "dcWindCurrentKw": metric_value("dcWindCurrentKw"),
            "dcWindTargetKw": metric_value("dcWindTargetKw"),
            "dcWindMaxAvailableKw": metric_value("dcWindMaxAvailableKw"),
            "dcPvCurrentKw": metric_value("dcPvCurrentKw"),
            "dcPvTargetKw": metric_value("dcPvTargetKw"),
            "dcPvMaxAvailableKw": metric_value("dcPvMaxAvailableKw"),
            "acStorageCurrentKw": metric_value(
                "acStorageCurrentKw",
                "acGridFollowingStorageCurrentKw",
                "acGridFormingStorageCurrentKw",
            ),
            "acStorageTargetKw": metric_value(
                "acStorageTargetKw",
                "acGridFollowingStorageTargetKw",
                "acGridFormingStorageTargetKw",
            ),
            "acStorageSocPercent": metric_soc_percent("acStorageSoc"),
            "dcStorageCurrentKw": metric_value(
                "dcStorageCurrentKw",
                "dcGridFollowingStorageCurrentKw",
                "dcGridFormingStorageCurrentKw",
            ),
            "dcStorageTargetKw": metric_value(
                "dcStorageTargetKw",
                "dcGridFollowingStorageTargetKw",
                "dcGridFormingStorageTargetKw",
            ),
            "dcStorageSocPercent": metric_soc_percent("dcStorageSoc"),
            "acGridFollowingStorageCurrentKw": metric_value("acGridFollowingStorageCurrentKw", "acGridStorageCurrentKw"),
            "acGridFollowingStorageTargetKw": metric_value("acGridFollowingStorageTargetKw", "acGridStorageTargetKw"),
            "dcGridFollowingStorageCurrentKw": metric_value("dcGridFollowingStorageCurrentKw", "dcGridStorageCurrentKw"),
            "dcGridFollowingStorageTargetKw": metric_value("dcGridFollowingStorageTargetKw", "dcGridStorageTargetKw"),
            "acGridFormingStorageCurrentKw": metric_value("acGridFormingStorageCurrentKw", "acBalanceStorageCurrentKw"),
            "acGridFormingStorageTargetKw": metric_value("acGridFormingStorageTargetKw", "acBalanceStorageTargetKw"),
            "dcGridFormingStorageCurrentKw": metric_value("dcGridFormingStorageCurrentKw", "dcBalanceStorageCurrentKw"),
            "dcGridFormingStorageTargetKw": metric_value("dcGridFormingStorageTargetKw", "dcBalanceStorageTargetKw"),
            "acGridFollowingStorageSocPercent": metric_soc_percent("acGridFollowingStorageSoc", "acGridStorageSoc"),
            "dcGridFollowingStorageSocPercent": metric_soc_percent("dcGridFollowingStorageSoc", "dcGridStorageSoc"),
            "acGridFormingStorageSocPercent": metric_soc_percent("acGridFormingStorageSoc", "acBalanceStorageSoc"),
            "dcGridFormingStorageSocPercent": metric_soc_percent("dcGridFormingStorageSoc", "dcBalanceStorageSoc"),
            "acDieselCurrentKw": metric_value("acDieselCurrentKw"),
            "acDieselMinKw": metric_value("acDieselMinKw"),
            "acDieselTargetKw": metric_value("acDieselTargetKw"),
            "dcDieselCurrentKw": metric_value("dcDieselCurrentKw"),
            "dcDieselMinKw": metric_value("dcDieselMinKw"),
            "dcDieselTargetKw": metric_value("dcDieselTargetKw"),
            "totalRenewableCurrentKw": metric_value("totalRenewableCurrentKw", "acRenewableCurrentKw", "dcRenewableCurrentKw"),
            "totalRenewableTargetKw": metric_value("totalRenewableTargetKw", "acRenewableTargetKw", "dcRenewableTargetKw"),
            "totalRenewableMaxAvailableKw": metric_value("totalRenewableMaxAvailableKw"),
            "totalWindCurrentKw": metric_value("totalWindCurrentKw", "acWindCurrentKw", "dcWindCurrentKw"),
            "totalWindTargetKw": metric_value("totalWindTargetKw", "acWindTargetKw", "dcWindTargetKw"),
            "totalWindMaxAvailableKw": metric_value("totalWindMaxAvailableKw"),
            "totalPvCurrentKw": metric_value("totalPvCurrentKw", "acPvCurrentKw", "dcPvCurrentKw"),
            "totalPvTargetKw": metric_value("totalPvTargetKw", "acPvTargetKw", "dcPvTargetKw"),
            "totalPvMaxAvailableKw": metric_value("totalPvMaxAvailableKw"),
            "totalStorageCurrentKw": metric_value(
                "totalStorageCurrentKw",
                "acStorageCurrentKw",
                "dcStorageCurrentKw",
            ),
            "totalStorageTargetKw": metric_value(
                "totalStorageTargetKw",
                "acStorageTargetKw",
                "dcStorageTargetKw",
            ),
            "totalStorageSocPercent": metric_soc_percent("totalStorageSoc"),
            "totalGridFollowingStorageCurrentKw": metric_value("totalGridFollowingStorageCurrentKw", "acGridFollowingStorageCurrentKw", "dcGridFollowingStorageCurrentKw"),
            "totalGridFollowingStorageTargetKw": metric_value("totalGridFollowingStorageTargetKw", "acGridFollowingStorageTargetKw", "dcGridFollowingStorageTargetKw"),
            "totalGridFollowingStorageSocPercent": metric_soc_percent("totalGridFollowingStorageSoc"),
            "totalGridFormingStorageCurrentKw": metric_value("totalGridFormingStorageCurrentKw", "acGridFormingStorageCurrentKw", "dcGridFormingStorageCurrentKw"),
            "totalGridFormingStorageTargetKw": metric_value("totalGridFormingStorageTargetKw", "acGridFormingStorageTargetKw", "dcGridFormingStorageTargetKw"),
            "totalGridFormingStorageSocPercent": metric_soc_percent("totalGridFormingStorageSoc"),
            "totalDieselCurrentKw": metric_value("totalDieselCurrentKw", "acDieselCurrentKw", "dcDieselCurrentKw"),
            "totalDieselMinKw": metric_value("totalDieselMinKw", "acDieselMinKw", "dcDieselMinKw"),
            "totalDieselTargetKw": metric_value("totalDieselTargetKw", "acDieselTargetKw", "dcDieselTargetKw"),
            "totalLoadKw": metric_value("totalLoadKw", "acLoadKw", "dcLoadKw"),
            "acdcCurrentKw": metric_value("acdcCurrentKw"),
            "acdcTargetKw": metric_value("acdcTargetKw"),
            "electrolyzerCurrentKw": metric_value("electrolyzerCurrentKw"),
            "electrolyzerTargetKw": metric_value("electrolyzerTargetKw"),
            "electrolyzerFlowCurrentNm3h": metric_value("electrolyzerFlowCurrentNm3h"),
            "electrolyzerFlowTargetNm3h": metric_value("electrolyzerFlowTargetNm3h"),
            "fuelCellCurrentKw": metric_value("fuelCellCurrentKw"),
            "fuelCellTargetKw": metric_value("fuelCellTargetKw"),
            "fuelCellFlowCurrentNm3h": metric_value("fuelCellFlowCurrentNm3h"),
            "fuelCellFlowTargetNm3h": metric_value("fuelCellFlowTargetNm3h"),
            "hydrogenStoragePressureMpa": metric_value("hydrogenStoragePressureMpa"),
            "hydrogenStoragePressureLowGuardMpa": metric_value("hydrogenStoragePressureLowGuardMpa"),
            "hydrogenStoragePressureHighGuardMpa": metric_value("hydrogenStoragePressureHighGuardMpa"),
            "hydrogenStorageGasQuantityNm3": metric_value("hydrogenStorageGasQuantityNm3"),
            "hydrogenStorageSocPercent": metric_soc_percent("hydrogenStorageSoc"),
            "hydrogenStorageFlowNm3h": metric_value("hydrogenStorageFlowNm3h"),
            "observedWindSpeed": _number(weather.get("observedWindSpeed")),
            "observedSolarIrradiance": _number(weather.get("observedSolarIrradiance")),
        }
        for key in (
            "acGridStorageCurrentKw",
            "acGridStorageTargetKw",
            "acGridStorageSoc",
            "dcGridStorageCurrentKw",
            "dcGridStorageTargetKw",
            "dcGridStorageSoc",
            "acBalanceStorageCurrentKw",
            "acBalanceStorageTargetKw",
            "dcBalanceStorageCurrentKw",
            "dcBalanceStorageTargetKw",
            "acBalanceStorageSoc",
            "dcBalanceStorageSoc",
            "dcRenewableToAcKw",
            "dcTransferGroups",
        ):
            point[key] = _json_safe_copy(metrics.get(key))
        return point

    @staticmethod
    def _command_row_target_key(row: Mapping[str, Any], index: int) -> Tuple[str, ...]:
        identity = tuple(
            str(row.get(key, "")).strip()
            for key in ("dev_type", "dev_name", "set_type")
        )
        return identity if any(identity) else ("index", str(index))

    @classmethod
    def _capture_effective_targets(cls, plan: Mapping[str, Any]) -> Dict[str, Any]:
        metrics = plan.get("metrics") if isinstance(plan.get("metrics"), Mapping) else {}
        rows = plan.get("commandRows")
        command_rows = (
            rows
            if isinstance(rows, Sequence) and not isinstance(rows, (str, bytes))
            else []
        )
        commands = plan.get("commands")
        return {
            "metrics": {
                str(key): _json_safe_copy(value)
                for key, value in metrics.items()
                if "target" in str(key).casefold()
            },
            "commands": _json_safe_copy(
                commands
                if isinstance(commands, Sequence) and not isinstance(commands, (str, bytes))
                else []
            ),
            "commandRows": {
                cls._command_row_target_key(row, index): {
                    key: _json_safe_copy(row.get(key))
                    for key in (
                        "commandKw",
                        "targetKw",
                        "projectedTargetKw",
                        "recoveryKw",
                        "strategyCommand",
                    )
                    if key in row
                }
                for index, row in enumerate(command_rows)
                if isinstance(row, Mapping)
            },
        }

    @classmethod
    def _plan_with_effective_targets(
        cls,
        plan: Mapping[str, Any],
        effective_target_snapshot: Optional[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        if effective_target_snapshot is None:
            return dict(plan)
        metrics = plan.get("metrics") if isinstance(plan.get("metrics"), Mapping) else {}
        effective_target_metrics = effective_target_snapshot.get("metrics")
        if not isinstance(effective_target_metrics, Mapping):
            effective_target_metrics = {}
        published_metrics = {
            str(key): value
            for key, value in metrics.items()
            if "target" not in str(key).casefold()
        }
        published_metrics.update(
            {
                str(key): _json_safe_copy(value)
                for key, value in effective_target_metrics.items()
            }
        )
        published_plan = dict(plan)
        published_plan["metrics"] = published_metrics
        published_plan["commands"] = _json_safe_copy(
            effective_target_snapshot.get("commands", [])
        )
        rows = plan.get("commandRows")
        command_rows = (
            rows
            if isinstance(rows, Sequence) and not isinstance(rows, (str, bytes))
            else []
        )
        effective_command_rows = effective_target_snapshot.get("commandRows")
        if not isinstance(effective_command_rows, Mapping):
            effective_command_rows = {}
        published_rows: List[Dict[str, Any]] = []
        held_fields = {
            "commandKw",
            "targetKw",
            "projectedTargetKw",
            "recoveryKw",
            "strategyCommand",
        }
        for index, row in enumerate(command_rows):
            if not isinstance(row, Mapping):
                continue
            published_row = {
                str(key): value
                for key, value in row.items()
                if key not in held_fields
            }
            target_fields = effective_command_rows.get(
                cls._command_row_target_key(row, index),
                {},
            )
            if isinstance(target_fields, Mapping):
                published_row.update(
                    {
                        str(key): _json_safe_copy(value)
                        for key, value in target_fields.items()
                    }
                )
            published_rows.append(published_row)
        published_plan["commandRows"] = published_rows
        return published_plan

    @staticmethod
    def _trend_lifecycle_changed(previous: Mapping[str, Any], current: Mapping[str, Any]) -> bool:
        previous_run_id = int(_number(previous.get("runId"), 0.0) or 0)
        current_run_id = int(_number(current.get("runId"), 0.0) or 0)
        if previous_run_id != current_run_id:
            return True
        previous_step = _number(previous.get("stepCount"))
        current_step = _number(current.get("stepCount"))
        if previous_step is not None and current_step is not None and current_step < previous_step:
            return True
        previous_minute = _number(previous.get("minute"))
        current_minute = _number(current.get("minute"))
        return (
            previous_minute is not None
            and current_minute is not None
            and current_minute < previous_minute
        )

    @classmethod
    def _latest_trend_segment(cls, points: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
        if not points:
            return []
        segment_start = 0
        for index in range(1, len(points)):
            if cls._trend_lifecycle_changed(points[index - 1], points[index]):
                segment_start = index
        return [dict(point) for point in points[segment_start:]]

    def _update_trend(self, state: Any, plan: Mapping[str, Any], snapshot: Mapping[str, Any]) -> None:
        point = self._trend_point(plan, snapshot)
        if not state.trend_normalized:
            state.trend = self._latest_trend_segment(state.trend)
            state.trend_normalized = True
        if state.trend and self._trend_lifecycle_changed(state.trend[-1], point):
            state.trend = []
        if state.trend and state.trend[-1].get("sampleKey") == point["sampleKey"]:
            state.trend[-1] = point
        else:
            state.trend.append(point)

    def _stage_trend(
        self,
        state: _ControllerState,
        plan: Mapping[str, Any],
        snapshot: Mapping[str, Any],
    ) -> _TrendCandidate:
        with state.lock:
            previous_trend = state.trend
            previous_length = len(previous_trend)
            previous_last = copy.deepcopy(previous_trend[-1]) if previous_trend else None
            was_normalized = state.trend_normalized
            candidate = _TrendCandidate(
                trend=copy.deepcopy(previous_trend),
                trend_normalized=state.trend_normalized,
            )
        self._update_trend(candidate, plan, snapshot)
        current_last = candidate.trend[-1] if candidate.trend else None
        lifecycle_reset = bool(
            previous_last is not None
            and current_last is not None
            and self._trend_lifecycle_changed(previous_last, current_last)
        )
        normalized_reset = bool(
            not was_normalized
            and len(self._latest_trend_segment(previous_trend)) < previous_length
        )
        changed = bool(
            len(candidate.trend) != previous_length
            or previous_last != current_last
        )
        candidate.persistence_reset = lifecycle_reset or normalized_reset
        candidate.persistence_replace_last = bool(
            changed
            and not candidate.persistence_reset
            and previous_last is not None
            and current_last is not None
            and str(previous_last.get("sampleKey", ""))
            == str(current_last.get("sampleKey", ""))
        )
        candidate.persistence_point = copy.deepcopy(current_last) if changed and current_last is not None else None
        return candidate

    def _command_payload(
        self,
        state: _ControllerState,
        plan: Mapping[str, Any],
        snapshot: Mapping[str, Any],
        trigger: str,
        *,
        settings: Optional[RenewableControlSettings] = None,
        loop_mode: Optional[str] = None,
    ) -> Dict[str, Any]:
        metrics = plan.get("metrics") if isinstance(plan.get("metrics"), Mapping) else {}
        clock = _measurement_sample_clock(snapshot)
        metrics_payload = _json_safe_copy(metrics)
        cycle_settings = settings if settings is not None else state.settings
        cycle_loop_mode = loop_mode if loop_mode is not None else state.loop_mode
        strategy_generation = str(plan.get("clockKey", "") or "").strip()
        if not strategy_generation:
            strategy_generation = "|".join(
                str(clock.get(key, "") or "")
                for key in ("run_id", "step_count", "absolute_minute", "time")
            )
        return {
            "source": "trainee-renewable-priority-backend",
            "command_origin": "automatic",
            "strategy_id": RENEWABLE_CONTROL_STRATEGY_ID,
            "generation": strategy_generation,
            "replace_strategy_generation": True,
            "valid_for_minutes": cycle_settings.command_valid_minutes,
            "sent_wall_time": _now_text(),
            "sent_simu_time": str(clock.get("time", "")),
            "sent_absolute_minute": _number(clock.get("absolute_minute", clock.get("minute"))),
            "set_values": copy.deepcopy(plan.get("commands", [])),
            "command_rows": copy.deepcopy(plan.get("commandRows", [])),
            "strategy": {
                "name": "renewable_priority",
                "strategy_id": RENEWABLE_CONTROL_STRATEGY_ID,
                "generation": strategy_generation,
                "replace_strategy_generation": True,
                "loop_mode": cycle_loop_mode,
                "trigger": trigger,
                "time": plan.get("time"),
                "metrics": metrics_payload,
                "load_kw": metrics.get("loadKw"),
                "renewable_available_kw": metrics.get("availableRenewable"),
                "renewable_used_kw": metrics.get("renewableTarget"),
                "storage_kw": metrics.get("storageTarget"),
                "storage_current_kw": metrics.get("storageCurrentKw"),
                "storage_soc": metrics.get("storageSoc"),
                "acdc_current_kw": metrics.get("acdcCurrentKw"),
                "acdc_target_kw": metrics.get("acdcTargetKw"),
                "diesel_residual_kw": metrics.get("dieselResidual"),
                "diesel_min_kw": metrics.get("dieselMinKw"),
                "diesel_target_kw": metrics.get("dieselTargetKw"),
                "curtail_kw": metrics.get("curtailKw"),
                "data_quality": plan.get("dataQuality"),
            },
        }

    def _submit_commands_for_service(
        self,
        service: Any,
        state: _ControllerState,
        payload: Mapping[str, Any],
        *,
        on_transport_start: Optional[Callable[[], None]] = None,
    ) -> Mapping[str, Any]:
        provider = self._service_bound_provider(
            self.command_sink,
            "submit_commands_for_service",
        )
        self._require_active_service_for_state(service, state)
        if on_transport_start is not None:
            on_transport_start()
        if provider is not None:
            return provider(service, payload)  # type: ignore[call-arg]
        return self.command_sink(
            str(getattr(service, "model_id", "default")),
            payload,
        )

    @staticmethod
    def _elapsed_milliseconds(started: float) -> float:
        return max(0.0, (time.perf_counter() - started) * 1000.0)

    @staticmethod
    def _snapshot_for_calculation(view: TraineeControlSnapshot) -> Dict[str, Any]:
        if bool(getattr(view, "snapshot_isolated", False)):
            return view.snapshot
        return copy.deepcopy(dict(view.snapshot))

    @staticmethod
    def _plan_performance_diagnostics(plan: Optional[Mapping[str, Any]]) -> Mapping[str, Any]:
        if not isinstance(plan, Mapping):
            return {}
        diagnostics = plan.get("performanceDiagnostics")
        return diagnostics if isinstance(diagnostics, Mapping) else {}

    def _record_cycle_performance_locked(
        self,
        state: _ControllerState,
        *,
        trigger: str,
        phases_ms: Mapping[str, Any],
        plan: Mapping[str, Any],
        dispatch_attempted: bool,
        dispatch_success: Optional[bool],
    ) -> None:
        plan_diagnostics = self._plan_performance_diagnostics(plan)
        plan_phases = (
            plan_diagnostics.get("phasesMs")
            if isinstance(plan_diagnostics.get("phasesMs"), Mapping)
            else {}
        )
        normalized_phases = {
            str(name): max(0.0, float(value))
            for name, value in {**plan_phases, **dict(phases_ms)}.items()
            if isinstance(value, (int, float)) and math.isfinite(float(value))
        }
        solver = (
            _json_safe_copy(plan_diagnostics.get("solver"))
            if isinstance(plan_diagnostics.get("solver"), Mapping)
            else {}
        )
        solver_success = solver.get("success")
        state.performance.record(
            {
                "wallTime": _now_text(),
                "simulationTime": str(plan.get("time", "--")),
                "clockKey": str(plan.get("clockKey", "")),
                "trigger": str(trigger or "manual"),
                "success": bool(solver_success is not False),
                "dispatchAttempted": bool(dispatch_attempted),
                "dispatchSuccess": dispatch_success,
                "phasesMs": normalized_phases,
                "solver": solver,
            }
        )

    def _exchange_performance_phases_for_service(
        self,
        service: Any,
    ) -> Dict[str, float]:
        try:
            status = self._receive_status_for_service(service)
        except Exception:
            return {}
        seconds_by_phase = {
            "exchangeRequestMs": status.get("requestDurationSeconds"),
            "exchangeProcessingMs": status.get(
                "refreshProcessingDurationSeconds"
            ),
            "exchangePublishMs": status.get("refreshPublishDurationSeconds"),
            "exchangeTotalMs": status.get("refreshTotalDurationSeconds"),
        }
        return {
            name: max(0.0, float(value) * 1000.0)
            for name, value in seconds_by_phase.items()
            if isinstance(value, (int, float)) and math.isfinite(float(value))
        }

    def collect_once(self, model_id: Optional[str]) -> Dict[str, Any]:
        """Refresh the shared plan and trend without changing or dispatching control state."""
        service = self._service_for(model_id)
        state = self._state_for_service(service)
        return self._collect_once_for_service(
            service,
            state,
            raise_on_retired=True,
        )

    def _collect_once_for_service(
        self,
        service: Any,
        state: _ControllerState,
        *,
        raise_on_retired: bool,
        serialization_options: Optional[Mapping[str, Any]] = None,
        snapshot_view: Optional[TraineeControlSnapshot] = None,
        expected_receive_signature: Optional[Tuple[Any, ...]] = None,
    ) -> Dict[str, Any]:
        response_options = dict(serialization_options or {})
        blocked = self._reject_without_receive_for_service(
            service,
            state,
            action_label="实时数据采集",
            record_log=False,
            raise_on_retired=raise_on_retired,
        )
        if blocked is not None:
            return blocked
        if self._receive_prerequisite_for_service(service).get("controlFrozen"):
            return self._serialize_for_service(service, state, **response_options)
        receive_signature = self._receive_state_signature_for_service(service)
        if (
            expected_receive_signature is not None
            and receive_signature != expected_receive_signature
        ):
            return self._serialize_for_service(service, state, **response_options)
        if not state.run_lock.acquire(blocking=False):
            return self._serialize_for_service(service, state, **response_options)
        cycle_started = time.perf_counter()
        cycle_phases: Dict[str, float] = {}
        cycle_plan: Optional[Dict[str, Any]] = None
        try:
            with state.lock:
                service_lock = getattr(service, "lock", None)
                with (service_lock if service_lock is not None else nullcontext()):
                    if not (
                        self._service_instance_id(service) == state.service_instance_id
                        and self._service_instance_active_locked(service)
                    ):
                        if raise_on_retired:
                            self._require_active_service_for_state_locked(service, state)
                        return self._serialize_for_service(service, state)
                operation_epoch = state.operation_epoch
                cycle_settings = state.settings
            snapshot_receive_started = time.perf_counter()
            if snapshot_view is None:
                try:
                    view = self._control_snapshot_for_service(service)
                except RuntimeError:
                    cycle_phases["snapshotReceiveMs"] = self._elapsed_milliseconds(
                        snapshot_receive_started
                    )
                    if not self._service_lifecycle_valid(service, state):
                        return self._serialize_cancelled_cycle(
                            service,
                            state,
                            clear_sending=False,
                        )
                    raise
            else:
                view = snapshot_view
            cycle_phases["snapshotReceiveMs"] = self._elapsed_milliseconds(
                snapshot_receive_started
            )
            snapshot_validation_started = time.perf_counter()
            if not self._view_matches_controller_state(view, state):
                return self._serialize_cancelled_cycle(
                    service,
                    state,
                    clear_sending=False,
                )
            snapshot = self._snapshot_for_calculation(view)
            if self._snapshot_simulation_paused(snapshot):
                return self._serialize_for_service(service, state, **response_options)
            source = view.source
            age = view.age_seconds
            blocked = self._reject_without_receive_for_service(
                service,
                state,
                action_label="实时数据采集",
                record_log=False,
                raise_on_retired=False,
            )
            if blocked is not None:
                return blocked
            if self._receive_state_signature_for_service(service) != receive_signature:
                return self._serialize_cancelled_cycle(
                    service,
                    state,
                    clear_sending=False,
                )
            cycle_phases["snapshotValidationMs"] = self._elapsed_milliseconds(
                snapshot_validation_started
            )
            strategy_compute_started = time.perf_counter()
            plan = calculate_renewable_control_plan(
                snapshot,
                cycle_settings,
                data_source=source,
                snapshot_age_seconds=age,
            )
            cycle_plan = plan
            cycle_phases["strategyComputeMs"] = self._elapsed_milliseconds(
                strategy_compute_started
            )
            with state.lock:
                effective_target_snapshot = (
                    state.effective_target_snapshot
                    if state.effective_target_snapshot is not None
                    else self._capture_effective_targets(plan)
                )
            published_plan = self._plan_with_effective_targets(
                plan,
                effective_target_snapshot,
            )
            trend_started = time.perf_counter()
            trend_candidate = self._stage_trend(state, published_plan, snapshot)
            cycle_phases["trendPostprocessMs"] = self._elapsed_milliseconds(
                trend_started
            )
            committed = False
            with state.lock:
                with self._candidate_generation_guard(
                    service,
                    view,
                    receive_signature,
                ) as generation_valid:
                    if (
                        generation_valid
                        and state.operation_epoch == operation_epoch
                        and self._service_instance_id(service) == state.service_instance_id
                    ):
                        if state.effective_target_snapshot is None:
                            state.effective_target_snapshot = effective_target_snapshot
                        state.last_plan = published_plan
                        state.plan_revision += 1
                        state.last_calculated_at = _now_text()
                        state.last_clock_key = str(plan.get("clockKey", ""))
                        state.trend = trend_candidate.trend
                        state.trend_normalized = trend_candidate.trend_normalized
                        if not state.enabled and _stale_receive_prerequisite_status(state.status):
                            state.status = _RENEWABLE_READY_IDLE_STATUS
                        state.revision += 1
                        committed = True
            if not committed:
                return self._serialize_cancelled_cycle(
                    service,
                    state,
                    clear_sending=False,
                )
            self._persist_trend_candidate_for_service(service, trend_candidate)
        finally:
            if cycle_plan is not None:
                cycle_phases["cycleTotalMs"] = self._elapsed_milliseconds(
                    cycle_started
                )
                cycle_phases.update(
                    self._exchange_performance_phases_for_service(service)
                )
                with state.lock:
                    self._record_cycle_performance_locked(
                        state,
                        trigger="preview",
                        phases_ms=cycle_phases,
                        plan=cycle_plan,
                        dispatch_attempted=False,
                        dispatch_success=None,
                    )
                    state.revision += 1
            state.run_lock.release()
        return self._serialize_for_service(service, state, **response_options)

    def run_once(
        self,
        model_id: Optional[str],
        *,
        trigger: str = "manual",
        allow_dispatch: bool = True,
        record_log: bool = True,
    ) -> Dict[str, Any]:
        service = self._service_for(model_id)
        state = self._state_for_service(service)
        return self._run_once_for_service(
            service,
            state,
            trigger=trigger,
            allow_dispatch=allow_dispatch,
            record_log=record_log,
            raise_on_retired=True,
        )

    def _run_once_for_service(
        self,
        service: Any,
        state: _ControllerState,
        *,
        trigger: str,
        allow_dispatch: bool,
        record_log: bool,
        raise_on_retired: bool,
        snapshot_view: Optional[TraineeControlSnapshot] = None,
        expected_receive_signature: Optional[Tuple[Any, ...]] = None,
    ) -> Dict[str, Any]:
        blocked = self._reject_without_receive_for_service(
            service,
            state,
            action_label="实时控制" if trigger in {"start", "auto"} else "单次计算",
            record_log=record_log,
            raise_on_retired=raise_on_retired,
        )
        if blocked is not None:
            return blocked
        if self._receive_prerequisite_for_service(service).get("controlFrozen"):
            return self._serialize_for_service(service, state)
        receive_signature = self._receive_state_signature_for_service(service)
        if (
            expected_receive_signature is not None
            and receive_signature != expected_receive_signature
        ):
            return self._serialize_for_service(service, state)
        wait_for_running_cycle = trigger in {"manual", "start"}
        if wait_for_running_cycle:
            acquired = state.run_lock.acquire(timeout=_USER_CONTROL_BUSY_WAIT_SECONDS)
        else:
            acquired = state.run_lock.acquire(blocking=False)
        if not acquired:
            if wait_for_running_cycle:
                return self._busy_cycle_response(
                    service,
                    state,
                    action_label="启动实时控制" if trigger == "start" else "单次计算",
                    record_log=record_log,
                    disable_control=trigger == "start",
                    raise_on_retired=raise_on_retired,
                )
            return self._serialize_for_service(service, state)
        cycle_started = time.perf_counter()
        cycle_phases: Dict[str, float] = {}
        cycle_plan: Optional[Dict[str, Any]] = None
        dispatch_attempted = False
        dispatch_success: Optional[bool] = None
        try:
            blocked = self._reject_without_receive_for_service(
                service,
                state,
                action_label="实时控制" if trigger in {"start", "auto"} else "单次计算",
                record_log=record_log,
                raise_on_retired=raise_on_retired,
            )
            if blocked is not None:
                return blocked
            with state.lock:
                service_lock = getattr(service, "lock", None)
                with (service_lock if service_lock is not None else nullcontext()):
                    if not (
                        self._service_instance_id(service) == state.service_instance_id
                        and self._service_instance_active_locked(service)
                    ):
                        if raise_on_retired:
                            self._require_active_service_for_state_locked(service, state)
                        return self._serialize_for_service(service, state)
                operation_epoch = state.operation_epoch
                cycle_settings = state.settings
                cycle_loop_mode = state.loop_mode
                cycle_requires_enabled = trigger in {"start", "auto"}
                if cycle_requires_enabled and not state.enabled:
                    return self._serialize_for_service(service, state)
                state.sending = True
                state.revision += 1
            snapshot_receive_started = time.perf_counter()
            if snapshot_view is None:
                try:
                    view = self._control_snapshot_for_service(service)
                except RuntimeError:
                    cycle_phases["snapshotReceiveMs"] = self._elapsed_milliseconds(
                        snapshot_receive_started
                    )
                    if not self._service_lifecycle_valid(service, state):
                        return self._serialize_cancelled_cycle(
                            service,
                            state,
                            clear_sending=True,
                        )
                    raise
            else:
                view = snapshot_view
            cycle_phases["snapshotReceiveMs"] = self._elapsed_milliseconds(
                snapshot_receive_started
            )
            snapshot_validation_started = time.perf_counter()
            if not self._view_matches_controller_state(view, state):
                return self._serialize_cancelled_cycle(
                    service,
                    state,
                    clear_sending=True,
                )
            snapshot = self._snapshot_for_calculation(view)
            if self._snapshot_simulation_paused(snapshot):
                return self._serialize_cancelled_cycle(
                    service,
                    state,
                    clear_sending=True,
                )
            source = view.source
            age = view.age_seconds
            fetch_error = view.error
            blocked = self._reject_without_receive_for_service(
                service,
                state,
                action_label="实时控制" if trigger in {"start", "auto"} else "单次计算",
                record_log=record_log,
                raise_on_retired=False,
            )
            if blocked is not None:
                with state.lock:
                    state.sending = False
                return self._serialize_for_service(service, state)
            if self._receive_state_signature_for_service(service) != receive_signature:
                return self._serialize_cancelled_cycle(
                    service,
                    state,
                    clear_sending=True,
                )
            cycle_phases["snapshotValidationMs"] = self._elapsed_milliseconds(
                snapshot_validation_started
            )
            strategy_compute_started = time.perf_counter()
            plan = calculate_renewable_control_plan(
                snapshot,
                cycle_settings,
                data_source=source,
                snapshot_age_seconds=age,
            )
            cycle_plan = plan
            cycle_phases["strategyComputeMs"] = self._elapsed_milliseconds(
                strategy_compute_started
            )
            publishes_control_targets = trigger != "preview"
            with state.lock:
                effective_target_snapshot = (
                    self._capture_effective_targets(plan)
                    if publishes_control_targets or state.effective_target_snapshot is None
                    else state.effective_target_snapshot
                )
            published_plan = self._plan_with_effective_targets(
                plan,
                effective_target_snapshot,
            )
            trend_started = time.perf_counter()
            trend_candidate = self._stage_trend(state, published_plan, snapshot)
            cycle_phases["trendPostprocessMs"] = self._elapsed_milliseconds(
                trend_started
            )
            commands = plan.get("commands") if isinstance(plan.get("commands"), Sequence) else []
            quality = plan.get("dataQuality") if isinstance(plan.get("dataQuality"), Mapping) else {}
            dispatch_prerequisite = self._receive_prerequisite_for_service(service)
            dispatch_generation_key = self._dispatch_generation_key(view, receive_signature)
            committed_runtime_logs: List[Dict[str, Any]] = []
            dispatch_payload: Optional[Dict[str, Any]] = None
            dispatch_clock_key = ""
            dispatch_ticket: Any = None
            dispatch_claimed = False
            committed = False
            with state.lock:
                with self._candidate_generation_guard(
                    service,
                    view,
                    receive_signature,
                ) as generation_valid:
                    controller_valid = (
                        state.operation_epoch == operation_epoch
                        and (not cycle_requires_enabled or state.enabled)
                        and self._service_instance_id(service) == state.service_instance_id
                    )
                    if not generation_valid or not controller_valid:
                        committed = False
                    else:
                        if publishes_control_targets or state.effective_target_snapshot is None:
                            state.effective_target_snapshot = effective_target_snapshot
                        state.last_plan = published_plan
                        state.plan_revision += 1
                        state.last_calculated_at = _now_text()
                        state.last_clock_key = str(plan.get("clockKey", ""))
                        state.trend = trend_candidate.trend
                        state.trend_normalized = trend_candidate.trend_normalized
                        if record_log:
                            committed_runtime_logs.append(
                                self._append_log(
                                    state,
                                    "策略决策",
                                    "计算完成",
                                    _compact_decision_log_detail(plan),
                                    full_detail=plan.get("decisionDetail", []),
                                    level=_decision_log_level(plan),
                                    simu_time=str(plan.get("time", "--")),
                                    persist_runtime=False,
                                )
                            )

                        should_dispatch = (
                            allow_dispatch
                            and cycle_loop_mode == "closed"
                            and bool(commands or state.strategy_generation_active)
                        )
                        if should_dispatch and not dispatch_prerequisite["canDispatch"]:
                            state.status = str(
                                dispatch_prerequisite.get("dispatchStatus")
                                or "实时数据状态不允许闭环下发。"
                            )
                            if record_log:
                                committed_runtime_logs.append(
                                    self._append_log(
                                        state,
                                        "策略控制",
                                        "闭环未下发",
                                        state.status,
                                        level="warn",
                                        simu_time=str(plan.get("time", "--")),
                                        persist_runtime=False,
                                    )
                                )
                        elif should_dispatch and not quality.get("dispatchAllowed"):
                            state.status = "控制策略已生成，但输入数据质量不满足闭环下发条件。"
                            if record_log:
                                committed_runtime_logs.append(
                                    self._append_log(
                                        state,
                                        "策略控制",
                                        "闭环未下发",
                                        state.status,
                                        level="warn",
                                        simu_time=str(plan.get("time", "--")),
                                        persist_runtime=False,
                                    )
                                )
                        elif should_dispatch:
                            command_serialize_started = time.perf_counter()
                            payload = self._command_payload(
                                state,
                                plan,
                                snapshot,
                                trigger,
                                settings=cycle_settings,
                                loop_mode=cycle_loop_mode,
                            )
                            cycle_phases["commandSerializeMs"] = (
                                self._elapsed_milliseconds(command_serialize_started)
                            )
                            dispatch_clock_key = str(plan.get("clockKey", "")).strip()
                            duplicate_dispatch = bool(
                                dispatch_clock_key
                                and (
                                    state.last_dispatched_clock_key == dispatch_clock_key
                                    or (
                                        state.pending_dispatch_clock_key == dispatch_clock_key
                                        and state.pending_dispatch_generation_key
                                        == dispatch_generation_key
                                    )
                                )
                            )
                            if duplicate_dispatch:
                                state.status = "当前仿真时刻已下发控制策略，已跳过重复下发。"
                                if record_log:
                                    committed_runtime_logs.append(
                                        self._append_log(
                                            state,
                                            "策略控制",
                                            "重复抑制",
                                            state.status,
                                            level="info",
                                            simu_time=str(plan.get("time", "--")),
                                            persist_runtime=False,
                                        )
                                    )
                            else:
                                # This guarded claim is the dispatch-eligibility
                                # linearization point; transport runs after lock release.
                                if dispatch_clock_key:
                                    state.pending_dispatch_clock_key = dispatch_clock_key
                                    state.pending_dispatch_generation_key = dispatch_generation_key
                                dispatch_payload = payload
                                dispatch_ticket = getattr(generation_valid, "dispatch_ticket", None)
                                dispatch_claimed = True
                        else:
                            if not commands:
                                state.status = "本轮没有可生成的遥调策略。"
                            elif cycle_loop_mode == "open" or not allow_dispatch:
                                state.status = (
                                    f"开环计算完成，生成 {len(commands)} 条遥调策略，"
                                    "未提交学员台指令入口。"
                                )
                            if record_log:
                                committed_runtime_logs.append(
                                    self._append_log(
                                        state,
                                        "策略控制",
                                        "开环未下发" if commands else "无可用策略",
                                        state.status,
                                        level="ok" if commands else "warn",
                                        simu_time=str(plan.get("time", "--")),
                                        persist_runtime=False,
                                    )
                                )
                        if fetch_error and record_log:
                            committed_runtime_logs.append(
                                self._append_log(
                                    state,
                                    "数据状态",
                                    "实时获取失败",
                                    fetch_error,
                                    level="warn",
                                    simu_time=str(plan.get("time", "--")),
                                    persist_runtime=False,
                                )
                            )
                        state.revision += 1
                        committed = True

            if not committed:
                return self._serialize_cancelled_cycle(
                    service,
                    state,
                    clear_sending=True,
                )
            self._persist_trend_candidate_for_service(service, trend_candidate)
            for entry in committed_runtime_logs:
                self._persist_runtime_log(state, entry)

            if dispatch_claimed and dispatch_payload is not None:
                response_runtime_logs: List[Dict[str, Any]] = []
                transport_started = False
                dispatch_attempted = True
                command_dispatch_started = time.perf_counter()

                def mark_transport_started() -> None:
                    nonlocal transport_started
                    with state.lock:
                        controller_valid = (
                            state.operation_epoch == operation_epoch
                            and (not cycle_requires_enabled or state.enabled)
                            and self._service_instance_id(service)
                            == state.service_instance_id
                            and state.pending_dispatch_clock_key == dispatch_clock_key
                            and state.pending_dispatch_generation_key
                            == dispatch_generation_key
                        )
                        if not controller_valid:
                            raise RuntimeError(
                                "控制周期状态或待下发声明已失效，未提交学员台指令。"
                            )
                        transport_started = True
                        if dispatch_clock_key:
                            state.last_dispatched_clock_key = dispatch_clock_key
                            state.last_dispatched_generation_key = dispatch_generation_key
                        if commands:
                            # Treat a transport-started non-empty generation as
                            # potentially active even when the response becomes
                            # ambiguous. An explicit stop will then revoke it.
                            state.strategy_generation_active = True
                        if (
                            state.pending_dispatch_clock_key == dispatch_clock_key
                            and state.pending_dispatch_generation_key == dispatch_generation_key
                        ):
                            state.pending_dispatch_clock_key = ""
                            state.pending_dispatch_generation_key = ()

                try:
                    if dispatch_ticket is not None:
                        with state.lock:
                            dispatch_permit = dispatch_ticket.prepare(
                                dispatch_payload,
                                on_transport_start=mark_transport_started,
                            )
                        result = dispatch_permit.submit()
                    else:
                        result = self._submit_commands_for_service(
                            service,
                            state,
                            dispatch_payload,
                            on_transport_start=mark_transport_started,
                        )
                except Exception as exc:
                    dispatch_success = False
                    with state.lock:
                        if (
                            not transport_started
                            and state.pending_dispatch_clock_key == dispatch_clock_key
                            and state.pending_dispatch_generation_key == dispatch_generation_key
                        ):
                            state.pending_dispatch_clock_key = ""
                            state.pending_dispatch_generation_key = ()
                        result_guard = (
                            dispatch_ticket.guard()
                            if dispatch_ticket is not None
                            else self._candidate_generation_guard(
                                service,
                                view,
                                receive_signature,
                            )
                        )
                        with result_guard as generation_valid:
                            controller_valid = (
                                state.operation_epoch == operation_epoch
                                and (not cycle_requires_enabled or state.enabled)
                                and self._service_instance_id(service) == state.service_instance_id
                            )
                            if generation_valid and controller_valid:
                                state.status = (
                                    f"学员台指令入口提交失败：{exc}；"
                                    "当前仿真时刻不再重复下发。"
                                )
                                if record_log:
                                    response_runtime_logs.append(
                                        self._append_log(
                                            state,
                                            "学员台响应",
                                            "下发失败",
                                            state.status,
                                            level="error",
                                            simu_time=str(plan.get("time", "--")),
                                            persist_runtime=False,
                                        )
                                    )
                else:
                    dispatch_success = True
                    accepted = (
                        int(_number(result.get("set_values"), len(commands)) or 0)
                        if isinstance(result, Mapping)
                        else len(commands)
                    )
                    with state.lock:
                        result_guard = (
                            dispatch_ticket.guard()
                            if dispatch_ticket is not None
                            else self._candidate_generation_guard(
                                service,
                                view,
                                receive_signature,
                            )
                        )
                        with result_guard as generation_valid:
                            controller_valid = (
                                state.operation_epoch == operation_epoch
                                and (not cycle_requires_enabled or state.enabled)
                                and self._service_instance_id(service) == state.service_instance_id
                            )
                            if generation_valid and controller_valid:
                                state.last_sent_at = _now_text()
                                state.strategy_generation_active = bool(commands)
                                state.status = f"已向学员台指令入口提交 {accepted} 条遥调指令。"
                                if record_log:
                                    response_runtime_logs.append(
                                        self._append_log(
                                            state,
                                            "学员台响应",
                                            "下发成功",
                                            f"学员台指令入口接受遥调指令 {accepted} 条；策略时刻 {plan.get('time', '--')}",
                                            level="ok",
                                            simu_time=str(plan.get("time", "--")),
                                            persist_runtime=False,
                                        )
                                    )
                finally:
                    cycle_phases["commandDispatchMs"] = (
                        self._elapsed_milliseconds(command_dispatch_started)
                    )
                for entry in response_runtime_logs:
                    self._persist_runtime_log(state, entry)
        finally:
            if cycle_plan is not None:
                cycle_phases["cycleTotalMs"] = self._elapsed_milliseconds(
                    cycle_started
                )
                cycle_phases.update(
                    self._exchange_performance_phases_for_service(service)
                )
            with state.lock:
                state.sending = False
                if cycle_plan is not None:
                    self._record_cycle_performance_locked(
                        state,
                        trigger=trigger,
                        phases_ms=cycle_phases,
                        plan=cycle_plan,
                        dispatch_attempted=dispatch_attempted,
                        dispatch_success=dispatch_success,
                    )
                state.revision += 1
            state.run_lock.release()
            self._drain_pending_strategy_cancel(service, state)
        return self._serialize_for_service(service, state)

    def _serialize_current_lifecycle(self, state: _ControllerState) -> Dict[str, Any]:
        try:
            current = self._state_for(state.model_id)
        except KeyError:
            current = state
        return self._serialize(current)

    def _serialize_with_prerequisite(
        self,
        state: _ControllerState,
        prerequisite: Mapping[str, Any],
        *,
        compact: bool = False,
        after_log_seq: int = 0,
        after_trend_sample_key: str = "",
        after_plan_revision: Optional[int] = None,
        after_performance_revision: Optional[int] = None,
        after_controller_instance_id: str = "",
    ) -> Dict[str, Any]:
        with state.lock:
            requested_log_seq = max(0, int(after_log_seq or 0))
            logs_reset = requested_log_seq <= 0 or requested_log_seq > state.log_seq
            logs = (
                state.logs
                if logs_reset
                else [
                    entry
                    for entry in state.logs
                    if int(_number(entry.get("seq"), 0.0) or 0) > requested_log_seq
                ]
            )

            requested_controller_instance_id = str(after_controller_instance_id or "")
            requested_sample_key = str(after_trend_sample_key or "")
            if (
                requested_controller_instance_id
                and requested_controller_instance_id != state.service_instance_id
            ):
                requested_sample_key = ""
            trend_reset = not requested_sample_key
            trend = state.trend
            if requested_sample_key:
                matching_index = next(
                    (
                        index
                        for index in range(len(state.trend) - 1, -1, -1)
                        if str(state.trend[index].get("sampleKey", "")) == requested_sample_key
                    ),
                    None,
                )
                if matching_index is None:
                    trend_reset = True
                else:
                    trend_reset = False
                    # Include the cursor point so the browser can replace a sample
                    # that was recomputed within the same simulation instant.
                    trend = state.trend[matching_index:]
            if compact:
                serialized_trend = [
                    {
                        key: _json_safe_copy(point.get(key))
                        for key in _COMPACT_TREND_FIELDS
                        if key in point
                    }
                    for point in trend
                ]
            else:
                serialized_trend = copy.deepcopy(trend)
            plan_cursor_matches = (
                after_plan_revision is not None
                and int(after_plan_revision) == state.plan_revision
                and str(after_controller_instance_id or "") == state.service_instance_id
            )
            performance_cursor_matches = (
                after_performance_revision is not None
                and int(after_performance_revision) == state.performance.revision
                and str(after_controller_instance_id or "") == state.service_instance_id
            )
            control_frozen = bool(prerequisite.get("controlFrozen"))
            payload = {
                "modelId": state.model_id,
                "controllerInstanceId": state.service_instance_id,
                "enabled": state.enabled,
                "desiredEnabled": state.desired_enabled,
                "resumePending": bool(state.desired_enabled and not state.enabled),
                "runState": (
                    "frozen"
                    if control_frozen and state.enabled
                    else "running"
                    if state.enabled
                    else "resume_pending"
                    if state.desired_enabled
                    else "stopped"
                ),
                "loopMode": state.loop_mode,
                "sending": state.sending,
                "settings": state.settings.payload(),
                "status": (
                    "模拟台已暂停，学员台保持冻结；恢复后将继续原运行状态。"
                    if control_frozen
                    else state.status
                ),
                "planRevision": state.plan_revision,
                "performanceRevision": state.performance.revision,
                "lastCalculatedAt": state.last_calculated_at,
                "lastSentAt": state.last_sent_at,
                "lastDispatchedClockKey": state.last_dispatched_clock_key,
                "lastDispatchedGenerationKey": copy.deepcopy(list(state.last_dispatched_generation_key)),
                "revision": state.revision,
                "logs": copy.deepcopy(logs),
                "logsReset": logs_reset,
                "latestLogSeq": state.log_seq,
                "trend": serialized_trend,
                "trendReset": trend_reset,
                "latestTrendSampleKey": str(state.trend[-1].get("sampleKey", "")) if state.trend else "",
                **prerequisite,
            }
            if not plan_cursor_matches:
                payload["lastPlan"] = copy.deepcopy(state.last_plan)
            if not performance_cursor_matches:
                payload["performanceDiagnostics"] = state.performance.payload()
            return payload

    def _serialize_for_service(
        self,
        service: Any,
        state: _ControllerState,
        *,
        compact: bool = False,
        after_log_seq: int = 0,
        after_trend_sample_key: str = "",
        after_plan_revision: Optional[int] = None,
        after_performance_revision: Optional[int] = None,
        after_controller_instance_id: str = "",
    ) -> Dict[str, Any]:
        prerequisite = self._receive_prerequisite_for_service(service)
        return self._serialize_with_prerequisite(
            state,
            prerequisite,
            compact=compact,
            after_log_seq=after_log_seq,
            after_trend_sample_key=after_trend_sample_key,
            after_plan_revision=after_plan_revision,
            after_performance_revision=after_performance_revision,
            after_controller_instance_id=after_controller_instance_id,
        )

    def _serialize(
        self,
        state: _ControllerState,
        *,
        compact: bool = False,
        after_log_seq: int = 0,
        after_trend_sample_key: str = "",
        after_plan_revision: Optional[int] = None,
        after_performance_revision: Optional[int] = None,
        after_controller_instance_id: str = "",
    ) -> Dict[str, Any]:
        try:
            service = self._service_for(state.model_id)
        except KeyError:
            service = None
        if (
            service is None
            or self._service_instance_id(service) != state.service_instance_id
        ):
            prerequisite = {
                "receiveActive": False,
                "receiveConfigured": False,
                "ready": False,
                "canRun": False,
                "canCalculate": False,
                "canDispatch": False,
                "prerequisiteStatus": "模型生命周期已失效或已退休。",
                "dispatchStatus": "模型生命周期已失效或已退休。",
            }
            return self._serialize_with_prerequisite(
                state,
                prerequisite,
                compact=compact,
                after_log_seq=after_log_seq,
                after_trend_sample_key=after_trend_sample_key,
                after_plan_revision=after_plan_revision,
                after_performance_revision=after_performance_revision,
                after_controller_instance_id=after_controller_instance_id,
            )
        return self._serialize_for_service(
            service,
            state,
            compact=compact,
            after_log_seq=after_log_seq,
            after_trend_sample_key=after_trend_sample_key,
            after_plan_revision=after_plan_revision,
            after_performance_revision=after_performance_revision,
            after_controller_instance_id=after_controller_instance_id,
        )

    def state(
        self,
        model_id: Optional[str],
        *,
        refresh: bool = False,
        compact: bool = False,
        after_log_seq: int = 0,
        after_trend_sample_key: str = "",
        after_plan_revision: Optional[int] = None,
        after_performance_revision: Optional[int] = None,
        after_controller_instance_id: str = "",
    ) -> Dict[str, Any]:
        service = self._service_for(model_id)
        return self.state_for_service(
            service,
            refresh=refresh,
            compact=compact,
            after_log_seq=after_log_seq,
            after_trend_sample_key=after_trend_sample_key,
            after_plan_revision=after_plan_revision,
            after_performance_revision=after_performance_revision,
            after_controller_instance_id=after_controller_instance_id,
        )

    def state_for_service(
        self,
        service: Any,
        *,
        refresh: bool = False,
        compact: bool = False,
        after_log_seq: int = 0,
        after_trend_sample_key: str = "",
        after_plan_revision: Optional[int] = None,
        after_performance_revision: Optional[int] = None,
        after_controller_instance_id: str = "",
    ) -> Dict[str, Any]:
        state = self._state_for_live_service(service)
        serialization_options = {
            "compact": compact,
            "after_log_seq": after_log_seq,
            "after_trend_sample_key": after_trend_sample_key,
            "after_plan_revision": after_plan_revision,
            "after_performance_revision": after_performance_revision,
            "after_controller_instance_id": after_controller_instance_id,
        }
        now = time.monotonic()
        collection_interval_seconds = self._collection_interval_seconds_for_service(
            service
        )
        if (
            refresh
            and not state.enabled
            and now - state.last_preview_started >= collection_interval_seconds
        ):
            with state.lock:
                service_lock = getattr(service, "lock", None)
                with (service_lock if service_lock is not None else nullcontext()):
                    self._require_active_service_for_state_locked(service, state)
                    state.last_preview_started = now
            return self._collect_once_for_service(
                service,
                state,
                raise_on_retired=True,
                serialization_options=serialization_options,
            )
        return self._serialize_for_service(service, state, **serialization_options)

    def _submit_background_cycle(
        self,
        state: _ControllerState,
        *,
        timestamp_attr: str,
        timestamp: float,
        callback: Callable[..., Dict[str, Any]],
        args: Tuple[Any, ...],
        kwargs: Mapping[str, Any],
        service: Any = None,
    ) -> bool:
        def run_pending_cycle() -> Dict[str, Any]:
            try:
                return callback(*args, **dict(kwargs))
            finally:
                with state.lock:
                    state.background_cycle_pending = False
                self._wake_worker()

        with self._background_submit_lock:
            if self._closed or self._stop_event.is_set():
                return False
            if service is not None and not self._service_is_current_registry_instance(service):
                return False
            with state.lock:
                service_lock = getattr(service, "lock", None) if service is not None else None
                with (service_lock if service_lock is not None else nullcontext()):
                    if service is not None and not (
                        self._service_instance_active_locked(service)
                        and self._service_instance_id(service) == state.service_instance_id
                    ):
                        return False
                    if state.sending or state.background_cycle_pending or state.run_lock.locked():
                        return False
                    state.background_cycle_pending = True
                    setattr(state, timestamp_attr, timestamp)
                    try:
                        self._executor.submit(run_pending_cycle)
                    except Exception:
                        state.background_cycle_pending = False
                        raise
        return True

    def _execute_pending_strategy_cancel(
        self,
        service: Any,
        state: _ControllerState,
        stop_operation_epoch: int,
    ) -> None:
        with state.lock:
            cancel_allowed = bool(
                state.strategy_cancel_pending
                and state.strategy_cancel_operation_epoch == stop_operation_epoch
                and state.operation_epoch == stop_operation_epoch
                and not state.enabled
                and self._service_instance_id(service) == state.service_instance_id
            )
            if not cancel_allowed:
                if state.strategy_cancel_operation_epoch == stop_operation_epoch:
                    state.strategy_cancel_pending = False
                return
            state.strategy_cancel_pending = False

        cancel_payload = {
            "source": "trainee-renewable-priority-backend",
            "command_origin": "automatic",
            "action": "cancel_strategy_generation",
            "strategy_id": RENEWABLE_CONTROL_STRATEGY_ID,
            "cancel_all_generations": True,
            "reason": "controller_stopped",
        }
        runtime_log_entry = None
        try:
            cancel_result = self._submit_commands_for_service(
                service,
                state,
                cancel_payload,
            )
        except Exception as exc:
            with state.lock:
                if (
                    state.operation_epoch == stop_operation_epoch
                    and not state.enabled
                ):
                    state.status = (
                        "实时控制已停止，但自动指令撤销失败："
                        f"{exc}；残留指令将在有效期结束后退出。"
                    )
                    runtime_log_entry = self._append_log(
                        state,
                        "策略控制",
                        "自动指令撤销失败",
                        state.status,
                        level="error",
                        simu_time=(
                            state.last_plan.get("time", "--")
                            if state.last_plan
                            else "--"
                        ),
                        persist_runtime=False,
                    )
                    state.revision += 1
        else:
            cancelled_generations = int(
                _number(cancel_result.get("cancelled_generations"), 0.0) or 0
            ) if isinstance(cancel_result, Mapping) else 0
            cancelled_controls = int(
                _number(cancel_result.get("cancelled_controls"), 0.0) or 0
            ) if isinstance(cancel_result, Mapping) else 0
            with state.lock:
                if (
                    state.operation_epoch == stop_operation_epoch
                    and not state.enabled
                ):
                    state.strategy_generation_active = False
                    state.effective_target_snapshot = None
                    state.status = (
                        "实时控制已在学员台后台停止，已撤销自动指令。"
                    )
                    runtime_log_entry = self._append_log(
                        state,
                        "策略控制",
                        "自动指令撤销",
                        (
                            f"撤销策略代次 {cancelled_generations} 个，"
                            f"控制点 {cancelled_controls} 个。"
                        ),
                        level="ok",
                        simu_time=(
                            state.last_plan.get("time", "--")
                            if state.last_plan
                            else "--"
                        ),
                        persist_runtime=False,
                    )
                    state.revision += 1
        if runtime_log_entry is not None:
            self._persist_runtime_log_for_service(
                service,
                state,
                runtime_log_entry,
            )

    def _drain_pending_strategy_cancel(
        self,
        service: Any,
        state: _ControllerState,
    ) -> bool:
        with state.lock:
            if not state.strategy_cancel_pending:
                return False
            stop_operation_epoch = state.strategy_cancel_operation_epoch
        if not state.run_lock.acquire(blocking=False):
            return False
        try:
            self._execute_pending_strategy_cancel(
                service,
                state,
                stop_operation_epoch,
            )
        finally:
            state.run_lock.release()
        return True

    def apply_action(self, model_id: Optional[str], payload: Mapping[str, Any]) -> Dict[str, Any]:
        service = self._service_for(model_id)
        state = self._state_for_service(service)
        self._require_active_service_for_state(service, state)
        action = str(payload.get("action", "state")).strip().lower()
        settings_payload = payload.get("settings") if isinstance(payload.get("settings"), Mapping) else payload
        if action in {"update_settings", "settings"}:
            with state.lock:
                service_lock = getattr(service, "lock", None)
                with (service_lock if service_lock is not None else nullcontext()):
                    self._require_active_service_for_state_locked(service, state)
                    requested_interval = next(
                        (
                            settings_payload[key]
                            for key in (
                                "simulation_interval_seconds",
                                "simulationIntervalSeconds",
                                "interval_seconds",
                                "intervalSeconds",
                            )
                            if key in settings_payload
                        ),
                        state.settings.interval_seconds,
                    )
                    self._validate_simulation_control_interval(
                        requested_interval,
                    )
                    next_settings = state.settings.updated(settings_payload)
                    self._validate_simulation_control_interval(
                        next_settings.interval_seconds,
                    )
                    self._validate_electrolyzer_soc_hysteresis(next_settings)
                    self._persist_configuration(
                        service,
                        next_settings,
                        state.loop_mode,
                        state.desired_enabled,
                    )
                    if next_settings != state.settings:
                        state.operation_epoch += 1
                    state.settings = next_settings
                    state.status = (
                        "新能源实时控制参数已更新并持久化；"
                        "自动控制周期为 "
                        f"{next_settings.interval_seconds:g} 仿真秒。"
                    )
                    state.revision += 1
            self._wake_worker()
            return self._serialize_for_service(service, state)
        if action in {"set_loop_mode", "loop_mode"}:
            next_mode = "closed" if str(payload.get("loop_mode", payload.get("loopMode", "open"))).lower() == "closed" else "open"
            runtime_log_entry = None
            with state.lock:
                service_lock = getattr(service, "lock", None)
                with (service_lock if service_lock is not None else nullcontext()):
                    self._require_active_service_for_state_locked(service, state)
                    previous = state.loop_mode
                    self._persist_configuration(
                        service,
                        state.settings,
                        next_mode,
                        state.desired_enabled,
                    )
                    if next_mode != previous:
                        state.operation_epoch += 1
                    state.loop_mode = next_mode
                    state.status = "闭环模式已启用，后续策略由后台下发执行。" if next_mode == "closed" else "开环模式已启用，后台只计算并记录日志。"
                    runtime_log_entry = self._append_log(
                        state,
                        "策略控制",
                        "方式切换",
                        f"{previous} -> {next_mode}；{state.status}",
                        simu_time=state.last_plan.get("time", "--") if state.last_plan else "--",
                        persist_runtime=False,
                    )
                    state.revision += 1
            try:
                self._persist_runtime_log_for_service(service, state, runtime_log_entry)
            except Exception:
                pass
            self._wake_worker()
            return self._serialize_for_service(service, state)
        if action == "start":
            start_operation_epoch = 0
            with state.lock:
                service_lock = getattr(service, "lock", None)
                with (service_lock if service_lock is not None else nullcontext()):
                    self._require_active_service_for_state_locked(service, state)
                    self._validate_simulation_control_interval(
                        state.settings.interval_seconds,
                    )
                    self._persist_configuration(
                        service,
                        state.settings,
                        state.loop_mode,
                        True,
                    )
                    state.operation_epoch += 1
                    start_operation_epoch = state.operation_epoch
                    state.desired_enabled = True
            blocked = self._reject_without_receive_for_service(
                service,
                state,
                action_label="启动实时控制",
                record_log=True,
                raise_on_retired=True,
            )
            if blocked is not None:
                return blocked
            runtime_log_entry = None
            start_cancelled = False
            with state.lock:
                service_lock = getattr(service, "lock", None)
                with (service_lock if service_lock is not None else nullcontext()):
                    self._require_active_service_for_state_locked(service, state)
                    if (
                        state.operation_epoch != start_operation_epoch
                        or not state.desired_enabled
                    ):
                        start_cancelled = True
                    else:
                        state.enabled = True
                        cycle_started_at = time.monotonic()
                        state.last_auto_started = cycle_started_at
                        state.last_preview_started = cycle_started_at
                        state.status = f"{'闭环' if state.loop_mode == 'closed' else '开环'}实时控制已在学员台后台启动。"
                        runtime_log_entry = self._append_log(
                            state,
                            "策略控制",
                            "启动",
                            state.status,
                            level="ok",
                            simu_time=state.last_plan.get("time", "--") if state.last_plan else "--",
                            persist_runtime=False,
                        )
                        state.revision += 1
            if start_cancelled:
                return self._serialize_for_service(service, state)
            defer_initial_cycle = False
            try:
                start_view = self._control_snapshot_for_service(service)
            except (KeyError, RuntimeError):
                start_view = None
            if (
                start_view is not None
                and self._view_matches_controller_state(start_view, state)
            ):
                start_clock = self._simulation_control_clock(start_view.snapshot)
                if start_clock is not None:
                    with state.lock:
                        if (
                            state.operation_epoch == start_operation_epoch
                            and state.desired_enabled
                            and state.enabled
                        ):
                            self._mark_simulation_control_started_locked(
                                state,
                                start_clock,
                            )
                            defer_initial_cycle = bool(
                                start_clock.state != "running"
                                or (
                                    start_clock.step_count <= 0
                                    and start_clock.absolute_second <= EPSILON
                                )
                            )
                            if defer_initial_cycle:
                                state.status = (
                                    f"{'闭环' if state.loop_mode == 'closed' else '开环'}"
                                    "实时控制已启动；仿真数据归零后的控制周期已从 0 重新计数。"
                                )
                                if runtime_log_entry is not None:
                                    runtime_log_entry["detail"] = state.status
                                state.revision += 1
            if runtime_log_entry is not None:
                self._persist_runtime_log_for_service(service, state, runtime_log_entry)
            if defer_initial_cycle:
                self._wake_worker()
                return self._serialize_for_service(service, state)
            result = self._run_once_for_service(
                service,
                state,
                trigger="start",
                allow_dispatch=True,
                record_log=True,
                raise_on_retired=True,
                snapshot_view=start_view,
            )
            self._wake_worker()
            return result
        if action == "stop":
            runtime_log_entry = None
            stop_operation_epoch = 0
            with state.lock:
                service_lock = getattr(service, "lock", None)
                with (service_lock if service_lock is not None else nullcontext()):
                    self._require_active_service_for_state_locked(service, state)
                    was_enabled = state.enabled
                    state.operation_epoch += 1
                    stop_operation_epoch = state.operation_epoch
                    state.enabled = False
                    state.desired_enabled = False
                    persistence_error = ""
                    try:
                        self._persist_configuration(
                            service,
                            state.settings,
                            state.loop_mode,
                            False,
                        )
                    except RuntimeError as exc:
                        persistence_error = str(exc)
                    state.strategy_cancel_pending = state.strategy_generation_active
                    state.effective_target_snapshot = None
                    state.strategy_cancel_operation_epoch = (
                        stop_operation_epoch
                        if state.strategy_cancel_pending
                        else 0
                    )
                    state.status = (
                        "实时控制已在学员台后台停止，正在撤销自动指令。"
                        if state.strategy_cancel_pending
                        else "实时控制已在学员台后台停止。"
                    )
                    if persistence_error:
                        state.status += f" 停止状态持久化失败：{persistence_error}"
                    if was_enabled:
                        runtime_log_entry = self._append_log(
                            state,
                            "策略控制",
                            "停止",
                            state.status,
                            level="warn",
                            simu_time=state.last_plan.get("time", "--") if state.last_plan else "--",
                            persist_runtime=False,
                        )
                    state.revision += 1
            if runtime_log_entry is not None:
                self._persist_runtime_log_for_service(service, state, runtime_log_entry)
            self._drain_pending_strategy_cancel(service, state)
            self._wake_worker()
            return self._serialize_for_service(service, state)
        if action in {"run_once", "calculate"}:
            result = self._run_once_for_service(
                service,
                state,
                trigger="manual",
                allow_dispatch=True,
                record_log=True,
                raise_on_retired=True,
            )
            self._wake_worker()
            return result
        if action in {"refresh", "preview"}:
            result = self._run_once_for_service(
                service,
                state,
                trigger="preview",
                allow_dispatch=False,
                record_log=False,
                raise_on_retired=True,
            )
            self._wake_worker()
            return result
        return self._serialize_for_service(service, state)

    def _run_worker_iteration(self, *, now: Optional[float] = None) -> float:
        iteration_now = time.monotonic() if now is None else float(now)
        next_deadlines: List[float] = []
        enumeration_succeeded = True
        try:
            services = (
                list(self.services.iter_services())
                if hasattr(self.services, "iter_services")
                else [self.services]
            )
        except Exception:
            services = []
            enumeration_succeeded = False
        for target in services:
            if not self._service_is_current_registry_instance(target):
                continue
            try:
                state = self._state_for_live_service(target)
                receive_prerequisite = self._receive_prerequisite_for_service(target)
            except (KeyError, RuntimeError):
                continue
            if receive_prerequisite.get("controlFrozen"):
                next_deadlines.append(iteration_now + 1.0)
                continue
            if not receive_prerequisite["canRun"]:
                if state.enabled or state.desired_enabled:
                    try:
                        self.receive_state_changed_for_service(target)
                    except RuntimeError:
                        pass
                continue
            with state.lock:
                resume_requested = bool(state.desired_enabled and not state.enabled)
            if resume_requested:
                try:
                    self.receive_state_changed_for_service(target)
                except RuntimeError:
                    continue
            collection_interval_seconds = max(
                0.01,
                self._collection_interval_seconds_for_service(target),
            )
            with state.lock:
                cycle_idle = (
                    not state.sending
                    and not state.background_cycle_pending
                    and not state.run_lock.locked()
                )
                enabled = state.enabled
                control_interval_seconds = max(
                    MINIMUM_CONTROL_INTERVAL_SECONDS,
                    float(state.settings.interval_seconds),
                )
                collection_deadline = (
                    state.last_preview_started + collection_interval_seconds
                )
            if not cycle_idle:
                continue
            control_clock: Optional[_SimulationControlClock] = None
            control_view: Optional[TraineeControlSnapshot] = None
            control_receive_signature: Optional[Tuple[Any, ...]] = None
            control_due = False
            if enabled:
                try:
                    control_view = self._control_snapshot_for_service(target)
                except (KeyError, RuntimeError):
                    control_view = None
                if (
                    control_view is not None
                    and self._view_matches_controller_state(control_view, state)
                ):
                    control_clock = self._simulation_control_clock(
                        control_view.snapshot
                    )
                    control_receive_signature = self._receive_state_signature_for_view(
                        control_view
                    )
                    with state.lock:
                        if state.enabled:
                            control_due = self._simulation_control_due_locked(
                                state,
                                control_clock,
                                control_interval_seconds,
                            )
            collection_due = iteration_now >= collection_deadline
            if not control_due and not collection_due:
                next_deadline = collection_deadline
                if enabled:
                    next_deadline = min(next_deadline, iteration_now + 1.0)
                next_deadlines.append(next_deadline)
                continue
            if control_due:
                try:
                    self._validate_simulation_control_interval(
                        control_interval_seconds,
                    )
                except ValueError as exc:
                    with state.lock:
                        state.enabled = False
                        state.desired_enabled = False
                        state.operation_epoch += 1
                        state.status = f"实时控制已停止：{exc}"
                        state.revision += 1
                        try:
                            self._persist_configuration(
                                target,
                                state.settings,
                                state.loop_mode,
                                False,
                            )
                        except RuntimeError as persist_exc:
                            state.status += f" 停止状态持久化失败：{persist_exc}"
                    continue
                submitted = self._submit_background_cycle(
                    state,
                    timestamp_attr="last_auto_started",
                    timestamp=iteration_now,
                    callback=self._run_once_for_service,
                    args=(target, state),
                    kwargs={
                        "trigger": "auto",
                        "allow_dispatch": True,
                        "record_log": True,
                        "raise_on_retired": False,
                        "snapshot_view": control_view,
                        "expected_receive_signature": control_receive_signature,
                    },
                    service=target,
                )
                if submitted:
                    with state.lock:
                        if control_clock is not None:
                            self._mark_simulation_control_started_locked(
                                state,
                                control_clock,
                            )
                        state.last_preview_started = iteration_now
            elif collection_due:
                self._submit_background_cycle(
                    state,
                    timestamp_attr="last_preview_started",
                    timestamp=iteration_now,
                    callback=self._collect_once_for_service,
                    args=(target, state),
                    kwargs={
                        "raise_on_retired": False,
                        "snapshot_view": control_view,
                        "expected_receive_signature": control_receive_signature,
                    },
                    service=target,
                )
        if enumeration_succeeded:
            with self._states_lock:
                states = list(self._states_by_service_instance.values())
            for state in states:
                try:
                    current = self._service_for(state.model_id)
                except KeyError:
                    current = None
                if (
                    current is not None
                    and self._service_instance_id(current) == state.service_instance_id
                ):
                    continue
                self._retire_state(state)
        if not next_deadlines:
            return 1.0
        deadline_now = time.monotonic() if now is None else iteration_now
        return max(0.01, min(1.0, min(next_deadlines) - deadline_now))

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            self._wake_event.clear()
            wait_seconds = self._run_worker_iteration()
            if self._stop_event.wait(0):
                break
            self._wake_event.wait(wait_seconds)
