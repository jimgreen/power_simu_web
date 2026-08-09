"""Reproducible random-scenario audit for the Qinling renewable controller.

The scenario generator uses only explicit model roles and parameter-table index
relations. Device names are retained for reporting and command addressing, but
are never used to classify equipment.
"""

from __future__ import annotations

import argparse
import copy
import csv
import json
import math
import random
import tempfile
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np
from scipy.optimize import linprog

from .model_semantics import grid_converter_keys
from .renewable_control import RenewableControlSettings, calculate_renewable_control_plan
from .service import PolarMicrogridSimulator


EPSILON = 1e-9
AUDIT_TOLERANCE_KW = 0.15
QINLING_MODEL_DIR = Path("models") / "simulator" / "source" / "\u79e6\u5cad\u7ad9"

STATUS_PASS = "pass"
STATUS_FAIL = "fail"
STATUS_NA = "not_applicable"

WIND_LEVELS = {
    "low": (3.2, 6.0),
    "medium": (7.0, 11.0),
    "high": (12.0, 24.0),
}
SOLAR_LEVELS = {
    "low": (0.0, 180.0),
    "medium": (240.0, 480.0),
    "high": (540.0, 720.0),
}
AC_LOAD_LEVELS = {
    "low": (114.0, 126.0),
    "medium": (126.0, 140.0),
    "high": (140.0, 154.0),
}
DC_LOAD_LEVELS = {
    "low": (76.0, 84.0),
    "medium": (84.0, 94.0),
    "high": (94.0, 102.0),
}
DIESEL_LEVELS = {
    "low": (30.0, 180.0),
    "medium": (180.0, 360.0),
    "high": (360.0, 720.0),
}
STORAGE_POWER_RATIOS = {
    "charge_high": (-0.90, -0.70),
    "charge_medium": (-0.60, -0.40),
    "charge_low": (-0.30, -0.15),
    "discharge_low": (0.15, 0.30),
    "discharge_medium": (0.40, 0.60),
    "discharge_high": (0.70, 0.90),
}

RELATION_SPECS = (
    ("wind", "ACWindGen", "ACGenerator", "idx_acgenerator"),
    ("wind", "DCWindGen", "DCGenerator", "idx_dcgenerator"),
    ("pv", "ACPVGen", "ACGenerator", "idx_acgenerator"),
    ("pv", "DCPVGen", "DCGenerator", "idx_dcgenerator"),
    ("storage", "ACStorageGen", "ACGenerator", "idx_acgenerator"),
    ("storage", "DCStorageGen", "DCGenerator", "idx_dcgenerator"),
    ("diesel", "ACDieselGen", "ACGenerator", "idx_acgenerator"),
    ("diesel", "DCDieselGen", "DCGenerator", "idx_dcgenerator"),
)

CRITERION_LABELS = {
    "optimization_balance": "优化后功率平衡",
    "power_bounds": "设备功率上下限",
    "soc_bounds": "储能SOC方向约束",
    "forced_soc_response": "低SOC强充/高SOC强放响应",
    "renewable_minimum": "新能源弃电最小",
    "diesel_minimum": "柴发出力最低",
    "protection_bands": "构网储能/柴发保护带",
    "step_limits": "设备调节步长",
    "soc_derating": "SOC降额曲线",
    "parallel_converters": "并联变流器分配",
}


class AuditConfigurationError(RuntimeError):
    """Raised when the source model cannot be audited without guessing."""


@dataclass(frozen=True)
class ResourceDevice:
    technology: str
    parameter_block: str
    model_block: str
    source_index: str
    device: Mapping[str, Any]
    parameter: Mapping[str, Any]

    @property
    def key(self) -> Tuple[str, str]:
        return self.model_block, str(self.device.get("dev_name", ""))

    @property
    def side(self) -> str:
        return "AC" if self.model_block.startswith("AC") else "DC"


@dataclass(frozen=True)
class ModelInventory:
    resources: Tuple[ResourceDevice, ...]
    grid_converters: Tuple[Mapping[str, Any], ...]
    ac_loads: Tuple[Mapping[str, Any], ...]
    dc_loads: Tuple[Mapping[str, Any], ...]

    def by_technology(self, technology: str, side: str = "") -> List[ResourceDevice]:
        return [
            resource
            for resource in self.resources
            if resource.technology == technology and (not side or resource.side == side)
        ]


@dataclass(frozen=True)
class ScenarioCase:
    scenario_id: int
    categories: Mapping[str, str]
    values: Mapping[str, float]
    snapshot: Mapping[str, Any]


@dataclass(frozen=True)
class CheckResult:
    status: str
    detail: str
    applicable_count: int = 0


def _number(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _raw(device: Mapping[str, Any]) -> Mapping[str, Any]:
    raw = device.get("raw")
    return raw if isinstance(raw, Mapping) else {}


def _device_index(device: Mapping[str, Any]) -> str:
    return str(_raw(device).get("idx", device.get("idx", ""))).strip()


def _device_key(device: Mapping[str, Any]) -> Tuple[str, str]:
    return (
        str(device.get("model_block", "")).strip(),
        str(device.get("dev_name", device.get("name", ""))).strip(),
    )


def _measurement(
    index: int,
    dev_type: str,
    dev_name: str,
    meas_type: str,
    value: float,
) -> Dict[str, Any]:
    return {
        "idx": index,
        "name": f"audit.{index}",
        "dev_type": dev_type,
        "dev_name": dev_name,
        "meas_type": meas_type,
        "value": float(value),
        "valid": 1,
        "weight": 1.0,
    }


def load_qinling_snapshot(project_root: Path) -> Dict[str, Any]:
    model_dir = project_root.resolve() / QINLING_MODEL_DIR
    if not (model_dir / "model.e").is_file():
        raise AuditConfigurationError(f"Qinling model not found: {model_dir}")
    with tempfile.TemporaryDirectory(prefix="qinling_strategy_audit_") as runtime_dir:
        service = PolarMicrogridSimulator(
            model_dir,
            runtime_dir,
            kernel=lambda _config: None,
            model_id="qinling-audit",
            model_name="Qinling audit",
        )
        snapshot = copy.deepcopy(service.snapshot())
        snapshot["audit_grid_converter_keys"] = [
            [model_block, dev_name]
            for model_block, dev_name in sorted(
                grid_converter_keys(service.source_model_book)
            )
        ]
        return snapshot


def build_inventory(snapshot: Mapping[str, Any]) -> ModelInventory:
    devices_by_index: Dict[Tuple[str, str], List[Mapping[str, Any]]] = defaultdict(list)
    for device in snapshot.get("devices", []) or []:
        if not isinstance(device, Mapping):
            continue
        block = str(device.get("model_block", "")).strip()
        index = _device_index(device)
        if block and index:
            devices_by_index[(block, index)].append(device)

    parameters = snapshot.get("device_parameters")
    if not isinstance(parameters, Mapping):
        raise AuditConfigurationError("device_parameters is missing")

    resources: List[ResourceDevice] = []
    used_sources: Dict[Tuple[str, str], str] = {}
    for technology, parameter_block, source_block, source_index_field in RELATION_SPECS:
        rows = parameters.get(parameter_block, []) or []
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
            raise AuditConfigurationError(f"{parameter_block} is not a row sequence")
        seen_parameter_indices: set[str] = set()
        for position, parameter in enumerate(rows, start=1):
            if not isinstance(parameter, Mapping):
                raise AuditConfigurationError(f"{parameter_block} row {position} is invalid")
            parameter_index = str(parameter.get("idx", "")).strip()
            source_index = str(parameter.get(source_index_field, "")).strip()
            if not parameter_index or parameter_index in seen_parameter_indices:
                raise AuditConfigurationError(
                    f"{parameter_block} contains a missing or duplicate idx at row {position}"
                )
            seen_parameter_indices.add(parameter_index)
            candidates = devices_by_index.get((source_block, source_index), [])
            if not source_index or len(candidates) != 1:
                raise AuditConfigurationError(
                    f"{parameter_block}.{parameter_index} does not resolve uniquely to "
                    f"{source_block}.{source_index or '--'}"
                )
            device = candidates[0]
            source_key = (source_block, source_index)
            if source_key in used_sources:
                raise AuditConfigurationError(
                    f"{source_block}.{source_index} is referenced by both "
                    f"{used_sources[source_key]} and {parameter_block}"
                )
            used_sources[source_key] = parameter_block
            resources.append(
                ResourceDevice(
                    technology=technology,
                    parameter_block=parameter_block,
                    model_block=source_block,
                    source_index=source_index,
                    device=device,
                    parameter=parameter,
                )
            )

    raw_grid_converter_keys = snapshot.get("audit_grid_converter_keys")
    if not isinstance(raw_grid_converter_keys, Sequence) or isinstance(
        raw_grid_converter_keys, (str, bytes)
    ):
        raise AuditConfigurationError("topology-derived grid converter keys are missing")
    topology_grid_converter_keys: set[Tuple[str, str]] = set()
    for position, item in enumerate(raw_grid_converter_keys, start=1):
        if (
            not isinstance(item, Sequence)
            or isinstance(item, (str, bytes))
            or len(item) != 2
        ):
            raise AuditConfigurationError(
                f"topology grid converter key {position} is invalid"
            )
        key = str(item[0]).strip(), str(item[1]).strip()
        if not all(key) or key in topology_grid_converter_keys:
            raise AuditConfigurationError(
                f"topology grid converter key {position} is missing or duplicate"
            )
        topology_grid_converter_keys.add(key)

    grid_converters = []
    converter_keys: set[Tuple[str, str]] = set()
    ac_loads = []
    dc_loads = []
    for device in snapshot.get("devices", []) or []:
        if not isinstance(device, Mapping):
            continue
        block = str(device.get("model_block", "")).strip()
        if block in {"ACDCConverter", "DCACConverter"}:
            key = _device_key(device)
            converter_keys.add(key)
            if key in topology_grid_converter_keys:
                grid_converters.append(device)
        elif block == "ACLoad":
            ac_loads.append(device)
        elif block == "DCLoad":
            dc_loads.append(device)

    unresolved_grid_converter_keys = topology_grid_converter_keys - converter_keys
    if unresolved_grid_converter_keys:
        raise AuditConfigurationError(
            "topology-derived grid converter keys do not resolve to model devices: "
            + ", ".join(".".join(key) for key in sorted(unresolved_grid_converter_keys))
        )
    if not grid_converters:
        raise AuditConfigurationError("no topology-valid grid AC/DC converter is defined")
    if not ac_loads or not dc_loads:
        raise AuditConfigurationError("both AC and DC loads are required")
    return ModelInventory(
        resources=tuple(resources),
        grid_converters=tuple(grid_converters),
        ac_loads=tuple(ac_loads),
        dc_loads=tuple(dc_loads),
    )


def _rated_power(resource: ResourceDevice) -> float:
    raw = _raw(resource.device)
    candidates = (
        raw.get("p_max"),
        resource.parameter.get("p_max"),
        resource.parameter.get("rated_power"),
        raw.get("rated_capacity"),
    )
    for value in candidates:
        number = _number(value)
        if number is not None and number > EPSILON:
            return number
    raise AuditConfigurationError(f"{resource.key} has no positive explicit power upper bound")


def _storage_power_limit(resource: ResourceDevice, direction: str) -> float:
    field = "max_charge_power" if direction == "charge" else "max_discharge_power"
    value = _number(resource.parameter.get(field))
    if value is None or value <= EPSILON:
        raise AuditConfigurationError(f"{resource.key} has invalid {field}")
    raw = _raw(resource.device)
    raw_limit = _number(raw.get("p_min" if direction == "charge" else "p_max"))
    if raw_limit is None:
        raise AuditConfigurationError(f"{resource.key} has no explicit main-device power bound")
    main_limit = abs(raw_limit)
    if main_limit <= EPSILON:
        raise AuditConfigurationError(f"{resource.key} main-device power bound is zero")
    return min(value, main_limit)


def _wind_available(resource: ResourceDevice, wind_speed: float) -> float:
    capacity = _rated_power(resource)
    cut_in = _number(resource.parameter.get("cut_in_wind_speed"))
    rated = _number(resource.parameter.get("rated_wind_speed"))
    cut_out = _number(resource.parameter.get("cut_out_wind_speed"))
    if cut_in is None or rated is None or cut_out is None or not (0 <= cut_in < rated < cut_out):
        raise AuditConfigurationError(f"{resource.key} has invalid wind-speed limits")
    if wind_speed < cut_in or wind_speed >= cut_out:
        return 0.0
    if wind_speed >= rated:
        return capacity
    return capacity * ((wind_speed - cut_in) / (rated - cut_in)) ** 3


def _pv_available(resource: ResourceDevice, irradiance: float, temperature: float) -> float:
    capacity = _rated_power(resource)
    reference_irradiance = _number(resource.parameter.get("reference_irradiance"))
    reference_temperature = _number(resource.parameter.get("reference_temperature"))
    temperature_coefficient = _number(
        resource.parameter.get(
            "temperature_coefficient",
            resource.parameter.get("temp_coefficient"),
        )
    )
    if (
        reference_irradiance is None
        or reference_irradiance <= 0.0
        or reference_temperature is None
        or temperature_coefficient is None
    ):
        raise AuditConfigurationError(f"{resource.key} has incomplete PV reference data")
    factor = max(0.0, irradiance) / reference_irradiance
    factor *= max(0.0, 1.0 + temperature_coefficient * (temperature - reference_temperature))
    return min(capacity, max(0.0, capacity * factor))


def _random_value(rng: random.Random, ranges: Mapping[str, Tuple[float, float]], level: str) -> float:
    lower, upper = ranges[level]
    return rng.uniform(lower, upper)


def _soc_value(rng: random.Random, level: str) -> float:
    if level == "medium":
        return rng.uniform(0.42, 0.58)
    if level == "low":
        if rng.random() < 0.45:
            return rng.uniform(0.02, 0.045)
        return rng.uniform(0.11, 0.32)
    if rng.random() < 0.45:
        return rng.uniform(0.955, 0.98)
    return rng.uniform(0.70, 0.89)


def _storage_total_power(rng: random.Random, category: str, capacity: float) -> float:
    low_ratio, high_ratio = STORAGE_POWER_RATIOS[category]
    return rng.uniform(low_ratio, high_ratio) * capacity


def _allocate_with_caps(
    total: float,
    capacities: Sequence[float],
    rng: random.Random,
) -> List[float]:
    if total < -EPSILON or total > sum(capacities) + 1e-6:
        raise ValueError("allocation total is outside capacity")
    if not capacities:
        return []
    remaining = max(0.0, total)
    allocation = [0.0] * len(capacities)
    active = {index for index, capacity in enumerate(capacities) if capacity > EPSILON}
    weights = [capacity * rng.uniform(0.85, 1.15) for capacity in capacities]
    while active and remaining > 1e-9:
        weight_sum = sum(weights[index] for index in active)
        if weight_sum <= EPSILON:
            break
        saturated = []
        for index in active:
            share = remaining * weights[index] / weight_sum
            headroom = capacities[index] - allocation[index]
            if share >= headroom - 1e-12:
                allocation[index] += headroom
                saturated.append(index)
        if saturated:
            remaining = total - sum(allocation)
            active.difference_update(saturated)
            continue
        for index in active:
            allocation[index] += remaining * weights[index] / weight_sum
        remaining = 0.0
    if remaining > 1e-6:
        raise ValueError("allocation did not converge")
    correction = total - sum(allocation)
    if abs(correction) > 1e-9:
        for index, capacity in enumerate(capacities):
            candidate = allocation[index] + correction
            if -1e-9 <= candidate <= capacity + 1e-9:
                allocation[index] = max(0.0, min(capacity, candidate))
                break
    return allocation


def _allocate_signed_power(
    total: float,
    resources: Sequence[ResourceDevice],
    rng: random.Random,
) -> Dict[Tuple[str, str], float]:
    direction = "discharge" if total >= 0.0 else "charge"
    capacities = [_storage_power_limit(resource, direction) for resource in resources]
    values = _allocate_with_caps(abs(total), capacities, rng)
    sign = 1.0 if total >= 0.0 else -1.0
    return {resource.key: sign * value for resource, value in zip(resources, values)}


def _converter_bounds(device: Mapping[str, Any]) -> Tuple[float, float]:
    raw = _raw(device)
    lower = _number(raw.get("p_ac_min", raw.get("ac_p_min")))
    upper = _number(raw.get("p_ac_max", raw.get("ac_p_max")))
    if lower is None or upper is None or lower > upper:
        raise AuditConfigurationError(f"{_device_key(device)} has invalid AC power bounds")
    return lower, upper


def _draw_categories(rng: random.Random) -> Dict[str, str]:
    return {
        "wind": rng.choice(tuple(WIND_LEVELS)),
        "solar": rng.choice(tuple(SOLAR_LEVELS)),
        "ac_soc": rng.choice(("low", "medium", "high")),
        "dc_soc": rng.choice(("low", "medium", "high")),
        "ac_storage_power": rng.choice(tuple(STORAGE_POWER_RATIOS)),
        "dc_storage_power": rng.choice(tuple(STORAGE_POWER_RATIOS)),
        "diesel": rng.choice(tuple(DIESEL_LEVELS)),
        "ac_load": rng.choice(tuple(AC_LOAD_LEVELS)),
        "dc_load": rng.choice(tuple(DC_LOAD_LEVELS)),
    }


def _generate_candidate(
    base_snapshot: Mapping[str, Any],
    inventory: ModelInventory,
    rng: random.Random,
    scenario_id: int,
) -> Optional[ScenarioCase]:
    categories = _draw_categories(rng)
    wind_speed = _random_value(rng, WIND_LEVELS, categories["wind"])
    irradiance = _random_value(rng, SOLAR_LEVELS, categories["solar"])
    temperature = rng.uniform(-27.0, -13.0)
    ac_soc = _soc_value(rng, categories["ac_soc"])
    dc_soc = _soc_value(rng, categories["dc_soc"])
    ac_load = _random_value(rng, AC_LOAD_LEVELS, categories["ac_load"])
    dc_load = _random_value(rng, DC_LOAD_LEVELS, categories["dc_load"])
    diesel_total = _random_value(rng, DIESEL_LEVELS, categories["diesel"])

    ac_storage = inventory.by_technology("storage", "AC")
    dc_storage = inventory.by_technology("storage", "DC")
    ac_storage_capacity = sum(_storage_power_limit(item, "charge") for item in ac_storage)
    dc_storage_capacity = sum(_storage_power_limit(item, "charge") for item in dc_storage)
    ac_storage_power = _storage_total_power(
        rng,
        categories["ac_storage_power"],
        ac_storage_capacity,
    )
    dc_storage_power = _storage_total_power(
        rng,
        categories["dc_storage_power"],
        dc_storage_capacity,
    )

    renewable_available: Dict[Tuple[str, str], float] = {}
    for resource in inventory.by_technology("wind"):
        renewable_available[resource.key] = _wind_available(resource, wind_speed)
    for resource in inventory.by_technology("pv"):
        renewable_available[resource.key] = _pv_available(resource, irradiance, temperature)

    ac_renewables = [
        item
        for item in inventory.resources
        if item.technology in {"wind", "pv"} and item.side == "AC"
    ]
    dc_renewables = [
        item
        for item in inventory.resources
        if item.technology in {"wind", "pv"} and item.side == "DC"
    ]
    ac_available = sum(renewable_available[item.key] for item in ac_renewables)
    dc_available = sum(renewable_available[item.key] for item in dc_renewables)
    renewable_required = (
        ac_load
        + dc_load
        - ac_storage_power
        - dc_storage_power
        - diesel_total
    )
    if renewable_required < -1e-6 or renewable_required > ac_available + dc_available + 1e-6:
        return None

    aggregate_converter_min = sum(_converter_bounds(item)[0] for item in inventory.grid_converters)
    aggregate_converter_max = sum(_converter_bounds(item)[1] for item in inventory.grid_converters)
    dc_renewable_min = max(
        0.0,
        renewable_required - ac_available,
        dc_load - dc_storage_power - aggregate_converter_max,
    )
    dc_renewable_max = min(
        dc_available,
        renewable_required,
        dc_load - dc_storage_power - aggregate_converter_min,
    )
    if dc_renewable_min > dc_renewable_max + 1e-7:
        return None
    dc_renewable_total = rng.uniform(dc_renewable_min, dc_renewable_max)
    ac_renewable_total = renewable_required - dc_renewable_total
    converter_total_p_ac = dc_load - dc_storage_power - dc_renewable_total

    try:
        ac_renewable_values = _allocate_with_caps(
            ac_renewable_total,
            [renewable_available[item.key] for item in ac_renewables],
            rng,
        )
        dc_renewable_values = _allocate_with_caps(
            dc_renewable_total,
            [renewable_available[item.key] for item in dc_renewables],
            rng,
        )
        ac_storage_values = _allocate_signed_power(ac_storage_power, ac_storage, rng)
        dc_storage_values = _allocate_signed_power(dc_storage_power, dc_storage, rng)
        diesels = inventory.by_technology("diesel", "AC")
        diesel_values = _allocate_with_caps(
            diesel_total,
            [_rated_power(item) for item in diesels],
            rng,
        )
        converter_capacities = [
            max(abs(lower), abs(upper))
            for lower, upper in (_converter_bounds(item) for item in inventory.grid_converters)
        ]
        converter_values_abs = _allocate_with_caps(
            abs(converter_total_p_ac),
            converter_capacities,
            rng,
        )
    except ValueError:
        return None

    converter_sign = 1.0 if converter_total_p_ac >= 0.0 else -1.0
    converter_values = [converter_sign * value for value in converter_values_abs]
    for device, value in zip(inventory.grid_converters, converter_values):
        lower, upper = _converter_bounds(device)
        if value < lower - 1e-7 or value > upper + 1e-7:
            return None

    renewable_values = {
        item.key: value
        for item, value in zip(ac_renewables, ac_renewable_values)
    }
    renewable_values.update(
        {
            item.key: value
            for item, value in zip(dc_renewables, dc_renewable_values)
        }
    )
    diesel_by_key = {item.key: value for item, value in zip(diesels, diesel_values)}

    snapshot = copy.deepcopy(base_snapshot)
    measurements: List[Dict[str, Any]] = []

    def add(dev_type: str, dev_name: str, meas_type: str, value: float) -> None:
        measurements.append(
            _measurement(len(measurements) + 1, dev_type, dev_name, meas_type, value)
        )

    add("Environment", "weather", "WIND_SPEED", wind_speed)
    add("Environment", "weather", "SOLAR_IRRADIANCE", irradiance)
    add("Environment", "weather", "AIR_TEMP", temperature)
    for resource in (*ac_renewables, *dc_renewables):
        add(resource.model_block, resource.key[1], "P_GEN", renewable_values[resource.key])
    for resource in ac_storage:
        add(resource.model_block, resource.key[1], "P_GEN", ac_storage_values[resource.key])
        add(resource.model_block, resource.key[1], "SOC", ac_soc)
    for resource in dc_storage:
        add(resource.model_block, resource.key[1], "P_GEN", dc_storage_values[resource.key])
        add(resource.model_block, resource.key[1], "SOC", dc_soc)
    for resource in diesels:
        add(resource.model_block, resource.key[1], "P_GEN", diesel_by_key[resource.key])
    for device, value in zip(inventory.grid_converters, converter_values):
        add(_device_key(device)[0], _device_key(device)[1], "P_AC", value)

    ac_load_weights = [0.995] + [0.005 / max(1, len(inventory.ac_loads) - 1)] * max(
        0, len(inventory.ac_loads) - 1
    )
    for device, weight in zip(inventory.ac_loads, ac_load_weights):
        add(_device_key(device)[0], _device_key(device)[1], "P_LOAD", ac_load * weight)
    dc_load_weights = [1.0 / len(inventory.dc_loads)] * len(inventory.dc_loads)
    for device, weight in zip(inventory.dc_loads, dc_load_weights):
        add(_device_key(device)[0], _device_key(device)[1], "P_LOAD", dc_load * weight)

    snapshot["measurements"] = {"scada": measurements, "real": []}
    snapshot["clock"] = {
        **dict(snapshot.get("clock", {})),
        "state": "running",
        "time": f"00:{scenario_id % 60:02d}:00",
        "minute": scenario_id,
        "absolute_minute": scenario_id,
        "step_minutes": 1.0,
        "speed": 1.0,
        "run_id": 1,
    }
    boundary = dict(snapshot.get("curve_boundary", {}))
    boundary["target_minute"] = scenario_id
    boundary["load_total"] = ac_load + dc_load
    boundary["point"] = {
        **dict(boundary.get("point", {})),
        "wind_speed_mps": wind_speed,
        "solar_irradiance_w_m2": irradiance,
        "air_temp_c": temperature,
    }
    snapshot["curve_boundary"] = boundary

    ac_balance = (
        ac_renewable_total
        + ac_storage_power
        + diesel_total
        - ac_load
        - converter_total_p_ac
    )
    dc_balance = (
        dc_renewable_total
        + dc_storage_power
        - dc_load
        + converter_total_p_ac
    )
    values = {
        "wind_speed_mps": wind_speed,
        "solar_irradiance_w_m2": irradiance,
        "air_temperature_c": temperature,
        "ac_storage_soc": ac_soc,
        "dc_storage_soc": dc_soc,
        "ac_storage_power_kw": ac_storage_power,
        "dc_storage_power_kw": dc_storage_power,
        "diesel_power_kw": diesel_total,
        "ac_load_kw": ac_load,
        "dc_load_kw": dc_load,
        "ac_renewable_available_kw": ac_available,
        "dc_renewable_available_kw": dc_available,
        "ac_renewable_current_kw": ac_renewable_total,
        "dc_renewable_current_kw": dc_renewable_total,
        "converter_p_ac_kw": converter_total_p_ac,
        "initial_ac_balance_residual_kw": ac_balance,
        "initial_dc_balance_residual_kw": dc_balance,
    }
    return ScenarioCase(
        scenario_id=scenario_id,
        categories=categories,
        values=values,
        snapshot=snapshot,
    )


def generate_scenarios(
    base_snapshot: Mapping[str, Any],
    inventory: ModelInventory,
    *,
    count: int,
    seed: int,
) -> List[ScenarioCase]:
    if count <= 0:
        return []
    rng = random.Random(seed)
    scenarios: List[ScenarioCase] = []
    attempts = 0
    maximum_attempts = max(1000, count * 500)
    while len(scenarios) < count and attempts < maximum_attempts:
        attempts += 1
        candidate = _generate_candidate(
            base_snapshot,
            inventory,
            rng,
            len(scenarios) + 1,
        )
        if candidate is not None:
            scenarios.append(candidate)
    if len(scenarios) != count:
        raise AuditConfigurationError(
            f"only generated {len(scenarios)} feasible scenarios after {attempts} attempts"
        )
    return scenarios


def _target(row: Mapping[str, Any]) -> Optional[float]:
    return _number(row.get("commandKw"))


def _check_result(violations: Sequence[str], applicable: int, success: str) -> CheckResult:
    if applicable <= 0:
        return CheckResult(STATUS_NA, "no applicable device", 0)
    if violations:
        return CheckResult(STATUS_FAIL, "; ".join(violations[:8]), applicable)
    return CheckResult(STATUS_PASS, success, applicable)


def _power_bounds_check(rows: Sequence[Mapping[str, Any]]) -> CheckResult:
    violations: List[str] = []
    applicable = 0
    for row in rows:
        target = _target(row)
        if not row.get("online") or target is None:
            continue
        lower: Optional[float] = None
        upper: Optional[float] = None
        if row.get("technology") in {"wind", "pv"}:
            lower = 0.0
            upper = _number(row.get("capacityKw"))
        elif row.get("technology") == "storage":
            lower = _number(row.get("signedMinTargetKw"), -_number(row.get("chargePower"), 0.0))
            upper = _number(row.get("signedMaxTargetKw"), _number(row.get("dischargePower"), 0.0))
        elif row.get("category") == "柴油发电":
            lower = _number(row.get("minKw"))
            upper = _number(row.get("capacityKw"))
        elif row.get("category") == "交直流变流器":
            lower = _number(row.get("signedMinTargetKw"))
            upper = _number(row.get("signedMaxTargetKw"))
        if lower is None or upper is None:
            continue
        applicable += 1
        if target < lower - AUDIT_TOLERANCE_KW or target > upper + AUDIT_TOLERANCE_KW:
            violations.append(
                f"{row.get('dev_type')}.{row.get('dev_name')} target={target:.3f} "
                f"outside [{lower:.3f},{upper:.3f}]"
            )
    return _check_result(violations, applicable, "all target powers are inside hard bounds")


def _soc_bounds_check(rows: Sequence[Mapping[str, Any]]) -> CheckResult:
    violations: List[str] = []
    applicable = 0
    for row in rows:
        if row.get("technology") != "storage" or not row.get("online"):
            continue
        soc = _number(row.get("soc"))
        soc_min = _number(row.get("socMin"))
        soc_max = _number(row.get("socMax"))
        target = _target(row)
        if soc is None or soc_min is None or soc_max is None or target is None:
            continue
        applicable += 1
        if soc <= soc_min + EPSILON and target > AUDIT_TOLERANCE_KW:
            violations.append(f"{row.get('dev_name')} low SOC still discharges at {target:.3f} kW")
        if soc >= soc_max - EPSILON and target < -AUDIT_TOLERANCE_KW:
            violations.append(f"{row.get('dev_name')} high SOC still charges at {target:.3f} kW")
    return _check_result(violations, applicable, "SOC boundary directions are protected")


def _forced_soc_response_check(
    rows: Sequence[Mapping[str, Any]],
    settings: RenewableControlSettings,
) -> CheckResult:
    violations: List[str] = []
    applicable = 0
    for row in rows:
        if row.get("technology") != "storage" or not row.get("online"):
            continue
        soc = _number(row.get("soc"))
        soc_min = _number(row.get("socMin"))
        soc_max = _number(row.get("socMax"))
        target = _target(row)
        if soc is None or soc_min is None or soc_max is None or target is None:
            continue
        if soc < soc_min - settings.soc_deadband - EPSILON:
            applicable += 1
            if target >= -AUDIT_TOLERANCE_KW:
                violations.append(f"{row.get('dev_name')} low SOC did not enter forced charge")
        elif soc > soc_max + settings.soc_deadband + EPSILON:
            applicable += 1
            if target <= AUDIT_TOLERANCE_KW:
                violations.append(f"{row.get('dev_name')} high SOC did not enter forced discharge")
    return _check_result(violations, applicable, "all extreme-SOC devices responded in the recovery direction")


def _protection_band_check(
    rows: Sequence[Mapping[str, Any]],
    settings: RenewableControlSettings,
) -> CheckResult:
    violations: List[str] = []
    applicable = 0
    for row in rows:
        target = _target(row)
        if not row.get("online") or target is None:
            continue
        if row.get("category") == "柴油发电":
            minimum = _number(row.get("minKw"))
            maximum = _number(row.get("capacityKw"))
            if minimum is None or maximum is None:
                continue
            applicable += 1
            guard = min(
                settings.diesel_power_protection_ratio * max(0.0, maximum),
                max(0.0, maximum - minimum) * 0.5,
            )
            if target < minimum + guard - AUDIT_TOLERANCE_KW or target > maximum - guard + AUDIT_TOLERANCE_KW:
                violations.append(f"{row.get('dev_name')} violates diesel protection band")
        elif row.get("technology") == "storage" and row.get("role") == "balance":
            charge = _number(row.get("maxChargePowerKw"))
            discharge = _number(row.get("maxDischargePowerKw"))
            if charge is None or discharge is None:
                continue
            applicable += 1
            ratio = min(0.5, max(0.0, settings.grid_forming_storage_protection_ratio))
            lower = -charge * (1.0 - ratio)
            upper = discharge * (1.0 - ratio)
            if target < lower - AUDIT_TOLERANCE_KW or target > upper + AUDIT_TOLERANCE_KW:
                violations.append(f"{row.get('dev_name')} violates grid-forming storage protection band")
    return _check_result(violations, applicable, "diesel and grid-forming storage reserves are retained")


def _step_limit_check(
    rows: Sequence[Mapping[str, Any]],
    plan: Mapping[str, Any],
    settings: RenewableControlSettings,
) -> CheckResult:
    override_keys = _optimization_step_override_keys(plan)
    violations: List[str] = []
    applicable = 0
    for row in rows:
        target = _target(row)
        current = _number(row.get("planningCurrentKw", row.get("currentKw")))
        if not row.get("online") or target is None or current is None:
            continue
        step: Optional[float] = None
        if row.get("technology") in {"wind", "pv"}:
            capacity = _number(row.get("capacityKw"))
            if capacity is not None:
                step = settings.step_coefficient * max(0.0, capacity)
        elif row.get("technology") == "storage" and row.get("role") == "grid_following":
            rated = max(
                _number(row.get("maxChargePowerKw"), 0.0) or 0.0,
                _number(row.get("maxDischargePowerKw"), 0.0) or 0.0,
            )
            step = settings.storage_step_ratio * rated
        if step is None:
            continue
        applicable += 1
        delta = abs(target - current)
        key = (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
        if delta > step + AUDIT_TOLERANCE_KW and key not in override_keys:
            violations.append(
                f"{row.get('dev_name')} delta={delta:.3f} exceeds step={step:.3f} without safety override"
            )
    return _check_result(violations, applicable, "all ordinary adjustments respect one-cycle steps")


def _optimization_step_override_keys(
    plan: Mapping[str, Any],
) -> set[Tuple[str, str]]:
    metrics = plan.get("metrics") if isinstance(plan.get("metrics"), Mapping) else {}
    return {
        (str(item.get("dev_type", "")), str(item.get("dev_name", "")))
        for item in metrics.get("optimizationStepOverrideDevices", []) or []
        if isinstance(item, Mapping)
    }


def _interpolate_curve(soc: float, curve: Sequence[Tuple[float, float]]) -> float:
    ordered = sorted((float(x), float(y)) for x, y in curve)
    if soc <= ordered[0][0]:
        return ordered[0][1]
    if soc >= ordered[-1][0]:
        return ordered[-1][1]
    for (left_soc, left_value), (right_soc, right_value) in zip(ordered, ordered[1:]):
        if left_soc <= soc <= right_soc:
            ratio = (soc - left_soc) / max(EPSILON, right_soc - left_soc)
            return left_value + ratio * (right_value - left_value)
    return ordered[-1][1]


def _soc_derating_check(
    rows: Sequence[Mapping[str, Any]],
    settings: RenewableControlSettings,
) -> CheckResult:
    violations: List[str] = []
    applicable = 0
    for row in rows:
        if row.get("technology") != "storage" or not row.get("online"):
            continue
        soc = _number(row.get("soc"))
        charge_max = _number(row.get("maxChargePowerKw"))
        discharge_max = _number(row.get("maxDischargePowerKw"))
        charge_factor = _number(row.get("chargeDeratingFactor"))
        discharge_factor = _number(row.get("dischargeDeratingFactor"))
        charge_power = _number(row.get("chargePower"))
        discharge_power = _number(row.get("dischargePower"))
        target = _target(row)
        if None in (
            soc,
            charge_max,
            discharge_max,
            charge_factor,
            discharge_factor,
            charge_power,
            discharge_power,
            target,
        ):
            continue
        applicable += 1
        expected_charge = _interpolate_curve(soc, settings.storage_charge_derating_curve)
        expected_discharge = _interpolate_curve(soc, settings.storage_discharge_derating_curve)
        if abs(charge_factor - expected_charge) > 1e-6:
            violations.append(f"{row.get('dev_name')} charge derating factor mismatch")
        if abs(discharge_factor - expected_discharge) > 1e-6:
            violations.append(f"{row.get('dev_name')} discharge derating factor mismatch")
        if charge_power > charge_max * expected_charge + AUDIT_TOLERANCE_KW:
            violations.append(f"{row.get('dev_name')} charge curve limit not applied")
        if discharge_power > discharge_max * expected_discharge + AUDIT_TOLERANCE_KW:
            violations.append(f"{row.get('dev_name')} discharge curve limit not applied")
        if target < -charge_power - AUDIT_TOLERANCE_KW or target > discharge_power + AUDIT_TOLERANCE_KW:
            violations.append(f"{row.get('dev_name')} target exceeds SOC-derated power range")
    return _check_result(violations, applicable, "all storage limits match the configured SOC curves")


def _parallel_converter_check(rows: Sequence[Mapping[str, Any]]) -> CheckResult:
    groups: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        if (
            row.get("category") == "交直流变流器"
            and row.get("online")
            and _target(row) is not None
            and str(row.get("dcTransferGroupId", ""))
        ):
            groups[str(row.get("dcTransferGroupId"))].append(row)
    violations: List[str] = []
    applicable = 0
    for group_id, group_rows in groups.items():
        if len(group_rows) < 2:
            continue
        applicable += 1
        ratios = []
        for row in group_rows:
            capacity = _number(row.get("transferCapacityKw"))
            target = _target(row)
            if capacity is None or capacity <= EPSILON or target is None:
                violations.append(f"{group_id} contains a converter without valid capacity")
                ratios = []
                break
            ratios.append(target / capacity)
        if ratios and max(ratios) - min(ratios) > 1e-6:
            violations.append(f"{group_id} converter targets are not capacity-proportional")
    return _check_result(violations, applicable, "parallel converters share power in proportion to capacity")


@dataclass(frozen=True)
class _LpVariable:
    key: Tuple[str, str]
    island_id: str
    kind: str
    current: float
    lower: float
    upper: float
    side: str = ""
    ac_coefficient: float = 0.0
    dc_coefficient: float = 0.0
    converter_group: str = ""
    converter_capacity: float = 0.0
    target: float = 0.0


def _optimization_variable(
    row: Mapping[str, Any],
    settings: RenewableControlSettings,
    override_keys: set[Tuple[str, str]],
) -> Optional[_LpVariable]:
    if not row.get("online"):
        return None
    key = (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
    island_id = str(row.get("optimizationIslandId", ""))
    current = _number(row.get("planningCurrentKw", row.get("currentKw")))
    target = _target(row)
    if not all(key) or not island_id or current is None or target is None:
        return None
    if row.get("technology") in {"wind", "pv"} and row.get("commandable"):
        capacity = _number(row.get("capacityKw"))
        if capacity is None or capacity < 0.0:
            return None
        step = settings.step_coefficient * capacity
        upper = min(capacity, max(0.0, current) + step)
        lower = 0.0 if key in override_keys else max(0.0, current - step)
        if lower > upper:
            lower = upper
        return _LpVariable(
            key, island_id, "renewable", current, lower, upper,
            side=str(row.get("connectionSide", "")), target=target,
        )
    if row.get("category") == "柴油发电" and (
        row.get("commandable") or row.get("stateEligible")
    ):
        minimum = _number(row.get("minKw"))
        maximum = _number(row.get("capacityKw"))
        if minimum is None or maximum is None or minimum > maximum:
            return None
        guard = min(
            settings.diesel_power_protection_ratio * maximum,
            max(0.0, maximum - minimum) * 0.5,
        )
        return _LpVariable(
            key, island_id, "diesel", current, minimum + guard, maximum - guard,
            side=str(row.get("connectionSide", "")), target=target,
        )
    if row.get("technology") == "storage" and (
        row.get("commandable") or (row.get("role") == "balance" and row.get("stateEligible"))
    ):
        charge = _number(row.get("chargePower"))
        discharge = _number(row.get("dischargePower"))
        rated_charge = _number(row.get("maxChargePowerKw"))
        rated_discharge = _number(row.get("maxDischargePowerKw"))
        if None in (charge, discharge, rated_charge, rated_discharge):
            return None
        safety_lower = -charge
        safety_upper = discharge
        if row.get("role") == "balance":
            ratio = min(0.5, max(0.0, settings.grid_forming_storage_protection_ratio))
            safety_lower = max(safety_lower, -rated_charge * (1.0 - ratio))
            safety_upper = min(safety_upper, rated_discharge * (1.0 - ratio))
        step = settings.storage_step_ratio * max(
            charge, discharge, rated_charge, rated_discharge
        )
        soc = _number(row.get("soc"))
        soc_min = _number(row.get("socMin"))
        soc_max = _number(row.get("socMax"))
        if soc is not None and soc_min is not None and soc < soc_min - settings.soc_deadband:
            forced = min(step, max(0.0, -safety_lower))
            if forced > EPSILON:
                safety_upper = min(safety_upper, -forced)
        elif soc is not None and soc_max is not None and soc > soc_max + settings.soc_deadband:
            forced = min(step, max(0.0, safety_upper))
            if forced > EPSILON:
                safety_lower = max(safety_lower, forced)
        if safety_lower > safety_upper + EPSILON:
            return None
        if row.get("role") == "balance":
            lower, upper = safety_lower, safety_upper
        elif current < safety_lower:
            lower = upper = safety_lower
        elif current > safety_upper:
            lower = upper = safety_upper
        else:
            lower = max(safety_lower, current - step)
            upper = min(safety_upper, current + step)
        return _LpVariable(
            key, island_id, "storage", current, lower, upper,
            side=str(row.get("connectionSide", "")), target=target,
        )
    if row.get("category") == "交直流变流器" and row.get("commandable"):
        lower = _number(row.get("signedMinTargetKw"))
        upper = _number(row.get("signedMaxTargetKw"))
        capacity = _number(row.get("transferCapacityKw"))
        if lower is None or upper is None or capacity is None or lower > upper:
            return None
        return _LpVariable(
            key,
            island_id,
            "converter",
            current,
            lower,
            upper,
            ac_coefficient=_number(row.get("acBalanceCoefficient"), -1.0) or -1.0,
            dc_coefficient=_number(row.get("dcBalanceCoefficient"), 1.0) or 1.0,
            converter_group=str(row.get("dcTransferGroupId", "")),
            converter_capacity=capacity,
            target=target,
        )
    return None


def _lexicographic_reference(
    rows: Sequence[Mapping[str, Any]],
    settings: RenewableControlSettings,
    override_keys: set[Tuple[str, str]],
) -> Tuple[Optional[float], Optional[float], str]:
    variables = [
        variable
        for row in rows
        if (variable := _optimization_variable(row, settings, override_keys)) is not None
    ]
    if not variables:
        return None, None, "no optimizer variables"
    balance_keys = sorted(
        {
            (variable.island_id, side)
            for variable in variables
            for side in (
                ("AC", "DC")
                if variable.kind == "converter"
                else (variable.side,)
            )
            if side in {"AC", "DC"}
        }
    )
    row_index = {key: index for index, key in enumerate(balance_keys)}
    matrix = np.zeros((len(balance_keys), len(variables)), dtype=float)
    for column, variable in enumerate(variables):
        if variable.kind == "converter":
            matrix[row_index[(variable.island_id, "AC")], column] += variable.ac_coefficient
            matrix[row_index[(variable.island_id, "DC")], column] += variable.dc_coefficient
        else:
            matrix[row_index[(variable.island_id, variable.side)], column] += 1.0
    current = np.array([variable.current for variable in variables], dtype=float)
    equality_rows = [row for row in matrix]
    equality_rhs = list(matrix @ current)

    converter_groups: Dict[Tuple[str, str], List[int]] = defaultdict(list)
    for index, variable in enumerate(variables):
        if variable.kind == "converter" and variable.converter_group:
            converter_groups[(variable.island_id, variable.converter_group)].append(index)
    for indexes in converter_groups.values():
        if len(indexes) < 2:
            continue
        reference = indexes[0]
        for index in indexes[1:]:
            row = np.zeros(len(variables), dtype=float)
            row[index] = variables[reference].converter_capacity
            row[reference] = -variables[index].converter_capacity
            equality_rows.append(row)
            equality_rhs.append(0.0)

    a_eq = np.vstack(equality_rows) if equality_rows else None
    b_eq = np.asarray(equality_rhs, dtype=float) if equality_rhs else None
    bounds = [(variable.lower, variable.upper) for variable in variables]
    renewable_indexes = [
        index for index, variable in enumerate(variables) if variable.kind == "renewable"
    ]
    diesel_indexes = [
        index for index, variable in enumerate(variables) if variable.kind == "diesel"
    ]
    if not renewable_indexes:
        return None, None, "no renewable variables"

    renewable_objective = np.zeros(len(variables), dtype=float)
    renewable_objective[renewable_indexes] = -1.0
    stage_one = linprog(
        renewable_objective,
        A_eq=a_eq,
        b_eq=b_eq,
        bounds=bounds,
        method="highs",
    )
    if not stage_one.success or stage_one.x is None:
        return None, None, f"reference renewable LP infeasible: {stage_one.message}"
    maximum_renewable = float(np.sum(stage_one.x[renewable_indexes]))

    renewable_fix = np.zeros(len(variables), dtype=float)
    renewable_fix[renewable_indexes] = 1.0
    if a_eq is None:
        stage_two_a_eq = renewable_fix.reshape(1, -1)
        stage_two_b_eq = np.array([maximum_renewable])
    else:
        stage_two_a_eq = np.vstack((a_eq, renewable_fix))
        stage_two_b_eq = np.concatenate((b_eq, np.array([maximum_renewable])))
    diesel_objective = np.zeros(len(variables), dtype=float)
    diesel_objective[diesel_indexes] = 1.0
    stage_two = linprog(
        diesel_objective,
        A_eq=stage_two_a_eq,
        b_eq=stage_two_b_eq,
        bounds=bounds,
        method="highs",
    )
    if not stage_two.success or stage_two.x is None:
        return maximum_renewable, None, f"reference diesel LP infeasible: {stage_two.message}"
    minimum_diesel = float(np.sum(stage_two.x[diesel_indexes]))
    return maximum_renewable, minimum_diesel, "independent two-stage LP solved"


def _objective_checks(
    rows: Sequence[Mapping[str, Any]],
    settings: RenewableControlSettings,
    override_keys: set[Tuple[str, str]],
) -> Tuple[CheckResult, CheckResult, Mapping[str, Any]]:
    maximum_renewable, minimum_diesel, detail = _lexicographic_reference(
        rows,
        settings,
        override_keys,
    )
    actual_renewable = sum(
        _target(row) or 0.0
        for row in rows
        if row.get("technology") in {"wind", "pv"} and row.get("online")
    )
    actual_diesel = sum(
        _target(row) or 0.0
        for row in rows
        if row.get("category") == "柴油发电" and row.get("online")
    )
    if maximum_renewable is None:
        renewable_status = STATUS_NA if detail == "no renewable variables" else STATUS_FAIL
        renewable = CheckResult(renewable_status, detail, 0)
    elif actual_renewable + AUDIT_TOLERANCE_KW < maximum_renewable:
        renewable = CheckResult(
            STATUS_FAIL,
            f"actual={actual_renewable:.3f}, independent optimum={maximum_renewable:.3f}",
            1,
        )
    else:
        renewable = CheckResult(
            STATUS_PASS,
            f"actual={actual_renewable:.3f}, independent optimum={maximum_renewable:.3f}",
            1,
        )
    if minimum_diesel is None:
        diesel_status = STATUS_NA if detail == "no diesel variables" else STATUS_FAIL
        diesel = CheckResult(diesel_status, detail, 0)
    elif actual_diesel > minimum_diesel + AUDIT_TOLERANCE_KW:
        diesel = CheckResult(
            STATUS_FAIL,
            f"actual={actual_diesel:.3f}, independent minimum={minimum_diesel:.3f}",
            1,
        )
    else:
        diesel = CheckResult(
            STATUS_PASS,
            f"actual={actual_diesel:.3f}, independent minimum={minimum_diesel:.3f}",
            1,
        )
    return renewable, diesel, {
        "actual_renewable_kw": actual_renewable,
        "reference_maximum_renewable_kw": maximum_renewable,
        "actual_diesel_kw": actual_diesel,
        "reference_minimum_diesel_kw": minimum_diesel,
        "reference_detail": detail,
    }


def _optimization_balance_check(plan: Mapping[str, Any]) -> CheckResult:
    metrics = plan.get("metrics")
    if not isinstance(metrics, Mapping):
        return CheckResult(STATUS_FAIL, "optimization metrics are missing", 0)
    residual = _number(metrics.get("optimizationMaxBalanceResidualKw"))
    if residual is None:
        return CheckResult(STATUS_FAIL, "optimization balance residual is missing", 0)
    if residual > AUDIT_TOLERANCE_KW:
        return CheckResult(
            STATUS_FAIL,
            f"maximum post-strategy balance residual={residual:.3f} kW",
            1,
        )
    return CheckResult(
        STATUS_PASS,
        f"maximum post-strategy balance residual={residual:.6f} kW",
        1,
    )


def audit_plan(
    plan: Mapping[str, Any],
    settings: RenewableControlSettings,
) -> Tuple[Mapping[str, CheckResult], Mapping[str, Any]]:
    rows = [row for row in plan.get("commandRows", []) or [] if isinstance(row, Mapping)]
    override_keys = _optimization_step_override_keys(plan)
    renewable_check, diesel_check, objective_metrics = _objective_checks(
        rows,
        settings,
        override_keys,
    )
    checks = {
        "optimization_balance": _optimization_balance_check(plan),
        "power_bounds": _power_bounds_check(rows),
        "soc_bounds": _soc_bounds_check(rows),
        "forced_soc_response": _forced_soc_response_check(rows, settings),
        "renewable_minimum": renewable_check,
        "diesel_minimum": diesel_check,
        "protection_bands": _protection_band_check(rows, settings),
        "step_limits": _step_limit_check(rows, plan, settings),
        "soc_derating": _soc_derating_check(rows, settings),
        "parallel_converters": _parallel_converter_check(rows),
    }
    return checks, objective_metrics


def _strategy_rows(plan: Mapping[str, Any]) -> List[Dict[str, Any]]:
    result = []
    for row in plan.get("commandRows", []) or []:
        if not isinstance(row, Mapping) or not row.get("online"):
            continue
        target = _target(row)
        if target is None:
            continue
        result.append(
            {
                "dev_type": str(row.get("dev_type", "")),
                "dev_name": str(row.get("dev_name", "")),
                "category": str(row.get("category", "")),
                "technology": str(row.get("technology", "")),
                "role": str(row.get("role", "")),
                "set_type": str(row.get("set_type", "")),
                "current_kw": _number(row.get("planningCurrentKw", row.get("currentKw"))),
                "target_kw": target,
                "lower_kw": _number(row.get("signedMinTargetKw", row.get("minKw"))),
                "upper_kw": _number(row.get("signedMaxTargetKw", row.get("capacityKw"))),
                "soc": _number(row.get("soc")),
                "optimization_status": str(row.get("optimizationStatus", "")),
                "strategy_command": bool(row.get("strategyCommand")),
            }
        )
    return result


def _weather_availability_diagnostic(plan: Mapping[str, Any]) -> Dict[str, Any]:
    exceeded = []
    total_excess = 0.0
    maximum_excess = 0.0
    for row in plan.get("commandRows", []) or []:
        if not isinstance(row, Mapping) or row.get("technology") not in {"wind", "pv"}:
            continue
        target = _target(row)
        weather_available = _number(row.get("weatherAvailableKw"))
        if not row.get("online") or target is None or weather_available is None:
            continue
        excess = max(0.0, target - weather_available)
        if excess <= AUDIT_TOLERANCE_KW:
            continue
        total_excess += excess
        maximum_excess = max(maximum_excess, excess)
        exceeded.append(
            {
                "dev_type": str(row.get("dev_type", "")),
                "dev_name": str(row.get("dev_name", "")),
                "target_kw": target,
                "weather_available_kw": weather_available,
                "excess_kw": excess,
            }
        )
    return {
        "exceeded": bool(exceeded),
        "device_count": len(exceeded),
        "total_excess_kw": total_excess,
        "maximum_device_excess_kw": maximum_excess,
        "devices": exceeded,
    }


def run_audit(
    project_root: Path,
    *,
    count: int = 100,
    seed: int = 20260809,
    settings: Optional[RenewableControlSettings] = None,
) -> Dict[str, Any]:
    active_settings = (settings or RenewableControlSettings()).normalized()
    base_snapshot = load_qinling_snapshot(project_root)
    inventory = build_inventory(base_snapshot)
    scenarios = generate_scenarios(
        base_snapshot,
        inventory,
        count=count,
        seed=seed,
    )
    records = []
    for scenario in scenarios:
        plan = calculate_renewable_control_plan(
            scenario.snapshot,
            active_settings,
            data_source="remote",
            snapshot_age_seconds=0.0,
        )
        checks, objective_metrics = audit_plan(plan, active_settings)
        metrics = plan.get("metrics") if isinstance(plan.get("metrics"), Mapping) else {}
        data_quality = plan.get("dataQuality") if isinstance(plan.get("dataQuality"), Mapping) else {}
        optimizer_success = bool(metrics.get("optimizationAllIslandsSuccessful"))
        dispatch_allowed = bool(data_quality.get("dispatchAllowed"))
        weather_diagnostic = _weather_availability_diagnostic(plan)
        records.append(
            {
                "scenario_id": scenario.scenario_id,
                "categories": dict(scenario.categories),
                "values": dict(scenario.values),
                "checks": {name: asdict(result) for name, result in checks.items()},
                "overall_pass": bool(
                    optimizer_success
                    and dispatch_allowed
                    and all(result.status != STATUS_FAIL for result in checks.values())
                ),
                "data_quality": copy.deepcopy(data_quality),
                "warnings": list(plan.get("warnings", []) or []),
                "weather_availability_diagnostic": weather_diagnostic,
                "optimization": {
                    "all_islands_successful": optimizer_success,
                    "max_balance_residual_kw": _number(metrics.get("optimizationMaxBalanceResidualKw")),
                    "step_override_applied": bool(metrics.get("optimizationStepOverrideApplied")),
                    "storage_charge_derating_active": bool(metrics.get("storageChargeDeratingActive")),
                    "storage_discharge_derating_active": bool(metrics.get("storageDischargeDeratingActive")),
                    "storage_below_lower_count": int(_number(metrics.get("storageBelowLowerCount"), 0.0) or 0),
                    "storage_above_upper_count": int(_number(metrics.get("storageAboveUpperCount"), 0.0) or 0),
                    "curtailment_kw": _number(metrics.get("curtailKw")),
                    "diesel_target_kw": _number(metrics.get("dieselTargetKw")),
                    **objective_metrics,
                },
                "dispatch_commands": copy.deepcopy(list(plan.get("commands", []) or [])),
                "commands": _strategy_rows(plan),
            }
        )

    criterion_summary = {}
    for name in CRITERION_LABELS:
        statuses = Counter(record["checks"][name]["status"] for record in records)
        criterion_summary[name] = {
            "label": CRITERION_LABELS[name],
            "pass": statuses[STATUS_PASS],
            "fail": statuses[STATUS_FAIL],
            "not_applicable": statuses[STATUS_NA],
        }
    category_coverage = {
        dimension: dict(Counter(record["categories"][dimension] for record in records))
        for dimension in (
            "wind",
            "solar",
            "ac_soc",
            "dc_soc",
            "ac_storage_power",
            "dc_storage_power",
            "diesel",
            "ac_load",
            "dc_load",
        )
    }
    operational_summary = {
        "optimizer_success": sum(
            1 for record in records if record["optimization"]["all_islands_successful"]
        ),
        "dispatch_allowed": sum(
            1 for record in records if record["data_quality"].get("dispatchAllowed")
        ),
        "balanced_strategies": sum(
            1
            for record in records
            if record["checks"]["optimization_balance"]["status"] == STATUS_PASS
        ),
        "step_override_scenarios": sum(
            1 for record in records if record["optimization"]["step_override_applied"]
        ),
        "charge_derating_scenarios": sum(
            1 for record in records if record["optimization"]["storage_charge_derating_active"]
        ),
        "discharge_derating_scenarios": sum(
            1 for record in records if record["optimization"]["storage_discharge_derating_active"]
        ),
        "below_soc_lower_scenarios": sum(
            1 for record in records if record["optimization"]["storage_below_lower_count"] > 0
        ),
        "above_soc_upper_scenarios": sum(
            1 for record in records if record["optimization"]["storage_above_upper_count"] > 0
        ),
        "warning_scenarios": sum(1 for record in records if record["warnings"]),
        "weather_estimate_exceeded_scenarios": sum(
            1 for record in records if record["weather_availability_diagnostic"]["exceeded"]
        ),
        "maximum_weather_estimate_excess_kw": max(
            (
                record["weather_availability_diagnostic"]["maximum_device_excess_kw"]
                for record in records
            ),
            default=0.0,
        ),
        "maximum_balance_residual_kw": max(
            (
                record["optimization"]["max_balance_residual_kw"] or 0.0
                for record in records
            ),
            default=0.0,
        ),
        "maximum_initial_balance_residual_kw": max(
            (
                max(
                    abs(record["values"]["initial_ac_balance_residual_kw"]),
                    abs(record["values"]["initial_dc_balance_residual_kw"]),
                )
                for record in records
            ),
            default=0.0,
        ),
    }
    variable_ranges = {
        key: {
            "minimum": min(record["values"][key] for record in records),
            "maximum": max(record["values"][key] for record in records),
        }
        for key in (
            "ac_renewable_current_kw",
            "dc_renewable_current_kw",
            "ac_storage_soc",
            "dc_storage_soc",
            "ac_storage_power_kw",
            "dc_storage_power_kw",
            "diesel_power_kw",
            "ac_load_kw",
            "dc_load_kw",
            "converter_p_ac_kw",
        )
    }
    return {
        "model": "Qinling Station",
        "count": count,
        "seed": seed,
        "settings": active_settings.payload(),
        "summary": {
            "overall_pass": sum(1 for record in records if record["overall_pass"]),
            "overall_fail": sum(1 for record in records if not record["overall_pass"]),
            "criterion_summary": criterion_summary,
            "category_coverage": category_coverage,
            "operational_summary": operational_summary,
            "variable_ranges": variable_ranges,
        },
        "scenarios": records,
    }


def write_audit_outputs(result: Mapping[str, Any], output_dir: Path) -> Dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    count = int(result.get("count", 0))
    output_stem = f"qinling_strategy_audit_{count}"
    json_path = output_dir / f"{output_stem}.json"
    csv_path = output_dir / f"{output_stem}.csv"
    report_path = output_dir / f"{output_stem}.md"
    json_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    scenarios = list(result.get("scenarios", []))
    fieldnames = [
        "scenario_id",
        "overall_pass",
        "wind",
        "solar",
        "ac_soc",
        "dc_soc",
        "ac_storage_power",
        "dc_storage_power",
        "diesel",
        "ac_load",
        "dc_load",
        "wind_speed_mps",
        "solar_irradiance_w_m2",
        "ac_storage_soc_value",
        "dc_storage_soc_value",
        "ac_storage_power_kw",
        "dc_storage_power_kw",
        "diesel_power_kw",
        "ac_load_kw",
        "dc_load_kw",
        "ac_renewable_power_kw",
        "dc_renewable_power_kw",
        "converter_p_ac_kw",
        "initial_ac_balance_residual_kw",
        "initial_dc_balance_residual_kw",
        *CRITERION_LABELS.keys(),
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in scenarios:
            row = {
                "scenario_id": record["scenario_id"],
                "overall_pass": record["overall_pass"],
                **record["categories"],
                "wind_speed_mps": record["values"]["wind_speed_mps"],
                "solar_irradiance_w_m2": record["values"]["solar_irradiance_w_m2"],
                "ac_storage_soc_value": record["values"]["ac_storage_soc"],
                "dc_storage_soc_value": record["values"]["dc_storage_soc"],
                "ac_storage_power_kw": record["values"]["ac_storage_power_kw"],
                "dc_storage_power_kw": record["values"]["dc_storage_power_kw"],
                "diesel_power_kw": record["values"]["diesel_power_kw"],
                "ac_load_kw": record["values"]["ac_load_kw"],
                "dc_load_kw": record["values"]["dc_load_kw"],
                "ac_renewable_power_kw": record["values"]["ac_renewable_current_kw"],
                "dc_renewable_power_kw": record["values"]["dc_renewable_current_kw"],
                "converter_p_ac_kw": record["values"]["converter_p_ac_kw"],
                "initial_ac_balance_residual_kw": record["values"]["initial_ac_balance_residual_kw"],
                "initial_dc_balance_residual_kw": record["values"]["initial_dc_balance_residual_kw"],
            }
            row.update(
                {
                    name: record["checks"][name]["status"]
                    for name in CRITERION_LABELS
                }
            )
            writer.writerow(row)

    summary = result["summary"]
    lines = [
        f"# 秦岭站新能源优化控制 {count} 工况自动审计",
        "",
        f"- 随机种子：`{result['seed']}`",
        f"- 工况数：`{result['count']}`",
        f"- 全部判据通过：`{summary['overall_pass']}`",
        f"- 至少一项失败：`{summary['overall_fail']}`",
        "- 电力方向：储能正值为放电、负值为充电；变流器 `P_AC>0` 为 AC→DC，`P_AC<0` 为 DC→AC。",
        "- 初始 ACDC 功率由直流侧平衡式自动生成：`P_AC = P_DC负荷 - P_DC储能 - P_DC新能源`，并独立复核交流侧平衡。",
        "- 当前控制合同把风速/辐照度可发功率作为统计值，不作为优化硬上限；设备硬上限仍取模型铭牌 `p_min/p_max`。",
        "",
        "## 判据汇总",
        "",
        "| 判据 | 通过 | 失败 | 不适用 |",
        "|---|---:|---:|---:|",
    ]
    for item in summary["criterion_summary"].values():
        lines.append(
            f"| {item['label']} | {item['pass']} | {item['fail']} | {item['not_applicable']} |"
        )
    operational = summary["operational_summary"]
    lines.extend(
        [
            "",
            "## 运行统计",
            "",
            f"- 优化岛全部求解成功：`{operational['optimizer_success']}/{result['count']}`",
            f"- 数据质量允许下发：`{operational['dispatch_allowed']}/{result['count']}`",
            f"- 优化后功率平衡：`{operational['balanced_strategies']}/{result['count']}`",
            f"- 安全校正突破普通步长：`{operational['step_override_scenarios']}` 个工况",
            f"- 充电SOC降额激活：`{operational['charge_derating_scenarios']}` 个工况",
            f"- 放电SOC降额激活：`{operational['discharge_derating_scenarios']}` 个工况",
            f"- SOC低于下限：`{operational['below_soc_lower_scenarios']}` 个工况",
            f"- SOC高于上限：`{operational['above_soc_upper_scenarios']}` 个工况",
            f"- 含告警但未形成硬约束失败：`{operational['warning_scenarios']}` 个工况",
            f"- 目标超过天气估算可发功率：`{operational['weather_estimate_exceeded_scenarios']}` 个工况（诊断项，不计入九项硬判据）",
            f"- 单设备最大天气估算超额：`{operational['maximum_weather_estimate_excess_kw']:.3f} kW`",
            f"- 最大初始功率平衡残差：`{operational['maximum_initial_balance_residual_kw']:.9f} kW`",
            f"- 最大优化功率平衡残差：`{operational['maximum_balance_residual_kw']:.9f} kW`",
        ]
    )
    range_labels = {
        "ac_renewable_current_kw": "交流新能源出力",
        "dc_renewable_current_kw": "直流新能源出力",
        "ac_storage_soc": "交流储能SOC",
        "dc_storage_soc": "直流储能SOC",
        "ac_storage_power_kw": "交流储能功率",
        "dc_storage_power_kw": "直流储能功率",
        "diesel_power_kw": "柴发功率",
        "ac_load_kw": "交流负荷功率",
        "dc_load_kw": "直流负荷功率",
        "converter_p_ac_kw": "ACDC P_AC",
    }
    lines.extend(
        [
            "",
            "## 随机变量范围",
            "",
            "| 变量 | 最小值 | 最大值 |",
            "|---|---:|---:|",
        ]
    )
    for key, limits in summary["variable_ranges"].items():
        lines.append(
            f"| {range_labels[key]} | {limits['minimum']:.6f} | {limits['maximum']:.6f} |"
        )
    lines.extend(
        [
            "",
            "## 分类覆盖",
            "",
            "| 变量 | 覆盖计数 |",
            "|---|---|",
        ]
    )
    for dimension, counts in summary["category_coverage"].items():
        counts_text = ", ".join(f"{level}={count}" for level, count in sorted(counts.items()))
        lines.append(f"| {dimension} | {counts_text} |")
    failures = [record for record in scenarios if not record["overall_pass"]]
    lines.extend(
        [
            "",
            "## 失败工况",
            "",
        ]
    )
    if not failures:
        lines.append(f"{count} 个工况未发现判据失败。")
    else:
        lines.extend(
            [
                "| 工况 | 失败判据 | 说明 |",
                "|---:|---|---|",
            ]
        )
        for record in failures:
            failed = [
                (CRITERION_LABELS[name], check["detail"])
                for name, check in record["checks"].items()
                if check["status"] == STATUS_FAIL
            ]
            labels = "、".join(label for label, _detail in failed)
            details = "；".join(detail for _label, detail in failed).replace("|", "/")
            lines.append(f"| {record['scenario_id']} | {labels} | {details} |")
    lines.extend(
        [
            "",
            "## 工况明细",
            "",
            "每个工况的完整设备目标和检查细节见同目录 JSON；可筛选明细见 CSV。",
            "",
            "| 工况 | 风/光 | AC/DC SOC | AC/DC储能功率(kW) | 柴发(kW) | AC/DC负荷(kW) | 结论 |",
            "|---:|---|---|---:|---:|---:|---|",
        ]
    )
    for record in scenarios:
        categories = record["categories"]
        values = record["values"]
        lines.append(
            f"| {record['scenario_id']} | {categories['wind']}/{categories['solar']} | "
            f"{values['ac_storage_soc']:.3f}/{values['dc_storage_soc']:.3f} | "
            f"{values['ac_storage_power_kw']:.1f}/{values['dc_storage_power_kw']:.1f} | "
            f"{values['diesel_power_kw']:.1f} | {values['ac_load_kw']:.1f}/{values['dc_load_kw']:.1f} | "
            f"{'通过' if record['overall_pass'] else '失败'} |"
        )
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": json_path, "csv": csv_path, "report": report_path}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Audit Qinling renewable control strategies")
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--count", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=20260809)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("runtime") / "qinling_strategy_audit",
    )
    args = parser.parse_args(argv)
    result = run_audit(
        args.project_root,
        count=args.count,
        seed=args.seed,
    )
    paths = write_audit_outputs(result, args.output_dir)
    print(
        json.dumps(
            {
                "summary": result["summary"],
                "outputs": {name: str(path.resolve()) for name, path in paths.items()},
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if result["summary"]["overall_fail"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
