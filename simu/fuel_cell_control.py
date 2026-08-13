"""Pure fuel-cell power state machine used by renewable control."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


EPSILON = 1e-9


@dataclass(frozen=True)
class FuelCellControlParameters:
    """Fuel-cell thresholds configured independently from electrolyzer control."""

    power_step_kw: float
    diesel_power_limit_kw: float
    electric_storage_soc_limit: float
    hydrogen_storage_soc_start_limit: float
    hydrogen_storage_soc_stop_limit: float


@dataclass(frozen=True)
class FuelCellControlInputs:
    current_power_kw: float
    maximum_power_kw: float
    start_threshold_kw: float
    stop_threshold_kw: float
    diesel_average_power_kw: float
    diesel_unit_count: int
    electric_storage_soc_average: Optional[float]
    hydrogen_storage_soc_average: Optional[float]


@dataclass(frozen=True)
class FuelCellControlDecision:
    action: str
    requested_delta_kw: float = 0.0
    required_start_delta_kw: Optional[float] = None
    reason: str = "hold_region"
    diesel_raise_margin_kw: float = 0.0
    diesel_reduce_margin_kw: float = 0.0


def _finite(value: Optional[float]) -> bool:
    return value is not None and math.isfinite(float(value))


def calculate_fuel_cell_power_decision(
    parameters: FuelCellControlParameters,
    inputs: FuelCellControlInputs,
) -> FuelCellControlDecision:
    """Return one-cycle start/increase/decrease/stop decision for a fuel cell.

    Diesel thresholds use average kW per online diesel unit. Electric-storage
    SOC uses the complete online fleet average, while hydrogen SOC uses the
    complete average of online tanks in the fuel cell's hydrogen island.
    """

    electric_soc = inputs.electric_storage_soc_average
    hydrogen_soc = inputs.hydrogen_storage_soc_average
    if not _finite(electric_soc) or not _finite(hydrogen_soc):
        return FuelCellControlDecision(
            action="hold",
            reason="incomplete_average_input",
        )

    diesel_count = max(1, int(inputs.diesel_unit_count))
    current_power = max(0.0, float(inputs.current_power_kw))
    maximum_power = max(0.0, float(inputs.maximum_power_kw))
    step_kw = max(0.0, float(parameters.power_step_kw))
    diesel_average = float(inputs.diesel_average_power_kw)
    diesel_limit = float(parameters.diesel_power_limit_kw)
    diesel_raise_margin_kw = max(
        0.0,
        (diesel_average - diesel_limit) * diesel_count,
    )
    diesel_reduce_margin_kw = max(
        0.0,
        (diesel_limit - diesel_average) * diesel_count,
    )

    electric_soc_low = (
        float(electric_soc)
        < float(parameters.electric_storage_soc_limit) - EPSILON
    )
    electric_soc_high = (
        float(electric_soc)
        > float(parameters.electric_storage_soc_limit) + EPSILON
    )
    hydrogen_soc_above_start = (
        float(hydrogen_soc)
        > float(parameters.hydrogen_storage_soc_start_limit) + EPSILON
    )
    hydrogen_soc_above_stop = (
        float(hydrogen_soc)
        > float(parameters.hydrogen_storage_soc_stop_limit) + EPSILON
    )
    hydrogen_soc_below_stop = (
        float(hydrogen_soc)
        < float(parameters.hydrogen_storage_soc_stop_limit) - EPSILON
    )

    running = current_power > EPSILON
    if not running:
        start_allowed = bool(
            diesel_raise_margin_kw > EPSILON
            and electric_soc_low
            and hydrogen_soc_above_start
        )
        if not start_allowed:
            return FuelCellControlDecision(
                action="hold",
                reason="start_conditions_not_met",
                diesel_raise_margin_kw=diesel_raise_margin_kw,
                diesel_reduce_margin_kw=diesel_reduce_margin_kw,
            )
        required_start = max(0.0, float(inputs.start_threshold_kw))
        if (
            required_start > diesel_raise_margin_kw + EPSILON
            or required_start > step_kw + EPSILON
            or required_start > maximum_power + EPSILON
        ):
            return FuelCellControlDecision(
                action="hold",
                required_start_delta_kw=required_start,
                reason="start_margin_insufficient",
                diesel_raise_margin_kw=diesel_raise_margin_kw,
                diesel_reduce_margin_kw=diesel_reduce_margin_kw,
            )
        return FuelCellControlDecision(
            action="start",
            requested_delta_kw=required_start,
            required_start_delta_kw=required_start,
            reason="start_conditions_met",
            diesel_raise_margin_kw=diesel_raise_margin_kw,
            diesel_reduce_margin_kw=diesel_reduce_margin_kw,
        )

    raise_allowed = bool(
        diesel_raise_margin_kw > EPSILON
        and electric_soc_low
        and hydrogen_soc_above_stop
    )
    storage_reduce_required = bool(electric_soc_high or hydrogen_soc_below_stop)
    diesel_reduce_required = diesel_reduce_margin_kw > EPSILON

    if raise_allowed:
        delta_kw = min(
            diesel_raise_margin_kw,
            step_kw,
            max(0.0, maximum_power - current_power),
        )
        return FuelCellControlDecision(
            action="increase" if delta_kw > EPSILON else "hold",
            requested_delta_kw=delta_kw,
            reason="raise_conditions_met" if delta_kw > EPSILON else "upper_power_limit",
            diesel_raise_margin_kw=diesel_raise_margin_kw,
            diesel_reduce_margin_kw=diesel_reduce_margin_kw,
        )

    if storage_reduce_required or diesel_reduce_required:
        delta_kw = -min(step_kw, current_power)
        proposed_power = max(0.0, current_power + delta_kw)
        if proposed_power < float(inputs.stop_threshold_kw) - EPSILON:
            return FuelCellControlDecision(
                action="stop",
                requested_delta_kw=-current_power,
                reason=(
                    "storage_soc_stop"
                    if storage_reduce_required
                    else "diesel_power_stop"
                ),
                diesel_raise_margin_kw=diesel_raise_margin_kw,
                diesel_reduce_margin_kw=diesel_reduce_margin_kw,
            )
        return FuelCellControlDecision(
            action="decrease",
            requested_delta_kw=delta_kw,
            reason=(
                "storage_soc_reduce"
                if storage_reduce_required
                else "diesel_power_reduce"
            ),
            diesel_raise_margin_kw=diesel_raise_margin_kw,
            diesel_reduce_margin_kw=diesel_reduce_margin_kw,
        )

    return FuelCellControlDecision(
        action="hold",
        reason="hold_region",
        diesel_raise_margin_kw=diesel_raise_margin_kw,
        diesel_reduce_margin_kw=diesel_reduce_margin_kw,
    )
