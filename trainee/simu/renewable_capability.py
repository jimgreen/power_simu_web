from __future__ import annotations

import math
from typing import Any, Mapping, Optional

from .control_config import default_number


EPSILON = 1e-9
WIND_POWER_CURVE_EXPONENT = default_number("wind_power_curve_exponent")


def _number(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def renewable_weather_available_kw(
    technology: str,
    parameter: Mapping[str, Any],
    capacity_kw: float,
    *,
    wind_speed: Optional[float],
    solar_irradiance: Optional[float],
    air_temperature: Optional[float],
) -> Optional[float]:
    """Return the simulator-aligned weather capability within rated limits."""

    capacity = _number(capacity_kw)
    if capacity is None or capacity <= EPSILON:
        return None
    capacity = max(0.0, capacity)
    parameter_limit = _number(parameter.get("p_max"))
    if parameter_limit is not None and parameter_limit >= 0.0:
        capacity = min(capacity, parameter_limit)

    if technology == "wind":
        speed = _number(wind_speed)
        cut_in = _number(
            parameter.get("cut_in_wind_speed", parameter.get("cut_in_speed"))
        )
        rated_speed = _number(parameter.get("rated_wind_speed"))
        cut_out = _number(
            parameter.get("cut_out_wind_speed", parameter.get("cut_out_speed"))
        )
        if (
            speed is None
            or cut_in is None
            or rated_speed is None
            or cut_out is None
            or cut_in < 0.0
            or rated_speed <= cut_in
            or cut_out <= rated_speed
        ):
            return None
        speed = max(0.0, speed)
        if speed < cut_in or speed >= cut_out:
            return 0.0
        if speed >= rated_speed:
            return capacity
        ratio = (speed - cut_in) / max(EPSILON, rated_speed - cut_in)
        return min(capacity, capacity * ratio**WIND_POWER_CURVE_EXPONENT)

    if technology == "pv":
        irradiance = _number(solar_irradiance)
        reference_irradiance = _number(parameter.get("reference_irradiance"))
        if (
            irradiance is None
            or reference_irradiance is None
            or reference_irradiance <= 0.0
        ):
            return None
        available = capacity * max(0.0, irradiance) / reference_irradiance

        # Keep the overview and control pages aligned with the simulation
        # kernel: temperature correction is applied only for its canonical
        # temp_coefficient field. Models that only define the legacy
        # temperature_coefficient field use irradiance-based capability.
        temperature_coefficient = _number(parameter.get("temp_coefficient"))
        if temperature_coefficient is not None:
            reference_temperature = _number(parameter.get("reference_temperature"))
            if reference_temperature is None:
                return None
            temperature = _number(air_temperature)
            if temperature is None:
                temperature = reference_temperature
            available *= max(
                0.0,
                1.0
                + temperature_coefficient
                * (temperature - reference_temperature),
            )
        return min(capacity, max(0.0, available))

    return None
