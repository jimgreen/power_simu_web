from __future__ import annotations

import hashlib
import math
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple

import numpy as np
from scipy.optimize import linprog, lsq_linear, minimize

from .control_config import default_integer, default_number
from .device_roles import (
    AC_TO_DC,
    converter_balance_coefficients,
)
from .resource_topology import DeviceKey, ResourceTopology


EPSILON = 1e-9
BALANCE_TOLERANCE_KW = default_number("optimization_balance_tolerance_kw")
BOUND_TOLERANCE_KW = default_number("optimization_bound_tolerance_kw")
BALANCE_DELTA_SQUARE_WEIGHT = default_number(
    "optimization_balance_delta_square_weight"
)
BALANCE_DELTA_WARNING_KW = default_number(
    "optimization_balance_delta_warning_kw"
)
RENEWABLE_CURTAILMENT_WEIGHT = default_number(
    "optimization_renewable_curtailment_weight"
)
DIESEL_OUTPUT_WEIGHT = default_number("optimization_diesel_output_weight")
CURTAILMENT_SQUARE_WEIGHT = default_number(
    "optimization_curtailment_square_weight"
)
SOURCE_STORAGE_ADJUSTMENT_SQUARE_WEIGHT = default_number(
    "optimization_source_storage_adjustment_square_weight"
)
OPTIMIZATION_FTOL = default_number("optimization_ftol")
OPTIMIZATION_MAX_ITERATIONS = default_integer("optimization_max_iterations")
MAXIMUM_POWER_PROTECTION_RATIO = default_number(
    "maximum_power_protection_ratio"
)
OPTIMIZATION_RANK_TOLERANCE = default_number("optimization_rank_tolerance")
OPTIMIZATION_ZERO_SNAP_TOLERANCE_KW = default_number(
    "optimization_zero_snap_tolerance_kw"
)


def _number(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _device_key(row: Mapping[str, Any]) -> DeviceKey:
    return str(row.get("dev_type", "")), str(row.get("dev_name", ""))


def _component_id(row: Mapping[str, Any]) -> str:
    side = str(row.get("connectionSide", "")).strip().upper()
    if side == "AC":
        return str(row.get("gridComponentId", "")).strip()
    if side == "DC":
        return str(
            row.get("dcTransferGroupId") or row.get("gridComponentId") or ""
        ).strip()
    return ""


@dataclass(frozen=True)
class _Variable:
    key: DeviceKey
    kind: str
    current_kw: float
    lower_kw: float
    upper_kw: float
    side: str = ""
    component_id: str = ""
    ac_component_id: str = ""
    dc_component_id: str = ""
    ac_balance_coefficient: float = 0.0
    dc_balance_coefficient: float = 0.0
    allocation_capacity_kw: float = 0.0
    renewable_available_kw: Optional[float] = None
    safety_lower_kw: Optional[float] = None
    safety_upper_kw: Optional[float] = None
    requires_safety_correction: bool = False
    normal_step_kw: float = 0.0


@dataclass(frozen=True)
class IslandOptimizationResult:
    island_id: str
    component_ids: Tuple[str, ...]
    device_keys: Tuple[DeviceKey, ...]
    success: bool
    status: str
    message: str
    target_by_device: Mapping[DeviceKey, float]
    balance_residual_by_component: Mapping[str, float]
    objective_value: Optional[float]
    renewable_curtailment_kw: float
    diesel_target_kw: float
    curtailment_square_weight: float
    adjustment_square_weight: float
    balance_delta_square_weight: float
    balance_delta_by_side: Mapping[str, float]
    max_balance_delta_kw: float
    step_override_applied: bool
    step_override_devices: Tuple[DeviceKey, ...]
    iterations: int
    solve_seconds: float


@dataclass(frozen=True)
class RenewableDispatchOptimizationResult:
    targets: Mapping[DeviceKey, float]
    available_by_renewable: Mapping[DeviceKey, float]
    curtailment_by_renewable: Mapping[DeviceKey, float]
    islands: Tuple[IslandOptimizationResult, ...]
    unassigned_devices: Tuple[DeviceKey, ...]
    all_success: bool
    max_balance_residual_kw: float
    balance_delta_warning_kw: float
    solve_seconds: float


class _DisjointSet:
    def __init__(self) -> None:
        self._parent: Dict[str, str] = {}

    def add(self, value: str) -> None:
        if value:
            self._parent.setdefault(value, value)

    def find(self, value: str) -> str:
        parent = self._parent[value]
        while parent != self._parent[parent]:
            parent = self._parent[parent]
        while value != parent:
            next_value = self._parent[value]
            self._parent[value] = parent
            value = next_value
        return parent

    def union(self, left: str, right: str) -> None:
        self.add(left)
        self.add(right)
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root == right_root:
            return
        if left_root < right_root:
            self._parent[right_root] = left_root
        else:
            self._parent[left_root] = right_root


def _renewable_variable(
    row: Mapping[str, Any],
    step_coefficient: float,
) -> Optional[_Variable]:
    if not row.get("online") or not row.get("commandable"):
        return None
    current = _number(row.get("planningCurrentKw", row.get("currentKw")))
    capacity = _number(row.get("capacityKw"))
    component_id = _component_id(row)
    key = _device_key(row)
    if current is None or capacity is None or capacity < 0.0 or not all(key) or not component_id:
        return None
    step_kw = step_coefficient * max(0.0, capacity)
    available = min(max(0.0, capacity), max(0.0, current) + step_kw)
    lower = max(0.0, current - step_kw)
    if lower > available + EPSILON:
        lower = available
    return _Variable(
        key=key,
        kind="renewable",
        current_kw=current,
        lower_kw=lower,
        upper_kw=max(0.0, available),
        side=str(row.get("connectionSide", "")).strip().upper(),
        component_id=component_id,
        renewable_available_kw=max(0.0, available),
        safety_lower_kw=0.0,
        safety_upper_kw=max(0.0, available),
        requires_safety_correction=bool(
            current < lower - EPSILON or current > available + EPSILON
        ),
        normal_step_kw=step_kw,
    )


def _diesel_variable(
    row: Mapping[str, Any],
    step_coefficient: float,
    protection_ratio: float,
) -> Optional[_Variable]:
    del step_coefficient
    if (
        not row.get("online")
        or row.get("automaticControlBlocked")
        or not (row.get("commandable") or row.get("stateEligible"))
    ):
        return None
    current = _number(row.get("currentKw"))
    minimum = _number(row.get("minKw"))
    maximum = _number(row.get("capacityKw"))
    component_id = _component_id(row)
    key = _device_key(row)
    if (
        current is None
        or minimum is None
        or maximum is None
        or minimum > maximum
        or not all(key)
        or not component_id
    ):
        return None
    guard_kw = min(
        max(0.0, protection_ratio) * max(0.0, maximum),
        max(0.0, maximum - minimum) * 0.5,
    )
    protected_minimum = minimum + guard_kw
    protected_maximum = maximum - guard_kw
    lower = protected_minimum
    upper = protected_maximum
    return _Variable(
        key=key,
        kind="diesel",
        current_kw=current,
        lower_kw=lower,
        upper_kw=upper,
        side=str(row.get("connectionSide", "")).strip().upper(),
        component_id=component_id,
        safety_lower_kw=protected_minimum,
        safety_upper_kw=protected_maximum,
        requires_safety_correction=bool(
            current < protected_minimum - EPSILON
            or current > protected_maximum + EPSILON
        ),
        normal_step_kw=math.inf,
    )


def _storage_variable(
    row: Mapping[str, Any],
    grid_forming_protection_ratio: float,
    storage_step_ratio: float,
    soc_deadband: float,
) -> Optional[_Variable]:
    state_eligible = bool(
        row.get("role") == "balance" and row.get("stateEligible")
    )
    if (
        not row.get("online")
        or row.get("automaticControlBlocked")
        or not (row.get("commandable") or state_eligible)
    ):
        return None
    current = _number(row.get("currentKw"))
    charge = _number(row.get("chargePower"))
    discharge = _number(row.get("dischargePower"))
    component_id = _component_id(row)
    key = _device_key(row)
    if (
        current is None
        or charge is None
        or discharge is None
        or charge < 0.0
        or discharge < 0.0
        or not all(key)
        or not component_id
    ):
        return None
    rated_charge = _number(row.get("maxChargePowerKw"))
    rated_discharge = _number(row.get("maxDischargePowerKw"))
    rated_charge_kw = (
        max(0.0, rated_charge) if rated_charge is not None else charge
    )
    rated_discharge_kw = (
        max(0.0, rated_discharge) if rated_discharge is not None else discharge
    )
    charge_derating_factor = _number(row.get("chargeDeratingFactor"))
    discharge_derating_factor = _number(row.get("dischargeDeratingFactor"))
    if charge_derating_factor is not None:
        charge = min(
            charge,
            rated_charge_kw * min(1.0, max(0.0, charge_derating_factor)),
        )
    if discharge_derating_factor is not None:
        discharge = min(
            discharge,
            rated_discharge_kw
            * min(1.0, max(0.0, discharge_derating_factor)),
        )

    safety_lower = -charge
    safety_upper = discharge
    if row.get("role") == "balance":
        protection_ratio = min(
            MAXIMUM_POWER_PROTECTION_RATIO,
            max(0.0, grid_forming_protection_ratio),
        )
        safety_lower = max(
            safety_lower,
            -rated_charge_kw * (1.0 - protection_ratio),
        )
        safety_upper = min(
            safety_upper,
            rated_discharge_kw * (1.0 - protection_ratio),
        )

    explicit_step_kw = next(
        (
            value
            for key_name in ("stepKw", "powerStepKw", "pStepKw")
            if (value := _number(row.get(key_name))) is not None and value >= 0.0
        ),
        None,
    )
    rated_power = max(
        charge,
        discharge,
        rated_charge_kw,
        rated_discharge_kw,
    )
    step_kw = (
        explicit_step_kw
        if explicit_step_kw is not None
        else max(0.0, storage_step_ratio) * rated_power
    )
    soc = _number(row.get("soc"))
    soc_min = _number(row.get("socMin"))
    soc_max = _number(row.get("socMax"))
    if soc is not None and soc_min is not None and soc < soc_min - soc_deadband - EPSILON:
        forced_charge_kw = min(step_kw, max(0.0, -safety_lower))
        if forced_charge_kw > EPSILON:
            safety_upper = min(safety_upper, -forced_charge_kw)
    elif soc is not None and soc_max is not None and soc > soc_max + soc_deadband + EPSILON:
        forced_discharge_kw = min(step_kw, max(0.0, safety_upper))
        if forced_discharge_kw > EPSILON:
            safety_lower = max(safety_lower, forced_discharge_kw)
    if safety_lower > safety_upper + EPSILON:
        return None

    # SOC segment limits define the hard feasible power range. Normal
    # dispatch may move only one configured step inside that range. When the
    # live point is already outside the range, project directly back to the
    # nearest safe boundary instead of preserving an unsafe value merely to
    # satisfy the ordinary step limit.
    if row.get("role") == "balance":
        # Grid-forming storage is a balancing source. It is constrained by
        # its guarded power range and SOC limits, but not by the ordinary
        # single-cycle adjustment step.
        lower = safety_lower
        upper = safety_upper
        normal_step_kw = math.inf
    elif current < safety_lower - EPSILON:
        lower = safety_lower
        upper = safety_lower
        normal_step_kw = step_kw
    elif current > safety_upper + EPSILON:
        lower = safety_upper
        upper = safety_upper
        normal_step_kw = step_kw
    else:
        lower = max(safety_lower, current - step_kw)
        upper = min(safety_upper, current + step_kw)
        normal_step_kw = step_kw
    return _Variable(
        key=key,
        kind="storage",
        current_kw=current,
        lower_kw=lower,
        upper_kw=upper,
        side=str(row.get("connectionSide", "")).strip().upper(),
        component_id=component_id,
        safety_lower_kw=safety_lower,
        safety_upper_kw=safety_upper,
        requires_safety_correction=bool(
            current < safety_lower - EPSILON
            or current > safety_upper + EPSILON
        ),
        normal_step_kw=normal_step_kw,
    )


def _converter_variable(
    row: Mapping[str, Any],
    topology: ResourceTopology,
    converter_step_ratio: float,
) -> Optional[_Variable]:
    del converter_step_ratio
    if not row.get("online") or not row.get("commandable"):
        return None
    key = _device_key(row)
    endpoints = topology.converter_component_ids.get(key)
    current = _number(row.get("currentKw"))
    minimum = _number(row.get("signedMinTargetKw"))
    maximum = _number(row.get("signedMaxTargetKw"))
    try:
        ac_balance_coefficient, dc_balance_coefficient = (
            converter_balance_coefficients(AC_TO_DC)
        )
    except ValueError:
        return None
    if (
        endpoints is None
        or current is None
        or minimum is None
        or maximum is None
        or minimum > maximum
        or abs(abs(ac_balance_coefficient) - 1.0) > EPSILON
        or abs(abs(dc_balance_coefficient) - 1.0) > EPSILON
        or abs(ac_balance_coefficient + dc_balance_coefficient) > EPSILON
        or not all(key)
    ):
        return None
    lower = minimum
    upper = maximum
    allocation_capacity_kw = _number(row.get("transferCapacityKw"))
    if allocation_capacity_kw is None or allocation_capacity_kw <= EPSILON:
        allocation_capacity_kw = max(abs(minimum), abs(maximum))
    if allocation_capacity_kw <= EPSILON:
        return None
    return _Variable(
        key=key,
        kind="converter",
        current_kw=current,
        lower_kw=lower,
        upper_kw=upper,
        ac_component_id=endpoints[0],
        dc_component_id=endpoints[1],
        ac_balance_coefficient=ac_balance_coefficient,
        dc_balance_coefficient=dc_balance_coefficient,
        allocation_capacity_kw=allocation_capacity_kw,
        safety_lower_kw=minimum,
        safety_upper_kw=maximum,
        requires_safety_correction=bool(
            current < minimum - EPSILON or current > maximum + EPSILON
        ),
        normal_step_kw=math.inf,
    )


def _independent_equality_rows(matrix: np.ndarray, rhs: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    if matrix.size == 0:
        return matrix, rhs
    selected: list[int] = []
    rank = 0
    for index in range(matrix.shape[0]):
        candidate = matrix[selected + [index], :]
        candidate_rank = int(
            np.linalg.matrix_rank(
                candidate,
                tol=OPTIMIZATION_RANK_TOLERANCE,
            )
        )
        if candidate_rank > rank:
            selected.append(index)
            rank = candidate_rank
    if not selected:
        return np.zeros((0, matrix.shape[1]), dtype=float), np.zeros(0, dtype=float)
    return matrix[selected, :], rhs[selected]


def _island_id(component_ids: Sequence[str]) -> str:
    payload = "\n".join(component_ids).encode("utf-8")
    return f"HYBRID:{hashlib.sha256(payload).hexdigest()[:16]}"


def _solve_island(
    component_ids: Tuple[str, ...],
    variables: Sequence[_Variable],
    *,
    renewable_curtailment_weight: float,
    diesel_output_weight: float,
    curtailment_square_weight: float,
    adjustment_square_weight: float,
    balance_delta_square_weight: float,
    balance_tolerance_kw: float,
    bound_tolerance_kw: float,
    optimization_ftol: float,
    optimization_max_iterations: int,
) -> IslandOptimizationResult:
    started = time.perf_counter()
    island_id = _island_id(component_ids)
    ordered = sorted(
        variables,
        key=lambda item: (
            {"renewable": 0, "diesel": 1, "storage": 2, "converter": 3}.get(item.kind, 9),
            item.key,
        ),
    )
    count = len(ordered)
    if count == 0:
        return IslandOptimizationResult(
            island_id=island_id,
            component_ids=component_ids,
            device_keys=(),
            success=True,
            status="empty",
            message="拓扑岛没有可调设备",
            target_by_device={},
            balance_residual_by_component={},
            objective_value=0.0,
            renewable_curtailment_kw=0.0,
            diesel_target_kw=0.0,
            curtailment_square_weight=0.0,
            adjustment_square_weight=0.0,
            balance_delta_square_weight=balance_delta_square_weight,
            balance_delta_by_side={},
            max_balance_delta_kw=0.0,
            step_override_applied=False,
            step_override_devices=(),
            iterations=0,
            solve_seconds=time.perf_counter() - started,
        )

    balance_sides = tuple(
        side
        for side in ("AC", "DC")
        if any(
            item.kind == "converter" or item.side == side
            for item in ordered
        )
    )
    index_by_side = {
        side: index for index, side in enumerate(balance_sides)
    }
    matrix = np.zeros((len(balance_sides), count), dtype=float)
    current = np.array([item.current_kw for item in ordered], dtype=float)
    normal_lower = np.array([item.lower_kw for item in ordered], dtype=float)
    normal_upper = np.array([item.upper_kw for item in ordered], dtype=float)
    for column, item in enumerate(ordered):
        if item.kind == "converter":
            matrix[index_by_side["AC"], column] += item.ac_balance_coefficient
            matrix[index_by_side["DC"], column] += item.dc_balance_coefficient
        else:
            matrix[index_by_side[item.side], column] += 1.0

    rhs = matrix @ current
    parallel_rows: list[np.ndarray] = []
    parallel_groups: Dict[Tuple[str, str], list[int]] = {}
    for index, item in enumerate(ordered):
        if item.kind != "converter":
            continue
        parallel_groups.setdefault(
            (item.ac_component_id, item.dc_component_id),
            [],
        ).append(index)
    for indexes in parallel_groups.values():
        if len(indexes) < 2:
            continue
        reference_index = indexes[0]
        reference_capacity = ordered[reference_index].allocation_capacity_kw
        for index in indexes[1:]:
            row = np.zeros(count, dtype=float)
            row[index] = reference_capacity
            row[reference_index] = -ordered[index].allocation_capacity_kw
            parallel_rows.append(row)
    parallel_matrix = (
        np.vstack(parallel_rows)
        if parallel_rows
        else np.zeros((0, count), dtype=float)
    )
    parallel_rhs = np.zeros(parallel_matrix.shape[0], dtype=float)

    def combined_equalities(
        balance_matrix: np.ndarray,
        balance_rhs: np.ndarray,
    ) -> Tuple[np.ndarray, np.ndarray]:
        if parallel_matrix.shape[0] == 0:
            return balance_matrix, balance_rhs
        if balance_matrix.shape[0] == 0:
            return parallel_matrix, parallel_rhs
        return (
            np.vstack((balance_matrix, parallel_matrix)),
            np.concatenate((balance_rhs, parallel_rhs)),
        )

    def exact_balance_feasibility(
        active_lower: np.ndarray,
        active_upper: np.ndarray,
    ) -> Any:
        equality_matrix, equality_rhs = combined_equalities(matrix, rhs)
        return linprog(
            np.zeros(count, dtype=float),
            A_eq=equality_matrix if equality_matrix.shape[0] else None,
            b_eq=equality_rhs if equality_matrix.shape[0] else None,
            bounds=list(zip(active_lower.tolist(), active_upper.tolist())),
            method="highs",
        )

    feasibility = exact_balance_feasibility(normal_lower, normal_upper)
    active_lower = normal_lower
    active_upper = normal_upper

    renewable_indexes = [index for index, item in enumerate(ordered) if item.kind == "renewable"]
    diesel_indexes = [index for index, item in enumerate(ordered) if item.kind == "diesel"]
    adjustment_indexes = [
        index for index, item in enumerate(ordered) if item.kind in {"diesel", "storage"}
    ]
    renewable_available = np.array(
        [ordered[index].renewable_available_kw or 0.0 for index in renewable_indexes],
        dtype=float,
    )
    def base_objective(device_values: np.ndarray) -> float:
        value = 0.0
        if renewable_indexes:
            curtailment = renewable_available - device_values[renewable_indexes]
            value += renewable_curtailment_weight * float(np.sum(curtailment))
            value += curtailment_square_weight * float(np.dot(curtailment, curtailment))
        if diesel_indexes:
            value += diesel_output_weight * float(np.sum(device_values[diesel_indexes]))
        if adjustment_indexes:
            adjustment = (
                device_values[adjustment_indexes] - current[adjustment_indexes]
            )
            value += adjustment_square_weight * float(np.dot(adjustment, adjustment))
        return value

    def base_gradient(device_values: np.ndarray) -> np.ndarray:
        result = np.zeros(count, dtype=float)
        if renewable_indexes:
            curtailment = renewable_available - device_values[renewable_indexes]
            result[renewable_indexes] = (
                -renewable_curtailment_weight
                - 2.0 * curtailment_square_weight * curtailment
            )
        if diesel_indexes:
            result[diesel_indexes] += diesel_output_weight
        if adjustment_indexes:
            result[adjustment_indexes] += (
                2.0
                * adjustment_square_weight
                * (
                    device_values[adjustment_indexes]
                    - current[adjustment_indexes]
                )
            )
        return result

    def balance_delta(device_values: np.ndarray) -> np.ndarray:
        # A * P + delta = A * P_current.  Eliminating delta from the two
        # balance equations gives this exact expression while leaving only
        # box-constrained device targets for the numerical optimizer.
        return rhs - matrix @ device_values

    def dc_priority_minimum_delta(
        active_lower: np.ndarray,
        active_upper: np.ndarray,
    ) -> Tuple[np.ndarray, bool]:
        """Minimize DC slack first, then AC slack for converter conflicts.

        This priority is only used after exact AC/DC balance has proved
        infeasible in an island containing a grid-boundary converter. It does
        not enter the normal dispatch objective, so AC and DC renewables still
        compete for feasible headroom under the same curtailment objective.
        """
        dc_index = index_by_side["DC"]
        ac_index = index_by_side["AC"]
        device_bounds = list(zip(active_lower.tolist(), active_upper.tolist()))
        extended_bounds = device_bounds + [(0.0, None)]
        extended_parallel_matrix = (
            np.hstack(
                (
                    parallel_matrix,
                    np.zeros((parallel_matrix.shape[0], 1), dtype=float),
                )
            )
            if parallel_matrix.shape[0]
            else None
        )

        dc_row = matrix[dc_index]
        stage_one_inequalities = np.vstack(
            (
                np.append(-dc_row, -1.0),
                np.append(dc_row, -1.0),
            )
        )
        stage_one_rhs = np.array((-rhs[dc_index], rhs[dc_index]), dtype=float)
        stage_one_objective = np.zeros(count + 1, dtype=float)
        stage_one_objective[-1] = 1.0
        stage_one = linprog(
            stage_one_objective,
            A_ub=stage_one_inequalities,
            b_ub=stage_one_rhs,
            A_eq=extended_parallel_matrix,
            b_eq=parallel_rhs if parallel_matrix.shape[0] else None,
            bounds=extended_bounds,
            method="highs",
        )
        if not stage_one.success or stage_one.x is None:
            return np.clip(current, active_lower, active_upper), False

        minimum_dc_delta = max(0.0, float(stage_one.x[-1]))
        priority_tolerance = max(EPSILON, min(1e-6, optimization_ftol))
        dc_delta_limit = minimum_dc_delta + priority_tolerance
        ac_row = matrix[ac_index]
        stage_two_inequalities = np.vstack(
            (
                np.append(-ac_row, -1.0),
                np.append(ac_row, -1.0),
                np.append(-dc_row, 0.0),
                np.append(dc_row, 0.0),
            )
        )
        stage_two_rhs = np.array(
            (
                -rhs[ac_index],
                rhs[ac_index],
                dc_delta_limit - rhs[dc_index],
                dc_delta_limit + rhs[dc_index],
            ),
            dtype=float,
        )
        stage_two_objective = np.zeros(count + 1, dtype=float)
        stage_two_objective[-1] = 1.0
        stage_two = linprog(
            stage_two_objective,
            A_ub=stage_two_inequalities,
            b_ub=stage_two_rhs,
            A_eq=extended_parallel_matrix,
            b_eq=parallel_rhs if parallel_matrix.shape[0] else None,
            bounds=extended_bounds,
            method="highs",
        )
        if not stage_two.success or stage_two.x is None:
            return np.asarray(stage_one.x[:count], dtype=float), False
        return np.asarray(stage_two.x[:count], dtype=float), True

    def objective(device_values: np.ndarray) -> float:
        delta = balance_delta(device_values)
        return base_objective(device_values) + balance_delta_square_weight * float(
            np.dot(delta, delta)
        )

    def solve_with_bounds(
        active_lower: np.ndarray,
        active_upper: np.ndarray,
        initial: Optional[np.ndarray] = None,
    ) -> Tuple[Any, np.ndarray, np.ndarray, bool, bool]:
        primary_converged = True
        if initial is not None:
            minimum_delta_values = np.clip(
                initial,
                active_lower,
                active_upper,
            )
        elif (
            "AC" in index_by_side
            and "DC" in index_by_side
            and any(item.kind == "converter" for item in ordered)
        ):
            minimum_delta_values, primary_converged = dc_priority_minimum_delta(
                active_lower,
                active_upper,
            )
        elif parallel_matrix.shape[0]:
            parallel_feasibility = linprog(
                np.zeros(count, dtype=float),
                A_eq=parallel_matrix,
                b_eq=parallel_rhs,
                bounds=list(zip(active_lower.tolist(), active_upper.tolist())),
                method="highs",
            )
            minimum_delta_values = np.asarray(
                parallel_feasibility.x
                if parallel_feasibility.success
                else np.clip(current, active_lower, active_upper),
                dtype=float,
            )
            parallel_constraints = (
                {
                    "type": "eq",
                    "fun": lambda values: parallel_matrix @ values,
                    "jac": lambda _values: parallel_matrix,
                },
            )
            primary_result = minimize(
                lambda values: float(
                    np.dot(balance_delta(values), balance_delta(values))
                ),
                minimum_delta_values,
                jac=lambda values: -2.0 * matrix.T @ balance_delta(values),
                bounds=list(zip(active_lower.tolist(), active_upper.tolist())),
                constraints=parallel_constraints,
                method="SLSQP",
                options={
                    "ftol": optimization_ftol,
                    "maxiter": optimization_max_iterations,
                    "disp": False,
                },
            )
            primary_values = np.asarray(
                getattr(primary_result, "x", minimum_delta_values),
                dtype=float,
            )
            if (
                primary_values.shape == minimum_delta_values.shape
                and np.all(np.isfinite(primary_values))
            ):
                minimum_delta_values = np.clip(
                    primary_values,
                    active_lower,
                    active_upper,
                )
            primary_converged = bool(primary_result.success)
        else:
            minimum_delta_values = np.clip(
                current,
                active_lower,
                active_upper,
            )
            free_indexes = np.flatnonzero(
                active_upper - active_lower > bound_tolerance_kw
            )
            fixed_indexes = np.flatnonzero(
                active_upper - active_lower <= bound_tolerance_kw
            )
            if free_indexes.size:
                reduced_rhs = rhs.copy()
                if fixed_indexes.size:
                    reduced_rhs -= (
                        matrix[:, fixed_indexes]
                        @ active_lower[fixed_indexes]
                    )
                    minimum_delta_values[fixed_indexes] = active_lower[
                        fixed_indexes
                    ]
                least_squares = lsq_linear(
                    matrix[:, free_indexes],
                    reduced_rhs,
                    bounds=(
                        active_lower[free_indexes],
                        active_upper[free_indexes],
                    ),
                    tol=optimization_ftol,
                    lsmr_tol="auto",
                    max_iter=optimization_max_iterations,
                )
                if least_squares.x is not None and np.all(
                    np.isfinite(least_squares.x)
                ):
                    minimum_delta_values[free_indexes] = least_squares.x
                primary_converged = bool(least_squares.success)
        minimum_delta = balance_delta(minimum_delta_values)
        target_balance = matrix @ minimum_delta_values
        target_matrix, target_rhs = combined_equalities(
            matrix,
            target_balance,
        )
        secondary_matrix, secondary_rhs = _independent_equality_rows(
            target_matrix,
            target_rhs,
        )
        constraints = []
        if secondary_matrix.shape[0]:
            constraints.append(
                {
                    "type": "eq",
                    "fun": lambda values: secondary_matrix @ values
                    - secondary_rhs,
                    "jac": lambda _values: secondary_matrix,
                }
            )
        active_bounds = list(zip(active_lower.tolist(), active_upper.tolist()))
        solved_result = minimize(
            base_objective,
            minimum_delta_values,
            jac=base_gradient,
            bounds=active_bounds,
            constraints=constraints,
            method="SLSQP",
            options={
                "ftol": optimization_ftol,
                "maxiter": optimization_max_iterations,
                "disp": False,
            },
        )
        raw_values = np.asarray(
            getattr(solved_result, "x", minimum_delta_values),
            dtype=float,
        )
        if raw_values.shape != minimum_delta_values.shape or not np.all(
            np.isfinite(raw_values)
        ):
            raw_values = minimum_delta_values
        solved_device_values = np.clip(
            raw_values,
            active_lower,
            active_upper,
        )
        solved_balance_delta = balance_delta(solved_device_values)
        delta_drift = float(
            np.max(np.abs(solved_balance_delta - minimum_delta))
        ) if minimum_delta.size else 0.0
        if not solved_result.success or delta_drift > balance_tolerance_kw:
            solved_device_values = minimum_delta_values
            solved_balance_delta = minimum_delta
        bounds_valid = bool(
            np.all(solved_device_values >= active_lower - bound_tolerance_kw)
            and np.all(solved_device_values <= active_upper + bound_tolerance_kw)
        )
        parallel_valid = bool(
            parallel_matrix.shape[0] == 0
            or np.max(np.abs(parallel_matrix @ solved_device_values))
            <= bound_tolerance_kw
        )
        valid = bool(
            np.all(np.isfinite(solved_device_values))
            and np.all(np.isfinite(solved_balance_delta))
            and bounds_valid
            and parallel_valid
        )
        return (
            solved_result,
            solved_device_values,
            solved_balance_delta,
            valid,
            bool(primary_converged and solved_result.success),
        )

    solved, values, solved_balance_delta, success, solver_converged = solve_with_bounds(
        active_lower,
        active_upper,
        feasibility.x if feasibility.success else None,
    )
    if not success:
        return IslandOptimizationResult(
            island_id=island_id,
            component_ids=component_ids,
            device_keys=tuple(item.key for item in ordered),
            success=False,
            status="failed",
            message=str(solved.message),
            target_by_device={},
            balance_residual_by_component={},
            objective_value=None,
            renewable_curtailment_kw=0.0,
            diesel_target_kw=0.0,
            curtailment_square_weight=curtailment_square_weight,
            adjustment_square_weight=adjustment_square_weight,
            balance_delta_square_weight=balance_delta_square_weight,
            balance_delta_by_side={},
            max_balance_delta_kw=0.0,
            step_override_applied=False,
            step_override_devices=(),
            iterations=int(getattr(solved, "nit", 0) or 0) if solved is not None else 0,
            solve_seconds=time.perf_counter() - started,
        )

    values[np.abs(values) < OPTIMIZATION_ZERO_SNAP_TOLERANCE_KW] = 0.0
    solved_balance_delta[
        np.abs(solved_balance_delta) < OPTIMIZATION_ZERO_SNAP_TOLERANCE_KW
    ] = 0.0
    step_override_devices = tuple(
        item.key
        for index, item in enumerate(ordered)
        if abs(values[index] - item.current_kw)
        > item.normal_step_kw + bound_tolerance_kw
    )
    step_override_applied = bool(step_override_devices)
    targets = {item.key: float(values[index]) for index, item in enumerate(ordered)}
    physical_residual_vector = matrix @ (values - current)
    residuals = {
        side: float(physical_residual_vector[index])
        for index, side in enumerate(balance_sides)
    }
    balance_delta_by_side = {
        side: float(solved_balance_delta[index])
        for index, side in enumerate(balance_sides)
    }
    max_balance_delta_kw = max(
        (abs(value) for value in balance_delta_by_side.values()),
        default=0.0,
    )
    balance_delta_active = max_balance_delta_kw > balance_tolerance_kw
    renewable_curtailment = sum(
        max(0.0, (item.renewable_available_kw or 0.0) - targets[item.key])
        for item in ordered
        if item.kind == "renewable"
    )
    diesel_target = sum(
        targets[item.key] for item in ordered if item.kind == "diesel"
    )
    if not solver_converged:
        status = "feasible_balance_delta_fallback"
    elif step_override_applied and balance_delta_active:
        status = "optimal_safety_override_with_balance_slack"
    elif balance_delta_active:
        status = "optimal_with_balance_slack"
    elif step_override_applied:
        status = "optimal_safety_override"
    else:
        status = "optimal"
    message = str(solved.message)
    if balance_delta_active:
        message = (
            f"{message}; max(delta_ac, delta_dc)="
            f"{max_balance_delta_kw:.6g} kW"
        )
    return IslandOptimizationResult(
        island_id=island_id,
        component_ids=component_ids,
        device_keys=tuple(item.key for item in ordered),
        success=True,
        status=status,
        message=message,
        target_by_device=targets,
        balance_residual_by_component=residuals,
        objective_value=float(objective(values)),
        renewable_curtailment_kw=renewable_curtailment,
        diesel_target_kw=diesel_target,
        curtailment_square_weight=curtailment_square_weight,
        adjustment_square_weight=adjustment_square_weight,
        balance_delta_square_weight=balance_delta_square_weight,
        balance_delta_by_side=balance_delta_by_side,
        max_balance_delta_kw=max_balance_delta_kw,
        step_override_applied=step_override_applied,
        step_override_devices=step_override_devices,
        iterations=int(getattr(solved, "nit", 0) or 0),
        solve_seconds=time.perf_counter() - started,
    )


def optimize_topology_islands(
    topology: ResourceTopology,
    *,
    renewable_rows: Sequence[Mapping[str, Any]],
    diesel_rows: Sequence[Mapping[str, Any]],
    storage_rows: Sequence[Mapping[str, Any]],
    converter_rows: Sequence[Mapping[str, Any]],
    step_coefficient: float = default_number("renewable_step_ratio"),
    converter_step_ratio: float = default_number("legacy_converter_step_ratio"),
    storage_step_ratio: float = default_number(
        "grid_following_storage_step_ratio"
    ),
    diesel_power_protection_ratio: float = default_number(
        "diesel_power_protection_ratio"
    ),
    grid_forming_storage_protection_ratio: float = default_number(
        "grid_forming_storage_protection_ratio"
    ),
    soc_deadband: float = default_number("soc_deadband"),
    renewable_curtailment_weight: float = RENEWABLE_CURTAILMENT_WEIGHT,
    diesel_output_weight: float = DIESEL_OUTPUT_WEIGHT,
    curtailment_square_weight: float = CURTAILMENT_SQUARE_WEIGHT,
    source_storage_adjustment_square_weight: float = SOURCE_STORAGE_ADJUSTMENT_SQUARE_WEIGHT,
    balance_delta_square_weight: float = BALANCE_DELTA_SQUARE_WEIGHT,
    balance_delta_warning_kw: float = BALANCE_DELTA_WARNING_KW,
    balance_tolerance_kw: float = BALANCE_TOLERANCE_KW,
    bound_tolerance_kw: float = BOUND_TOLERANCE_KW,
    optimization_ftol: float = OPTIMIZATION_FTOL,
    optimization_max_iterations: int = OPTIMIZATION_MAX_ITERATIONS,
) -> RenewableDispatchOptimizationResult:
    started = time.perf_counter()
    step_coefficient = max(0.0, float(step_coefficient))
    converter_step_ratio = max(0.0, float(converter_step_ratio))
    storage_step_ratio = max(0.0, float(storage_step_ratio))
    diesel_power_protection_ratio = min(
        MAXIMUM_POWER_PROTECTION_RATIO,
        max(0.0, float(diesel_power_protection_ratio)),
    )
    grid_forming_storage_protection_ratio = min(
        MAXIMUM_POWER_PROTECTION_RATIO,
        max(0.0, float(grid_forming_storage_protection_ratio)),
    )
    soc_deadband = max(0.0, float(soc_deadband))
    renewable_curtailment_weight = max(
        0.0, float(renewable_curtailment_weight)
    )
    diesel_output_weight = max(0.0, float(diesel_output_weight))
    curtailment_square_weight = max(0.0, float(curtailment_square_weight))
    source_storage_adjustment_square_weight = max(
        0.0, float(source_storage_adjustment_square_weight)
    )
    balance_delta_square_weight = max(
        EPSILON, float(balance_delta_square_weight)
    )
    balance_delta_warning_kw = max(0.0, float(balance_delta_warning_kw))
    balance_tolerance_kw = max(EPSILON, float(balance_tolerance_kw))
    bound_tolerance_kw = max(EPSILON, float(bound_tolerance_kw))
    optimization_ftol = max(EPSILON, float(optimization_ftol))
    optimization_max_iterations = max(1, int(optimization_max_iterations))
    variables: list[_Variable] = []
    expected_keys: set[DeviceKey] = set()

    for row in renewable_rows:
        if row.get("online") and row.get("commandable"):
            expected_keys.add(_device_key(row))
        variable = _renewable_variable(row, step_coefficient)
        if variable is not None:
            variables.append(variable)
    for row in diesel_rows:
        if (
            row.get("online")
            and not row.get("automaticControlBlocked")
            and (row.get("commandable") or row.get("stateEligible"))
        ):
            expected_keys.add(_device_key(row))
        variable = _diesel_variable(
            row,
            step_coefficient,
            diesel_power_protection_ratio,
        )
        if variable is not None:
            variables.append(variable)
    for row in storage_rows:
        if (
            row.get("online")
            and not row.get("automaticControlBlocked")
            and (
                row.get("commandable")
                or row.get("role") == "balance"
                and row.get("stateEligible")
            )
        ):
            expected_keys.add(_device_key(row))
        variable = _storage_variable(
            row,
            grid_forming_storage_protection_ratio,
            storage_step_ratio,
            soc_deadband,
        )
        if variable is not None:
            variables.append(variable)
    for row in converter_rows:
        if row.get("online") and row.get("commandable"):
            expected_keys.add(_device_key(row))
        variable = _converter_variable(row, topology, converter_step_ratio)
        if variable is not None:
            variables.append(variable)

    variable_keys = {item.key for item in variables}
    unassigned = tuple(sorted(expected_keys - variable_keys))
    components = _DisjointSet()
    for item in variables:
        if item.kind == "converter":
            components.union(item.ac_component_id, item.dc_component_id)
        else:
            components.add(item.component_id)
    for ac_component_id, dc_component_id in topology.converter_component_ids.values():
        components.union(ac_component_id, dc_component_id)

    variables_by_root: Dict[str, list[_Variable]] = {}
    components_by_root: Dict[str, set[str]] = {}
    for component_id in list(components._parent):
        root = components.find(component_id)
        components_by_root.setdefault(root, set()).add(component_id)
    for item in variables:
        component_id = item.ac_component_id if item.kind == "converter" else item.component_id
        root = components.find(component_id)
        variables_by_root.setdefault(root, []).append(item)

    island_results = tuple(
        _solve_island(
            tuple(sorted(components_by_root[root])),
            variables_by_root.get(root, ()),
            renewable_curtailment_weight=renewable_curtailment_weight,
            diesel_output_weight=diesel_output_weight,
            curtailment_square_weight=curtailment_square_weight,
            adjustment_square_weight=source_storage_adjustment_square_weight,
            balance_delta_square_weight=balance_delta_square_weight,
            balance_tolerance_kw=balance_tolerance_kw,
            bound_tolerance_kw=bound_tolerance_kw,
            optimization_ftol=optimization_ftol,
            optimization_max_iterations=optimization_max_iterations,
        )
        for root in sorted(components_by_root)
        if variables_by_root.get(root)
    )
    targets: Dict[DeviceKey, float] = {}
    for island in island_results:
        if island.success:
            targets.update(island.target_by_device)
    available_by_renewable = {
        item.key: float(item.renewable_available_kw or 0.0)
        for item in variables
        if item.kind == "renewable"
    }
    curtailment_by_renewable = {
        key: max(0.0, available - targets.get(key, available))
        for key, available in available_by_renewable.items()
        if key in targets
    }
    max_residual = max(
        (
            abs(residual)
            for island in island_results
            for residual in island.balance_residual_by_component.values()
        ),
        default=0.0,
    )
    return RenewableDispatchOptimizationResult(
        targets=targets,
        available_by_renewable=available_by_renewable,
        curtailment_by_renewable=curtailment_by_renewable,
        islands=island_results,
        unassigned_devices=unassigned,
        all_success=bool(island_results)
        and all(island.success for island in island_results)
        and not unassigned,
        max_balance_residual_kw=max_residual,
        balance_delta_warning_kw=balance_delta_warning_kw,
        solve_seconds=time.perf_counter() - started,
    )
