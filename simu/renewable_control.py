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
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen


EPSILON = 1e-9
GENERATION_CAPACITY_TOLERANCE_RATIO = 0.001
GENERATION_CAPACITY_TOLERANCE_CAP_RATIO = 0.01
MEASUREMENT_NOISE_SIGMA_MULTIPLIER = 5.0
POWER_CONTROL_MODES = {"P", "PQ", "PV", "ACP"}
REMOTE_SNAPSHOT_STATIC_FIELDS = ("definitions", "settings", "device_parameters")
RENEWABLE_CONTROL_STATE_FILE = "renewable_control.json"
DEADBAND_STEP_SCALE = 0.20
DEFAULT_CONVERTER_SOC_POWER_LIMITS = (
    0.0,
    0.0,
    0.2,
    0.4,
    0.4,
    0.5,
    0.6,
    0.8,
    0.8,
    1.0,
)


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


def _normalize_converter_soc_power_limits(values: Any) -> Tuple[float, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise ValueError("变流器SOC功率限额必须包含10个分段值")
    if len(values) != 10:
        raise ValueError("变流器SOC功率限额必须包含10个分段值")
    normalized: List[float] = []
    for index, value in enumerate(values):
        number = _number(value)
        if number is None or number < 0.0 or number > 1.0:
            raise ValueError(f"第{index + 1}个变流器SOC功率限额必须位于0%至100%之间")
        rounded_tenth = round(number * 10.0)
        if abs(number * 10.0 - rounded_tenth) > 1e-7:
            raise ValueError(f"第{index + 1}个变流器SOC功率限额必须采用10%档位")
        normalized.append(rounded_tenth / 10.0)
    for index in range(1, len(normalized)):
        if normalized[index] + EPSILON < normalized[index - 1]:
            raise ValueError(
                f"变流器SOC功率限额必须单调不下降：第{index + 1}档不能低于第{index}档"
            )
    return tuple(normalized)


def _live_soc_ratio(value: Any, default: Optional[float] = None) -> Optional[float]:
    number = _number(value)
    if number is None:
        return default
    if isinstance(value, str) and "%" in value:
        return number / 100.0
    return number


def _command_number(value: float) -> float:
    normalized = 0.0 if abs(value) < 0.0005 else value
    return round(normalized, 3)


def _device_type(device: Mapping[str, Any]) -> str:
    return str(device.get("dev_type", device.get("type", "")))


def _device_name(device: Mapping[str, Any]) -> str:
    return str(device.get("dev_name", device.get("name", "")))


def _device_index(device: Mapping[str, Any]) -> str:
    raw = device.get("raw") if isinstance(device.get("raw"), Mapping) else {}
    return str(device.get("idx", raw.get("idx", ""))).strip()


def _device_key(device: Mapping[str, Any]) -> Tuple[str, str]:
    return _device_type(device), _device_name(device)


def _parameter_rows(snapshot: Mapping[str, Any], block_name: str) -> List[Mapping[str, Any]]:
    parameters = snapshot.get("device_parameters")
    if not isinstance(parameters, Mapping):
        return []
    wanted = block_name.lower()
    for name, rows in parameters.items():
        if str(name).lower() == wanted and isinstance(rows, Sequence) and not isinstance(rows, (str, bytes)):
            return [row for row in rows if isinstance(row, Mapping)]
    return []


def _parameter_name(row: Mapping[str, Any]) -> str:
    return str(row.get("name", row.get("dev_name", "")))


def _indexed_device(snapshot: Mapping[str, Any], dev_type: str, index: Any) -> Optional[Mapping[str, Any]]:
    target = str(index if index is not None else "").strip()
    if not target:
        return None
    for device in snapshot.get("devices", []) or []:
        if isinstance(device, Mapping) and _device_type(device) == dev_type and _device_index(device) == target:
            return device
    return None


def _device_map(snapshot: Mapping[str, Any]) -> Dict[Tuple[str, str], Mapping[str, Any]]:
    return {
        _device_key(device): device
        for device in snapshot.get("devices", []) or []
        if isinstance(device, Mapping)
    }


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
    raw = device.get("raw") if isinstance(device.get("raw"), Mapping) else {}
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
    interval_seconds: float = 2.0
    soc_min: float = 0.3
    soc_max: float = 0.9
    large_step_threshold_kw: float = 10.0
    step_coefficient: float = 0.03
    storage_switch_deadband_kw: float = 5.0
    diesel_deadband_ratio: float = 0.03
    soc_deadband: float = 0.05
    converter_step_ratio: float = 0.03
    converter_soc_power_limits: Tuple[float, ...] = DEFAULT_CONVERTER_SOC_POWER_LIMITS
    command_valid_minutes: float = 120.0

    def normalized(self) -> "RenewableControlSettings":
        minimum = _clamp(float(self.soc_min), 0.0, 1.0)
        maximum = _clamp(float(self.soc_max), minimum, 1.0)
        return replace(
            self,
            interval_seconds=max(1.0, float(self.interval_seconds)),
            soc_min=minimum,
            soc_max=maximum,
            large_step_threshold_kw=max(0.0, float(self.large_step_threshold_kw)),
            step_coefficient=max(0.0, float(self.step_coefficient)),
            storage_switch_deadband_kw=max(0.0, float(self.storage_switch_deadband_kw)),
            diesel_deadband_ratio=max(0.0, float(self.diesel_deadband_ratio)),
            soc_deadband=_clamp(float(self.soc_deadband), 0.0, 1.0),
            converter_step_ratio=max(0.0, float(self.converter_step_ratio)),
            converter_soc_power_limits=_normalize_converter_soc_power_limits(
                self.converter_soc_power_limits
            ),
            command_valid_minutes=max(0.1, float(self.command_valid_minutes)),
        )

    def updated(self, payload: Mapping[str, Any]) -> "RenewableControlSettings":
        aliases = {
            "interval_seconds": ("interval_seconds", "intervalSeconds"),
            "soc_min": ("soc_min", "socMin"),
            "soc_max": ("soc_max", "socMax"),
            "large_step_threshold_kw": ("large_step_threshold_kw", "largeStepThresholdKw"),
            "step_coefficient": ("step_coefficient", "stepCoefficient", "renewableStepRatio"),
            "storage_switch_deadband_kw": ("storage_switch_deadband_kw", "storageSwitchDeadbandKw"),
            "diesel_deadband_ratio": ("diesel_deadband_ratio", "dieselDeadbandRatio"),
            "soc_deadband": ("soc_deadband", "socDeadband"),
            "converter_step_ratio": ("converter_step_ratio", "converterStepRatio"),
            "command_valid_minutes": ("command_valid_minutes", "commandValidMinutes"),
        }
        values: Dict[str, Any] = {}
        for field_name, names in aliases.items():
            for name in names:
                if name in payload:
                    parsed = _number(payload.get(name))
                    if parsed is not None:
                        values[field_name] = parsed
                    break
        for name in ("converter_soc_power_limits", "converterSocPowerLimits"):
            if name in payload:
                values["converter_soc_power_limits"] = _normalize_converter_soc_power_limits(
                    payload.get(name)
                )
                break
        return replace(self, **values).normalized()

    def payload(self) -> Dict[str, Any]:
        return {
            "intervalSeconds": self.interval_seconds,
            "socMin": self.soc_min,
            "socMax": self.soc_max,
            "largeStepThresholdKw": self.large_step_threshold_kw,
            "stepCoefficient": self.step_coefficient,
            "storageSwitchDeadbandKw": self.storage_switch_deadband_kw,
            "renewableStepRatio": self.step_coefficient,
            "dieselDeadbandRatio": self.diesel_deadband_ratio,
            "socDeadband": self.soc_deadband,
            "converterStepRatio": self.converter_step_ratio,
            "converterSocPowerLimits": list(self.converter_soc_power_limits),
            "commandValidMinutes": self.command_valid_minutes,
        }


class _Quality:
    def __init__(self, source: str, snapshot_age_seconds: float) -> None:
        self.source = source
        self.snapshot_age_seconds = max(0.0, float(snapshot_age_seconds))
        self.issues: List[str] = []
        self.inputs: Dict[str, Dict[str, Any]] = {}
        self.blocked = False
        self.dispatch_forbidden = source != "remote"
        if source == "cached":
            self.add("模拟台实时快照获取失败，当前使用最近一次有效快照", dispatch_forbidden=True)
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
    raw = device.get("raw") if device and isinstance(device.get("raw"), Mapping) else {}
    direct = _positive(
        (
            row.get("rated_power"),
            row.get("rated_capacity"),
            row.get("p_max"),
            raw.get("rated_capacity"),
            raw.get("rated_power"),
            raw.get("p_max"),
        )
    )
    if direct > 0 or category != "光伏":
        return direct
    efficiency = _ratio(row.get("module_efficiency", row.get("conversion_efficiency")), None)
    area = _positive((row.get("array_area"), row.get("area")))
    reference = _positive((row.get("reference_irradiance"),), 1000.0)
    return reference * area * efficiency / 1000.0 if efficiency is not None and area > 0 else 0.0


def _bounded_available(
    value: Optional[float],
    row: Mapping[str, Any],
    device: Optional[Mapping[str, Any]],
) -> Optional[float]:
    if value is None:
        return None
    raw = device.get("raw") if device and isinstance(device.get("raw"), Mapping) else {}
    p_min = max(0.0, _number(row.get("p_min", raw.get("p_min")), 0.0) or 0.0)
    raw_max = _number(row.get("p_max", raw.get("p_max")))
    p_max = max(p_min, value) if raw_max is None else max(p_min, raw_max)
    return _clamp(max(0.0, value), p_min, p_max)


def _wind_available(
    row: Mapping[str, Any],
    device: Optional[Mapping[str, Any]],
    wind_speed: Optional[float],
) -> Optional[float]:
    if wind_speed is None:
        return None
    rated = _rated_capacity(row, device, "风电")
    cut_in = _number(row.get("cut_in_wind_speed", row.get("cut_in_speed")))
    rated_speed = _number(row.get("rated_wind_speed"))
    cut_out = _number(row.get("cut_out_wind_speed", row.get("cut_out_speed")))
    if rated <= 0 or cut_in is None or rated_speed is None or cut_out is None:
        return None
    effective_rated = max(rated_speed, cut_in + EPSILON)
    effective_cut_out = max(cut_out, effective_rated + EPSILON)
    speed = max(0.0, wind_speed)
    if speed < cut_in or speed >= effective_cut_out:
        return 0.0
    available = rated if speed >= effective_rated else rated * ((speed - cut_in) / (effective_rated - cut_in)) ** 3
    return _bounded_available(available, row, device)


def _pv_available(
    row: Mapping[str, Any],
    device: Optional[Mapping[str, Any]],
    irradiance: Optional[float],
    air_temperature: Optional[float],
) -> Optional[float]:
    if irradiance is None:
        return None
    rated = _rated_capacity(row, device, "光伏")
    efficiency = _ratio(row.get("module_efficiency", row.get("conversion_efficiency")), None)
    area = _positive((row.get("array_area"), row.get("area")))
    reference_irradiance = max(EPSILON, _number(row.get("reference_irradiance"), 1000.0) or 1000.0)
    reference_temperature = _number(row.get("reference_temperature"), 25.0) or 25.0
    temperature_coefficient = _number(row.get("temp_coefficient"), 0.0) or 0.0
    available = (
        max(0.0, irradiance) * area * efficiency / 1000.0
        if efficiency is not None and area > 0
        else rated * max(0.0, irradiance) / reference_irradiance
    )
    if rated > 0:
        available = min(available, rated)
    if air_temperature is not None:
        available *= max(0.0, 1.0 + temperature_coefficient * (air_temperature - reference_temperature))
    return _bounded_available(available, row, device)


def _load_boundary(
    snapshot: Mapping[str, Any],
    measurements: Mapping[Tuple[str, str, str], MeasurementValue],
    quality: _Quality,
) -> float:
    total = 0.0
    sources: set[str] = set()
    measured_count = 0
    for device in snapshot.get("devices", []) or []:
        if not isinstance(device, Mapping) or _device_type(device) not in {"ACLoad", "DCLoad"}:
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
        if not isinstance(device, Mapping) or _device_type(device) not in {"ACLoad", "DCLoad"}:
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
    planning = _clamp(current, 0.0, capacity_kw) if capacity_kw > 0 else current
    if capacity_kw > 0 and current > capacity_kw:
        weight = _number(measured.row.get("weight"), 0.0) or 0.0
        noise_margin = MEASUREMENT_NOISE_SIGMA_MULTIPLIER / math.sqrt(weight) if weight > 0 else 0.0
        warning_tolerance = max(
            EPSILON,
            min(
                capacity_kw * GENERATION_CAPACITY_TOLERANCE_CAP_RATIO,
                max(capacity_kw * GENERATION_CAPACITY_TOLERANCE_RATIO, noise_margin),
            ),
        )
        if current > capacity_kw + warning_tolerance:
            quality.add(f"{label}实时有功 {current:g} kW 超过额定容量 {capacity_kw:g} kW，规划值按额定容量限幅")
    return current, planning


def _renewable_rows(
    snapshot: Mapping[str, Any],
    measurements: Mapping[Tuple[str, str, str], MeasurementValue],
    wind_speed: Optional[float],
    irradiance: Optional[float],
    air_temperature: Optional[float],
    quality: _Quality,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for category, block_name, dev_type, index_name, candidates in (
        ("风电", "ACWindGen", "ACGenerator", "idx_acgenerator", ("p_set", "p_ac_set")),
        ("光伏", "DCPVGen", "DCGenerator", "idx_dcgenerator", ("p_set",)),
    ):
        for index, parameter in enumerate(_parameter_rows(snapshot, block_name), start=1):
            device = _indexed_device(snapshot, dev_type, parameter.get(index_name))
            name = _device_name(device) if device else _parameter_name(parameter) or f"{dev_type}_{parameter.get(index_name, index)}"
            online = _is_online(device, measurements)
            capacity = _rated_capacity(parameter, device, category)
            measured = _measured(measurements, dev_type, name, ("P_GEN", "P", "P_AC", "P_DC")) if online else None
            current, planning_current = _normalized_generation_current(measured, capacity, quality, f"{category}{name}")
            available = (
                _wind_available(parameter, device, wind_speed)
                if category == "风电"
                else _pv_available(parameter, device, irradiance, air_temperature)
            ) if online else 0.0
            environment_known = wind_speed is not None if category == "风电" else irradiance is not None
            capability_known = available is not None
            set_type = _preferred_set_type(snapshot, device, candidates)
            recovery_ready = planning_current is not None and capacity > 0
            rows.append(
                {
                    "category": category,
                    "dev_type": dev_type,
                    "dev_name": name,
                    "online": online,
                    "environmentKnown": environment_known,
                    "capabilityKnown": capability_known,
                    "capacityKw": capacity,
                    "currentKw": current if online else 0.0,
                    "planningCurrentKw": planning_current if online else 0.0,
                    "headroomKw": max(0.0, capacity - (planning_current or 0.0)) if recovery_ready else 0.0,
                    "commandable": online and bool(set_type) and (capability_known or recovery_ready),
                    "availableKw": available,
                    "set_type": set_type,
                    "statusLabel": (
                        "停用"
                        if not online
                        else "无遥调点"
                        if not set_type
                        else "可控"
                        if capability_known
                        else f"{'风速' if category == '风电' else '辐照'}未知·渐进恢复"
                        if recovery_ready
                        else f"{'风速' if category == '风电' else '辐照'}/实时值未知"
                    ),
                }
            )

    if rows:
        return rows

    devices = _device_map(snapshot)
    for category, block_name, dev_type, candidates in (
        ("风电", "wind_generator", "ACGenerator", ("p_set", "p_ac_set")),
        ("光伏", "pv_generator", "DCGenerator", ("p_set",)),
    ):
        for parameter in _parameter_rows(snapshot, block_name):
            name = _parameter_name(parameter)
            device = devices.get((dev_type, name))
            online = _is_online(device, measurements)
            capacity = _rated_capacity(parameter, device, category)
            measured = _measured(measurements, dev_type, name, ("P_GEN", "P", "P_AC", "P_DC")) if online else None
            current, planning_current = _normalized_generation_current(measured, capacity, quality, f"{category}{name}")
            available = (
                _wind_available(parameter, device, wind_speed)
                if category == "风电"
                else _pv_available(parameter, device, irradiance, air_temperature)
            ) if online else 0.0
            environment_known = wind_speed is not None if category == "风电" else irradiance is not None
            set_type = _preferred_set_type(snapshot, device, candidates)
            rows.append(
                {
                    "category": category,
                    "dev_type": dev_type,
                    "dev_name": name,
                    "online": online,
                    "environmentKnown": environment_known,
                    "capabilityKnown": available is not None,
                    "capacityKw": capacity,
                    "currentKw": current if online else 0.0,
                    "planningCurrentKw": planning_current if online else 0.0,
                    "headroomKw": max(0.0, capacity - (planning_current or 0.0)) if planning_current is not None else 0.0,
                    "commandable": online and bool(set_type) and (available is not None or (planning_current is not None and capacity > 0)),
                    "availableKw": available,
                    "set_type": set_type,
                    "statusLabel": "可控" if online and set_type else "无遥调点" if online else "停用",
                }
            )
    return rows


def _diesel_rows(
    snapshot: Mapping[str, Any],
    measurements: Mapping[Tuple[str, str, str], MeasurementValue],
) -> List[Dict[str, Any]]:
    wind_indexes = {
        str(row.get("idx_acgenerator", "")).strip()
        for row in _parameter_rows(snapshot, "ACWindGen")
        if str(row.get("idx_acgenerator", "")).strip()
    }
    parameters = [*_parameter_rows(snapshot, "diesel_generator"), *_parameter_rows(snapshot, "ACDieselGen")]
    by_name = {_parameter_name(row): row for row in parameters if _parameter_name(row)}
    rows: List[Dict[str, Any]] = []
    for device in snapshot.get("devices", []) or []:
        if not isinstance(device, Mapping) or _device_type(device) != "ACGenerator":
            continue
        if _device_index(device) in wind_indexes:
            continue
        name = _device_name(device)
        raw = device.get("raw") if isinstance(device.get("raw"), Mapping) else {}
        identity = f"{name} {raw.get('dev_type', '')}".lower()
        if name not in by_name and "diesel" not in identity and "柴" not in identity and "source" not in identity:
            continue
        parameter = by_name.get(name, {})
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
        measured = _measured(measurements, "ACGenerator", name, ("P_GEN", "P")) if online else None
        current = measured.value if measured else None
        set_type = _preferred_set_type(snapshot, device, ("p_set", "p_ac_set"))
        rows.append(
            {
                "category": "柴油发电",
                "dev_type": "ACGenerator",
                "dev_name": name,
                "online": online,
                "commandable": False,
                "currentKw": current if online else 0.0,
                "minKw": minimum,
                "capacityKw": capacity,
                "set_type": set_type,
                "statusLabel": "停用" if not online else "平衡运行" if set_type else "无遥调点",
            }
        )
    return rows


def _effective_step_minutes(snapshot: Mapping[str, Any]) -> float:
    parameters = snapshot.get("system_parameters")
    if isinstance(parameters, Mapping):
        effective = _number(parameters.get("effective_step_minutes"))
        if effective is not None and effective > 0:
            return effective
    clock = snapshot.get("clock") if isinstance(snapshot.get("clock"), Mapping) else {}
    step = max(1.0 / 60.0, _number(clock.get("step_minutes"), 1.0) or 1.0)
    speed = max(1.0, _number(clock.get("speed"), 1.0) or 1.0)
    return step * speed


def _storage_rows(
    snapshot: Mapping[str, Any],
    measurements: Mapping[Tuple[str, str, str], MeasurementValue],
    settings: RenewableControlSettings,
    quality: _Quality,
) -> List[Dict[str, Any]]:
    step_hours = max(1.0 / 3600.0, _effective_step_minutes(snapshot) / 60.0)
    rows: List[Dict[str, Any]] = []
    for index, parameter in enumerate(_parameter_rows(snapshot, "DCStorageGen"), start=1):
        device = _indexed_device(snapshot, "DCGenerator", parameter.get("idx_dcgenerator"))
        name = _device_name(device) if device else f"DCGenerator_{parameter.get('idx_dcgenerator', index)}"
        online = _is_online(device, measurements)
        soc_measurement = _measured(measurements, "DCGenerator", name, ("SOC",)) if online else None
        live_soc = _live_soc_ratio(soc_measurement.value) if soc_measurement else None
        fallback_soc = _ratio(
            parameter.get("state_of_charge", parameter.get("soc_curr", parameter.get("soc_cur"))),
            0.5,
        )
        soc = live_soc if live_soc is not None else fallback_soc
        soc_known = live_soc is not None
        if online and not soc_known:
            quality.add(f"储能{name}缺少有效实时SOC，本轮禁止该储能参与充放电调节")
        power = _measured(measurements, "DCGenerator", name, ("P_GEN", "P")) if online else None
        capacity = max(
            EPSILON,
            _positive(
                (
                    parameter.get("energy_capacity"),
                    parameter.get("capacity_kwh"),
                    parameter.get("emva"),
                    (device.get("raw") or {}).get("rated_capacity") if device and isinstance(device.get("raw"), Mapping) else None,
                ),
                1.0,
            ),
        )
        defined_min = _ratio(parameter.get("soc_lower_limit", parameter.get("soc_min")), None)
        defined_max = _ratio(parameter.get("soc_upper_limit", parameter.get("soc_max")), None)
        soc_min = _clamp(defined_min if defined_min is not None else settings.soc_min, 0.0, 1.0)
        soc_max = _clamp(defined_max if defined_max is not None else settings.soc_max, soc_min, 1.0)
        efficiency = max(EPSILON, _ratio(parameter.get("charge_discharge_efficiency"), 1.0) or 1.0)
        charge_max = max(0.0, _number(parameter.get("max_charge_power", parameter.get("charge_p_max")), 0.0) or 0.0)
        discharge_max = max(
            0.0,
            _number(
                parameter.get("max_discharge_power", parameter.get("dis_charge_p_max", parameter.get("discharge_p_max"))),
                0.0,
            )
            or 0.0,
        )
        charge_by_energy = max(0.0, ((soc_max - (soc or 0.0)) * capacity) / (efficiency * step_hours)) if soc_known else 0.0
        discharge_by_energy = max(0.0, (((soc or 0.0) - soc_min) * capacity * efficiency) / step_hours) if soc_known else 0.0
        soc_constraint = (
            "offline"
            if not online
            else "unknown"
            if not soc_known
            else "above_upper"
            if (soc or 0.0) >= soc_max
            else "below_lower"
            if (soc or 0.0) <= soc_min
            else "normal"
        )
        status_label = {
            "offline": "停用",
            "unknown": "SOC未知",
            "above_upper": "SOC达到上限·禁止充电",
            "below_lower": "SOC达到下限·禁止放电",
            "normal": "随网平衡",
        }[soc_constraint]
        rows.append(
            {
                "category": "储能平衡源",
                "dev_type": "DCGenerator",
                "dev_name": name,
                "source_name": name,
                "online": online,
                "commandable": False,
                "currentKw": power.value if power else 0.0 if not online else None,
                "soc": soc,
                "socKnown": soc_known,
                "socMin": soc_min,
                "socMax": soc_max,
                "socConstraint": soc_constraint,
                "capacityKwh": capacity,
                "chargePower": min(charge_max, charge_by_energy),
                "dischargePower": min(discharge_max, discharge_by_energy),
                "efficiency": efficiency,
                "set_type": "",
                "statusLabel": status_label,
            }
        )
    return rows


def _converter_rows(
    snapshot: Mapping[str, Any],
    measurements: Mapping[Tuple[str, str, str], MeasurementValue],
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for device in snapshot.get("devices", []) or []:
        if not isinstance(device, Mapping) or _device_type(device) != "DCACConverter":
            continue
        mode = _runtime_mode(snapshot, device)
        set_type = _preferred_set_type(snapshot, device, ("p_ac_set", "p_set"))
        online = _is_online(device, measurements)
        commandable = online and mode in POWER_CONTROL_MODES and bool(set_type)
        if not commandable:
            continue
        measured = _measured(measurements, "DCACConverter", _device_name(device), ("P_AC", "P_DC", "P"))
        raw = device.get("raw") if isinstance(device.get("raw"), Mapping) else {}
        transfer_capacity = _positive(
            (raw.get("rated_capacity"), raw.get("p_max"), raw.get("max_power"), raw.get("rated_power"))
        )
        rows.append(
            {
                "category": "交直流变流器",
                "dev_type": "DCACConverter",
                "dev_name": _device_name(device),
                "online": online,
                "commandable": commandable,
                "mode": mode,
                "set_type": set_type,
                "currentKw": measured.value if measured else None,
                "transferCapacityKw": transfer_capacity,
                "capacitySource": "model" if transfer_capacity > 0 else "missing",
                "statusLabel": f"并联 {mode}",
            }
        )
    return rows


def _resolve_converter_capacities(
    rows: Sequence[Mapping[str, Any]],
    storage_transfer_capacity_kw: float,
) -> List[Dict[str, Any]]:
    if not rows:
        return []
    fallback_capacity = max(0.0, storage_transfer_capacity_kw) / len(rows)
    resolved: List[Dict[str, Any]] = []
    for source in rows:
        row = dict(source)
        capacity = max(0.0, _number(row.get("transferCapacityKw"), 0.0) or 0.0)
        if capacity <= 0 and fallback_capacity > EPSILON:
            row["transferCapacityKw"] = fallback_capacity
            row["capacitySource"] = "storage_boundary"
        resolved.append(row)
    return resolved


def _allocate(items: Sequence[Mapping[str, Any]], total: float, capacity_key: str) -> List[float]:
    target = max(0.0, total)
    capacities = [max(0.0, _number(item.get(capacity_key), 0.0) or 0.0) for item in items]
    total_capacity = sum(capacities)
    if target <= 0 or total_capacity <= 0:
        return [0.0 for _ in items]
    return [min(capacity, target * capacity / total_capacity) for capacity in capacities]


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


def _converter_soc_limit_ratio(
    soc: Optional[float],
    limits: Sequence[float],
) -> Tuple[float, Optional[int]]:
    if soc is None or not math.isfinite(soc):
        return 1.0, None
    band_index = min(9, max(0, math.floor(soc * 10.0 + EPSILON)))
    return float(limits[band_index]), band_index


def _allocate_converters(rows: Sequence[Mapping[str, Any]], total: float) -> List[float]:
    target = max(0.0, total)
    if not rows or target <= 0:
        return [0.0 for _ in rows]
    if all((_number(row.get("transferCapacityKw"), 0.0) or 0.0) > 0 for row in rows):
        return _allocate(rows, target, "transferCapacityKw")
    return [target / len(rows) for _ in rows]


def _source_label(source: str) -> str:
    return {"remote": "模拟台实时快照", "cached": "最近一次有效模拟台快照", "local": "学员台本地数据"}.get(source, source)


def calculate_renewable_control_plan(
    snapshot: Mapping[str, Any],
    settings: Optional[RenewableControlSettings] = None,
    *,
    data_source: str = "remote",
    snapshot_age_seconds: float = 0.0,
) -> Dict[str, Any]:
    settings = (settings or RenewableControlSettings()).normalized()
    quality = _Quality(data_source, snapshot_age_seconds)
    measurements = _measurement_index(snapshot)
    load_kw = _load_boundary(snapshot, measurements, quality)
    wind_measurement = _measured(measurements, "Environment", "weather", ("WIND_SPEED",))
    irradiance_measurement = _measured(measurements, "Environment", "weather", ("SOLAR_IRRADIANCE",))
    temperature_measurement = _measured(measurements, "Environment", "weather", ("AIR_TEMP",))
    observed_wind_speed = wind_measurement.value if wind_measurement else None
    observed_irradiance = irradiance_measurement.value if irradiance_measurement else None
    observed_air_temperature = temperature_measurement.value if temperature_measurement else None
    wind_speed = None
    irradiance = None
    air_temperature = None
    quality.input("windSpeed", observed_wind_speed, "ignored_by_control_policy", False)
    quality.input("solarIrradiance", observed_irradiance, "ignored_by_control_policy", False)
    quality.input("airTemperature", observed_air_temperature, "ignored_by_control_policy", False)

    renewable_rows = _renewable_rows(
        snapshot,
        measurements,
        wind_speed,
        irradiance,
        air_temperature,
        quality,
    )
    diesel_rows = _diesel_rows(snapshot, measurements)
    storage_rows = _storage_rows(snapshot, measurements, settings, quality)
    converter_rows = _converter_rows(snapshot, measurements)

    finite = lambda value: value if isinstance(value, (int, float)) and math.isfinite(value) else 0.0
    online_renewable = [row for row in renewable_rows if row["online"]]
    missing_renewable_power = [row for row in online_renewable if row.get("currentKw") is None]
    for row in missing_renewable_power:
        quality.add(
            f"{row['category']}{row['dev_name']}缺少有效实时有功，无法计算新能源出力变化量",
            blocked=True,
        )
    capability_unknown_rows = [
        row
        for row in online_renewable
        if row.get("environmentKnown") and not row.get("capabilityKnown")
    ]
    for row in capability_unknown_rows:
        quality.add(
            f"{row['category']}{row['dev_name']}缺少计算最大可发所需的有效模型参数",
            blocked=True,
        )
    renewable_current = sum(finite(row.get("currentKw")) for row in online_renewable)
    renewable_capacity = sum(max(0.0, finite(row.get("capacityKw"))) for row in online_renewable)
    wind_current = sum(finite(row.get("currentKw")) for row in online_renewable if row["category"] == "风电")
    pv_current = sum(finite(row.get("currentKw")) for row in online_renewable if row["category"] == "光伏")

    online_diesel = [row for row in diesel_rows if row["online"]]
    measured_diesel = [row for row in online_diesel if row.get("currentKw") is not None]
    diesel_current = sum(finite(row.get("currentKw")) for row in measured_diesel) if measured_diesel else None
    diesel_min = sum(max(0.0, finite(row.get("minKw"))) for row in online_diesel)
    diesel_capacity = sum(max(0.0, finite(row.get("capacityKw"))) for row in online_diesel)
    diesel_deadband_kw = settings.diesel_deadband_ratio * diesel_capacity

    online_storage = [row for row in storage_rows if row["online"]]
    measured_storage = [row for row in online_storage if row.get("currentKw") is not None]
    storage_current = sum(finite(row.get("currentKw")) for row in measured_storage) if measured_storage else None
    known_soc = [finite(row.get("soc")) for row in online_storage if row.get("socKnown") and row.get("soc") is not None]
    storage_soc = sum(known_soc) / len(known_soc) if known_soc else None
    known_soc_rows = [row for row in online_storage if row.get("socKnown") and row.get("soc") is not None]
    storage_soc_lower_limit = (
        sum(finite(row.get("socMin")) for row in known_soc_rows) / len(known_soc_rows)
        if known_soc_rows
        else None
    )
    storage_soc_upper_limit = (
        sum(finite(row.get("socMax")) for row in known_soc_rows) / len(known_soc_rows)
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
    soc_above_upper_deadband = (
        storage_soc is not None
        and storage_soc_upper_limit is not None
        and storage_soc > storage_soc_upper_limit + settings.soc_deadband + EPSILON
    )
    soc_below_lower_deadband = (
        storage_soc is not None
        and storage_soc_lower_limit is not None
        and storage_soc < storage_soc_lower_limit - settings.soc_deadband - EPSILON
    )
    storage_above_upper = [row for row in online_storage if row.get("socConstraint") == "above_upper"]
    storage_below_lower = [row for row in online_storage if row.get("socConstraint") == "below_lower"]
    raw_charge = sum(max(0.0, finite(row.get("chargePower"))) for row in online_storage)
    raw_discharge = sum(max(0.0, finite(row.get("dischargePower"))) for row in online_storage)
    converter_rows = _resolve_converter_capacities(converter_rows, max(raw_charge, raw_discharge))

    measured_converters = [row for row in converter_rows if row.get("currentKw") is not None]
    converter_current = sum(finite(row.get("currentKw")) for row in measured_converters) if measured_converters else None
    if converter_rows and len(measured_converters) != len(converter_rows):
        quality.add("部分在线功率控制型交直流变流器缺少有效实时有功", dispatch_forbidden=True)
    if any(finite(row.get("transferCapacityKw")) <= 0 for row in converter_rows):
        quality.add("部分在线功率控制型交直流变流器缺少有效容量边界", dispatch_forbidden=True)
    converter_limit = _parallel_converter_limit(converter_rows)
    converter_soc_limit_ratio, converter_soc_band_index = _converter_soc_limit_ratio(
        storage_soc,
        settings.converter_soc_power_limits,
    )
    converter_soc_band_lower_percent = (
        converter_soc_band_index * 10 if converter_soc_band_index is not None else None
    )
    converter_soc_band_upper_percent = (
        min(100, (converter_soc_band_index + 1) * 10)
        if converter_soc_band_index is not None
        else None
    )
    converter_soc_limit = (
        converter_limit * converter_soc_limit_ratio
        if math.isfinite(converter_limit)
        else converter_limit
    )
    storage_power_capacity = max(raw_charge, raw_discharge)
    if converter_rows and math.isfinite(converter_soc_limit):
        storage_power_capacity = (
            min(storage_power_capacity, converter_soc_limit)
            if storage_power_capacity > EPSILON
            else converter_soc_limit
        )
    converter_base_step_kw = (
        settings.converter_step_ratio * converter_limit
        if converter_rows and math.isfinite(converter_limit)
        else 0.0
    )
    if online_storage and not converter_rows:
        quality.add(
            "无在线功率控制型交直流变流器，储能保持当前功率且禁止闭环下发",
            dispatch_forbidden=True,
        )
    if not online_diesel:
        quality.add("没有在线柴油发电机，缺少新能源控制所需的系统平衡基准", blocked=True)
    elif len(measured_diesel) != len(online_diesel):
        quality.add("部分在线柴油发电机缺少有效实时有功，无法可靠计算柴发下调裕度", blocked=True)
    diesel_current_for_control = diesel_current if diesel_current is not None else diesel_min
    if online_storage and len(measured_storage) != len(online_storage):
        quality.add("部分在线储能缺少有效实时有功，闭环控制暂不使用其功率反馈", dispatch_forbidden=True)
    storage_current_for_control = (
        storage_current
        if storage_current is not None
        else -converter_current
        if converter_current is not None
        else 0.0
    )
    converter_current_for_control = (
        min(0.0, converter_current)
        if converter_rows and converter_current is not None and len(measured_converters) == len(converter_rows)
        else -storage_current_for_control
        if converter_rows
        else 0.0
    )
    converter_reverse_power_detected = bool(
        converter_rows
        and converter_current is not None
        and converter_current > EPSILON
    )
    diesel_down_margin = diesel_current_for_control - diesel_min
    diesel_up_margin = max(0.0, diesel_capacity - diesel_current_for_control) if diesel_capacity > EPSILON else 0.0
    storage_min_target = -raw_charge if converter_rows else storage_current_for_control
    storage_max_target = raw_discharge if converter_rows else storage_current_for_control
    converter_lower_target = (
        -converter_soc_limit
        if converter_rows and math.isfinite(converter_soc_limit)
        else min(0.0, converter_current_for_control)
        if converter_rows
        else 0.0
    )
    converter_upper_target = 0.0
    if converter_rows and math.isfinite(converter_soc_limit):
        converter_storage_baseline = storage_current_for_control + converter_current_for_control
        converter_storage_min = converter_storage_baseline - converter_upper_target
        converter_storage_max = converter_storage_baseline - converter_lower_target
        storage_min_target = max(storage_min_target, converter_storage_min)
        storage_max_target = min(storage_max_target, converter_storage_max)
        if abs(converter_current_for_control) > converter_limit + 0.001:
            quality.add("交直流变流器实时有功已经超过并联容量边界", blocked=True)
    if storage_min_target > storage_max_target + EPSILON:
        quality.add("储能SOC功率边界与交直流变流器容量边界没有可行交集", blocked=True)
        fallback_storage_target = _clamp(storage_current_for_control, -raw_charge, raw_discharge)
        storage_min_target = fallback_storage_target
        storage_max_target = fallback_storage_target
    total_charge = max(0.0, -storage_min_target) if converter_rows else 0.0
    total_discharge = max(0.0, storage_max_target) if converter_rows else 0.0
    renewable_balance_limit = 0.0
    diesel_control_region = (
        "high"
        if diesel_current_for_control > diesel_min + diesel_deadband_kw
        else "low"
        if diesel_current_for_control < diesel_min - diesel_deadband_kw
        else "deadband"
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
    renewable_recovery_step_scale = DEADBAND_STEP_SCALE if upper_soc_deadband_active else 1.0
    renewable_curtail_step_scale = 1.0
    renewable_recovery_effective_step_ratio = settings.step_coefficient * renewable_recovery_step_scale
    renewable_curtail_effective_step_ratio = settings.step_coefficient * renewable_curtail_step_scale
    renewable_recovery_step_request_kw = sum(
        min(
            max(0.0, finite(row.get("capacityKw")) - finite(row.get("planningCurrentKw"))),
            renewable_recovery_effective_step_ratio * max(0.0, finite(row.get("capacityKw"))),
        )
        for row in online_renewable
        if row.get("commandable") and row.get("planningCurrentKw") is not None
    )
    renewable_curtail_step_request_kw = sum(
        min(
            max(0.0, finite(row.get("planningCurrentKw"))),
            renewable_curtail_effective_step_ratio * max(0.0, finite(row.get("capacityKw"))),
        )
        for row in online_renewable
        if row.get("commandable") and row.get("planningCurrentKw") is not None
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
    if not converter_rows or storage_soc is None:
        storage_control_action = "hold"
    elif soc_above_upper_deadband:
        raw_converter_desired_target = converter_lower_target
        storage_control_action = "increase_discharge_above_soc_upper_deadband"
    elif soc_below_lower_deadband:
        raw_converter_desired_target = 0.0
        storage_control_action = (
            "stop_discharge_below_soc_lower_deadband"
            if converter_current_for_control < -EPSILON
            else "reverse_power_forbidden_below_soc_lower_deadband"
        )
    elif soc_at_or_above_upper:
        if converter_current_for_control > EPSILON:
            raw_converter_desired_target = 0.0
            storage_control_action = "stop_reverse_power_at_soc_upper"
        elif diesel_control_region == "high":
            raw_converter_desired_target = max(
                converter_lower_target,
                converter_current_for_control - max(0.0, diesel_down_margin),
            )
            storage_control_action = "increase_discharge"
        elif diesel_control_region == "low" and converter_current_for_control < -EPSILON:
            raw_converter_desired_target = 0.0
            storage_control_action = "reduce_discharge_low_diesel"
    elif soc_at_or_below_lower:
        raw_converter_desired_target = 0.0
        storage_control_action = (
            "stop_discharge_at_soc_lower"
            if converter_current_for_control < -EPSILON
            else "stop_reverse_power_at_soc_lower"
            if converter_current_for_control > EPSILON
            else "hold_at_soc_lower"
        )
    elif diesel_control_region == "high":
        raw_converter_desired_target = max(
            converter_lower_target,
            converter_current_for_control - max(0.0, diesel_down_margin),
        )
        storage_control_action = "increase_discharge"
    elif diesel_control_region == "low":
        raw_converter_desired_target = 0.0
        storage_control_action = (
            "reduce_discharge_low_diesel"
            if converter_current_for_control < -EPSILON
            else "stop_reverse_power_low_diesel"
            if converter_current_for_control > EPSILON
            else "hold_low_diesel"
        )

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
    unbounded_converter_desired_target = (
        storage_current_for_control
        + converter_current_for_control
        - desired_storage_target
        if converter_rows
        else 0.0
    )
    converter_desired_target = _clamp(
        unbounded_converter_desired_target,
        converter_lower_target,
        converter_upper_target,
    )
    converter_hard_limit_applied = converter_hard_limit_applied or (
        abs(converter_desired_target - unbounded_converter_desired_target) > 0.001
    )
    converter_step_direction = (
        "increase"
        if converter_desired_target > converter_current_for_control + EPSILON
        else "decrease"
        if converter_desired_target < converter_current_for_control - EPSILON
        else "hold"
    )
    converter_slow_increase = (
        converter_step_direction == "increase"
        and (lower_soc_deadband_active or diesel_deadband_active)
    )
    converter_step_scale = DEADBAND_STEP_SCALE if converter_slow_increase else 1.0
    converter_step_kw = converter_base_step_kw * converter_step_scale
    stepped_converter_target = (
        _move_toward(converter_current_for_control, converter_desired_target, converter_step_kw)
        if converter_rows
        else 0.0
    )
    converter_target = _clamp(
        stepped_converter_target,
        converter_lower_target,
        converter_upper_target,
    )
    converter_hard_limit_applied = converter_hard_limit_applied or (
        abs(converter_target - stepped_converter_target) > 0.001
    )
    storage_target = (
        storage_current_for_control + converter_current_for_control - converter_target
        if converter_rows
        else storage_current_for_control
    )
    storage_candidate_target = desired_storage_target
    storage_deadband_action = storage_control_action
    converter_step_limited = abs(converter_target - converter_desired_target) > 0.001

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

    if storage_soc is None or storage_soc_upper_limit is None:
        renewable_control_action = "hold_unknown_soc"
    elif storage_soc < storage_soc_upper_limit - EPSILON:
        renewable_control_action = "recover_one_step"
    elif diesel_current_for_control <= diesel_min + diesel_deadband_kw + EPSILON:
        renewable_control_action = "curtail_one_step_full_soc"
    else:
        renewable_control_action = "recover_one_step"

    renewable_step_direction = (
        "increase"
        if renewable_control_action == "recover_one_step"
        else "decrease"
        if renewable_control_action == "curtail_one_step_full_soc"
        else "hold"
    )
    renewable_step_scale = (
        renewable_recovery_step_scale
        if renewable_step_direction == "increase"
        else renewable_curtail_step_scale
    )
    renewable_effective_step_ratio = settings.step_coefficient * renewable_step_scale
    renewable_target_by_device: Dict[Tuple[str, str], Optional[float]] = {}
    for row in online_renewable:
        key = (row["dev_type"], row["dev_name"])
        if row.get("planningCurrentKw") is None:
            renewable_target_by_device[key] = None
            continue
        current_kw = finite(row.get("planningCurrentKw"))
        capacity_kw = max(0.0, finite(row.get("capacityKw")))
        step_kw = renewable_effective_step_ratio * capacity_kw
        if not row.get("commandable"):
            target_kw = current_kw
        elif renewable_control_action == "curtail_one_step_full_soc":
            target_kw = max(0.0, current_kw - step_kw)
        elif renewable_control_action == "recover_one_step":
            target_kw = min(capacity_kw, current_kw + step_kw)
        else:
            target_kw = current_kw
        renewable_target_by_device[key] = _clamp(target_kw, 0.0, capacity_kw) if capacity_kw > EPSILON else 0.0

    renewable_target = sum(finite(value) for value in renewable_target_by_device.values())
    renewable_delta = renewable_target - renewable_current
    storage_delta = storage_target - storage_current_for_control
    current_diesel_violation = _diesel_boundary_violation(
        diesel_current_for_control,
        diesel_min,
        diesel_capacity,
    )
    candidate_effect = storage_delta
    predicted_diesel = diesel_current_for_control - candidate_effect
    diesel_target = predicted_diesel
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
    storage_by_name = {row["dev_name"]: storage_allocations[index] for index, row in enumerate(online_storage)}

    diesel_dispatch = [{**row, "headroomKw": max(0.0, row["capacityKw"] - row["minKw"])} for row in online_diesel]
    diesel_additional = max(0.0, diesel_target - diesel_min)
    diesel_headroom = sum(row["headroomKw"] for row in diesel_dispatch)
    diesel_additional_allocations = (
        _allocate(diesel_dispatch, diesel_additional, "headroomKw")
        if diesel_headroom > 0
        else [diesel_additional / max(1, len(diesel_dispatch)) for _ in diesel_dispatch]
    )
    diesel_by_name = {
        row["dev_name"]: row["minKw"] + diesel_additional_allocations[index]
        for index, row in enumerate(diesel_dispatch)
    }

    converter_direction = 1.0 if converter_target > 0 else -1.0 if converter_target < 0 else 0.0
    converter_allocations = [
        value * converter_direction
        for value in _allocate_converters(converter_rows, abs(converter_target))
    ]
    converter_target = sum(converter_allocations) if converter_rows else 0.0

    command_rows: List[Dict[str, Any]] = []
    for row in renewable_rows:
        key = (row["dev_type"], row["dev_name"])
        strategy_command = (
            row["commandable"] and row["capabilityKnown"]
            if row["environmentKnown"]
            else row["commandable"] and row.get("planningCurrentKw") is not None and finite(row.get("capacityKw")) > 0
        )
        command_rows.append(
            {
                **row,
                "recoveryKw": max(
                    0.0,
                    finite(renewable_target_by_device.get(key)) - finite(row.get("currentKw")),
                ),
                "strategyCommand": strategy_command,
                "commandKw": (
                    renewable_target_by_device.get(key)
                    if row.get("online") and key in renewable_target_by_device
                    else finite(row.get("planningCurrentKw"))
                    if row.get("online") and row.get("planningCurrentKw") is not None
                    else None
                    if row.get("online")
                    else 0.0
                ),
            }
        )
    command_rows.extend(
        {
            **row,
            "commandable": False,
            "strategyCommand": False,
            "availableKw": max(finite(row.get("chargePower")), finite(row.get("dischargePower"))) if row["online"] else 0.0,
            "commandKw": storage_by_name.get(row["dev_name"], 0.0),
        }
        for row in storage_rows
    )
    command_rows.extend(
        {
            **row,
            "commandable": False,
            "strategyCommand": False,
            "availableKw": row["capacityKw"],
            "commandKw": diesel_by_name.get(row["dev_name"], row["minKw"]) if row["online"] else 0.0,
        }
        for row in diesel_rows
    )
    command_rows.extend(
        {
            **row,
            "ratedAvailableKw": row["transferCapacityKw"]
            if row["transferCapacityKw"] > 0
            else max(total_charge, total_discharge) / max(1, len(converter_rows)),
            "availableKw": row["transferCapacityKw"] * converter_soc_limit_ratio
            if row["transferCapacityKw"] > 0
            else (
                max(total_charge, total_discharge)
                * converter_soc_limit_ratio
                / max(1, len(converter_rows))
            ),
            "socLimitRatio": converter_soc_limit_ratio,
            "strategyCommand": True,
            "commandKw": converter_allocations[index],
        }
        for index, row in enumerate(converter_rows)
    )

    commands = [
        {
            "dev_type": row["dev_type"],
            "dev_name": row["dev_name"],
            "set_type": row["set_type"],
            "set_value": _command_number(float(row["commandKw"])),
        }
        for row in command_rows
        if row.get("online")
        and row.get("commandable") is not False
        and row.get("strategyCommand") is not False
        and row.get("set_type")
        and isinstance(row.get("commandKw"), (int, float))
        and math.isfinite(float(row["commandKw"]))
    ]

    warnings: List[str] = []
    if any(row["category"] == "风电" for row in renewable_rows) and wind_speed is None:
        warnings.append("风速量测默认不参与新能源控制，风电按当前出力与容量执行渐进恢复")
    if any(row["category"] == "光伏" for row in renewable_rows) and irradiance is None:
        warnings.append("太阳辐照度量测默认不参与新能源控制，光伏按当前出力与容量执行渐进恢复")
    warnings.extend(issue for issue in quality.issues if issue not in warnings)

    wind_available = sum(
        max(0.0, finite(row.get("capacityKw")))
        for row in renewable_rows
        if row["category"] == "风电" and row.get("online")
    )
    pv_available = sum(
        max(0.0, finite(row.get("capacityKw")))
        for row in renewable_rows
        if row["category"] == "光伏" and row.get("online")
    )
    available_renewable = wind_available + pv_available
    curtail_kw = max(0.0, available_renewable - renewable_target)
    recovery_kw = max(0.0, renewable_delta)
    recovery_candidate_count = sum(
        1
        for row in online_renewable
        if row.get("commandable") and finite(row.get("capacityKw")) > finite(row.get("currentKw")) + EPSILON
    )
    clock = snapshot.get("clock") if isinstance(snapshot.get("clock"), Mapping) else {}
    time_text = str(clock.get("time", "--"))
    run_id = int(_number(clock.get("run_id"), 0.0) or 0)
    clock_key = f"{run_id}|{clock.get('absolute_minute', clock.get('minute', ''))}|{time_text}"
    quality_payload = quality.payload()
    metrics = {
        "availableRenewable": available_renewable,
        "renewableCurrentKw": renewable_current,
        "windCurrentKw": wind_current,
        "pvCurrentKw": pv_current,
        "windAvailable": wind_available,
        "pvAvailable": pv_available,
        "storageChargeAvailable": total_charge,
        "storageDischargeAvailable": total_discharge,
        "storageCurrentKw": storage_current,
        "storageSoc": storage_soc,
        "storageSocLowerLimit": storage_soc_lower_limit,
        "storageSocUpperLimit": storage_soc_upper_limit,
        "storageSocRegion": storage_soc_region,
        "socDeadband": settings.soc_deadband,
        "lowerSocDeadbandActive": lower_soc_deadband_active,
        "upperSocDeadbandActive": upper_soc_deadband_active,
        "socAboveUpperDeadband": soc_above_upper_deadband,
        "socBelowLowerDeadband": soc_below_lower_deadband,
        "socUpperDeadbandThreshold": (
            storage_soc_upper_limit + settings.soc_deadband
            if storage_soc_upper_limit is not None
            else None
        ),
        "socLowerDeadbandThreshold": (
            storage_soc_lower_limit - settings.soc_deadband
            if storage_soc_lower_limit is not None
            else None
        ),
        "storageAboveUpperCount": len(storage_above_upper),
        "storageBelowLowerCount": len(storage_below_lower),
        "absorptionLimitKw": renewable_balance_limit,
        "renewableBalanceLimitKw": renewable_balance_limit,
        "renewableRecoveryStepRequestKw": renewable_recovery_step_request_kw,
        "renewableCurtailStepRequestKw": renewable_curtail_step_request_kw,
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
        "storageSwitchDeadbandKw": settings.storage_switch_deadband_kw,
        "storageSwitchDeadbandAction": storage_deadband_action,
        "acdcCurrentKw": converter_current,
        "acdcCurrentForControlKw": converter_current_for_control,
        "acdcDesiredTargetKw": converter_desired_target,
        "acdcTargetKw": converter_target,
        "acdcAdjustmentKw": converter_target - converter_current if converter_current is not None else None,
        "converterRatedCapacityKw": converter_limit if math.isfinite(converter_limit) else None,
        "converterSocLimitRatio": converter_soc_limit_ratio,
        "converterSocLimitKw": converter_soc_limit if math.isfinite(converter_soc_limit) else None,
        "converterSocBandIndex": converter_soc_band_index,
        "converterSocBandLowerPercent": converter_soc_band_lower_percent,
        "converterSocBandUpperPercent": converter_soc_band_upper_percent,
        "converterSocLimitApplied": converter_soc_limit_ratio < 1.0 - EPSILON,
        "converterReversePowerForbidden": True,
        "converterReversePowerDetected": converter_reverse_power_detected,
        "converterTargetLowerLimitKw": converter_lower_target,
        "converterTargetUpperLimitKw": converter_upper_target,
        "converterHardLimitApplied": converter_hard_limit_applied,
        "converterStepRatio": settings.converter_step_ratio,
        "converterBaseStepKw": converter_base_step_kw,
        "converterStepDirection": converter_step_direction,
        "converterSlowIncrease": converter_slow_increase,
        "converterStepScale": converter_step_scale,
        "converterStepKw": converter_step_kw,
        "converterStepLimited": converter_step_limited,
        "dieselResidual": diesel_residual,
        "dieselCurrentKw": diesel_current,
        "dieselMinKw": diesel_min,
        "dieselDownMarginKw": diesel_down_margin,
        "dieselUpMarginKw": diesel_up_margin,
        "dieselDeadbandRatio": settings.diesel_deadband_ratio,
        "dieselDeadbandKw": diesel_deadband_kw,
        "dieselDeadbandActive": diesel_deadband_active,
        "dieselControlRegion": diesel_control_region,
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
        "renewableStepDirection": renewable_step_direction,
        "renewableRecoveryStepScale": renewable_recovery_step_scale,
        "renewableCurtailStepScale": renewable_curtail_step_scale,
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
    if not converter_step_reasons:
        converter_step_reason_text = "不在缩放死区，保持原步长"
    elif converter_step_direction == "increase":
        converter_step_reason_text = (
            f"{converter_step_region_text}内升功率，采用{DEADBAND_STEP_SCALE * 100:.0f}%步长"
        )
    elif converter_step_direction == "decrease":
        converter_step_reason_text = f"{converter_step_region_text}内降功率，保持原步长"
    else:
        converter_step_reason_text = f"{converter_step_region_text}内无功率调整，保持原步长"
    if not upper_soc_deadband_active:
        renewable_step_reason_text = "不在SOC上限死区，保持原步长"
    elif renewable_step_direction == "increase":
        renewable_step_reason_text = (
            f"SOC上限死区内升功率，采用{DEADBAND_STEP_SCALE * 100:.0f}%步长"
        )
    elif renewable_step_direction == "decrease":
        renewable_step_reason_text = "SOC上限死区内降功率，保持原步长"
    else:
        renewable_step_reason_text = "SOC上限死区内无功率调整，保持原步长"
    converter_rated_capacity_text = (
        f"{converter_limit:.2f}"
        if math.isfinite(converter_limit)
        else "--"
    )
    converter_soc_limit_text = (
        f"{converter_soc_limit:.2f}"
        if math.isfinite(converter_soc_limit)
        else "--"
    )
    converter_soc_band_text = (
        f"{converter_soc_band_lower_percent}%-{converter_soc_band_upper_percent}%"
        if converter_soc_band_index is not None
        else "未知SOC"
    )
    decision_detail = [
        f"数据来源：{_source_label(data_source)}，质量 {quality_payload['status']}，闭环下发{'允许' if quality_payload['dispatchAllowed'] else '禁止'}",
        "控制架构：ACDC与新能源两条策略相互独立，分别生成目标，不做功率增量相加、替代、吸收或联合预测",
        f"控制基准：时刻 {time_text}，新能源当前 {renewable_current:.2f} kW，柴发当前 {diesel_current_for_control:.2f} kW、下限 {diesel_min:.2f} kW",
        f"柴发分区：死区比例 {settings.diesel_deadband_ratio * 100:.2f}%（±{diesel_deadband_kw:.2f} kW），当前位于 {diesel_control_region} 区",
        f"储能状态：当前 {storage_current_for_control:.2f} kW，SOC {storage_soc * 100 if storage_soc is not None else '--'}%，运行边界 [{storage_soc_lower_limit * 100 if storage_soc_lower_limit is not None else '--'}%, {storage_soc_upper_limit * 100 if storage_soc_upper_limit is not None else '--'}%]",
        f"SOC分区：下限 {storage_soc_lower_limit * 100 if storage_soc_lower_limit is not None else '--'}%，上限 {storage_soc_upper_limit * 100 if storage_soc_upper_limit is not None else '--'}%，死区 {settings.soc_deadband * 100:.2f}%，当前 {storage_soc_region}",
        f"SOC运行约束：达到上限禁止充电，超过上限加死区后主动增加放电；达到下限禁止放电，低于下限减死区后变流器归零",
        f"环境策略：风速 {observed_wind_speed if observed_wind_speed is not None else '--'}、太阳辐照度 {observed_irradiance if observed_irradiance is not None else '--'}、温度 {observed_air_temperature if observed_air_temperature is not None else '--'}，均按默认策略忽略",
        f"ACDC SOC限额：原始并联容量 {converter_rated_capacity_text} kW，当前SOC命中 {converter_soc_band_text} 区间，配置上限 {converter_soc_limit_ratio * 100:.0f}%，正向送电功率幅值上限 {converter_soc_limit_text} kW",
        f"ACDC方向约束：禁止交流侧向直流侧倒送，自动控制目标范围 [{converter_lower_target:.2f}, {converter_upper_target:.2f}] kW",
        f"ACDC策略：只读取柴发分区与SOC分区，动作 {storage_control_action}；实时 {converter_current if converter_current is not None else '--'} kW，控制基准 {converter_current_for_control:.2f} kW，基础步长 {converter_base_step_kw:.2f} kW，{converter_step_reason_text}，实际按 {converter_step_scale * 100:.0f}% 即 {converter_step_kw:.2f} kW 调节，目标 {converter_target:.2f} kW",
        f"ACDC独立预估：对应储能平衡功率由 {storage_current_for_control:.2f} kW 变为 {storage_target:.2f} kW，柴发反馈参考值 {diesel_target:.2f} kW；该值不叠加新能源动作",
        f"新能源策略：只按SOC决定恢复，电池未满时按单机容量步长恢复；仅在SOC达到上限且柴发进入下限死区时弃电，本轮动作 {renewable_control_action}",
        f"新能源目标：当前 {renewable_current:.2f} kW，基础单步比例 {settings.step_coefficient * 100:.2f}%，{renewable_step_reason_text}，实际按 {renewable_step_scale * 100:.0f}% 即 {renewable_effective_step_ratio * 100:.2f}% 调节，目标 {renewable_target:.2f} kW",
        f"负荷功率仅用于展示：当前 {load_kw:.2f} kW，不参与新能源、储能、变流器或柴发目标计算",
        f"独立边界检查：ACDC目标已按并联容量、SOC分档功率上限、禁止倒送、SOC充放电方向和变流器步长限幅；新能源目标仅按设备容量和新能源步长限幅",
        *[f"数据告警：{issue}" for issue in quality_payload["issues"]],
    ]
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
    }


def _request_json(
    url: str,
    *,
    method: str = "GET",
    payload: Optional[Mapping[str, Any]] = None,
    timeout: float = 8.0,
) -> Any:
    body = None
    headers = {"Accept": "application/json"}
    if method in {"POST", "PUT"}:
        body = json.dumps(payload or {}, ensure_ascii=False, default=str).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            text = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(detail or str(exc.reason)) from exc
    except URLError as exc:
        raise RuntimeError(f"模拟台服务不可达：{exc.reason}") from exc
    try:
        return json.loads(text) if text else {}
    except json.JSONDecodeError as exc:
        raise RuntimeError("模拟台返回内容不是有效 JSON") from exc


def _url_with_query(path: str, **overrides: Any) -> str:
    parsed = urlparse(path)
    query = parse_qs(parsed.query, keep_blank_values=True)
    for key, value in overrides.items():
        if value is None:
            query.pop(key, None)
        else:
            query[key] = [str(value)]
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, urlencode(query, doseq=True), parsed.fragment))


def _merge_snapshot(previous: Optional[Mapping[str, Any]], current: Mapping[str, Any]) -> Dict[str, Any]:
    merged = copy.deepcopy(dict(previous or {}))
    for key, value in current.items():
        merged[key] = copy.deepcopy(value)
    return merged


@dataclass
class _ControllerState:
    model_id: str
    settings: RenewableControlSettings = field(default_factory=RenewableControlSettings)
    enabled: bool = False
    loop_mode: str = "open"
    sending: bool = False
    status: str = "请选择单次计算或启动实时控制。"
    last_plan: Optional[Dict[str, Any]] = None
    last_calculated_at: str = ""
    last_sent_at: str = ""
    last_clock_key: str = ""
    last_dispatched_clock_key: str = ""
    last_auto_started: float = 0.0
    last_preview_started: float = 0.0
    revision: int = 0
    log_seq: int = 0
    logs: List[Dict[str, Any]] = field(default_factory=list)
    trend: List[Dict[str, Any]] = field(default_factory=list)
    cached_snapshot: Optional[Dict[str, Any]] = None
    cached_snapshot_at: float = 0.0
    cached_static_signature: str = ""
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    run_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)


class TraineeRenewableControlManager:
    """Model-scoped shared control state and background execution."""

    def __init__(
        self,
        services: Any,
        *,
        request_json: Callable[..., Any] = _request_json,
        start_worker: bool = True,
    ) -> None:
        self.services = services
        self.request_json = request_json
        self._states: Dict[str, _ControllerState] = {}
        self._states_lock = threading.RLock()
        self._stop_event = threading.Event()
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="renewable-control")
        self._worker: Optional[threading.Thread] = None
        if start_worker:
            self._worker = threading.Thread(target=self._worker_loop, name="trainee-renewable-control", daemon=True)
            self._worker.start()

    def close(self) -> None:
        self._stop_event.set()
        if self._worker and self._worker.is_alive():
            self._worker.join(timeout=2)
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _service_for(self, model_id: Optional[str]) -> Any:
        if hasattr(self.services, "service_for"):
            return self.services.service_for(model_id)
        return self.services

    def _model_id(self, model_id: Optional[str]) -> str:
        service = self._service_for(model_id)
        return str(getattr(service, "model_id", model_id or "default"))

    def _persistence_path(self, model_id: Optional[str]) -> Optional[Path]:
        target = self._service_for(model_id)
        runtime_dir = getattr(target, "runtime_dir", None)
        return Path(runtime_dir) / RENEWABLE_CONTROL_STATE_FILE if runtime_dir else None

    def _load_configuration(self, model_id: Optional[str]) -> Tuple[RenewableControlSettings, str]:
        path = self._persistence_path(model_id)
        if path is None or not path.exists():
            return RenewableControlSettings(), "open"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return RenewableControlSettings(), "open"
        if not isinstance(payload, Mapping):
            return RenewableControlSettings(), "open"
        settings_payload = payload.get("settings")
        settings = RenewableControlSettings().updated(
            settings_payload if isinstance(settings_payload, Mapping) else payload
        )
        loop_mode = "closed" if str(payload.get("loopMode", payload.get("loop_mode", "open"))).lower() == "closed" else "open"
        return settings, loop_mode

    def _persist_configuration(
        self,
        model_id: Optional[str],
        settings: RenewableControlSettings,
        loop_mode: str,
    ) -> None:
        path = self._persistence_path(model_id)
        if path is None:
            raise RuntimeError("当前模型没有可用的运行目录，无法持久化新能源控制参数")
        payload = {
            "version": 1,
            "modelId": self._model_id(model_id),
            "loopMode": "closed" if loop_mode == "closed" else "open",
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

    def _state_for(self, model_id: Optional[str]) -> _ControllerState:
        normalized = self._model_id(model_id)
        with self._states_lock:
            state = self._states.get(normalized)
            if state is None:
                settings, loop_mode = self._load_configuration(normalized)
                state = _ControllerState(normalized, settings=settings, loop_mode=loop_mode)
                self._states[normalized] = state
            return state

    @staticmethod
    def _connection(target: Any) -> Optional[Dict[str, str]]:
        receive_state = target.trainee_receive_state()
        base = str(receive_state.get("teacher_api_base") or "").rstrip("/")
        snapshot_path = str(receive_state.get("snapshot_path") or "")
        command_path = str(receive_state.get("command_path") or "")
        if not base or not snapshot_path:
            return None
        return {"base": base, "snapshot_path": snapshot_path, "command_path": command_path}

    @staticmethod
    def _static_signature(snapshot: Mapping[str, Any]) -> str:
        meta = snapshot.get("static_meta")
        if not isinstance(meta, Mapping):
            return ""
        selected = {key: meta.get(key) for key in REMOTE_SNAPSHOT_STATIC_FIELDS}
        return json.dumps(selected, ensure_ascii=False, sort_keys=True, default=str)

    def _fetch_remote_snapshot(self, state: _ControllerState, target: Any, connection: Mapping[str, str]) -> Dict[str, Any]:
        snapshot_path = _url_with_query(
            connection["snapshot_path"],
            lite=1,
            logs=0,
            commands=0,
            measurements=1,
            devices=1,
            static=0,
        )
        snapshot_url = urljoin(connection["base"] + "/", snapshot_path.lstrip("/"))
        current = self.request_json(snapshot_url)
        if not isinstance(current, Mapping):
            raise RuntimeError("模拟台快照不是 JSON 对象")
        signature = self._static_signature(current)
        need_static = not state.cached_snapshot or not state.cached_static_signature or signature != state.cached_static_signature
        if need_static:
            static_path = _url_with_query(
                connection["snapshot_path"],
                lite=1,
                logs=0,
                commands=0,
                measurements=1,
                devices=1,
                static=",".join(REMOTE_SNAPSHOT_STATIC_FIELDS),
            )
            static_url = urljoin(connection["base"] + "/", static_path.lstrip("/"))
            with_static = self.request_json(static_url)
            if not isinstance(with_static, Mapping):
                raise RuntimeError("模拟台静态快照不是 JSON 对象")
            current = _merge_snapshot(current, with_static)
            signature = self._static_signature(current)
        merged = _merge_snapshot(state.cached_snapshot, current)
        state.cached_snapshot = merged
        state.cached_snapshot_at = time.time()
        state.cached_static_signature = signature or state.cached_static_signature
        return merged

    def _snapshot_for_calculation(self, model_id: Optional[str]) -> Tuple[Dict[str, Any], str, float, Optional[str]]:
        target = self._service_for(model_id)
        state = self._state_for(model_id)
        connection = self._connection(target)
        if connection:
            try:
                return self._fetch_remote_snapshot(state, target, connection), "remote", 0.0, None
            except Exception as exc:
                with state.lock:
                    cached = copy.deepcopy(state.cached_snapshot)
                    age = max(0.0, time.time() - state.cached_snapshot_at) if state.cached_snapshot_at else 0.0
                if cached:
                    return cached, "cached", age, str(exc)
                error = str(exc)
        else:
            error = "当前模型尚未配置模拟台交互链接"
        local = target.snapshot(
            include_static=True,
            include_runtime_logs=False,
            include_measurements=True,
            include_devices=True,
            include_commands=False,
            static_fields=list(REMOTE_SNAPSHOT_STATIC_FIELDS),
        )
        return local, "local", 0.0, error

    def _append_log(
        self,
        state: _ControllerState,
        log_type: str,
        result: str,
        detail: Any,
        *,
        level: str = "info",
        simu_time: str = "--",
    ) -> None:
        state.log_seq += 1
        normalized_detail = detail if isinstance(detail, str) else "；".join(str(item) for item in detail if item)
        state.logs.insert(
            0,
            {
                "seq": state.log_seq,
                "wall_time": _now_text(),
                "simu_time": simu_time or "--",
                "type": log_type,
                "target": "新能源优先",
                "result": result,
                "detail": normalized_detail,
                "level": level,
            },
        )
        state.logs = state.logs[:300]
        try:
            target = self._service_for(state.model_id)
            append_runtime_log = getattr(target, "_append_runtime_log", None)
            if callable(append_runtime_log):
                target_lock = getattr(target, "lock", None)
                if target_lock is not None:
                    with target_lock:
                        append_runtime_log(
                            log_type,
                            "新能源优先",
                            result,
                            normalized_detail,
                            level=level,
                            simu_time=simu_time,
                        )
                else:
                    append_runtime_log(
                        log_type,
                        "新能源优先",
                        result,
                        normalized_detail,
                        level=level,
                        simu_time=simu_time,
                    )
        except Exception:
            # A runtime-log persistence failure must not interrupt the controller.
            pass

    @staticmethod
    def _trend_point(plan: Mapping[str, Any], snapshot: Mapping[str, Any]) -> Dict[str, Any]:
        metrics = plan.get("metrics") if isinstance(plan.get("metrics"), Mapping) else {}
        clock = snapshot.get("clock") if isinstance(snapshot.get("clock"), Mapping) else {}
        run_id = int(_number(clock.get("run_id"), 0.0) or 0)
        minute = _number(clock.get("absolute_minute", clock.get("minute")), 0.0) or 0.0
        return {
            "sampleKey": f"{run_id}|{minute}|{clock.get('time', '')}",
            "runId": run_id,
            "minute": minute,
            "time": str(clock.get("time", "--")),
            "loadKw": metrics.get("loadKw"),
            "dieselKw": metrics.get("dieselCurrentKw"),
            "storageKw": metrics.get("storageCurrentKw"),
            "storageSocPercent": metrics.get("storageSoc") * 100 if isinstance(metrics.get("storageSoc"), (int, float)) else None,
            "renewableKw": metrics.get("renewableCurrentKw"),
            "acdcCurrentKw": metrics.get("acdcCurrentKw"),
            "acdcTargetKw": metrics.get("acdcTargetKw"),
        }

    def _update_trend(self, state: _ControllerState, plan: Mapping[str, Any], snapshot: Mapping[str, Any]) -> None:
        point = self._trend_point(plan, snapshot)
        if state.trend and state.trend[-1].get("runId") != point["runId"]:
            state.trend = []
        if state.trend and state.trend[-1].get("sampleKey") == point["sampleKey"]:
            state.trend[-1] = point
        else:
            state.trend.append(point)
        state.trend = state.trend[-45000:]

    def _command_payload(self, state: _ControllerState, plan: Mapping[str, Any], snapshot: Mapping[str, Any], trigger: str) -> Dict[str, Any]:
        metrics = plan.get("metrics") if isinstance(plan.get("metrics"), Mapping) else {}
        clock = snapshot.get("clock") if isinstance(snapshot.get("clock"), Mapping) else {}
        return {
            "source": "trainee-renewable-priority-backend",
            "valid_for_minutes": state.settings.command_valid_minutes,
            "sent_wall_time": _now_text(),
            "sent_simu_time": str(clock.get("time", "")),
            "sent_absolute_minute": _number(clock.get("absolute_minute", clock.get("minute"))),
            "set_values": copy.deepcopy(plan.get("commands", [])),
            "strategy": {
                "name": "renewable_priority",
                "loop_mode": state.loop_mode,
                "trigger": trigger,
                "time": plan.get("time"),
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

    def run_once(
        self,
        model_id: Optional[str],
        *,
        trigger: str = "manual",
        allow_dispatch: bool = True,
        record_log: bool = True,
    ) -> Dict[str, Any]:
        state = self._state_for(model_id)
        if not state.run_lock.acquire(blocking=False):
            return self.state(model_id)
        try:
            with state.lock:
                state.sending = True
                state.revision += 1
            snapshot, source, age, fetch_error = self._snapshot_for_calculation(model_id)
            plan = calculate_renewable_control_plan(snapshot, state.settings, data_source=source, snapshot_age_seconds=age)
            with state.lock:
                state.last_plan = plan
                state.last_calculated_at = _now_text()
                state.last_clock_key = str(plan.get("clockKey", ""))
                self._update_trend(state, plan, snapshot)
                if record_log:
                    self._append_log(
                        state,
                        "策略决策",
                        "计算完成",
                        plan.get("decisionDetail", []),
                        level="info" if plan.get("dataQuality", {}).get("status") == "ok" else "warn",
                        simu_time=str(plan.get("time", "--")),
                    )

            commands = plan.get("commands") if isinstance(plan.get("commands"), Sequence) else []
            quality = plan.get("dataQuality") if isinstance(plan.get("dataQuality"), Mapping) else {}
            should_dispatch = allow_dispatch and state.loop_mode == "closed" and bool(commands)
            if should_dispatch and not quality.get("dispatchAllowed"):
                with state.lock:
                    state.status = "控制策略已生成，但输入数据质量不满足闭环下发条件。"
                    if record_log:
                        self._append_log(state, "策略控制", "闭环未下发", state.status, level="warn", simu_time=str(plan.get("time", "--")))
            elif should_dispatch:
                target = self._service_for(model_id)
                connection = self._connection(target)
                if not connection or not connection.get("command_path"):
                    with state.lock:
                        state.status = "控制策略已生成，但当前没有可用的模拟台指令接口。"
                        if record_log:
                            self._append_log(state, "策略控制", "下发失败", state.status, level="error", simu_time=str(plan.get("time", "--")))
                else:
                    command_url = urljoin(connection["base"] + "/", connection["command_path"].lstrip("/"))
                    payload = self._command_payload(state, plan, snapshot, trigger)
                    dispatch_clock_key = str(plan.get("clockKey", "")).strip()
                    with state.lock:
                        duplicate_dispatch = bool(
                            dispatch_clock_key
                            and state.last_dispatched_clock_key == dispatch_clock_key
                        )
                        if duplicate_dispatch:
                            state.status = "当前仿真时刻已下发控制策略，已跳过重复下发。"
                            if record_log:
                                self._append_log(
                                    state,
                                    "策略控制",
                                    "重复抑制",
                                    state.status,
                                    level="info",
                                    simu_time=str(plan.get("time", "--")),
                                )
                        elif dispatch_clock_key:
                            # Claim the simulation instant before the HTTP call. A timeout may
                            # be ambiguous, so retrying the same instant could duplicate control.
                            state.last_dispatched_clock_key = dispatch_clock_key
                    if not duplicate_dispatch:
                        try:
                            result = self.request_json(command_url, method="POST", payload=payload)
                        except Exception as exc:
                            with state.lock:
                                state.status = f"遥调指令下发失败：{exc}；当前仿真时刻不再重复下发。"
                                if record_log:
                                    self._append_log(state, "模拟台响应", "下发失败", state.status, level="error", simu_time=str(plan.get("time", "--")))
                        else:
                            accepted = int(_number(result.get("set_values"), len(commands)) or 0) if isinstance(result, Mapping) else len(commands)
                            with state.lock:
                                state.last_sent_at = _now_text()
                                state.status = f"已由学员台后台下发 {accepted} 条遥调指令。"
                                if record_log:
                                    self._append_log(
                                        state,
                                        "模拟台响应",
                                        "下发成功",
                                        f"模拟台接受遥调指令 {accepted} 条；策略时刻 {plan.get('time', '--')}",
                                        level="ok",
                                        simu_time=str(plan.get("time", "--")),
                                    )
            else:
                with state.lock:
                    if not commands:
                        state.status = "本轮没有可生成的遥调策略。"
                    elif state.loop_mode == "open" or not allow_dispatch:
                        state.status = f"开环计算完成，生成 {len(commands)} 条遥调策略，未向模拟台下发。"
                    if record_log:
                        self._append_log(
                            state,
                            "策略控制",
                            "开环未下发" if commands else "无可用策略",
                            state.status,
                            level="ok" if commands else "warn",
                            simu_time=str(plan.get("time", "--")),
                        )
            if fetch_error and record_log:
                with state.lock:
                    self._append_log(state, "数据状态", "实时获取失败", fetch_error, level="warn", simu_time=str(plan.get("time", "--")))
            with state.lock:
                state.revision += 1
        finally:
            with state.lock:
                state.sending = False
                state.revision += 1
            state.run_lock.release()
        return self.state(model_id)

    def _serialize(self, state: _ControllerState) -> Dict[str, Any]:
        with state.lock:
            return {
                "modelId": state.model_id,
                "enabled": state.enabled,
                "loopMode": state.loop_mode,
                "sending": state.sending,
                "settings": state.settings.payload(),
                "status": state.status,
                "lastPlan": copy.deepcopy(state.last_plan),
                "lastCalculatedAt": state.last_calculated_at,
                "lastSentAt": state.last_sent_at,
                "lastDispatchedClockKey": state.last_dispatched_clock_key,
                "revision": state.revision,
                "logs": copy.deepcopy(state.logs),
                "trend": copy.deepcopy(state.trend),
            }

    def state(self, model_id: Optional[str], *, refresh: bool = False) -> Dict[str, Any]:
        state = self._state_for(model_id)
        now = time.monotonic()
        if refresh and not state.enabled and now - state.last_preview_started >= 0.9:
            with state.lock:
                state.last_preview_started = now
            return self.run_once(model_id, trigger="preview", allow_dispatch=False, record_log=False)
        return self._serialize(state)

    def apply_action(self, model_id: Optional[str], payload: Mapping[str, Any]) -> Dict[str, Any]:
        state = self._state_for(model_id)
        action = str(payload.get("action", "state")).strip().lower()
        settings_payload = payload.get("settings") if isinstance(payload.get("settings"), Mapping) else payload
        if action in {"update_settings", "settings"}:
            with state.lock:
                next_settings = state.settings.updated(settings_payload)
                self._persist_configuration(state.model_id, next_settings, state.loop_mode)
                state.settings = next_settings
                state.status = "新能源实时控制参数已更新并持久化。"
                state.revision += 1
            return self._serialize(state)
        if action in {"set_loop_mode", "loop_mode"}:
            next_mode = "closed" if str(payload.get("loop_mode", payload.get("loopMode", "open"))).lower() == "closed" else "open"
            with state.lock:
                previous = state.loop_mode
                self._persist_configuration(state.model_id, state.settings, next_mode)
                state.loop_mode = next_mode
                state.status = "闭环模式已启用，后续策略由后台下发执行。" if next_mode == "closed" else "开环模式已启用，后台只计算并记录日志。"
                self._append_log(state, "策略控制", "方式切换", f"{previous} -> {next_mode}；{state.status}", simu_time=state.last_plan.get("time", "--") if state.last_plan else "--")
                state.revision += 1
            return self._serialize(state)
        if action == "start":
            with state.lock:
                state.enabled = True
                state.last_auto_started = 0.0
                state.status = f"{'闭环' if state.loop_mode == 'closed' else '开环'}实时控制已在学员台后台启动。"
                self._append_log(state, "策略控制", "启动", state.status, level="ok", simu_time=state.last_plan.get("time", "--") if state.last_plan else "--")
                state.revision += 1
            return self.run_once(model_id, trigger="start", allow_dispatch=True, record_log=True)
        if action == "stop":
            with state.lock:
                was_enabled = state.enabled
                state.enabled = False
                state.status = "实时控制已在学员台后台停止。"
                if was_enabled:
                    self._append_log(state, "策略控制", "停止", state.status, level="warn", simu_time=state.last_plan.get("time", "--") if state.last_plan else "--")
                state.revision += 1
            return self._serialize(state)
        if action in {"run_once", "calculate"}:
            return self.run_once(model_id, trigger="manual", allow_dispatch=True, record_log=True)
        if action in {"refresh", "preview"}:
            return self.run_once(model_id, trigger="preview", allow_dispatch=False, record_log=False)
        return self._serialize(state)

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            now = time.monotonic()
            try:
                services = list(self.services.iter_services()) if hasattr(self.services, "iter_services") else [self.services]
            except Exception:
                services = []
            live_ids = set()
            for target in services:
                model_id = str(getattr(target, "model_id", "default"))
                live_ids.add(model_id)
                state = self._state_for(model_id)
                with state.lock:
                    due = state.enabled and not state.sending and now - state.last_auto_started >= state.settings.interval_seconds
                    if due:
                        state.last_auto_started = now
                if due:
                    self._executor.submit(self.run_once, model_id, trigger="auto", allow_dispatch=True, record_log=True)
            with self._states_lock:
                for stale in set(self._states) - live_ids:
                    self._states.pop(stale, None)
            self._stop_event.wait(0.1)
